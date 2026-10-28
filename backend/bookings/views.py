from datetime import datetime

from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.permissions import HasAppPermission
from core.timezones import DATE_PATTERN

from .booking_service import BookingBusy, set_slots_closed
from .models import SLOT_CAPACITY, SLOT_MINUTES, SlotTime
from .public_views import PATH_TYPES
from .scheduling import BOOKING_TIMEZONE_NAME, PAST, booking_window, day_slots, parent_state
from .serializers import BookingLinkSerializer, SlotChangeSerializer
from .services import links_for, owns_booking_links


class BdeBookingLinksView(APIView):
    """
    GET /api/bde/booking-links/
    The caller's own permanent booking links -- one Demo, one Diagnostic --
    issued on the first request and the same on every request after.

    Nothing in the request chooses whose links are returned (a ``bde_id``
    parameter, say, is never read), so an account only ever sees its own.
    Guarded by accounts.view_own_booking_links, which only the BDE role may
    hold; a superuser holds it as well (decision D1) without being a BDE, so
    links are also only ever issued to an active BDE account.
    """
    permission_classes = [IsAuthenticated, HasAppPermission('accounts.view_own_booking_links')]

    def get(self, request, *args, **kwargs):
        if not owns_booking_links(request.user):
            return Response(
                {
                    "error": "NOT_A_BDE",
                    "message": "Booking links belong to BDE accounts, and this account is not one.",
                },
                status=status.HTTP_403_FORBIDDEN,
            )
        links = links_for(request.user, request=request)
        return Response({"links": BookingLinkSerializer(links, many=True).data}, status=status.HTTP_200_OK)


def _refuse(message, code, http_status=status.HTTP_400_BAD_REQUEST, **extra):
    return Response({'error': message, 'code': code, **extra}, status=http_status)


def _name(user):
    return (user.full_name or user.email) if user else None


class BookingSlotsView(APIView):
    """
    GET  /api/booking-slots/<demo|diagnostic>/<YYYY-MM-DD>/
    POST /api/booking-slots/<demo|diagnostic>/<YYYY-MM-DD>/
         {"action": "close" | "reopen", "times": ["19:30", ...], "reason": "..."}

    One date's Demo or Diagnostic slots for the administrators who manage
    them: every active time with its bookings and the status parents see, and
    closing or reopening any of them (several at once: all or none). A closed
    slot keeps the bookings it holds and takes no new one -- the public pages
    show it as Fully Booked -- and a reopened one takes bookings again only
    while seats remain (bookings.booking_service). Nothing here deletes or
    changes a booking. Past dates are history: shown, never changed.

    Guarded by accounts.manage_booking_slots, which only the ADMIN role may
    hold (a superuser holds it as well, decision D1).
    """
    permission_classes = [IsAuthenticated, HasAppPermission('accounts.manage_booking_slots')]

    def get(self, request, booking_type, date):
        booking_type, local_date, refusal = _slot_day(booking_type, date)
        if refusal:
            return refusal
        return Response(_day(booking_type, local_date), status=status.HTTP_200_OK)

    def post(self, request, booking_type, date):
        booking_type, local_date, refusal = _slot_day(booking_type, date)
        if refusal:
            return refusal
        serializer = SlotChangeSerializer(data=request.data)
        if not serializer.is_valid():
            return _refuse('Choose close or reopen and at least one slot time (HH:MM).', 'VALIDATION_ERROR',
                           fields=serializer.errors)
        if parent_state(booking_type, local_date) == PAST:
            return _refuse('Slots on past dates cannot be changed.', 'DATE_IN_PAST')

        data = serializer.validated_data
        closing = data['action'] == 'close'
        if closing:
            offered = set(SlotTime.objects.filter(booking_type=booking_type, is_active=True).values_list('start_time', flat=True))
            unknown = sorted(start for start in set(data['times']) if start not in offered)
            if unknown:
                listed = ', '.join(start.strftime('%H:%M') for start in unknown)
                return _refuse(f'Not a {booking_type.lower()} time: {listed}.', 'UNKNOWN_TIME')
        try:
            changed = set_slots_closed(booking_type, local_date, data['times'], closing,
                                       actor=request.user, reason=data['reason'].strip())
        except BookingBusy:
            return _refuse('Could not update the slots right now. Please try again.', 'SLOTS_BUSY',
                           http_status=status.HTTP_503_SERVICE_UNAVAILABLE)
        return Response(
            {**_day(booking_type, local_date), 'changed': [start.strftime('%H:%M') for start in changed]},
            status=status.HTTP_200_OK,
        )


def _slot_day(booking_type, value):
    """(booking type, date, None) for the path, or (.., .., the answer refusing it)."""
    try:
        booking_type = PATH_TYPES[booking_type]
    except KeyError:
        raise NotFound()
    try:
        if not DATE_PATTERN.match(value):
            raise ValueError(value)
        return booking_type, datetime.strptime(value, '%Y-%m-%d').date(), None
    except ValueError:
        return booking_type, None, _refuse('Dates are YYYY-MM-DD.', 'INVALID_DATE')


def _day(booking_type, local_date):
    window = booking_window(booking_type)
    state = parent_state(booking_type, local_date)
    return {
        'booking_type': booking_type,
        'date': local_date.isoformat(),
        'timezone': BOOKING_TIMEZONE_NAME,
        'slot_minutes': SLOT_MINUTES,
        'capacity': SLOT_CAPACITY,
        # Where the date stands for parents: past, today, open (bookable) or upcoming.
        'parent_state': state,
        'window': {'first': window[0].isoformat(), 'last': window[-1].isoformat()},
        'editable': state != PAST,
        'slots': [
            {
                **slot,
                'closed_at': slot['closed_at'].isoformat() if slot['closed_at'] else None,
                'closed_by': _name(slot['closed_by']),
            }
            for slot in day_slots(booking_type, local_date)
        ],
    }
