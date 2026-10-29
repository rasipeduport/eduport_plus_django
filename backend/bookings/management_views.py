"""
Booking management for the Admin / Coordinator (bookings.coordination):

    GET    /api/bookings/                          every booking, paged and filtered
    GET    /api/bookings/<id>/                     one booking in full
    GET    /api/bookings/<id>/tutors/              every active tutor, free or not for its slot
    GET    /api/bookings/slots/<slot id>/tutors/   the same for a slot
    PUT    /api/bookings/<id>/tutor/ {tutor_id}    assign or reassign its tutor
    DELETE /api/bookings/<id>/tutor/               unassign it

Reading needs accounts.view_all_bookings, changing the tutor
accounts.assign_booking_tutor; only the ADMIN role may hold either (a superuser
holds both, decision D1). Nothing in a request widens what is shown: every
caller holding the permission sees every booking, and nobody else sees any.
The tutor is changed only by bookings.booking_service, which checks the tutor
and the booking again under its locks whatever the picker showed. Errors
answer ``{"error": CODE, "message": ...}``.
"""
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.pagination import page_params
from core.permissions import ByMethod, HasAppPermission

from . import coordination
from .booking_service import BookingError, TutorNotAssignable, TutorUnavailable, assign_tutor, unassign_tutor
from .models import BookingSlot
from .scheduling import BOOKING_TIMEZONE_NAME
from .serializers import TutorAssignmentSerializer

User = get_user_model()

VIEW_ALL_BOOKINGS = HasAppPermission('accounts.view_all_bookings')
ASSIGN_BOOKING_TUTOR = HasAppPermission('accounts.assign_booking_tutor')


def _error(code, message, http_status, **extra):
    return Response({'error': code, 'message': message, **extra}, status=http_status)


def _no_booking():
    return _error('NOT_FOUND', 'No such booking.', status.HTTP_404_NOT_FOUND)


class BookingListView(APIView):
    """
    GET /api/bookings/?type=&status=&assigned=&tutor=&slot=&from=&to=&when=&q=&page=&page_size=
    Every booking, soonest slot first (``when=past``: most recent first),
    always paged: {"results", "count", "page", "page_size", "timezone"}. The
    filters are coordination.parse_filters'; an unknown value answers 400
    INVALID_INPUT naming the parameters, never a guessed filter.
    """
    permission_classes = [IsAuthenticated, VIEW_ALL_BOOKINGS]

    def get(self, request, *args, **kwargs):
        filters, invalid = coordination.parse_filters(request.query_params)
        if invalid:
            return _error('INVALID_INPUT', 'Check the booking filters.', status.HTTP_400_BAD_REQUEST, fields=invalid)
        now = timezone.now()
        bookings = coordination.filtered(coordination.listed(), now, **filters)
        page, page_size = page_params(request)
        offset = (page - 1) * page_size
        return Response(
            {
                'results': [coordination.booking_row(booking, now) for booking in bookings[offset:offset + page_size]],
                'count': bookings.count(),
                'page': page,
                'page_size': page_size,
                'timezone': BOOKING_TIMEZONE_NAME,
            },
            status=status.HTTP_200_OK,
        )


class BookingDetailView(APIView):
    """GET /api/bookings/<id>/ -- one booking in full."""
    permission_classes = [IsAuthenticated, VIEW_ALL_BOOKINGS]

    def get(self, request, pk, *args, **kwargs):
        booking = coordination.listed().filter(pk=pk).first()
        if booking is None:
            return _no_booking()
        return Response(coordination.booking_detail(booking, timezone.now()), status=status.HTTP_200_OK)


class BookingTutorsView(APIView):
    """
    GET /api/bookings/<id>/tutors/
    Every active tutor for the booking's slot, AVAILABLE or UNAVAILABLE with
    the reason, its current tutor marked; and whether its tutor may be changed
    at all (a cancelled booking or a started slot keeps the one it has).
    """
    permission_classes = [IsAuthenticated, VIEW_ALL_BOOKINGS]

    def get(self, request, pk, *args, **kwargs):
        booking = coordination.listed().filter(pk=pk).first()
        if booking is None:
            return _no_booking()
        now = timezone.now()
        refusal = coordination.tutor_change_refusal(booking, now)
        return Response(
            {
                'booking_id': str(booking.id),
                'slot': coordination.slot_brief(booking.slot, now),
                'timezone': BOOKING_TIMEZONE_NAME,
                'tutor_changeable': refusal is None,
                'tutor_change_refusal': refusal,
                'tutors': coordination.tutor_availability(booking.slot, booking=booking),
            },
            status=status.HTTP_200_OK,
        )


class SlotTutorsView(APIView):
    """GET /api/bookings/slots/<slot id>/tutors/ -- every active tutor, AVAILABLE or UNAVAILABLE for the slot."""
    permission_classes = [IsAuthenticated, VIEW_ALL_BOOKINGS]

    def get(self, request, slot_id, *args, **kwargs):
        slot = BookingSlot.objects.filter(pk=slot_id).first()
        if slot is None:
            return _error('NOT_FOUND', 'No such slot.', status.HTTP_404_NOT_FOUND)
        return Response(
            {
                'slot': coordination.slot_brief(slot, timezone.now()),
                'timezone': BOOKING_TIMEZONE_NAME,
                'tutors': coordination.tutor_availability(slot),
            },
            status=status.HTTP_200_OK,
        )


class BookingTutorView(APIView):
    """
    PUT    /api/bookings/<id>/tutor/ {"tutor_id": "<account id>"}
           Assign the tutor, or replace the one assigned (the same one again
           changes nothing). 409 TUTOR_UNAVAILABLE with ``conflict`` when they
           already teach a class or another booking then; 400 INVALID_TUTOR
           for an account that is not an active tutor; 409 BOOKING_CANCELLED or
           SLOT_STARTED when the booking's tutor can no longer change.
    DELETE /api/bookings/<id>/tutor/
           Unassign it, under the same rules.
    Both answer the booking in full with ``changed``.
    """
    permission_classes = [IsAuthenticated, ByMethod(PUT=ASSIGN_BOOKING_TUTOR, DELETE=ASSIGN_BOOKING_TUTOR)]

    def put(self, request, pk, *args, **kwargs):
        booking = coordination.listed().filter(pk=pk).first()
        if booking is None:
            return _no_booking()
        serializer = TutorAssignmentSerializer(data=request.data)
        if not serializer.is_valid():
            return _error('VALIDATION_ERROR', 'Choose a tutor.', status.HTTP_400_BAD_REQUEST, fields=serializer.errors)
        tutor = User.objects.filter(pk=serializer.validated_data['tutor_id']).first()
        if tutor is None:
            return _error(TutorNotAssignable.code, TutorNotAssignable.message, TutorNotAssignable.http_status)
        return self._changed(lambda: assign_tutor(booking, tutor, actor=request.user))

    def delete(self, request, pk, *args, **kwargs):
        booking = coordination.listed().filter(pk=pk).first()
        if booking is None:
            return _no_booking()
        return self._changed(lambda: unassign_tutor(booking, actor=request.user))

    @staticmethod
    def _changed(change):
        try:
            booking, changed = change()
        except TutorUnavailable as exc:
            return _error(exc.code, exc.message, exc.http_status, conflict=coordination.conflict_reason(exc.conflict))
        except BookingError as exc:
            return _error(exc.code, exc.message, exc.http_status)
        booking = coordination.listed().get(pk=booking.pk)
        return Response(
            {**coordination.booking_detail(booking, timezone.now()), 'changed': changed},
            status=status.HTTP_200_OK,
        )
