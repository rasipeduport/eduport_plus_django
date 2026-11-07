"""
My Bookings for tutors (bookings.tutor_bookings):

    GET  /api/tutor/bookings/                    the bookings assigned to the caller, paged and filtered
    GET  /api/tutor/bookings/<type>/<id>/        one of them (``<type>`` is demo or diagnostic)
    POST /api/tutor/bookings/<type>/<id>/start/  Start Demo / Start Diagnostic
    GET  /api/tutor/bookings/<type>/<id>/notes/  staff's notes on its lead (bookings.notes)
    POST /api/tutor/bookings/<type>/<id>/notes/  add one, as its tutor

Each one's report -- read, submit, edit, history -- is under ``…/report/``
(reports.tutor_views).

Guarded by accounts.view_assigned_bookings, which only the TUTOR role may hold;
a superuser holds it as well (decision D1). Starting needs
accounts.submit_booking_report too, the permission a tutor writes the report
with -- each booking's ``actions.start`` says whether the caller may start it
now. Nothing in a request chooses whose
bookings are read: always the ones assigned to the caller now, so a superuser
who teaches none lists none, and a booking reassigned to another tutor, or
unassigned, is gone from both -- 404, as a booking that does not exist is.
Errors answer ``{"error": CODE, "message": ...}``.
"""
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.authz import has_app_permission
from core.pagination import page_params
from core.permissions import HasAppPermission

from . import notes, tutor_bookings
from .booking_service import BookingError, start_booking
from .models import LeadNoteRole, booking_model
from .public_views import PATH_TYPES
from .scheduling import BOOKING_TIMEZONE_NAME
from .serializers import LeadNoteSerializer

VIEW_ASSIGNED_BOOKINGS = HasAppPermission('accounts.view_assigned_bookings')
START_PERMISSION = 'accounts.submit_booking_report'
SUBMIT_BOOKING_REPORT = HasAppPermission(START_PERMISSION)


def _error(code, message, http_status, **extra):
    return Response({'error': code, 'message': message, **extra}, status=http_status)


def _can_start(request):
    return has_app_permission(request.user, START_PERMISSION, request)


def _assigned_booking(request, booking_type, pk):
    """The ``<type>`` booking ``pk`` if it is assigned to the caller now, else None. An unknown type is 404."""
    try:
        model = booking_model(PATH_TYPES[booking_type])
    except KeyError:
        raise NotFound()
    return tutor_bookings.assigned_to(request.user, model).filter(pk=pk).first()


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
        can_start = _can_start(request)
        return Response(
            {
                'results': [
                    tutor_bookings.booking_row(booking, now, can_start) for booking in bookings[offset:offset + page_size]
                ],
                'count': len(bookings),
                'page': page,
                'page_size': page_size,
                'timezone': BOOKING_TIMEZONE_NAME,
            },
            status=status.HTTP_200_OK,
        )


class TutorBookingDetailView(APIView):
    """GET /api/tutor/bookings/<type>/<id>/ -- one booking assigned to the caller; any other is 404."""
    permission_classes = [IsAuthenticated, VIEW_ASSIGNED_BOOKINGS]

    def get(self, request, booking_type, pk, *args, **kwargs):
        booking = _assigned_booking(request, booking_type, pk)
        if booking is None:
            return _error('NOT_FOUND', 'No such booking.', status.HTTP_404_NOT_FOUND)
        return Response(
            tutor_bookings.booking_detail(booking, timezone.now(), _can_start(request)), status=status.HTTP_200_OK,
        )


class TutorBookingStartView(APIView):
    """
    POST /api/tutor/bookings/<type>/<id>/start/
    Start Demo / Start Diagnostic (booking_service.start_booking): record that
    the caller has started teaching the booking, now, by the server's clock.
    No body is read. 200 {"booking": <the booking, as GET answers it>,
    "changed"}: ``changed`` is false for one already started (a second click,
    another tab), which is left as it is. 409 START_TOO_EARLY (before
    ``start_opens_at``) or START_WINDOW_CLOSED (its slot has ended),
    BOOKING_COMPLETED, BOOKING_CANCELLED or BOOKING_RESCHEDULED; 503
    CAPACITY_CHECK_UNAVAILABLE when the booking is busy. A booking not assigned
    to the caller is 404, checked again under the booking's lock.
    """
    permission_classes = [IsAuthenticated, VIEW_ASSIGNED_BOOKINGS, SUBMIT_BOOKING_REPORT]

    def post(self, request, booking_type, pk, *args, **kwargs):
        booking = _assigned_booking(request, booking_type, pk)
        if booking is None:
            return _error('NOT_FOUND', 'No such booking.', status.HTTP_404_NOT_FOUND)
        try:
            booking, changed = start_booking(booking, request.user)
        except BookingError as exc:
            return _error(exc.code, exc.message, exc.http_status)
        # Read again with its report, as GET reads it: a started booking keeps its tutor.
        booking = tutor_bookings.assigned_to(request.user, type(booking)).get(pk=booking.pk)
        return Response(
            {'booking': tutor_bookings.booking_detail(booking, timezone.now(), can_start=True), 'changed': changed},
            status=status.HTTP_200_OK,
        )


class TutorBookingNotesView(APIView):
    """
    GET  /api/tutor/bookings/<type>/<id>/notes/
         The notes on the lead of one of the caller's bookings, oldest first --
         the lead's, shared by all its bookings, its BDE and the administrators
         (bookings.notes): {"results", "count", "timezone"}.
    POST /api/tutor/bookings/<type>/<id>/notes/ {"body": "..."}
         Add one, as its tutor; answers the notes as they now stand (201), or
         400 VALIDATION_ERROR for an empty or overlong note.
    A booking not assigned to the caller now is 404, as one that does not exist.
    """
    permission_classes = [IsAuthenticated, VIEW_ASSIGNED_BOOKINGS]

    def get(self, request, booking_type, pk, *args, **kwargs):
        booking = _assigned_booking(request, booking_type, pk)
        if booking is None:
            return _error('NOT_FOUND', 'No such booking.', status.HTTP_404_NOT_FOUND)
        return Response(notes.notes_of(booking.lead), status=status.HTTP_200_OK)

    def post(self, request, booking_type, pk, *args, **kwargs):
        booking = _assigned_booking(request, booking_type, pk)
        if booking is None:
            return _error('NOT_FOUND', 'No such booking.', status.HTTP_404_NOT_FOUND)
        serializer = LeadNoteSerializer(data=request.data)
        if not serializer.is_valid():
            return _error('VALIDATION_ERROR', notes.INVALID_NOTE, status.HTTP_400_BAD_REQUEST, fields=serializer.errors)
        notes.add_note(booking.lead, request.user, LeadNoteRole.TUTOR, serializer.validated_data['body'])
        return Response(notes.notes_of(booking.lead), status=status.HTTP_201_CREATED)
