"""
Creating, cancelling, rescheduling and starting bookings, assigning their
tutors, closing slots and setting the schedule: the one place booking rows
are written.

create_booking runs in one transaction:

1. The slot row for the date and time is created by its first booking.
   get_or_create inserts in a savepoint; a concurrent request inserting the
   same slot waits on the unique index and, once the first commits, reads
   that row instead -- one row per slot.
2. The slot row is locked (SELECT ... FOR UPDATE), the project's pattern for
   check-then-write. Every booking, cancellation and closure of the slot
   queues behind this lock, so the count read under it is exact.
3. Under the lock the lead is matched and its row locked too (FOR NO KEY
   UPDATE, the lead-level lock of design B.7); a booking the lead already
   holds in this slot is returned as it is (a repeated submission); a lead
   that already holds a live booking of this type (LeadAlreadyBooked), or
   one of the other type at an overlapping time (LeadTimeConflict), is
   refused (Q26); a closed or full slot is refused; otherwise the lowest
   free seat (1-3) is taken.

The lead lock is what keeps Q26 true under concurrency: two requests for one
child in different slots, or of different types, lock different slot rows
and would both pass a check made under those alone. Both queue on the lead
row instead, and the second checks only once the first has committed, so it
sees that booking in either table. No index can stand behind the rules: a
live booking is one whose slot has not ended yet, which changes with the
clock, and the overlap rule spans both tables and the slots.

Diagnostic and Demo bookings live in tables of their own
(bookings.models.booking_model); every write below picks the table of the
booking's type, and every check that spans both types (a tutor's commitments,
a phone number's bookings today) reads both. Each write also records the
change in the booking's history (bookings.history), in the same transaction,
and a booking's creation, answer from the parent, cancellation, reschedule,
tutor change or Meet link change keeps its parent communication in step there
too (communications.planner).

The seats' partial unique index makes a fourth booked row for one slot
impossible even for code that skipped the lock; the lock is what keeps the
count right and concurrent requests off that index. A lock wait longer than
LOCK_TIMEOUT, or a deadlock, answers BookingBusy (CAPACITY_CHECK_UNAVAILABLE)
instead of holding the request.

assign_tutor takes the slot and booking locks in the same order, then the
tutor's scheduling lock -- the one sessions take before booking a class for
that tutor -- and the tutor's account row, so a class being scheduled, the
account being deactivated or another assignment for the same tutor all wait
for it (or it for them) and the availability it checks is still true when it
commits.

reschedule_booking takes the most locks, always in this order (design B.7):
both slots in time order, then the lead (FOR NO KEY UPDATE: the lead-level
conflict check), then the booking, then the tutor's scheduling lock and row
when a tutor would carry over. Every other writer takes a prefix of it;
set_tutor_meet_link keeps the same order without the slots and the lead: the
tutor's live bookings, then the tutor's row.

A booking copies its tutor's permanent Google Meet link when the tutor is
assigned (or carried over by a reschedule) and drops it when unassigned.
set_tutor_meet_link keeps live bookings in step with a changed link; every
other booking keeps the link it had.
"""
from dataclasses import dataclass
from datetime import date as date_type, datetime, time as time_type, timedelta

from django.conf import settings
from django.db import OperationalError, connection, transaction
from django.utils import timezone

from accounts.models import RoleChoices, User
from activity.utils import log_activity
from communications import planner
from sessions.models import Session, SessionStatusChoices
from sessions.services import lock_tutor_schedule

from . import history
from .attribution import resolve_referral
from .leads import match_lead, normalize_phone
from .lifecycle import START_EARLY, start_opens_at
from .models import (
    BOOKING_MODELS,
    HOLDS_SEAT,
    MANUAL_CANCEL_REASONS,
    SLOT_CAPACITY,
    BookingEventKind,
    BookingSlot,
    BookingStatus,
    CancelReason,
    Lead,
    NotConfirmedReason,
    ParentConfirmation,
    ReferralStatus,
    RescheduleReason,
    SlotTime,
    booking_model,
)
from .scheduling import booking_window, slot_instants

LOCK_TIMEOUT = '3s'
# lock_not_available, deadlock_detected
BUSY_SQLSTATES = {'55P03', '40P01'}


class BookingError(Exception):
    code = 'BOOKING_FAILED'
    http_status = 400
    message = 'The booking could not be made.'


class DateOutOfWindow(BookingError):
    code = 'DATE_OUT_OF_WINDOW'
    message = 'That date is not available for booking. Please pick another.'


class SlotUnavailable(BookingError):
    code = 'SLOT_UNAVAILABLE'
    http_status = 409
    message = 'That time is not offered. Please choose another time.'


class SlotFull(BookingError):
    code = 'SLOT_FULL'
    http_status = 409
    message = 'This slot is fully booked. Please choose another time.'


class TooManyBookings(BookingError):
    code = 'TOO_MANY_BOOKINGS'
    http_status = 429
    message = 'Too many bookings for this phone number today. Please try again tomorrow.'


class BookingBusy(BookingError):
    code = 'CAPACITY_CHECK_UNAVAILABLE'
    http_status = 503
    message = 'Could not check this slot right now. Please try again.'


class BookingCancelled(BookingError):
    code = 'BOOKING_CANCELLED'
    http_status = 409
    message = 'This booking is cancelled, so its tutor cannot be changed.'


class BookingCompleted(BookingError):
    code = 'BOOKING_COMPLETED'
    http_status = 409
    message = 'This booking is completed, so it can no longer be changed.'


class BookingRescheduled(BookingError):
    code = 'BOOKING_RESCHEDULED'
    http_status = 409
    message = 'This booking was moved to another slot, so it can no longer be changed.'


class SlotStarted(BookingError):
    """The booking's scheduled time has passed -- never that it has started: only its tutor starts it (BookingStarted)."""
    code = 'SLOT_STARTED'
    http_status = 409
    message = "This booking's scheduled time has passed."


class SlotEnded(BookingError):
    code = 'SLOT_ENDED'
    http_status = 409
    message = "This booking's slot has ended, so its tutor cannot be changed."


class BookingStarted(BookingError):
    """Its tutor has started it (start_booking): who teaches it, and when, no longer change."""
    code = 'BOOKING_STARTED'
    http_status = 409
    message = 'This booking has already started, so its tutor cannot be changed.'


class BookingNotAssigned(BookingError):
    """A tutor acting on a booking that is not assigned to them: answered as one that does not exist."""
    code = 'NOT_FOUND'
    http_status = 404
    message = 'No such booking.'


class StartTooEarly(BookingError):
    code = 'START_TOO_EARLY'
    http_status = 409
    message = f'A booking can be started from {START_EARLY.seconds // 60} minutes before its scheduled time.'


class StartWindowClosed(BookingError):
    code = 'START_WINDOW_CLOSED'
    http_status = 409
    message = "This booking's slot has ended, so it can no longer be started."


class InvalidReason(BookingError):
    code = 'INVALID_REASON'
    message = 'Choose a reason from the list.'


class NoShowBeforeStart(BookingError):
    code = 'NO_SHOW_BEFORE_START'
    http_status = 409
    message = 'A booking can be marked No-show only once its scheduled time has passed.'


class BookingNotOwned(BookingError):
    """A BDE acting on a booking whose lead they do not own: answered as one that does not exist."""
    code = 'NOT_FOUND'
    http_status = 404
    message = 'No such booking.'


class SameSlot(BookingError):
    code = 'SAME_SLOT'
    http_status = 409
    message = 'The booking is already in that slot. Choose another time.'


class CancelledNotMovable(BookingCancelled):
    message = 'This booking is cancelled, so it can no longer be moved.'


class StartedNotMovable(BookingStarted):
    message = 'This booking has already started, so it can no longer be moved.'


class CompletedNotStartable(BookingCompleted):
    message = 'This booking is already completed.'


class CancelledNotStartable(BookingCancelled):
    message = 'This booking is cancelled, so it cannot be started.'


class RescheduledNotStartable(BookingRescheduled):
    message = 'This booking was moved to another slot. Start the new booking instead.'


class InvalidConfirmation(BookingError):
    code = 'INVALID_CONFIRMATION'
    message = 'Record the parent as Confirmed or Not Confirmed.'


class CancellationNotConfirmed(BookingError):
    """Not Confirmed without the BDE confirming that it cancels the booking."""
    code = 'CANCELLATION_NOT_CONFIRMED'
    message = 'Not Confirmed cancels the booking. Confirm the cancellation to record it.'


class CancelledNotConfirmable(BookingCancelled):
    message = "This booking is cancelled, so the parent's answer can no longer be recorded."


class CompletedNotConfirmable(BookingCompleted):
    message = "This booking is completed, so the parent's answer can no longer be recorded."


class RescheduledNotConfirmable(BookingRescheduled):
    message = "This booking was moved to another slot. Record the parent's answer on the new booking."


class StartedNotConfirmable(BookingStarted):
    message = "This booking has already started, so the parent's answer can no longer be recorded."


class PastStartNotConfirmable(SlotStarted):
    message = "This booking's scheduled time has passed, so the parent's answer can no longer be recorded."


class LeadTimeConflict(BookingError):
    """The lead already holds another live booking, of either type, at the new time (Q26)."""
    code = 'LEAD_TIME_CONFLICT'
    http_status = 409
    message = 'This child already has another booking at that time. Choose another time.'

    def __init__(self, booking):
        super().__init__(self.message)
        self.booking = booking


class LeadAlreadyBooked(BookingError):
    """The lead already holds a live booking of this type: one at a time, per type (Q26)."""
    code = 'LEAD_ALREADY_BOOKED'
    http_status = 409

    def __init__(self, booking):
        self.message = (
            f'This child already has a {booking.get_booking_type_display()} booked. '
            'Only one can be booked at a time.'
        )
        super().__init__(self.message)
        self.booking = booking


class TutorNotAssignable(BookingError):
    code = 'INVALID_TUTOR'
    message = 'Selected tutor is not an active tutor.'


class NotATutor(BookingError):
    code = 'NOT_A_TUTOR'
    message = 'Only a tutor account has a permanent Meet link.'


class TutorUnavailable(BookingError):
    code = 'TUTOR_UNAVAILABLE'
    http_status = 409
    message = 'This tutor already has a class or another booking at this time.'

    def __init__(self, conflict):
        super().__init__(self.message)
        self.conflict = conflict


# What keeps a tutor from a slot (TutorConflict.kind).
CONFLICT_SESSION = 'session'
CONFLICT_BOOKING = 'booking'


@dataclass(frozen=True)
class TutorConflict:
    """A scheduled class (sessions.Session) or a live booking the tutor already teaches in the window."""
    kind: str
    id: object
    starts_at: datetime
    ends_at: datetime
    # A booking's type (BookingType): a booking is named by its type and its id.
    booking_type: str | None = None


@dataclass(frozen=True)
class BookingRequest:
    booking_type: str
    date: date_type
    time: time_type
    parent_name: str
    phone_dial_code: str
    phone_number: str
    student_name: str
    school: str
    student_class: str
    syllabus: str
    country: str = ''
    display_time: str = ''
    # The raw ``ref`` value, whatever its type: bookings.attribution judges it.
    ref: object = None


def create_booking(request, now=None):
    """
    Book ``request``; returns (booking, created). ``created`` is False for a
    repeated submission, which gets the booking it already made. Raises a
    BookingError subclass, or leads.InvalidLeadDetails.

    One live booking per child and type, and none overlapping another of the
    child's (Q26). Live is what an enquiry calls booked: BOOKED, its slot not
    yet ended (bookings.enquiries). A cancelled, rescheduled or completed
    booking holds nothing, nor does a booked one whose slot has ended -- the
    child may book that type again.
    """
    now = now or timezone.now()
    model = booking_model(request.booking_type)
    if request.date not in booking_window(request.booking_type, now):
        raise DateOutOfWindow()
    if not SlotTime.objects.filter(booking_type=request.booking_type, start_time=request.time, is_active=True).exists():
        raise SlotUnavailable()
    _dial, _national, phone_key = normalize_phone(request.phone_dial_code, request.phone_number)
    referral = resolve_referral(request.ref, request.booking_type)

    try:
        with transaction.atomic():
            _set_lock_timeout()
            slot = _locked_slot(request.booking_type, request.date, request.time)
            lead = _locked_lead(match_lead(_lead_details(request)).pk)

            existing = model.objects.filter(slot=slot, lead=lead, status__in=HOLDS_SEAT).first()
            if existing is not None:
                return existing, False
            live = live_booking(lead, model, now)
            if live is not None:
                raise LeadAlreadyBooked(live)
            clash = lead_conflict(lead, slot.starts_at, slot.ends_at)
            if clash is not None:
                raise LeadTimeConflict(clash)
            if slot.closed_at is not None:
                raise SlotFull()
            taken = set(model.objects.filter(slot=slot, status__in=HOLDS_SEAT).values_list('seat', flat=True))
            free = [seat for seat in range(1, min(slot.capacity, SLOT_CAPACITY) + 1) if seat not in taken]
            if not free:
                raise SlotFull()
            since = timezone.now() - timedelta(days=1)
            if _bookings_since(phone_key, since) >= settings.BOOKING_PHONE_DAILY_LIMIT:
                raise TooManyBookings()

            if referral.status == ReferralStatus.ATTRIBUTED:
                # First valid attribution wins: only a lead nobody owns yet
                # takes this BDE, whatever request commits second.
                Lead.objects.filter(pk=lead.pk, owner_bde__isnull=True).update(
                    owner_bde=referral.bde, owner_link=referral.link, owner_assigned_at=timezone.now(),
                )
            booking = model.objects.create(
                lead=lead,
                slot=slot,
                seat=free[0],
                referral_status=referral.status,
                referral_link=referral.link,
                attributed_bde=referral.bde,
                details=_submitted(request),
            )
            history.record(
                booking, BookingEventKind.CREATED,
                slot_id=slot.id, seat=booking.seat, referral_status=booking.referral_status, via='public_booking',
            )
            owner_id = Lead.objects.filter(pk=lead.pk).values_list('owner_bde_id', flat=True).get()
            # Its five communication steps and first messages, committed with it or not at all.
            planner.plan_booking(booking, now)
    except OperationalError as exc:
        if getattr(exc.__cause__, 'sqlstate', None) in BUSY_SQLSTATES:
            raise BookingBusy() from exc
        raise

    log_activity(
        action='booking.create',
        entity_type='booking',
        entity_id=booking.id,
        entity_label=slot_label(slot),
        # Ids and outcomes only: no names, phone numbers or tokens.
        context={
            'booking_type': booking.booking_type,
            'slot_starts_at': slot.starts_at.isoformat(),
            'referral_status': booking.referral_status,
            'attributed_bde_id': _str_or_none(booking.attributed_bde_id),
            'lead_id': str(booking.lead_id),
            'lead_owner_id': _str_or_none(owner_id),
            'via': 'public_booking',
        },
    )
    return booking, True


def cancel_booking(booking, *, reason_code, actor=None, now=None, owner_bde=None):
    """
    Cancel ``booking`` (kept as a record; its seat is freed) for ``reason_code``
    (a CancelReason, else InvalidReason). Returns (booking, changed); one
    already cancelled is left as it is. A completed booking (BookingCompleted)
    or a rescheduled one (BookingRescheduled) can no longer be cancelled, and
    No-show only once the slot's scheduled time has passed (NoShowBeforeStart,
    D12) -- whether or not its tutor started it.

    The reason is a code, never free text (M1): the booking, its history and
    the activity log keep the code only. "Parent did not confirm" is not one
    to pick: only recording the parent's answer cancels with it
    (record_parent_confirmation). The Admin may cancel any booking; a BDE only
    the bookings of their own leads (Q22): with ``owner_bde`` given, the
    booking's lead must be theirs, checked under the booking's lock
    (BookingNotOwned, answered as a booking that does not exist).
    """
    if reason_code not in MANUAL_CANCEL_REASONS:
        raise InvalidReason()
    now = now or timezone.now()
    try:
        with transaction.atomic():
            _set_lock_timeout()
            # The slot lock first, the same order create_booking takes them in.
            booking = _locked_booking(booking)
            if owner_bde is not None and booking.lead.owner_bde_id != owner_bde.pk:
                raise BookingNotOwned()
            if booking.status == BookingStatus.CANCELLED:
                return booking, False
            if booking.status == BookingStatus.COMPLETED:
                raise BookingCompleted()
            if booking.status == BookingStatus.RESCHEDULED:
                raise BookingRescheduled()
            if reason_code == CancelReason.NO_SHOW and booking.slot.starts_at > now:
                raise NoShowBeforeStart()
            _cancel_locked(booking, reason_code, actor, now)
    except OperationalError as exc:
        if getattr(exc.__cause__, 'sqlstate', None) in BUSY_SQLSTATES:
            raise BookingBusy() from exc
        raise
    _log_cancellation(booking, reason_code, actor)
    return booking, True


def record_parent_confirmation(booking, outcome, *, reason_code='', confirm_cancellation=False, actor=None,
                               now=None, owner_bde=None):
    """
    Record what the parent said when the BDE asked them to confirm ``booking``
    (PRD 3.11, step 3): ``outcome`` is a ParentConfirmation, Confirmed or Not
    Confirmed (else InvalidConfirmation). Returns (booking, changed).

    Confirmed is recorded at once -- when, and by whom -- and saying it again
    changes nothing. It sends nothing itself: the confirmed message goes once
    the booking also has its tutor, their Meet link and the BDE's contact
    details (communications.planner.parent_confirmed). Not Confirmed needs a
    NotConfirmedReason (InvalidReason) and ``confirm_cancellation`` -- the BDE
    agreeing that it cancels the booking (CancellationNotConfirmed) -- and
    then cancels it, with the same cancellation cancel_booking makes, in the
    same transaction: reason "Parent did not confirm", its future tasks and
    unsent messages stopped. A Confirmed parent may still turn out Not
    Confirmed; nothing goes back to Awaiting.

    Only while the booking is booked, its tutor has not started it and its
    scheduled time has not come (the *NotConfirmable errors): a Not Confirmed
    must never cancel a class its tutor has begun, however early they started
    it. The Admin may record any booking's answer; a BDE
    only their own leads' (``owner_bde``, checked under the booking's lock as
    for cancel_booking).
    """
    if outcome == ParentConfirmation.NOT_CONFIRMED:
        if reason_code not in NotConfirmedReason.values:
            raise InvalidReason()
        if not confirm_cancellation:
            raise CancellationNotConfirmed()
    elif outcome == ParentConfirmation.CONFIRMED:
        reason_code = ''
    else:
        raise InvalidConfirmation()
    now = now or timezone.now()
    try:
        with transaction.atomic():
            _set_lock_timeout()
            booking = _locked_booking(booking)
            if owner_bde is not None and booking.lead.owner_bde_id != owner_bde.pk:
                raise BookingNotOwned()
            if booking.status == BookingStatus.CANCELLED:
                raise CancelledNotConfirmable()
            if booking.status == BookingStatus.COMPLETED:
                raise CompletedNotConfirmable()
            if booking.status == BookingStatus.RESCHEDULED:
                raise RescheduledNotConfirmable()
            if booking.started_at is not None:
                raise StartedNotConfirmable()
            if booking.slot.starts_at <= now:
                raise PastStartNotConfirmable()
            if outcome == booking.parent_confirmation:
                return booking, False
            booking.parent_confirmation = outcome
            booking.parent_confirmation_at = timezone.now()
            booking.parent_confirmation_by = actor
            booking.not_confirmed_reason = reason_code
            answer_fields = [
                'parent_confirmation', 'parent_confirmation_at', 'parent_confirmation_by', 'not_confirmed_reason',
            ]
            if outcome == ParentConfirmation.CONFIRMED:
                booking.save(update_fields=[*answer_fields, 'updated_at'])
                history.record(booking, BookingEventKind.PARENT_CONFIRMED, actor=actor)
                planner.parent_confirmed(booking, now, actor=actor)
            else:
                history.record(booking, BookingEventKind.PARENT_NOT_CONFIRMED, actor=actor, reason_code=reason_code)
                _cancel_locked(booking, CancelReason.NOT_CONFIRMED, actor, now, extra_fields=answer_fields)
    except OperationalError as exc:
        if getattr(exc.__cause__, 'sqlstate', None) in BUSY_SQLSTATES:
            raise BookingBusy() from exc
        raise
    log_activity(
        action='booking.parent_confirmation',
        entity_type='booking',
        entity_id=booking.id,
        entity_label=slot_label(booking.slot),
        # Codes only, never free text (M1).
        context={
            'booking_type': booking.booking_type,
            'outcome': outcome,
            'reason_code': reason_code or None,
            'lead_id': str(booking.lead_id),
        },
        actor=actor,
    )
    if outcome == ParentConfirmation.NOT_CONFIRMED:
        _log_cancellation(booking, CancelReason.NOT_CONFIRMED, actor)
    return booking, True


@dataclass(frozen=True)
class RescheduleResult:
    """
    What reschedule_booking did: ``booking`` is the replacement (BOOKED in the
    new slot), ``previous`` the booking it replaced (now RESCHEDULED).
    ``tutor_carried_over`` says whether the tutor moved with it (Q24); when one
    was assigned but did not, ``tutor_conflict`` (a TutorConflict) or
    ``tutor_not_assignable`` says why.
    """
    booking: object
    previous: object
    tutor_carried_over: bool
    tutor: object = None
    tutor_conflict: object = None
    tutor_not_assignable: bool = False


def reschedule_booking(booking, local_date, local_time, *, reason_code, actor=None, now=None):
    """
    Move ``booking`` to the slot of its type at ``local_date`` / ``local_time``
    for ``reason_code`` (a RescheduleReason, else InvalidReason). The booking
    is kept as RESCHEDULED and a new BOOKED booking in the new slot replaces it
    (its ``rescheduled_from``), so repeated moves form one chain (no limit,
    Q23). Returns a RescheduleResult.

    Only a booked booking (BookingCompleted, BookingRescheduled,
    CancelledNotMovable) its tutor has not started (StartedNotMovable) --
    one whose scheduled time passed, or whose slot ended, with no start may
    still move: the class never happened -- and only into a slot the public
    pages would offer: a date in the window (DateOutOfWindow), an active time
    (SlotUnavailable), open with a free seat (SlotFull), not its own
    (SameSlot). The lead may hold no other live booking of this type
    (LeadAlreadyBooked: one a parent made after the slot of this one ended)
    nor one of either type at the new time (LeadTimeConflict, Q26). The
    tutor carries over when they are an active tutor free for the new slot;
    otherwise the replacement starts unassigned and the result says why (Q24).
    The old booking keeps its tutor as history. Who may reschedule -- the Admin
    only (Q23) -- is the caller's check.
    """
    if reason_code not in RescheduleReason.values:
        raise InvalidReason()
    now = now or timezone.now()
    model = type(booking)
    booking_type = model.BOOKING_TYPE
    if local_date not in booking_window(booking_type, now):
        raise DateOutOfWindow()
    if not SlotTime.objects.filter(booking_type=booking_type, start_time=local_time, is_active=True).exists():
        raise SlotUnavailable()
    new_starts_at, new_ends_at = slot_instants(local_date, local_time)
    try:
        with transaction.atomic():
            _set_lock_timeout()
            current = model.objects.select_related('slot').get(pk=booking.pk)
            if (current.slot.local_date, current.slot.local_time) == (local_date, local_time):
                raise SameSlot()
            # Both slots in time order, then the lead, then the booking (B.7).
            if current.slot.starts_at <= new_starts_at:
                BookingSlot.objects.select_for_update().get(pk=current.slot_id)
                new_slot = _locked_slot(booking_type, local_date, local_time)
            else:
                new_slot = _locked_slot(booking_type, local_date, local_time)
                BookingSlot.objects.select_for_update().get(pk=current.slot_id)
            lead = _locked_lead(current.lead_id)
            old = model.objects.select_for_update().select_related('slot').get(pk=booking.pk)
            if old.status == BookingStatus.COMPLETED:
                raise BookingCompleted()
            if old.status == BookingStatus.RESCHEDULED:
                raise BookingRescheduled()
            if old.status != BookingStatus.BOOKED:
                raise CancelledNotMovable()
            if old.started_at is not None:
                raise StartedNotMovable()
            if new_slot.closed_at is not None:
                raise SlotFull()
            taken = set(model.objects.filter(slot=new_slot, status__in=HOLDS_SEAT).values_list('seat', flat=True))
            free = [seat for seat in range(1, min(new_slot.capacity, SLOT_CAPACITY) + 1) if seat not in taken]
            if not free:
                raise SlotFull()
            # Once its slot has ended this booking is no longer live, so the
            # parent may have booked this type again: moving it as well would
            # leave two (Q26), checked under the lead lock as create_booking does.
            live = live_booking(lead, model, now, exclude_booking=old)
            if live is not None:
                raise LeadAlreadyBooked(live)
            clash = lead_conflict(lead, new_starts_at, new_ends_at, exclude_booking=old)
            if clash is not None:
                raise LeadTimeConflict(clash)

            tutor, tutor_conflict, not_assignable = None, None, False
            if old.assigned_tutor_id:
                tutor = _locked_tutor(old.assigned_tutor_id)
                if not is_assignable_tutor(tutor):
                    not_assignable = True
                else:
                    tutor_conflict = find_tutor_conflict(tutor, new_starts_at, new_ends_at, exclude_booking=old)
            carried = tutor is not None and not not_assignable and tutor_conflict is None

            moved_at = timezone.now()
            old.status = BookingStatus.RESCHEDULED
            old.rescheduled_at = moved_at
            old.rescheduled_by = actor
            old.reschedule_reason_code = reason_code
            old.save(update_fields=['status', 'rescheduled_at', 'rescheduled_by', 'reschedule_reason_code', 'updated_at'])
            new = model.objects.create(
                lead=lead,
                slot=new_slot,
                seat=free[0],
                channel=old.channel,
                created_by=old.created_by,
                referral_status=old.referral_status,
                referral_link=old.referral_link,
                attributed_bde=old.attributed_bde,
                details=old.details,
                rescheduled_from=old,
                assigned_tutor=tutor if carried else None,
                tutor_assigned_at=moved_at if carried else None,
                tutor_assigned_by=actor if carried else None,
                # A new assignment: the tutor's link as it is now. The old
                # booking keeps the one it had.
                tutor_meet_link=tutor.tutor_meet_link if carried else None,
            )
            history.record(
                old, BookingEventKind.RESCHEDULED, actor=actor,
                from_status=BookingStatus.BOOKED, to_status=BookingStatus.RESCHEDULED, reason_code=reason_code,
                old_slot_id=old.slot_id, new_slot_id=new_slot.id, replacement_id=new.id,
            )
            history.record(
                new, BookingEventKind.CREATED, actor=actor,
                slot_id=new_slot.id, seat=new.seat, referral_status=new.referral_status, via='reschedule',
                rescheduled_from_id=old.id,
            )
            if carried:
                history.record(
                    new, BookingEventKind.TUTOR_ASSIGNED, actor=actor,
                    old_tutor_id=None, new_tutor_id=tutor.pk, via='reschedule',
                )
            # The old booking's communication stops; the new one's is planned from its own slot.
            planner.booking_rescheduled(old, new, now)
    except OperationalError as exc:
        if getattr(exc.__cause__, 'sqlstate', None) in BUSY_SQLSTATES:
            raise BookingBusy() from exc
        raise
    log_activity(
        action='booking.reschedule',
        entity_type='booking',
        entity_id=new.id,
        entity_label=slot_label(new_slot),
        # Ids, instants and codes only: no names, no free text.
        context={
            'booking_type': booking_type,
            'rescheduled_from_id': str(old.id),
            'old_slot_starts_at': old.slot.starts_at.isoformat(),
            'new_slot_starts_at': new_slot.starts_at.isoformat(),
            'reason_code': reason_code,
            'lead_id': str(lead.id),
            'tutor_id': _str_or_none(old.assigned_tutor_id),
            'tutor_carried_over': carried,
        },
        actor=actor,
    )
    return RescheduleResult(
        booking=new, previous=old, tutor_carried_over=carried, tutor=tutor,
        tutor_conflict=tutor_conflict, tutor_not_assignable=not_assignable,
    )


def live_booking(lead, model, now, exclude_booking=None):
    """
    The lead's live booking of ``model``'s type -- booked, its slot not yet
    ended, as an enquiry counts it -- ``exclude_booking`` left out, or None:
    the one booking of a type a child may hold at a time (Q26).
    """
    bookings = model.objects.filter(lead=lead, status=BookingStatus.BOOKED, slot__ends_at__gt=now)
    if exclude_booking is not None:
        bookings = bookings.exclude(pk=exclude_booking.pk)
    return bookings.select_related('slot').first()


def lead_commitments(lead, starts_at, ends_at, exclude_booking=None):
    """
    The lead's other live (BOOKED) bookings, of either type, whose slots overlap
    ``[starts_at, ends_at)``, soonest first (Q26). Touching windows do not
    overlap; a rescheduled or cancelled booking holds no time.
    """
    found = []
    for model in BOOKING_MODELS:
        bookings = model.objects.filter(
            lead=lead, status=BookingStatus.BOOKED, slot__starts_at__lt=ends_at, slot__ends_at__gt=starts_at,
        )
        if isinstance(exclude_booking, model):
            bookings = bookings.exclude(pk=exclude_booking.pk)
        found.extend(bookings.select_related('slot'))
    return sorted(found, key=lambda booking: (booking.slot.starts_at, booking.created_at))


def lead_conflict(lead, starts_at, ends_at, exclude_booking=None):
    """The first of lead_commitments, or None."""
    commitments = lead_commitments(lead, starts_at, ends_at, exclude_booking)
    return commitments[0] if commitments else None


def tutor_commitments(tutor, starts_at, ends_at, exclude_booking=None):
    """
    Everything of ``tutor``'s overlapping ``[starts_at, ends_at)`` -- SCHEDULED
    classes and live bookings, as TutorConflicts -- soonest first: what
    find_tutor_conflict checks one window against, read once for a longer one.
    """
    found = [_class_conflict(session) for session in _overlapping_classes(starts_at, ends_at).filter(tutor=tutor)]
    found += [_booking_conflict(booking) for booking in
              _overlapping_bookings(starts_at, ends_at, exclude_booking, assigned_tutor=tutor)]
    return sorted(found, key=lambda conflict: conflict.starts_at)


def is_assignable_tutor(user):
    """
    Whether ``user`` may be given a booking to teach: an active TUTOR account,
    the rule every tutor assignment in the Hub applies (decision D5).
    """
    return bool(
        user is not None
        and user.role == RoleChoices.TUTOR
        and user.is_active
        and user.deactivated_at is None
    )


def assignable_tutors():
    """Every account ``is_assignable_tutor`` accepts, as a queryset: the tutors a picker offers."""
    return User.objects.filter(role=RoleChoices.TUTOR, is_active=True, deactivated_at__isnull=True)


def find_tutor_conflict(tutor, starts_at, ends_at, exclude_booking=None):
    """
    The first thing that keeps ``tutor`` from teaching ``[starts_at, ends_at)``,
    as a TutorConflict, or None. Tuition is one-to-one, so a tutor teaches one
    student at a time: a SCHEDULED class of theirs blocks the window (the rule
    of sessions.services.find_conflict -- attended and cancelled classes do
    not, and touching windows do not overlap), and so does any other booked
    or completed booking assigned to them whose slot overlaps it -- another
    booking in the same slot included, whatever seats remain, and either
    booking type.
    ``exclude_booking`` is the booking being assigned. A cancelled booking
    keeps its tutor but blocks nothing.

    Availability for a slot is this plus is_assignable_tutor; assign_tutor
    repeats both under its locks, so a caller's earlier answer is never enough.
    """
    session = _overlapping_classes(starts_at, ends_at).filter(tutor=tutor).order_by('start_time').first()
    if session is not None:
        return _class_conflict(session)
    booking = find_booking_conflict(tutor, starts_at, ends_at, exclude_booking=exclude_booking)
    if booking is not None:
        return _booking_conflict(booking)
    return None


def tutor_conflicts(tutors, starts_at, ends_at, exclude_booking=None):
    """
    ``find_tutor_conflict`` for many tutors at once, in two queries: each of
    ``tutors`` kept from ``[starts_at, ends_at)``, mapped to its first
    TutorConflict (a class before a booking, as there); a free tutor is
    absent. What a tutor picker shows -- never what an assignment trusts:
    assign_tutor checks again under its locks.
    """
    found = {}
    classes = _overlapping_classes(starts_at, ends_at).filter(tutor__in=tutors).order_by('start_time')
    for session in classes:
        found.setdefault(session.tutor_id, _class_conflict(session))
    for booking in _overlapping_bookings(starts_at, ends_at, exclude_booking, assigned_tutor__in=tutors):
        found.setdefault(booking.assigned_tutor_id, _booking_conflict(booking))
    return found


def find_booking_conflict(tutor, starts_at, ends_at, exclude_booking=None):
    """
    The first booked or completed booking, of either type, assigned to
    ``tutor`` whose slot overlaps ``[starts_at, ends_at)`` (half-open, so
    touching windows do not overlap), with its slot, or None. Cancelled and
    rescheduled bookings keep their tutor but block nothing, and an unassigned
    booking holds no tutor at all.

    The one definition of a tutor's booking commitments: find_tutor_conflict
    asks it before a booking is assigned, and the sessions views before a
    class is scheduled, rescheduled or handed to a tutor -- each under the
    tutor's scheduling lock (sessions.services.lock_scheduling /
    lock_tutor_schedule), so neither write can slip past the other.
    """
    bookings = _overlapping_bookings(starts_at, ends_at, exclude_booking, assigned_tutor=tutor)
    return bookings[0] if bookings else None


def _overlapping_classes(starts_at, ends_at):
    """SCHEDULED classes overlapping ``[starts_at, ends_at)``: the rule of sessions.services.find_conflict."""
    return Session.objects.filter(
        status=SessionStatusChoices.SCHEDULED,
        start_time__lt=ends_at,
        end_time__gt=starts_at,
    )


def _overlapping_bookings(starts_at, ends_at, exclude_booking=None, **filters):
    """
    The booked and completed bookings of both types whose slot overlaps
    ``[starts_at, ends_at)`` and that match ``filters``, ``exclude_booking``
    left out, with their slots, soonest first.
    """
    found = []
    for model in BOOKING_MODELS:
        bookings = model.objects.filter(
            status__in=HOLDS_SEAT,
            slot__starts_at__lt=ends_at,
            slot__ends_at__gt=starts_at,
            **filters,
        )
        if isinstance(exclude_booking, model):
            bookings = bookings.exclude(pk=exclude_booking.pk)
        found.extend(bookings.select_related('slot'))
    return sorted(found, key=lambda booking: (booking.slot.starts_at, booking.created_at))


def _class_conflict(session):
    return TutorConflict(CONFLICT_SESSION, session.id, session.start_time, session.end_time)


def _booking_conflict(booking):
    return TutorConflict(
        CONFLICT_BOOKING, booking.id, booking.slot.starts_at, booking.slot.ends_at, booking_type=booking.booking_type,
    )


def upcoming_assignments(tutor, now=None):
    """
    The booked bookings, of either type, assigned to ``tutor`` whose slot has
    not ended, soonest first. An account holding any may not stop being an
    active tutor (Team deactivation or role change, the Django admin): there
    is no rule yet for handing a booking to another tutor, so they are
    reassigned or unassigned first (assign_tutor / unassign_tutor), never left
    on an account that cannot teach them (one already started cannot be handed
    over, so the account waits for its slot to end). The caller holds the account's row
    lock, which assign_tutor also takes, so no assignment can land after the
    count.
    """
    now = now or timezone.now()
    found = []
    for model in BOOKING_MODELS:
        found.extend(
            model.objects.filter(assigned_tutor=tutor, status=BookingStatus.BOOKED, slot__ends_at__gt=now)
            .select_related('slot')
        )
    return sorted(found, key=lambda booking: (booking.slot.starts_at, booking.created_at))


def assign_tutor(booking, tutor, actor=None, now=None):
    """
    Make ``tutor`` the one who teaches ``booking``; returns (booking, changed).

    Only an active TUTOR (else TutorNotAssignable), only while the booking is
    booked (BookingCancelled, BookingCompleted, BookingRescheduled), its tutor
    has not started it (BookingStarted) and its slot has not ended
    (SlotEnded) -- a booking whose scheduled time passed with no start may
    still be handed to a tutor who can take it -- and
    only when the tutor is free for the whole slot (TutorUnavailable, see
    find_tutor_conflict). Every check is made again under the locks, whatever
    the caller saw before. The same tutor again changes nothing and is not
    logged; another tutor replaces the current one -- a reassignment, checked
    exactly like a first assignment.
    """
    now = now or timezone.now()
    try:
        with transaction.atomic():
            _set_lock_timeout()
            booking = _locked_booking(booking)
            _check_tutor_changeable(booking, now)
            tutor = _locked_tutor(tutor.pk)
            if not is_assignable_tutor(tutor):
                raise TutorNotAssignable()
            if booking.assigned_tutor_id == tutor.pk:
                return booking, False
            conflict = find_tutor_conflict(tutor, booking.slot.starts_at, booking.slot.ends_at, exclude_booking=booking)
            if conflict is not None:
                raise TutorUnavailable(conflict)
            previous_tutor_id = booking.assigned_tutor_id
            booking.assigned_tutor = tutor
            booking.tutor_assigned_at = timezone.now()
            booking.tutor_assigned_by = actor
            # The new tutor's permanent link as it is now, read under their row lock.
            booking.tutor_meet_link = tutor.tutor_meet_link
            booking.save(update_fields=[
                'assigned_tutor', 'tutor_assigned_at', 'tutor_assigned_by', 'tutor_meet_link', 'updated_at',
            ])
            history.record(
                booking, BookingEventKind.TUTOR_ASSIGNED, actor=actor,
                old_tutor_id=previous_tutor_id, new_tutor_id=tutor.pk,
            )
            # A waiting confirmed message may now have its tutor and Meet link.
            planner.refresh_messages(booking, now)
    except OperationalError as exc:
        if getattr(exc.__cause__, 'sqlstate', None) in BUSY_SQLSTATES:
            raise BookingBusy() from exc
        raise
    _log_tutor_change(booking, 'booking.assign_tutor', actor, previous_tutor_id, tutor.pk)
    return booking, True


def unassign_tutor(booking, actor=None, now=None):
    """
    Take the tutor off ``booking``, clearing who was assigned, when and by
    whom; returns (booking, changed). Under the same rules as assign_tutor --
    booked, not started, slot not ended -- so a cancelled, started or past
    booking keeps the tutor it had. A booking with no tutor is left as it is.
    """
    now = now or timezone.now()
    try:
        with transaction.atomic():
            _set_lock_timeout()
            booking = _locked_booking(booking)
            _check_tutor_changeable(booking, now)
            previous_tutor_id = booking.assigned_tutor_id
            if previous_tutor_id is None:
                return booking, False
            booking.assigned_tutor = None
            booking.tutor_assigned_at = None
            booking.tutor_assigned_by = None
            booking.tutor_meet_link = None
            booking.save(update_fields=[
                'assigned_tutor', 'tutor_assigned_at', 'tutor_assigned_by', 'tutor_meet_link', 'updated_at',
            ])
            history.record(booking, BookingEventKind.TUTOR_UNASSIGNED, actor=actor, old_tutor_id=previous_tutor_id)
            # An unsent confirmed message waits again for a tutor.
            planner.refresh_messages(booking, now)
    except OperationalError as exc:
        if getattr(exc.__cause__, 'sqlstate', None) in BUSY_SQLSTATES:
            raise BookingBusy() from exc
        raise
    _log_tutor_change(booking, 'booking.unassign_tutor', actor, previous_tutor_id, None)
    return booking, True


def start_booking(booking, tutor, now=None):
    """
    Record that ``tutor`` has started teaching ``booking``: their Start Demo or
    Start Diagnostic, the only thing that starts a booking -- its scheduled
    time alone never does (bookings.lifecycle). Returns (booking, changed); a
    booking already started is left as it is, however often Start is sent
    again (a second click, another tab), with one STARTED event in its history.

    Only the booking's assigned tutor (anyone else is told it does not exist,
    BookingNotAssigned), only while it is booked (CompletedNotStartable,
    CancelledNotStartable, RescheduledNotStartable), and only from START_EARLY
    before its slot starts (StartTooEarly) until the slot ends
    (StartWindowClosed). ``started_at`` is the server's clock read under the
    locks (``now`` pins it), so the moment checked is the moment recorded.

    Locks: the slot, then the booking (_locked_booking), the order every
    booking write takes them in. A Start racing a cancellation, a reschedule,
    a tutor change or another Start waits for it, or it for the Start, and
    whichever commits second sees what the first did. Its communication steps
    keep their scheduled times and the after-activity message still follows
    completion; the automatic messages before the class no longer go once it
    has started (communications.rendering, BOOKING_ACTIVE), as the BDE's
    confirmation actions already close.
    """
    try:
        with transaction.atomic():
            _set_lock_timeout()
            booking = _locked_booking(booking)
            at = now or timezone.now()
            if booking.assigned_tutor_id is None or booking.assigned_tutor_id != tutor.pk:
                raise BookingNotAssigned()
            if booking.status == BookingStatus.COMPLETED:
                raise CompletedNotStartable()
            if booking.status == BookingStatus.RESCHEDULED:
                raise RescheduledNotStartable()
            if booking.status != BookingStatus.BOOKED:
                raise CancelledNotStartable()
            if booking.started_at is not None:
                return booking, False
            if at < start_opens_at(booking.slot):
                raise StartTooEarly()
            if at >= booking.slot.ends_at:
                raise StartWindowClosed()
            booking.started_at = at
            booking.started_by = tutor
            booking.save(update_fields=['started_at', 'started_by', 'updated_at'])
            history.record(booking, BookingEventKind.STARTED, actor=tutor)
    except OperationalError as exc:
        if getattr(exc.__cause__, 'sqlstate', None) in BUSY_SQLSTATES:
            raise BookingBusy() from exc
        raise
    log_activity(
        action='booking.start',
        entity_type='booking',
        entity_id=booking.id,
        entity_label=slot_label(booking.slot),
        # Ids and instants only, as for every booking entry.
        context={
            'booking_type': booking.booking_type,
            'slot_starts_at': booking.slot.starts_at.isoformat(),
            'started_at': booking.started_at.isoformat(),
            'lead_id': str(booking.lead_id),
        },
        actor=tutor,
    )
    return booking, True


def set_tutor_meet_link(tutor, meet_link, actor=None, now=None):
    """
    Make ``meet_link`` -- in its stored form (accounts.meet_links), or None to
    remove it -- ``tutor``'s permanent Google Meet link. Returns (tutor,
    changed, bookings): the account as saved, whether its link changed, and
    the bookings whose link changed with it, soonest first.

    Each live booking assigned to the tutor -- booked, its slot not yet ended,
    as an enquiry counts it -- and not started yet takes the new link too, so
    the classes still to be taught use it. Every other booking keeps the link
    it had: one started, or whose slot has ended, or one completed, cancelled
    or moved, records the room it was taught in (or was to be), whatever the
    tutor's link becomes. Each booking
    changed records MEET_LINK_UPDATED in its history -- whether it has a link,
    never the link. Only a TUTOR account has one (NotATutor), active or not.
    Who may set it -- an administrator -- is the caller's check, and so is the
    activity log.

    Locks: the tutor's live bookings first, then the account row -- the order
    assign_tutor takes a booking and its tutor in -- so an assignment racing
    this change either commits first and is updated here, or waits for it and
    copies the new link.
    """
    now = now or timezone.now()
    live = {
        'assigned_tutor_id': tutor.pk, 'status': BookingStatus.BOOKED, 'slot__ends_at__gt': now,
        'started_at__isnull': True,
    }
    try:
        with transaction.atomic():
            _set_lock_timeout()
            for model in BOOKING_MODELS:
                list(model.objects.select_for_update(of=('self',)).filter(**live).order_by('pk').only('pk'))
            account = User.objects.select_for_update(no_key=True).filter(pk=tutor.pk).first()
            if account is None or account.role != RoleChoices.TUTOR:
                raise NotATutor()
            if account.tutor_meet_link == meet_link:
                return account, False, []
            account.tutor_meet_link = meet_link
            account.save(update_fields=['tutor_meet_link', 'updated_at'])
            changed = []
            for model in BOOKING_MODELS:
                for booking in model.objects.filter(**live).select_related('slot'):
                    if booking.tutor_meet_link == meet_link:
                        continue
                    booking.tutor_meet_link = meet_link
                    booking.save(update_fields=['tutor_meet_link', 'updated_at'])
                    history.record(
                        booking, BookingEventKind.MEET_LINK_UPDATED, actor=actor, has_meet_link=meet_link is not None,
                    )
                    # Its unsent confirmed message goes with the new link, or waits for one.
                    planner.refresh_messages(booking, now)
                    changed.append(booking)
    except OperationalError as exc:
        if getattr(exc.__cause__, 'sqlstate', None) in BUSY_SQLSTATES:
            raise BookingBusy() from exc
        raise
    return account, True, sorted(changed, key=lambda booking: (booking.slot.starts_at, booking.created_at))


def close_slot(booking_type, local_date, local_time, actor=None, reason=''):
    """Close one slot: it shows as Fully Booked and takes no new booking. Returns (slot, changed)."""
    with transaction.atomic():
        _set_lock_timeout()
        slot = _locked_slot(booking_type, local_date, local_time)
        if slot.closed_at is not None:
            return slot, False
        slot.closed_at = timezone.now()
        slot.closed_by = actor
        slot.close_reason = reason or ''
        slot.save(update_fields=['closed_at', 'closed_by', 'close_reason'])
    _log_slot(slot, 'booking_slot.close', actor, slot.close_reason)
    return slot, True


def reopen_slot(booking_type, local_date, local_time, actor=None):
    """Reopen a closed slot. Returns (slot or None, changed)."""
    with transaction.atomic():
        _set_lock_timeout()
        slot = (
            BookingSlot.objects.select_for_update()
            .filter(booking_type=booking_type, local_date=local_date, local_time=local_time)
            .first()
        )
        if slot is None or slot.closed_at is None:
            return slot, False
        slot.closed_at = None
        slot.closed_by = None
        slot.close_reason = ''
        slot.save(update_fields=['closed_at', 'closed_by', 'close_reason'])
    _log_slot(slot, 'booking_slot.reopen', actor, '')
    return slot, True


def set_slots_closed(booking_type, local_date, times, closed, actor=None, reason=''):
    """
    Close (``closed=True``) or reopen several slots of one date together: all
    of them, or -- when a slot stays locked past LOCK_TIMEOUT -- none
    (BookingBusy). Bookings are never touched: a closed slot keeps the ones it
    holds, and a reopened one takes new ones only while seats remain. Slots
    are locked in time order, so two such changes cannot deadlock. Returns the
    times whose state changed.
    """
    changed = []
    try:
        with transaction.atomic():
            for start in sorted(set(times)):
                if closed:
                    _slot, did_change = close_slot(booking_type, local_date, start, actor=actor, reason=reason)
                else:
                    _slot, did_change = reopen_slot(booking_type, local_date, start, actor=actor)
                if did_change:
                    changed.append(start)
    except OperationalError as exc:
        if getattr(exc.__cause__, 'sqlstate', None) in BUSY_SQLSTATES:
            raise BookingBusy() from exc
        raise
    return changed


def set_schedule(booking_type, times, actor=None, via='model'):
    """
    Make ``times`` exactly the active times of ``booking_type``: listed times
    are created or reactivated, the others deactivated (never deleted, so
    bookings made at a retired time keep their slot). Returns (added, removed).
    """
    wanted = set(times)
    with transaction.atomic():
        current = {entry.start_time: entry for entry in SlotTime.objects.select_for_update().filter(booking_type=booking_type)}
        added = sorted(t for t in wanted if t not in current or not current[t].is_active)
        removed = sorted(t for t, entry in current.items() if entry.is_active and t not in wanted)
        for start in added:
            SlotTime.objects.update_or_create(booking_type=booking_type, start_time=start, defaults={'is_active': True})
        SlotTime.objects.filter(booking_type=booking_type, start_time__in=removed).update(is_active=False, updated_at=timezone.now())
    if added or removed:
        log_activity(
            action='booking_schedule.update',
            entity_type='booking_schedule',
            entity_id=booking_type,
            entity_label=f'{booking_type.title()} schedule',
            changes={'times': {
                'old': sorted(_hhmm(t) for t, entry in current.items() if entry.is_active),
                'new': sorted(_hhmm(t) for t in wanted),
            }},
            context={'added': [_hhmm(t) for t in added], 'removed': [_hhmm(t) for t in removed], 'via': via},
            actor=actor,
        )
    return added, removed


def slot_label(slot):
    """'Demo · 28 Oct 2026, 19:30 IST' -- what the activity log names a slot by."""
    return f'{slot.get_booking_type_display()} · {slot.local_date:%d %b %Y}, {_hhmm(slot.local_time)} IST'


# ---------------------------------------------------------------- helpers

def _set_lock_timeout():
    if connection.vendor == 'postgresql':
        with connection.cursor() as cursor:
            cursor.execute(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT}'")


def _locked_slot(booking_type, local_date, local_time):
    starts_at, ends_at = slot_instants(local_date, local_time)
    slot, _created = BookingSlot.objects.get_or_create(
        booking_type=booking_type,
        local_date=local_date,
        local_time=local_time,
        defaults={'starts_at': starts_at, 'ends_at': ends_at},
    )
    return BookingSlot.objects.select_for_update().get(pk=slot.pk)


def _locked_lead(lead_id):
    """
    Lead ``lead_id`` read under its row lock, FOR NO KEY UPDATE: the lead-level
    lock every booking of the child queues on (Q26, design B.7), taken after
    the slot locks and before the booking's. NO KEY leaves rows that only
    reference the lead (a new booking, an event) unblocked.
    """
    return Lead.objects.select_for_update(no_key=True).get(pk=lead_id)


def _locked_booking(booking):
    """``booking`` read again under its slot's lock and then its own: the order every booking write takes them in."""
    BookingSlot.objects.select_for_update().filter(pk=booking.slot_id).first()
    return type(booking).objects.select_for_update(of=('self',)).select_related('slot', 'lead').get(pk=booking.pk)


def _cancel_locked(booking, reason_code, actor, now, extra_fields=()):
    """
    Cancel ``booking``, already read under its locks and checked, for
    ``reason_code``: its status, its history and its communication -- open
    tasks cancelled, unsent messages stopped -- in the caller's transaction.
    ``extra_fields`` are other fields the caller changed, saved with it.
    """
    previous_status = booking.status
    booking.status = BookingStatus.CANCELLED
    booking.cancelled_at = timezone.now()
    booking.cancelled_by = actor
    booking.cancel_reason_code = reason_code
    booking.save(update_fields=[
        'status', 'cancelled_at', 'cancelled_by', 'cancel_reason_code', *extra_fields, 'updated_at',
    ])
    history.record(
        booking, BookingEventKind.CANCELLED, actor=actor,
        from_status=previous_status, to_status=booking.status, reason_code=reason_code,
    )
    planner.booking_cancelled(booking, now)


def _log_cancellation(booking, reason_code, actor):
    log_activity(
        action='booking.cancel',
        entity_type='booking',
        entity_id=booking.id,
        entity_label=slot_label(booking.slot),
        # The code only, never a free-text reason (M1).
        context={'booking_type': booking.booking_type, 'reason_code': reason_code, 'lead_id': str(booking.lead_id)},
        actor=actor,
    )


def _check_tutor_changeable(booking, now):
    if booking.status == BookingStatus.COMPLETED:
        raise BookingCompleted()
    if booking.status == BookingStatus.RESCHEDULED:
        raise BookingRescheduled()
    if booking.status != BookingStatus.BOOKED:
        raise BookingCancelled()
    if booking.started_at is not None:
        raise BookingStarted()
    if booking.slot.ends_at <= now:
        raise SlotEnded()


def _locked_tutor(tutor_id):
    """
    Account ``tutor_id``, or None, once nothing else is scheduling it: first
    the tutor's scheduling lock (sessions.services.lock_tutor_schedule, the
    tutor key of lock_scheduling), which a class being scheduled for this
    tutor holds until it commits, so the conflict check then sees it; then the
    account row, locked FOR NO KEY UPDATE like Team's
    (accounts.team.locked_staff_account), so the account cannot be deactivated
    before this assignment commits. NO KEY leaves rows that only reference the
    account (a new session, a log entry) unblocked.
    """
    lock_tutor_schedule(tutor_id)
    return User.objects.select_for_update(no_key=True).filter(pk=tutor_id).first()


def _log_tutor_change(booking, action, actor, old_tutor_id, new_tutor_id):
    log_activity(
        action=action,
        entity_type='booking',
        entity_id=booking.id,
        entity_label=slot_label(booking.slot),
        # Ids only, as for every booking entry: no student, parent, phone or tutor name.
        context={
            'booking_type': booking.booking_type,
            'slot_starts_at': booking.slot.starts_at.isoformat(),
            'lead_id': str(booking.lead_id),
            'old_tutor_id': _str_or_none(old_tutor_id),
            'new_tutor_id': _str_or_none(new_tutor_id),
        },
        actor=actor,
    )


def _bookings_since(phone_key, since):
    """How many bookings, of either type, the phone number ``phone_key`` has made since ``since``."""
    return sum(
        model.objects.filter(lead__phone_key=phone_key, created_at__gte=since).count() for model in BOOKING_MODELS
    )


def _lead_details(request):
    return {
        'parent_name': request.parent_name,
        'phone_dial_code': request.phone_dial_code,
        'phone_number': request.phone_number,
        'student_name': request.student_name,
        'school': request.school,
        'student_class': request.student_class,
        'syllabus': request.syllabus,
        'country': request.country,
    }


def _submitted(request):
    return {
        'parent_name': request.parent_name,
        'phone': f'{request.phone_dial_code} {request.phone_number}',
        'student_name': request.student_name,
        'school': request.school,
        'student_class': request.student_class,
        'syllabus': request.syllabus,
        'country': request.country,
        'display_time': request.display_time,
    }


def _log_slot(slot, action, actor, reason):
    log_activity(
        action=action,
        entity_type='booking_slot',
        entity_id=slot.id,
        entity_label=slot_label(slot),
        context={'booking_type': slot.booking_type, 'reason': reason} if reason else {'booking_type': slot.booking_type},
        actor=actor,
    )


def _hhmm(value):
    return value.strftime('%H:%M')


def _str_or_none(value):
    return str(value) if value else None
