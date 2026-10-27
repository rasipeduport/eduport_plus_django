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
