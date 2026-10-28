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
books or closes it. Each booking (Booking) belongs to a lead (Lead): one
parent's enquiry for one child, matched by phone and student name.
bookings.booking_service is the only writer of bookings; the leads a BDE adds
by hand (their enquiries) are written by bookings.enquiries.
"""
import secrets
import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

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
    CANCELLED = 'CANCELLED', 'Cancelled'


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


class Booking(models.Model):
    """
    One booking of one slot. Never deleted: a cancellation is a status, and
    frees the seat. While booked, each booking holds one of the slot's seats
    (1..3), so even beside the slot lock the database cannot hold a fourth
    booked row for a slot.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    booking_type = models.CharField(max_length=20, choices=BookingType.choices)
    lead = models.ForeignKey(Lead, on_delete=models.PROTECT, related_name='bookings')
    slot = models.ForeignKey(BookingSlot, on_delete=models.PROTECT, related_name='bookings')
    seat = models.PositiveSmallIntegerField()
    status = models.CharField(max_length=20, choices=BookingStatus.choices, default=BookingStatus.BOOKED)
    referral_status = models.CharField(max_length=20, choices=ReferralStatus.choices)
    # The link the ref token matched, kept for review even when it could not
    # attribute the booking (revoked, inactive owner, other booking type).
    referral_link = models.ForeignKey(
        BookingLink,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='bookings'
    )
    # The BDE this booking is attributed to: set only for ATTRIBUTED.
    attributed_bde = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='attributed_bookings'
    )
    # What the parent submitted, as submitted (the lead keeps the latest).
    details = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='cancelled_bookings'
    )
    cancel_reason = models.TextField(blank=True, default='')

    class Meta:
        db_table = 'bookings'
        verbose_name = 'Booking'
        verbose_name_plural = 'Bookings'
        ordering = ['-created_at']
        constraints = [
            # A repeated submission returns the booking it already made.
            models.UniqueConstraint(
                fields=['lead', 'slot'],
                condition=Q(status=BookingStatus.BOOKED),
                name='bookings_one_active_per_lead_and_slot',
            ),
            models.UniqueConstraint(
                fields=['slot', 'seat'],
                condition=Q(status=BookingStatus.BOOKED),
                name='bookings_one_active_per_seat',
            ),
            models.CheckConstraint(
                condition=Q(seat__gte=1) & Q(seat__lte=SLOT_CAPACITY),
                name='bookings_seat_in_range',
            ),
            models.CheckConstraint(
                condition=Q(booking_type__in=BookingType.values),
                name='bookings_known_type',
            ),
            models.CheckConstraint(
                condition=Q(status__in=BookingStatus.values),
                name='bookings_known_status',
            ),
            models.CheckConstraint(
                condition=(
                    Q(status=BookingStatus.BOOKED, cancelled_at__isnull=True, cancelled_by__isnull=True)
                    | Q(status=BookingStatus.CANCELLED, cancelled_at__isnull=False)
                ),
                name='bookings_cancellation_fields',
            ),
            models.CheckConstraint(
                condition=(
                    Q(referral_status__in=REFERRAL_WITH_LINK, referral_link__isnull=False)
                    | Q(referral_status__in=REFERRAL_WITHOUT_LINK, referral_link__isnull=True)
                ),
                name='bookings_referral_link_matches_status',
            ),
            models.CheckConstraint(
                condition=(
                    Q(referral_status=ReferralStatus.ATTRIBUTED, attributed_bde__isnull=False)
                    | (~Q(referral_status=ReferralStatus.ATTRIBUTED) & Q(attributed_bde__isnull=True))
                ),
                name='bookings_attributed_only_when_attributed',
            ),
        ]
        indexes = [
            models.Index(fields=['attributed_bde', 'created_at'], name='bookings_bde_created_idx'),
        ]

    def __str__(self):
        return f"{self.get_booking_type_display()} booking {self.id} ({self.get_status_display()})"
