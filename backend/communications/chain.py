"""
A booking's reschedule chain (bookings.models.BookingBase.rescheduled_from):
the bookings it replaced, the ones that replaced it, and where the
acknowledgement of the bookings before it stands -- so that only one goes per
chain (communications.planner, communications.rendering).
"""
from django.db.models import TextChoices

from bookings.models import DiagnosticBooking

from .models import HANDED_OVER_STATUSES, OUTCOME_UNKNOWN, Message, MessageStatus, Step


class EarlierAcknowledgement(TextChoices):
    """The acknowledgement of the bookings a booking replaced, all of them together."""
    NONE = 'NONE', 'No earlier booking'
    # Accepted by the provider, or later: the chain is acknowledged.
    ACCEPTED = 'ACCEPTED', 'Accepted for an earlier booking'
    # Being handed to the provider right now: not known yet.
    IN_FLIGHT = 'IN_FLIGHT', 'Being sent for an earlier booking'
    # The provider may have taken it, and nobody knows: for someone to check.
    UNKNOWN = 'UNKNOWN', 'Outcome unknown for an earlier booking'
    # Refused, cancelled or never sent: the chain is not acknowledged.
    NOT_ACCEPTED = 'NOT_ACCEPTED', 'Not accepted for any earlier booking'


def earlier_bookings(booking):
    """The ids of the bookings ``booking`` replaced, the nearest first."""
    model = type(booking)
    ids, pk = [], booking.rescheduled_from_id
    while pk is not None and pk not in ids and pk != booking.pk:
        ids.append(pk)
        pk = model.objects.filter(pk=pk).values_list('rescheduled_from_id', flat=True).first()
    return ids


def later_bookings(booking):
    """The bookings that replaced ``booking``, the nearest first."""
    model = type(booking)
    found, current = [], booking
    while True:
        following = model.objects.select_related('slot', 'lead').filter(rescheduled_from=current).first()
        if following is None or following in found:
            return found
        found.append(following)
        current = following


def earlier_acknowledgement(booking):
    """Where the acknowledgement of the bookings ``booking`` replaced stands (an EarlierAcknowledgement)."""
    earlier = earlier_bookings(booking)
    if not earlier:
        return EarlierAcknowledgement.NONE
    field = 'diagnostic_booking' if isinstance(booking, DiagnosticBooking) else 'demo_booking'
    acks = Message.objects.filter(**{f'{field}__in': earlier}, template__step=Step.ACKNOWLEDGEMENT)
    if acks.filter(status__in=HANDED_OVER_STATUSES).exists():
        return EarlierAcknowledgement.ACCEPTED
    if acks.filter(claimed_at__isnull=False).exists():
        return EarlierAcknowledgement.IN_FLIGHT
    if acks.filter(status=MessageStatus.FAILED, failure_code=OUTCOME_UNKNOWN).exists():
        return EarlierAcknowledgement.UNKNOWN
    return EarlierAcknowledgement.NOT_ACCEPTED
