"""
Booking links: the permanent, reusable links a BDE shares with parents.

Each active BDE has one active link per booking type -- a Demo link
(<marketing site>/demo?ref=<token>) and a Diagnostic link (.../exam?ref=<token>).
A link is never used up: any number of parents may book through it, and it
stays the same until it is revoked.

The token is the only thing a link carries: an opaque random string from
``secrets``, never derived from the account, so the URL does not reveal its
owner and one BDE's link says nothing about another's. It identifies the BDE
for attribution and nothing more -- it opens no lead, student or booking data,
and it is expected to travel (WhatsApp forwards, analytics page views).

Bookings: the public Demo and Diagnostic booking pages book one-hour slots,
three bookings at most per slot, on a schedule of times of day per booking
type (SlotTime). A slot on a given date (BookingSlot) exists once someone
books or closes it. Diagnostic and Demo bookings live in tables of their own
(DiagnosticBooking, DemoBooking) with the same columns (BookingBase); each
belongs to a lead (Lead): one parent's enquiry for one child, matched by phone
and student name, shared by both types. A booking is taught one-to-one by the
tutor assigned to it, and every change to it is kept in its history
(BookingEvent). bookings.booking_service is the only writer of bookings; the
leads a BDE adds by hand (their enquiries) are written by bookings.enquiries.
"""
import secrets
import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from accounts.meet_links import MEET_LINK_DB_PATTERN, MEET_LINK_MAX_LENGTH

# 16 random bytes: 128 bits, 22 URL-safe characters.
TOKEN_BYTES = 16


def new_link_token():
    """A fresh, unguessable link token."""
    return secrets.token_urlsafe(TOKEN_BYTES)


class BookingType(models.TextChoices):
    DEMO = 'DEMO', 'Demo'
    DIAGNOSTIC = 'DIAGNOSTIC', 'Diagnostic'


class BookingLink(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # PROTECT: a link is the record bookings will be attributed through, so a
    # BDE who owns one is deactivated (Team), never deleted.
    bde = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='booking_links'
    )
    booking_type = models.CharField(max_length=20, choices=BookingType.choices)
    token = models.CharField(max_length=64, unique=True, default=new_link_token, editable=False)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_booking_links'
    )
    # NULL revoked_at = active, as with User.deactivated_at. A revoked link
    # stays as history; the BDE's next request is issued a new one.
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='revoked_booking_links'
    )

    class Meta:
        db_table = 'booking_links'
        verbose_name = 'Booking link'
        verbose_name_plural = 'Booking links'
        ordering = ['-created_at']
        constraints = [
            # At most one active link per BDE and booking type. Two requests
            # issuing the same link at once cannot both succeed: the second
            # insert fails here (bookings.services reads the winner's back).
            models.UniqueConstraint(
                fields=['bde', 'booking_type'],
                condition=Q(revoked_at__isnull=True),
                name='booking_links_one_active_per_type',
            ),
            models.CheckConstraint(
                condition=Q(booking_type__in=BookingType.values),
                name='booking_links_known_type',
            ),
            models.CheckConstraint(
                condition=Q(revoked_by__isnull=True) | Q(revoked_at__isnull=False),
                name='booking_links_revoked_by_needs_revoked_at',
            ),
        ]

    def __str__(self):
        # Never the token: this shows up in the Django admin and in logs.
        state = 'revoked' if self.revoked_at else 'active'
        return f"{self.get_booking_type_display()} link of {self.bde_id} ({state})"

    @property
    def is_active(self):
        return self.revoked_at is None


# ---------------------------------------------------------------- bookings

# Every slot lasts an hour and holds at most three bookings -- the rules the
# public booking pages have always used.
SLOT_MINUTES = 60
SLOT_CAPACITY = 3


class BookingStatus(models.TextChoices):
    BOOKED = 'BOOKED', 'Booked'
    COMPLETED = 'COMPLETED', 'Completed'
    CANCELLED = 'CANCELLED', 'Cancelled'
    RESCHEDULED = 'RESCHEDULED', 'Rescheduled'


# A booking still to come and one its tutor has completed keep their seat; a
# cancelled or rescheduled one frees it.
HOLDS_SEAT = (BookingStatus.BOOKED, BookingStatus.COMPLETED)


class CancelReason(models.TextChoices):
    """
    Why a booking was cancelled: a code from this list, never free text (Q9,
    decision M1), so nothing personal reaches the permanent history. No-show
    only once the slot has started (D12).
    """
    NO_SHOW = 'NO_SHOW', 'No-show'
    PARENT_REQUEST = 'PARENT_REQUEST', 'Parent asked to cancel'
    DUPLICATE = 'DUPLICATE', 'Duplicate booking'
    BOOKED_BY_MISTAKE = 'BOOKED_BY_MISTAKE', 'Booked by mistake'
    OTHER = 'OTHER', 'Other'


class RescheduleReason(models.TextChoices):
    """Why a booking was moved to another slot: a code, never free text (Q9, M1)."""
    PARENT_REQUEST = 'PARENT_REQUEST', 'Parent asked to move'
    TUTOR_UNAVAILABLE = 'TUTOR_UNAVAILABLE', 'Tutor unavailable'
    OTHER = 'OTHER', 'Other'


class BookingChannel(models.TextChoices):
    """How a booking was made."""
    PUBLIC_PAGE = 'PUBLIC_PAGE', 'Public booking page'
    BDE_HANDOFF = 'BDE_HANDOFF', 'BDE handoff'


class ReferralStatus(models.TextChoices):
    """What a booking's ``ref`` token turned out to be (bookings.attribution)."""
    ATTRIBUTED = 'ATTRIBUTED', 'Attributed'
    NO_REF = 'NO_REF', 'No referral token'
    INVALID_REF = 'INVALID_REF', 'Malformed token'
    UNKNOWN_REF = 'UNKNOWN_REF', 'Unknown token'
    REVOKED_LINK = 'REVOKED_LINK', 'Revoked link'
    INACTIVE_BDE = 'INACTIVE_BDE', 'Link owner is not an active BDE'
    WRONG_TYPE = 'WRONG_TYPE', 'Link for the other booking type'


# Outcomes that found a BookingLink row; the rest never reached one.
REFERRAL_WITH_LINK = (
    ReferralStatus.ATTRIBUTED,
    ReferralStatus.REVOKED_LINK,
    ReferralStatus.INACTIVE_BDE,
    ReferralStatus.WRONG_TYPE,
)
REFERRAL_WITHOUT_LINK = (ReferralStatus.NO_REF, ReferralStatus.INVALID_REF, ReferralStatus.UNKNOWN_REF)


class SlotTime(models.Model):
    """
    A time of day a booking type is offered, in Indian time -- what the
    Calendar sheet's header row used to hold. Configured with
    ``manage.py booking_schedule``; a retired time is deactivated, not deleted.
    """
    booking_type = models.CharField(max_length=20, choices=BookingType.choices)
    start_time = models.TimeField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'booking_slot_times'
        verbose_name = 'Slot time'
        verbose_name_plural = 'Slot times'
        ordering = ['booking_type', 'start_time']
        constraints = [
            models.UniqueConstraint(fields=['booking_type', 'start_time'], name='booking_slot_times_one_per_time'),
            models.CheckConstraint(
                condition=Q(booking_type__in=BookingType.values),
                name='booking_slot_times_known_type',
            ),
        ]

    def __str__(self):
        return f"{self.get_booking_type_display()} at {self.start_time:%H:%M}"


class BookingSlot(models.Model):
    """
    One booking type at one Indian date and time. Created by the first booking
    (or closure) of that slot, so a slot nobody has touched has no row.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    booking_type = models.CharField(max_length=20, choices=BookingType.choices)
    local_date = models.DateField()
    local_time = models.TimeField()
    # The same moment as an instant (UTC), and its end an hour later.
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    capacity = models.PositiveSmallIntegerField(default=SLOT_CAPACITY)
    # A closed slot shows as Fully Booked and takes no booking; the bookings
    # it already holds stay.
    closed_at = models.DateTimeField(null=True, blank=True)
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='closed_booking_slots'
    )
    close_reason = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        db_table = 'booking_slots'
        verbose_name = 'Booking slot'
        verbose_name_plural = 'Booking slots'
        ordering = ['local_date', 'local_time']
        constraints = [
            models.UniqueConstraint(
                fields=['booking_type', 'local_date', 'local_time'],
                name='booking_slots_one_per_occurrence',
            ),
            models.CheckConstraint(
                condition=Q(capacity__gte=1) & Q(capacity__lte=SLOT_CAPACITY),
                name='booking_slots_capacity_in_range',
            ),
            models.CheckConstraint(condition=Q(ends_at__gt=models.F('starts_at')), name='booking_slots_ends_after_start'),
            models.CheckConstraint(
                condition=Q(closed_by__isnull=True) | Q(closed_at__isnull=False),
                name='booking_slots_closed_by_needs_closed_at',
            ),
            models.CheckConstraint(
                condition=Q(booking_type__in=BookingType.values),
                name='booking_slots_known_type',
            ),
        ]
        indexes = [
            models.Index(fields=['booking_type', 'local_date'], name='booking_slots_type_date_idx'),
        ]

    def __str__(self):
        return f"{self.get_booking_type_display()} {self.local_date} {self.local_time:%H:%M}"


class LeadSource(models.TextChoices):
    """How an enquiry first reached Eduport Plus."""
    BOOKING_PAGE = 'BOOKING_PAGE', 'Booking page'
    PHONE_CALL = 'PHONE_CALL', 'Phone call'
    WHATSAPP = 'WHATSAPP', 'WhatsApp'
    WALK_IN = 'WALK_IN', 'Walk-in'
    REFERRAL = 'REFERRAL', 'Referral'
    SOCIAL_MEDIA = 'SOCIAL_MEDIA', 'Social media'
    OTHER = 'OTHER', 'Other'


# What a BDE may pick when adding an enquiry by hand; BOOKING_PAGE is set only
# by a public booking.
MANUAL_LEAD_SOURCES = [value for value in LeadSource.values if value != LeadSource.BOOKING_PAGE]


class Lead(models.Model):
    """
    One parent's enquiry for one child: matched by phone and student name, so
    siblings sharing a parent's phone stay separate leads. The owner is the
    first BDE whose valid link brought a booking, or the BDE who added it by
    hand, and is never overwritten by a later one.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    parent_name = models.CharField(max_length=255)
    phone_dial_code = models.CharField(max_length=5)
    phone_number = models.CharField(max_length=15)
    # "+<dial code><national number>", the matching key (bookings.leads).
    phone_key = models.CharField(max_length=20)
    student_name = models.CharField(max_length=255)
    student_name_key = models.CharField(max_length=255)
    school_name = models.CharField(max_length=255)
    grade = models.CharField(max_length=50)
    syllabus = models.CharField(max_length=100)
    country = models.CharField(max_length=100, blank=True, default='')
    # A lead the booking pages create came from them; a BDE adding one by hand
    # names how it reached them (bookings.enquiries).
    source = models.CharField(max_length=20, choices=LeadSource.choices, default=LeadSource.BOOKING_PAGE)
    owner_bde = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='owned_leads'
    )
    owner_link = models.ForeignKey(
        BookingLink,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='owned_leads'
    )
    owner_assigned_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'leads'
        verbose_name = 'Lead'
        verbose_name_plural = 'Leads'
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(fields=['phone_key', 'student_name_key'], name='leads_one_per_phone_and_student'),
            models.CheckConstraint(
                condition=(
                    Q(owner_bde__isnull=True, owner_link__isnull=True, owner_assigned_at__isnull=True)
                    | Q(owner_bde__isnull=False, owner_assigned_at__isnull=False)
                ),
                name='leads_owner_fields_together',
            ),
            models.CheckConstraint(
                condition=Q(source__in=LeadSource.values),
                name='leads_known_source',
            ),
        ]

    def __str__(self):
        return f"Lead {self.id}"


def _cleared(*events):
    """Each of ``events`` (completed, cancelled, rescheduled) not recorded: its time and author empty."""
    return Q(**{f'{event}_{field}__isnull': True for event in events for field in ('at', 'by')})


class BookingBase(models.Model):
    """
    The columns every booking table shares, so Diagnostic and Demo bookings
    stay separate tables (DiagnosticBooking, DemoBooking) that can still be
    read side by side. Each table adds its lead, slot and tutor relations,
    named for its type, and the type it holds (BOOKING_TYPE). Its slot is
    always of that type: a trigger on each table refuses any other, and one on
    booking_slots a change of type once a booking holds the slot (bookings.0005).

    One booking of one slot. Never deleted: a cancellation is a status and
    frees the seat. While booked or completed, a booking holds one of the
    slot's seats (1..3), so even beside the slot lock the database cannot hold
    a fourth booking for a slot. A rescheduled booking frees its seat too and
    points at nothing; its replacement points back at it (rescheduled_from),
    so moves form one chain.
    """
    BOOKING_TYPE = None
    # The lead's and slot's relation to this table (lead.<name>, slot.<name>).
    RELATED_NAME = None

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    seat = models.PositiveSmallIntegerField()
    status = models.CharField(max_length=20, choices=BookingStatus.choices, default=BookingStatus.BOOKED)
    # A public page booking, or one a BDE made through a handoff (who made it: created_by).
    channel = models.CharField(max_length=20, choices=BookingChannel.choices, default=BookingChannel.PUBLIC_PAGE)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='created_%(class)ss'
    )
    # What the booking's ``ref`` token turned out to be; empty for a handoff,
    # which carries no token.
    referral_status = models.CharField(max_length=20, choices=ReferralStatus.choices, null=True, blank=True)
    # The link the ref token matched, kept for review even when it could not
    # attribute the booking (revoked, inactive owner, other booking type).
    referral_link = models.ForeignKey(
        BookingLink,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='%(class)ss'
    )
    # The BDE this booking is attributed to: set only for ATTRIBUTED.
    attributed_bde = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='attributed_%(class)ss'
    )
    # What the parent submitted, as submitted, written once (the lead keeps the latest).
    details = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)
    # Set by the tutor's first report (a later phase).
    completed_at = models.DateTimeField(null=True, blank=True)
    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='completed_%(class)ss'
    )
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='cancelled_%(class)ss'
    )
    # Why it was cancelled (CancelReason), set with the status.
    cancel_reason_code = models.CharField(max_length=30, choices=CancelReason.choices, blank=True, default='')
    # Free text from before reason codes (bookings.0006): kept for the rows
    # that have it, never written again.
    cancel_reason = models.TextField(blank=True, default='')
    # The booking this one replaced when it was moved to another slot.
    rescheduled_from = models.OneToOneField(
        'self',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='rescheduled_to'
    )
    rescheduled_at = models.DateTimeField(null=True, blank=True)
    rescheduled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='rescheduled_%(class)ss'
    )
    # Why it was moved (RescheduleReason), set with the status.
    reschedule_reason_code = models.CharField(max_length=30, choices=RescheduleReason.choices, blank=True, default='')
    # When the tutor (the table's assigned_tutor) was assigned, and by whom.
    # A cancelled booking keeps its tutor, as the record of who was to teach it.
    tutor_assigned_at = models.DateTimeField(null=True, blank=True)
    tutor_assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='tutor_assigned_%(class)ss'
    )
    # The Google Meet room this booking is taught in: its tutor's permanent
    # link (accounts.User.tutor_meet_link), copied when the tutor is assigned
    # and kept in step while the booking is live (booking_service.
    # set_tutor_meet_link). Once its slot has ended, or it is completed,
    # cancelled or moved, it keeps the link it had, whatever the tutor's
    # becomes. NULL = no tutor, or a tutor with no link configured.
    tutor_meet_link = models.CharField(max_length=MEET_LINK_MAX_LENGTH, null=True, blank=True)

    class Meta:
        abstract = True
        ordering = ['-created_at']
        constraints = [
            # A repeated submission returns the booking it already made.
            models.UniqueConstraint(
                fields=['lead', 'slot'],
                condition=Q(status__in=HOLDS_SEAT),
                name='%(class)s_one_holding_per_lead_and_slot',
            ),
            models.UniqueConstraint(
                fields=['slot', 'seat'],
                condition=Q(status__in=HOLDS_SEAT),
                name='%(class)s_one_holding_per_seat',
            ),
            models.CheckConstraint(
                condition=Q(seat__gte=1) & Q(seat__lte=SLOT_CAPACITY),
                name='%(class)s_seat_in_range',
            ),
            models.CheckConstraint(
                condition=Q(status__in=BookingStatus.values),
                name='%(class)s_known_status',
            ),
            models.CheckConstraint(
                condition=Q(channel__in=BookingChannel.values),
                name='%(class)s_known_channel',
            ),
            # One state at a time: a completed booking is never also cancelled or rescheduled.
            models.CheckConstraint(
                condition=(
                    (Q(status=BookingStatus.BOOKED) & _cleared('completed', 'cancelled', 'rescheduled'))
                    | (Q(status=BookingStatus.COMPLETED, completed_at__isnull=False, assigned_tutor__isnull=False)
                       & _cleared('cancelled', 'rescheduled'))
                    | (Q(status=BookingStatus.CANCELLED, cancelled_at__isnull=False) & _cleared('completed', 'rescheduled'))
                    | (Q(status=BookingStatus.RESCHEDULED, rescheduled_at__isnull=False) & _cleared('completed', 'cancelled'))
                ),
                name='%(class)s_state_fields',
            ),
            models.CheckConstraint(
                condition=Q(rescheduled_from__isnull=True) | ~Q(rescheduled_from=models.F('id')),
                name='%(class)s_not_its_own_predecessor',
            ),
            # A reason code exactly when the status records one: a cancelled
            # booking says why, a moved one too, and no other carries either.
            models.CheckConstraint(
                condition=(
                    (Q(status=BookingStatus.CANCELLED) & Q(cancel_reason_code__in=CancelReason.values))
                    | (~Q(status=BookingStatus.CANCELLED) & Q(cancel_reason_code=''))
                ),
                name='%(class)s_cancel_reason_with_status',
            ),
            models.CheckConstraint(
                condition=(
                    (Q(status=BookingStatus.RESCHEDULED) & Q(reschedule_reason_code__in=RescheduleReason.values))
                    | (~Q(status=BookingStatus.RESCHEDULED) & Q(reschedule_reason_code=''))
                ),
                name='%(class)s_reschedule_reason_with_status',
            ),
            # A public page booking went through attribution; a handoff names its BDE instead.
            models.CheckConstraint(
                condition=(
                    Q(channel=BookingChannel.PUBLIC_PAGE, referral_status__isnull=False, created_by__isnull=True)
                    | Q(channel=BookingChannel.BDE_HANDOFF, referral_status__isnull=True, referral_link__isnull=True,
                        attributed_bde__isnull=True, created_by__isnull=False)
                ),
                name='%(class)s_channel_fields',
            ),
            models.CheckConstraint(
                condition=Q(referral_status__isnull=True) | Q(referral_status__in=ReferralStatus.values),
                name='%(class)s_known_referral_status',
            ),
            models.CheckConstraint(
                condition=(
                    Q(referral_status__isnull=True)
                    | Q(referral_status__in=REFERRAL_WITH_LINK, referral_link__isnull=False)
                    | Q(referral_status__in=REFERRAL_WITHOUT_LINK, referral_link__isnull=True)
                ),
                name='%(class)s_referral_link_matches_status',
            ),
            models.CheckConstraint(
                condition=(
                    Q(referral_status=ReferralStatus.ATTRIBUTED, attributed_bde__isnull=False)
                    | (~Q(referral_status=ReferralStatus.ATTRIBUTED) & Q(attributed_bde__isnull=True))
                ),
                name='%(class)s_attributed_only_when_attributed',
            ),
            # A tutor comes with the moment they were assigned. Who assigned
            # them may since be gone (SET_NULL), but is never kept without a tutor.
            models.CheckConstraint(
                condition=(
                    Q(assigned_tutor__isnull=True, tutor_assigned_at__isnull=True, tutor_assigned_by__isnull=True)
                    | Q(assigned_tutor__isnull=False, tutor_assigned_at__isnull=False)
                ),
                name='%(class)s_tutor_assignment_fields',
            ),
            # The Meet link is the tutor's: none without one, and only a Google Meet link.
            models.CheckConstraint(
                condition=Q(tutor_meet_link__isnull=True) | Q(assigned_tutor__isnull=False),
                name='%(class)s_meet_link_needs_tutor',
            ),
            models.CheckConstraint(
                condition=Q(tutor_meet_link__isnull=True) | Q(tutor_meet_link__regex=MEET_LINK_DB_PATTERN),
                name='%(class)s_meet_link_google_meet',
            ),
        ]
        indexes = [
            models.Index(fields=['attributed_bde', 'created_at'], name='%(class)s_bde_idx'),
            # A tutor's bookings and their slots: the availability check.
            models.Index(fields=['assigned_tutor', 'slot'], name='%(class)s_tutor_idx'),
            models.Index(fields=['lead', 'status'], name='%(class)s_lead_idx'),
            models.Index(fields=['status', 'completed_at'], name='%(class)s_done_idx'),
        ]

    def __str__(self):
        return f"{self.get_booking_type_display()} booking {self.id} ({self.get_status_display()})"

    @property
    def booking_type(self):
        return self.BOOKING_TYPE

    def get_booking_type_display(self):
        return BookingType(self.BOOKING_TYPE).label


class DiagnosticBooking(BookingBase):
    BOOKING_TYPE = BookingType.DIAGNOSTIC
    RELATED_NAME = 'diagnostic_bookings'

    lead = models.ForeignKey(Lead, on_delete=models.PROTECT, related_name='diagnostic_bookings')
    slot = models.ForeignKey(BookingSlot, on_delete=models.PROTECT, related_name='diagnostic_bookings')
    # The tutor who teaches this booking (bookings.booking_service.assign_tutor).
    assigned_tutor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='assigned_diagnostic_bookings'
    )

    class Meta(BookingBase.Meta):
        db_table = 'diagnostic_bookings'
        verbose_name = 'Diagnostic booking'
        verbose_name_plural = 'Diagnostic bookings'
        constraints = [
            *BookingBase.Meta.constraints,
            # Only Demo bookings are made through a BDE handoff.
            models.CheckConstraint(
                condition=Q(channel=BookingChannel.PUBLIC_PAGE),
                name='%(class)s_public_page_only',
            ),
        ]


class DemoBooking(BookingBase):
    BOOKING_TYPE = BookingType.DEMO
    RELATED_NAME = 'demo_bookings'

    lead = models.ForeignKey(Lead, on_delete=models.PROTECT, related_name='demo_bookings')
    slot = models.ForeignKey(BookingSlot, on_delete=models.PROTECT, related_name='demo_bookings')
    # The tutor who teaches this booking (bookings.booking_service.assign_tutor).
    assigned_tutor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='assigned_demo_bookings'
    )

    class Meta(BookingBase.Meta):
        db_table = 'demo_bookings'
        verbose_name = 'Demo booking'
        verbose_name_plural = 'Demo bookings'


# Every booking table, and the one holding each booking type.
BOOKING_MODELS = (DiagnosticBooking, DemoBooking)
_MODEL_BY_TYPE = {model.BOOKING_TYPE: model for model in BOOKING_MODELS}


def booking_model(booking_type):
    """The booking table of ``booking_type`` (a BookingType value)."""
    return _MODEL_BY_TYPE[booking_type]


# ---------------------------------------------------------------- history

class BookingEventKind(models.TextChoices):
    CREATED = 'CREATED', 'Created'
    TUTOR_ASSIGNED = 'TUTOR_ASSIGNED', 'Tutor assigned'
    TUTOR_UNASSIGNED = 'TUTOR_UNASSIGNED', 'Tutor unassigned'
    RESCHEDULED = 'RESCHEDULED', 'Rescheduled'
    CANCELLED = 'CANCELLED', 'Cancelled'
    COMPLETED = 'COMPLETED', 'Completed'
    REPORT_EDITED = 'REPORT_EDITED', 'Report edited'
    MEET_LINK_UPDATED = 'MEET_LINK_UPDATED', 'Meet link updated'


class BookingEvent(models.Model):
    """
    One change to one booking, written in the same transaction as the change
    (bookings.history), so a booking's history never misses a step. Append-only:
    a database trigger refuses every update and delete. ``data`` holds ids and
    values only -- never a name or a phone number.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    diagnostic_booking = models.ForeignKey(
        DiagnosticBooking,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='events'
    )
    demo_booking = models.ForeignKey(
        DemoBooking,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='events'
    )
    kind = models.CharField(max_length=30, choices=BookingEventKind.choices)
    data = models.JSONField(default=dict, blank=True)
    # No database constraint, as for activity_log: an account's deletion must
    # never have to rewrite a row the trigger keeps unchangeable.
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.DO_NOTHING,
        db_constraint=False,
        null=True,
        blank=True,
        related_name='booking_events'
    )
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        db_table = 'booking_events'
        verbose_name = 'Booking event'
        verbose_name_plural = 'Booking events'
        ordering = ['created_at']
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(diagnostic_booking__isnull=False, demo_booking__isnull=True)
                    | Q(diagnostic_booking__isnull=True, demo_booking__isnull=False)
                ),
                name='booking_events_one_booking',
            ),
            models.CheckConstraint(
                condition=Q(kind__in=BookingEventKind.values),
                name='booking_events_known_kind',
            ),
        ]
        indexes = [
            models.Index(fields=['diagnostic_booking', 'created_at'], name='booking_events_diag_idx'),
            models.Index(fields=['demo_booking', 'created_at'], name='booking_events_demo_idx'),
        ]

    def __str__(self):
        return f"{self.get_kind_display()} ({self.created_at:%Y-%m-%d %H:%M})"

    @property
    def booking(self):
        return self.diagnostic_booking or self.demo_booking
