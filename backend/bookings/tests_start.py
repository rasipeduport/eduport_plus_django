"""
Start Demo / Start Diagnostic (booking_service.start_booking, POST
/api/tutor/bookings/<type>/<id>/start/): only the assigned tutor starts a
booking, only from five minutes before its slot until the slot ends, and
once -- and what a start, or its absence, means everywhere else: where the
booking stands (bookings.lifecycle), tutor changes and moves (D3, D4),
No-show, the Meet room, parent communication, the Admin's and the BDE's
read-only views and the BDE's enquiry status (D5) -- including under
concurrency.
"""
import json
import threading
from datetime import timedelta
from itertools import count
from unittest import skipUnless

from django.contrib.auth.models import Permission
from django.db import IntegrityError, connection, transaction
from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import RoleGroup
from activity.models import ActivityLog
from communications.overview import booking_communication
from communications.services import BookingNotUpcoming, request_confirmation
from communications.tests_planning import MEET_LINK
from reports.services import submit_report
from reports.tests_services import report_input

from .booking_service import (
    BookingNotAssigned,
    BookingStarted,
    CancelledNotStartable,
    CompletedNotStartable,
    NoShowBeforeStart,
    RescheduledNotStartable,
    StartedNotConfirmable,
    StartedNotMovable,
    StartTooEarly,
    StartWindowClosed,
    assign_tutor,
    cancel_booking,
    create_booking,
    record_parent_confirmation,
    reschedule_booking,
    set_tutor_meet_link,
    start_booking,
)
from .lifecycle import START_EARLY, ActivityState, activity_state
from .models import (
    BookingEventKind,
    BookingSlot,
    BookingStatus,
    CancelReason,
    DemoBooking,
    Lead,
    ParentConfirmation,
    ReferralStatus,
    RescheduleReason,
)
from .scheduling import BOOKING_TIMEZONE, indian_today
from .tests_booking import DAY, DEMO, DIAGNOSTIC, EVENING, MORNING, NOW, account, request, schedule, start

PHONES = count()


def phone():
    return f'05066{next(PHONES):05d}'


def booked(student, tutor=None, admin=None, booking_type=DEMO, day=DAY, at=EVENING, now=NOW):
    """A public booking of ``student``'s (a lead of its own), given to ``tutor`` when one is named."""
    booking, _ = create_booking(
        request(student=student, phone=phone(), booking_type=booking_type, day=day, at=at), now=now,
    )
    if tutor is not None:
        booking = assign_tutor(booking, tutor, actor=admin, now=now)[0]
    return booking


def on_the_clock(tutor, admin, minutes=-10, student='Kiran'):
    """
    A Demo whose slot starts ``minutes`` from now by the real clock (ten
    minutes ago by default), written straight to its tables -- the booking
    pages never offer today -- and given to ``tutor``.
    """
    starts_at = timezone.now() + timedelta(minutes=minutes)
    local = starts_at.astimezone(BOOKING_TIMEZONE)
    slot = BookingSlot.objects.create(
        booking_type=DEMO, local_date=local.date(), local_time=local.time().replace(tzinfo=None),
        starts_at=starts_at, ends_at=starts_at + timedelta(hours=1),
    )
    number = phone()
    lead = Lead.objects.create(
        parent_name='Asha Nair', phone_dial_code='+971', phone_number=number[1:], phone_key=f'+971{number[1:]}',
        student_name=student, student_name_key=student.lower(), school_name='Delhi Private School',
        grade='Class 8', syllabus='CBSE',
    )
    booking = DemoBooking.objects.create(lead=lead, slot=slot, seat=1, referral_status=ReferralStatus.NO_REF)
    return assign_tutor(booking, tutor, actor=admin, now=starts_at - timedelta(minutes=30))[0]


class StartTestCase(TestCase):
    def setUp(self):
        schedule()
        self.admin = account('admin_one', role='ADMIN')
        self.tutor = account('tutor_anu', role='TUTOR')
        self.other_tutor = account('tutor_binu', role='TUTOR')
        # A Demo at 19:30 IST on 28 Oct 2026, taught by Anu; NOW is the day before.
        self.booking = self.booked('Riya')

    def booked(self, student, days=0, tutor=True, **kwargs):
        return booked(student, self.tutor if tutor else None, self.admin, day=DAY + timedelta(days=days), **kwargs)

    def start(self, booking, at, tutor=None):
        return start_booking(booking, tutor or self.tutor, now=at)

    def fresh(self, booking):
        return type(booking).objects.select_related('slot').get(pk=booking.pk)

    def assertNotStarted(self, booking):
        booking = self.fresh(booking)
        self.assertEqual((booking.started_at, booking.started_by), (None, None))
        self.assertFalse(booking.events.filter(kind=BookingEventKind.STARTED).exists())
        self.assertFalse(ActivityLog.objects.filter(action='booking.start', entity_id=str(booking.id)).exists())


# ------------------------------------------------------------------ the start

class StartTests(StartTestCase):
    def test_start_opens_exactly_five_minutes_before_the_slot(self):
        opens = self.booking.slot.starts_at - timedelta(minutes=5)
        with self.assertRaises(StartTooEarly) as refused:
            self.start(self.booking, opens - timedelta(seconds=1))
        self.assertEqual((refused.exception.code, refused.exception.http_status), ('START_TOO_EARLY', 409))
        self.assertNotStarted(self.booking)

        booking, changed = self.start(self.booking, opens)
        self.assertTrue(changed)
        self.assertEqual((booking.started_at, booking.started_by, booking.status), (opens, self.tutor, BookingStatus.BOOKED))
        self.assertEqual(self.fresh(self.booking).started_at, opens)

    def test_start_stays_open_until_the_slot_ends(self):
        at_start = self.booked('Ali', days=1)
        self.assertEqual(self.start(at_start, at_start.slot.starts_at)[0].started_at, at_start.slot.starts_at)
        last_moment = self.booked('Sara', days=2, booking_type=DIAGNOSTIC)
        self.assertTrue(self.start(last_moment, last_moment.slot.ends_at - timedelta(seconds=1))[1])
        ended = self.booked('Noor', days=3)
        for moment in (ended.slot.ends_at, ended.slot.ends_at + timedelta(days=1)):
            with self.subTest(now=moment), self.assertRaises(StartWindowClosed) as refused:
                self.start(ended, moment)
            self.assertEqual(refused.exception.code, 'START_WINDOW_CLOSED')
        self.assertNotStarted(ended)

    def test_the_server_clock_is_what_is_recorded(self):
        live = on_the_clock(self.tutor, self.admin)
        before = timezone.now()
        booking, changed = start_booking(live, self.tutor)
        self.assertTrue(changed)
        self.assertTrue(before <= booking.started_at <= timezone.now())

    def test_only_the_assigned_tutor_starts_it(self):
        at = self.booking.slot.starts_at
        with self.assertRaises(BookingNotAssigned) as refused:
            self.start(self.booking, at, tutor=self.other_tutor)
        self.assertEqual((refused.exception.code, refused.exception.http_status), ('NOT_FOUND', 404))
        unassigned = self.booked('Ali', days=1, tutor=False)
        with self.assertRaises(BookingNotAssigned):
            self.start(unassigned, unassigned.slot.starts_at)
        # Reassigned since the tutor's page was read: the check is the booking as it is under its lock.
        reassigned = self.booked('Sara', days=2)
        assign_tutor(reassigned, self.other_tutor, actor=self.admin, now=NOW)
        with self.assertRaises(BookingNotAssigned):
            self.start(reassigned, reassigned.slot.starts_at)
        for booking in (self.booking, unassigned, reassigned):
            self.assertNotStarted(booking)
        self.assertTrue(self.start(reassigned, reassigned.slot.starts_at, tutor=self.other_tutor)[1])

    def test_only_a_booked_booking(self):
        cancel_booking(self.booking, reason_code=CancelReason.PARENT_REQUEST, actor=self.admin, now=NOW)
        with self.assertRaises(CancelledNotStartable) as refused:
            self.start(self.booking, self.booking.slot.starts_at)
        self.assertEqual(refused.exception.code, 'BOOKING_CANCELLED')

        moved = self.booked('Ali', days=1)
        result = reschedule_booking(moved, DAY + timedelta(days=2), EVENING, reason_code=RescheduleReason.OTHER,
                                    actor=self.admin, now=NOW)
        with self.assertRaises(RescheduledNotStartable) as refused:
            self.start(moved, moved.slot.starts_at)
        self.assertEqual(refused.exception.code, 'BOOKING_RESCHEDULED')
        # The booking that replaced it is the one to start: its tutor carried over.
        self.assertTrue(self.start(result.booking, result.booking.slot.starts_at)[1])

        completed = start(self.booked('Sara', days=3))
        submit_report(completed, self.tutor, report_input(completed), now=completed.slot.starts_at + timedelta(minutes=30))
        with self.assertRaises(CompletedNotStartable) as refused:
            self.start(completed, completed.slot.starts_at + timedelta(minutes=40))
        self.assertEqual(refused.exception.code, 'BOOKING_COMPLETED')
        for booking in (self.booking, moved):
            self.assertNotStarted(booking)

    def test_a_second_start_changes_nothing(self):
        first, changed = self.start(self.booking, self.booking.slot.starts_at)
        self.assertTrue(changed)
        # Another click, another tab -- even once the slot is over.
        for again in (self.booking.slot.starts_at + timedelta(minutes=10), self.booking.slot.ends_at + timedelta(days=1)):
            with self.subTest(now=again):
                booking, changed = self.start(self.booking, again)
                self.assertFalse(changed)
                self.assertEqual(booking.started_at, first.started_at)
        self.assertEqual(self.booking.events.filter(kind=BookingEventKind.STARTED).count(), 1)
        self.assertEqual(ActivityLog.objects.filter(action='booking.start').count(), 1)

    def test_the_history_and_the_activity_log_keep_ids_and_instants_only(self):
        at = self.booking.slot.starts_at + timedelta(minutes=2)
        booking, _ = self.start(self.booking, at)
        event = booking.events.get(kind=BookingEventKind.STARTED)
        self.assertEqual((event.actor, event.data), (self.tutor, {}))
        entry = ActivityLog.objects.get(action='booking.start')
        self.assertEqual((entry.entity_type, entry.entity_id, entry.actor), ('booking', str(booking.id), self.tutor))
        self.assertEqual(entry.entity_label, 'Demo · 28 Oct 2026, 19:30 IST')
        self.assertEqual(entry.context, {
            'booking_type': DEMO, 'slot_starts_at': booking.slot.starts_at.isoformat(), 'started_at': at.isoformat(),
            'lead_id': str(booking.lead_id),
        })
        for private in ('Riya', 'Asha', '50666'):
            self.assertNotIn(private, json.dumps([entry.entity_label, entry.changes, entry.context]))

    def test_the_database_keeps_a_start_with_its_tutor(self):
        unassigned = self.booked('Ali', days=1, tutor=False)
        moved = self.booked('Sara', days=2)
        reschedule_booking(moved, DAY + timedelta(days=3), EVENING, reason_code=RescheduleReason.OTHER, now=NOW)
        cases = (
            (unassigned, {'started_at': NOW}),
            (self.booking, {'started_by': self.tutor}),
            (moved, {'started_at': NOW}),
        )
        for booking, fields in cases:
            with self.subTest(fields=list(fields)), self.assertRaises(IntegrityError), transaction.atomic():
                DemoBooking.objects.filter(pk=booking.pk).update(**fields)


class ActivityStateTests(StartTestCase):
    def test_where_a_booked_booking_stands_by_the_clock_and_its_start(self):
        slot = self.booking.slot
        opens = slot.starts_at - START_EARLY
        cases = (
            (opens - timedelta(seconds=1), ActivityState.UPCOMING),
            (opens, ActivityState.READY),
            (slot.starts_at - timedelta(seconds=1), ActivityState.READY),
            # The scheduled time alone starts nothing: late, then not started at all.
            (slot.starts_at, ActivityState.LATE),
            (slot.ends_at - timedelta(seconds=1), ActivityState.LATE),
            (slot.ends_at, ActivityState.NOT_STARTED),
            (slot.ends_at + timedelta(days=30), ActivityState.NOT_STARTED),
        )
        for now, state in cases:
            with self.subTest(now=now):
                self.assertEqual(activity_state(self.booking, now), state)
        started = self.start(self.booking, slot.starts_at + timedelta(minutes=3))[0]
        for now in (slot.starts_at + timedelta(minutes=3), slot.ends_at + timedelta(days=1)):
            self.assertEqual(activity_state(started, now), ActivityState.IN_PROGRESS)

    def test_a_status_decides_the_rest(self):
        completed = start(self.booked('Ali', days=1))
        submit_report(completed, self.tutor, report_input(completed), now=completed.slot.starts_at + timedelta(minutes=30))
        cancelled = self.booked('Sara', days=2)
        cancel_booking(cancelled, reason_code=CancelReason.OTHER, now=NOW)
        moved = self.booked('Noor', days=3)
        reschedule_booking(moved, DAY + timedelta(days=4), EVENING, reason_code=RescheduleReason.OTHER, now=NOW)
        for booking, state in ((completed, 'COMPLETED'), (cancelled, 'CANCELLED'), (moved, 'RESCHEDULED')):
            with self.subTest(state=state):
                self.assertEqual(activity_state(self.fresh(booking), NOW), state)


class AfterStartRuleTests(StartTestCase):
    def test_no_show_follows_the_scheduled_time_not_the_start(self):
        early = self.booking.slot.starts_at - timedelta(minutes=4)
        start(self.booking, minutes=-5)
        with self.assertRaises(NoShowBeforeStart):
            cancel_booking(self.booking, reason_code=CancelReason.NO_SHOW, actor=self.admin, now=early)
        # Once the scheduled time has passed: a No-show whether or not the tutor started.
        never = self.booked('Ali', days=1)
        self.assertTrue(cancel_booking(never, reason_code=CancelReason.NO_SHOW, now=never.slot.starts_at)[1])
        at = self.booking.slot.starts_at + timedelta(minutes=15)
        booking, changed = cancel_booking(self.booking, reason_code=CancelReason.NO_SHOW, actor=self.admin, now=at)
        self.assertTrue(changed)
        # A cancelled booking keeps the start it had, as history.
        booking = self.fresh(booking)
        self.assertEqual((booking.status, booking.started_by), (BookingStatus.CANCELLED, self.tutor))
        self.assertEqual(activity_state(booking, at), ActivityState.CANCELLED)

    def test_a_started_booking_is_neither_moved_nor_given_another_tutor(self):
        start(self.booking)
        changes = (
            (lambda: reschedule_booking(self.booking, DAY + timedelta(days=1), EVENING,
                                        reason_code=RescheduleReason.OTHER, now=NOW), StartedNotMovable),
            (lambda: assign_tutor(self.booking, self.other_tutor, now=NOW), BookingStarted),
        )
        for change, error in changes:
            with self.subTest(error=error.__name__), self.assertRaises(error) as refused:
                change()
            self.assertEqual(refused.exception.code, 'BOOKING_STARTED')
        booking = self.fresh(self.booking)
        self.assertEqual((booking.status, booking.assigned_tutor), (BookingStatus.BOOKED, self.tutor))

    def test_a_started_booking_keeps_its_meet_room(self):
        start(self.booking)
        later = self.booked('Ali', days=1)
        _tutor, changed, bookings = set_tutor_meet_link(
            self.tutor, MEET_LINK, actor=self.admin, now=self.booking.slot.starts_at + timedelta(minutes=10),
        )
        self.assertTrue(changed)
        self.assertEqual([booking.pk for booking in bookings], [later.pk])
        self.assertEqual((self.fresh(self.booking).tutor_meet_link, self.fresh(later).tutor_meet_link), (None, MEET_LINK))

    def test_parent_communication_stops_at_the_start(self):
        early = self.booking.slot.starts_at - timedelta(minutes=4)
        actions = booking_communication(self.fresh(self.booking), early, self.admin)['actions']
        self.assertEqual(actions, {'request_confirmation': True, 'record_confirmation': True})
        start(self.booking, minutes=-5)
        booking = self.fresh(self.booking)
        actions = booking_communication(booking, early, self.admin)['actions']
        self.assertEqual(actions, {'request_confirmation': False, 'record_confirmation': False})
        with self.assertRaises(BookingNotUpcoming):
            request_confirmation(booking, actor=self.admin, now=early)
        for outcome in (ParentConfirmation.CONFIRMED, ParentConfirmation.NOT_CONFIRMED):
            with self.subTest(outcome=outcome), self.assertRaises(StartedNotConfirmable) as refused:
                record_parent_confirmation(booking, outcome, reason_code='NO_RESPONSE', confirm_cancellation=True,
                                           actor=self.admin, now=early)
            self.assertEqual(refused.exception.code, 'BOOKING_STARTED')
        booking = self.fresh(booking)
        self.assertEqual((booking.status, booking.parent_confirmation), (BookingStatus.BOOKED, ParentConfirmation.AWAITING))


# ------------------------------------------------------------- concurrency

@skipUnless(connection.vendor == 'postgresql', 'the booking locks need PostgreSQL row locking')
class ConcurrentStartTests(TransactionTestCase):
    """Real threads, each with its own database connection, starting together."""

    def setUp(self):
        schedule()
        self.admin = account('admin_race', role='ADMIN')
        self.tutor = account('tutor_race', role='TUTOR')
        self.other_tutor = account('tutor_other', role='TUTOR')

    def race(self, calls):
        barrier = threading.Barrier(len(calls))
        outcomes = [None] * len(calls)

        def run(index, call):
            try:
                barrier.wait(timeout=10)
                outcomes[index] = call()
            except Exception as exc:  # the outcome, reported in the assertion
                outcomes[index] = type(exc).__name__
            finally:
                connection.close()

        threads = [threading.Thread(target=run, args=(i, call)) for i, call in enumerate(calls)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        return outcomes

    def booking(self, student, days=0):
        return booked(student, self.tutor, self.admin, day=DAY + timedelta(days=days))

    def starter(self, booking, tutor=None):
        at = booking.slot.starts_at + timedelta(minutes=1)
        return lambda: 'started' if start_booking(booking, tutor or self.tutor, now=at)[1] else 'unchanged'

    def fresh(self, booking):
        return DemoBooking.objects.get(pk=booking.pk)

    def test_two_starts_at_once_record_one(self):
        booking = self.booking('Riya')
        outcomes = self.race([self.starter(booking), self.starter(booking)])
        self.assertEqual(sorted(outcomes), ['started', 'unchanged'], outcomes)
        self.assertEqual(booking.events.filter(kind=BookingEventKind.STARTED).count(), 1)
        self.assertEqual(ActivityLog.objects.filter(action='booking.start').count(), 1)

    def test_a_start_racing_a_cancellation(self):
        for round_ in range(3):
            booking = self.booking(f'Child {round_}', days=round_)
            at = booking.slot.starts_at + timedelta(minutes=1)

            def cancel(booking=booking, at=at):
                return cancel_booking(booking, reason_code=CancelReason.NO_SHOW, actor=self.admin, now=at)[1] and 'cancelled'

            outcomes = self.race([self.starter(booking), cancel])
            self.assertIn(sorted(outcomes), (['cancelled', 'started'], ['CancelledNotStartable', 'cancelled']), outcomes)
            booking = self.fresh(booking)
            # Cancelled either way; started only if the start went first -- never a start after the cancellation.
            self.assertEqual(booking.status, BookingStatus.CANCELLED)
            self.assertEqual(booking.started_at is not None, 'started' in outcomes)

    def test_a_start_racing_a_reassignment(self):
        for round_ in range(3):
            booking = self.booking(f'Child {round_}', days=round_)
            at = booking.slot.starts_at + timedelta(minutes=1)

            def reassign(booking=booking, at=at):
                return assign_tutor(booking, self.other_tutor, actor=self.admin, now=at)[1] and 'reassigned'

            outcomes = self.race([self.starter(booking), reassign])
            self.assertIn(sorted(outcomes), (['BookingStarted', 'started'], ['BookingNotAssigned', 'reassigned']), outcomes)
            booking = self.fresh(booking)
            # A start is always by the tutor who teaches it.
            if booking.started_at is not None:
                self.assertEqual((booking.started_by_id, booking.assigned_tutor_id), (self.tutor.pk, self.tutor.pk))
            else:
                self.assertEqual(booking.assigned_tutor_id, self.other_tutor.pk)

    def test_a_start_racing_a_reschedule(self):
        for round_ in range(3):
            booking = self.booking(f'Child {round_}', days=round_)
            at = booking.slot.starts_at - timedelta(minutes=2)

            def move(booking=booking, at=at, round_=round_):
                reschedule_booking(booking, DAY + timedelta(days=4 + round_), MORNING,
                                   reason_code=RescheduleReason.OTHER, actor=self.admin, now=at)
                return 'moved'

            def begin(booking=booking, at=at):
                return start_booking(booking, self.tutor, now=at)[1] and 'started'

            outcomes = self.race([begin, move])
            self.assertIn(sorted(outcomes), (['StartedNotMovable', 'started'], ['RescheduledNotStartable', 'moved']), outcomes)
            booking = self.fresh(booking)
            # Never moved once started, never started once moved.
            self.assertEqual(
                (booking.status, booking.started_at is not None),
                (BookingStatus.BOOKED, True) if 'started' in outcomes else (BookingStatus.RESCHEDULED, False),
            )


# ------------------------------------------------------------------ the API

def start_url(booking, booking_type=None):
    return f'/api/tutor/bookings/{(booking_type or booking.booking_type).lower()}/{booking.id}/start/'


class StartApiTestCase(APITestCase):
    def setUp(self):
        schedule()
        self.admin = account('admin_one', role='ADMIN')
        self.tutor = account('tutor_anu', role='TUTOR')
        self.other_tutor = account('tutor_binu', role='TUTOR')
        self.bde = account('bde_one', role='BDE')
        self.client.force_authenticate(self.tutor)

    def as_user(self, user):
        self.client.force_authenticate(user=type(user).objects.get(pk=user.pk))

    def ahead(self, student='Ali', days=2, tutor=True):
        """A Demo two days ahead, by the real clock, given to the tutor."""
        made = booked(student, now=timezone.now(), day=indian_today() + timedelta(days=days))
        return assign_tutor(made, self.tutor, actor=self.admin)[0] if tutor else made

    def yesterday(self, student, owner=None, at=EVENING):
        """Yesterday's Demo, booked and given to the tutor three days ago."""
        then = timezone.now() - timedelta(days=3)
        made = booked(student, self.tutor, self.admin, day=indian_today() - timedelta(days=1), at=at, now=then)
        if owner is not None:
            Lead.objects.filter(pk=made.lead_id).update(owner_bde=owner, owner_assigned_at=then)
        return made

    def assertRefused(self, response, http_status, code):
        self.assertEqual((response.status_code, response.json()['error']), (http_status, code), response.content)
        self.assertTrue(response.json()['message'])


class StartApiTests(StartApiTestCase):
    def test_the_assigned_tutor_starts_it(self):
        live = on_the_clock(self.tutor, self.admin)
        response = self.client.post(start_url(live))
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual((set(body), body['changed']), ({'booking', 'changed'}, True))
        shown = body['booking']
        self.assertEqual(
            (shown['id'], shown['status'], shown['activity_state'], shown['actions'], shown['start_refusal']['code']),
            (str(live.id), 'BOOKED', 'IN_PROGRESS', {'start': False}, 'BOOKING_STARTED'),
        )
        live.refresh_from_db()
        self.assertEqual((shown['started_at'], live.started_by), (live.started_at.isoformat(), self.tutor))
        # Again (a second click): nothing changes.
        again = self.client.post(start_url(live)).json()
        self.assertEqual((again['changed'], again['booking']['started_at']), (False, shown['started_at']))
        self.assertEqual(live.events.filter(kind=BookingEventKind.STARTED).count(), 1)
        # The tutor's list shows it started.
        row = self.client.get('/api/tutor/bookings/').json()['results'][0]
        self.assertEqual((row['started_at'], row['activity_state']), (shown['started_at'], 'IN_PROGRESS'))

    def test_the_list_offers_start_only_while_it_is_open(self):
        late = on_the_clock(self.tutor, self.admin, minutes=-10, student='Kiran')
        ready = on_the_clock(self.tutor, self.admin, minutes=63, student='Meera')
        ahead = self.ahead()
        rows = {row['id']: row for row in self.client.get('/api/tutor/bookings/').json()['results']}
        self.assertEqual(
            {booking_id: (row['activity_state'], row['actions']['start'], (row['start_refusal'] or {}).get('code'))
             for booking_id, row in rows.items()},
            {
                str(late.id): ('LATE', True, None),
                str(ready.id): ('UPCOMING', False, 'START_TOO_EARLY'),
                str(ahead.id): ('UPCOMING', False, 'START_TOO_EARLY'),
            },
        )
        self.assertEqual(rows[str(ready.id)]['start_opens_at'], (ready.slot.starts_at - START_EARLY).isoformat())
        BookingSlot.objects.filter(pk=ready.slot_id).update(
            starts_at=timezone.now() + timedelta(minutes=3), ends_at=timezone.now() + timedelta(minutes=63),
        )
        shown = self.client.get(f'/api/tutor/bookings/demo/{ready.id}/').json()
        self.assertEqual((shown['activity_state'], shown['actions'], shown['start_refusal']), ('READY', {'start': True}, None))
        self.assertEqual(self.client.post(start_url(ready)).status_code, 200)

    def test_every_refusal_answers_its_code_and_writes_nothing(self):
        self.assertRefused(self.client.post(start_url(self.ahead())), 409, 'START_TOO_EARLY')
        ended = on_the_clock(self.tutor, self.admin, minutes=-90)
        self.assertRefused(self.client.post(start_url(ended)), 409, 'START_WINDOW_CLOSED')
        self.assertEqual(self.client.get(f'/api/tutor/bookings/demo/{ended.id}/').json()['activity_state'], 'NOT_STARTED')
        cancelled = on_the_clock(self.tutor, self.admin, minutes=-10, student='Sara')
        cancel_booking(cancelled, reason_code=CancelReason.PARENT_REQUEST, actor=self.admin)
        self.assertRefused(self.client.post(start_url(cancelled)), 409, 'BOOKING_CANCELLED')
        self.assertFalse(ActivityLog.objects.filter(action='booking.start').exists())

    def test_only_the_assigned_tutor_reaches_it(self):
        live = on_the_clock(self.tutor, self.admin)
        self.as_user(self.other_tutor)
        self.assertEqual(self.client.post(start_url(live)).json(), {'error': 'NOT_FOUND', 'message': 'No such booking.'})
        self.as_user(self.tutor)
        unassigned = self.ahead(student='Noor', tutor=False)
        self.assertRefused(self.client.post(start_url(unassigned)), 404, 'NOT_FOUND')
        self.assertEqual(self.client.post(f'/api/tutor/bookings/session/{live.id}/start/').status_code, 404)
        self.assertEqual(self.client.post(start_url(live, booking_type=DIAGNOSTIC)).status_code, 404)
        for who in (self.admin, self.bde, account('mentor_one', role='MENTOR')):
            with self.subTest(caller=who.role):
                self.as_user(who)
                self.assertEqual(self.client.post(start_url(live)).status_code, status.HTTP_403_FORBIDDEN)
        self.client.force_authenticate(user=None)
        self.assertEqual(self.client.post(start_url(live)).status_code, status.HTTP_403_FORBIDDEN)
        live.refresh_from_db()
        self.assertIsNone(live.started_at)

    def test_a_tutor_without_the_report_permission_cannot_start(self):
        live = on_the_clock(self.tutor, self.admin)
        group = RoleGroup.objects.select_related('group').get(role='TUTOR').group
        group.permissions.remove(Permission.objects.get(codename='submit_booking_report'))
        self.as_user(self.tutor)
        shown = self.client.get(f'/api/tutor/bookings/demo/{live.id}/').json()
        self.assertEqual((shown['actions'], shown['start_refusal']['code']), ({'start': False}, 'PERMISSION_DENIED'))
        self.assertEqual(self.client.post(start_url(live)).status_code, status.HTTP_403_FORBIDDEN)
        live.refresh_from_db()
        self.assertIsNone(live.started_at)


class ReadOnlyStartTests(StartApiTestCase):
    def test_the_admin_sees_the_start_and_what_it_rules_out(self):
        live = on_the_clock(self.tutor, self.admin)
        self.client.post(start_url(live))
        self.as_user(self.admin)
        detail = self.client.get(f'/api/bookings/demo/{live.id}/').json()
        live.refresh_from_db()
        self.assertEqual(
            (detail['activity_state'], detail['started_at'], detail['started_by']),
            ('IN_PROGRESS', live.started_at.isoformat(), {'id': str(self.tutor.id), 'full_name': 'Tutor Anu'}),
        )
        self.assertEqual((detail['tutor_changeable'], detail['tutor_change_refusal']['code']), (False, 'BOOKING_STARTED'))
        # Read-only: the Admin has no Start; a started booking cannot move.
        self.assertEqual(detail['actions'], {'cancel': True, 'no_show': True, 'reschedule': False})
        row = self.client.get('/api/bookings/demo/').json()['results'][0]
        self.assertEqual((row['activity_state'], row['started_at']), ('IN_PROGRESS', detail['started_at']))
        events = self.client.get(f'/api/bookings/demo/{live.id}/history/').json()['events']
        started = [event for event in events if event['kind'] == 'STARTED']
        self.assertEqual([(event['kind_label'], event['actor']['id']) for event in started], [('Started', str(self.tutor.id))])
        # Before any start: not started, and the tutor may still change until the slot ends (D4).
        other = on_the_clock(self.other_tutor, self.admin, minutes=-20, student='Sara')
        detail = self.client.get(f'/api/bookings/demo/{other.id}/').json()
        self.assertEqual((detail['activity_state'], detail['started_at'], detail['started_by']), ('LATE', None, None))
        self.assertEqual((detail['tutor_changeable'], detail['actions']['reschedule']), (True, True))

    def test_the_bde_sees_whether_it_started(self):
        taught = self.yesterday('Riya', owner=self.bde)
        start(taught)
        missed = self.yesterday('Ali', owner=self.bde, at=MORNING)
        self.as_user(self.bde)
        rows = {row['id']: row for row in self.client.get('/api/bde/enquiries/').json()['results']}
        for booking, state in ((taught, 'IN_PROGRESS'), (missed, 'NOT_STARTED')):
            with self.subTest(state=state):
                shown = self.client.get(f'/api/bde/enquiries/{booking.lead_id}/').json()['bookings'][0]
                booking.refresh_from_db()
                self.assertEqual(
                    (shown['activity_state'], shown['started_at']),
                    (state, booking.started_at.isoformat() if booking.started_at else None),
                )
                self.assertNotIn('started_by', shown)
        # D5: an enquiry is Booking done only when a class happened, never because its slot ended.
        self.assertEqual(
            (rows[str(taught.lead_id)]['status'], rows[str(missed.lead_id)]['status']), ('DONE', 'NOT_STARTED'),
        )
        self.assertEqual(rows[str(missed.lead_id)]['status_label'], 'Not started')
        only = self.client.get('/api/bde/enquiries/', {'status': 'NOT_STARTED'}).json()['results']
        self.assertEqual([row['id'] for row in only], [str(missed.lead_id)])

    def test_an_enquiry_status_follows_what_happened(self):
        missed = self.yesterday('Riya', owner=self.bde)
        number = '0' + missed.lead.phone_number

        def status_of():
            rows = self.client.get('/api/bde/enquiries/').json()['results']
            return next(row['status'] for row in rows if row['id'] == str(missed.lead_id))

        self.as_user(self.bde)
        self.assertEqual(status_of(), 'NOT_STARTED')
        # The parent books again: the booking still to come decides it.
        again, created = create_booking(request(student='Riya', phone=number, day=indian_today() + timedelta(days=2)))
        self.assertEqual((created, again.lead_id), (True, missed.lead_id))
        self.assertEqual(status_of(), 'BOOKED')
        cancel_booking(again, reason_code=CancelReason.PARENT_REQUEST)
        self.assertEqual(status_of(), 'NOT_STARTED')
        # A class that happened -- yesterday morning's Diagnostic, started and reported -- makes it done.
        then = timezone.now() - timedelta(days=3)
        diagnostic, _ = create_booking(request(
            student='Riya', phone=number, booking_type=DIAGNOSTIC, day=indian_today() - timedelta(days=1), at=MORNING,
        ), now=then)
        diagnostic = start(assign_tutor(diagnostic, self.tutor, now=then)[0])
        submit_report(diagnostic, self.tutor, report_input(diagnostic), now=diagnostic.slot.starts_at + timedelta(minutes=30))
        self.assertEqual(status_of(), 'DONE')
