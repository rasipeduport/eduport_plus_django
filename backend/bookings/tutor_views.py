"""
My Bookings for tutors (bookings.tutor_bookings):

    GET /api/tutor/bookings/        the bookings assigned to the caller, paged and filtered
    GET /api/tutor/bookings/<id>/   one of them

Guarded by accounts.view_assigned_bookings, which only the TUTOR role may hold;
a superuser holds it as well (decision D1). Nothing in a request chooses whose
bookings are read: always the ones assigned to the caller now, so a superuser
who teaches none lists none, and a booking reassigned to another tutor, or
unassigned, is gone from both -- 404, as a booking that does not exist is.
Errors answer ``{"error": CODE, "message": ...}``.
"""
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.pagination import page_params
from core.permissions import HasAppPermission

from . import tutor_bookings
from .scheduling import BOOKING_TIMEZONE_NAME

VIEW_ASSIGNED_BOOKINGS = HasAppPermission('accounts.view_assigned_bookings')


def _error(code, message, http_status, **extra):
    return Response({'error': code, 'message': message, **extra}, status=http_status)


class TutorBookingListView(APIView):
    """
    GET /api/tutor/bookings/?type=&when=&page=&page_size=
    The caller's bookings, upcoming by default, soonest slot first
    (``when=past``: most recent first), always paged: {"results", "count",
    "page", "page_size", "timezone"}. An unknown filter value answers 400
    INVALID_INPUT naming the parameters.
    """
    permission_classes = [IsAuthenticated, VIEW_ASSIGNED_BOOKINGS]

    def get(self, request, *args, **kwargs):
        filters, invalid = tutor_bookings.parse_filters(request.query_params)
        if invalid:
            return _error('INVALID_INPUT', 'Check the booking filters.', status.HTTP_400_BAD_REQUEST, fields=invalid)
        now = timezone.now()
        bookings = tutor_bookings.listed(request.user, now, **filters)
        page, page_size = page_params(request)
        offset = (page - 1) * page_size
        return Response(
            {
                'results': [tutor_bookings.booking_row(booking, now) for booking in bookings[offset:offset + page_size]],
                'count': bookings.count(),
                'page': page,
                'page_size': page_size,
                'timezone': BOOKING_TIMEZONE_NAME,
            },
            status=status.HTTP_200_OK,
        )


class TutorBookingDetailView(APIView):
    """GET /api/tutor/bookings/<id>/ -- one booking assigned to the caller; any other is 404."""
    permission_classes = [IsAuthenticated, VIEW_ASSIGNED_BOOKINGS]

    def get(self, request, pk, *args, **kwargs):
        booking = tutor_bookings.assigned_to(request.user).filter(pk=pk).first()
        if booking is None:
            return _error('NOT_FOUND', 'No such booking.', status.HTTP_404_NOT_FOUND)
        return Response(tutor_bookings.booking_detail(booking, timezone.now()), status=status.HTTP_200_OK)
