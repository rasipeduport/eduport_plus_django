"""
Booking management for the Admin / Coordinator (bookings.coordination):

    GET    /api/bookings/<type>/                        every booking of the type, paged and filtered
    GET    /api/bookings/<type>/<id>/                   one booking in full
    GET    /api/bookings/<type>/<id>/tutors/            every active tutor, free or not for its slot
    GET    /api/bookings/slots/<slot id>/tutors/        the same for a slot
    PUT    /api/bookings/<type>/<id>/tutor/ {tutor_id}  assign or reassign its tutor
    DELETE /api/bookings/<type>/<id>/tutor/             unassign it
    GET    /api/bookings/<type>/<id>/history/           its timeline, across its reschedule chain
    GET    /api/bookings/<type>/<id>/reschedule-options/  where it may move, and whether its tutor is free there
    POST   /api/bookings/<type>/<id>/reschedule/ {date, time, reason}  move it
    POST   /api/bookings/<type>/<id>/cancel/ {reason}   cancel it, or mark it No-show

Its report, read-only, is under ``…/report/`` (reports.management_views).

``<type>`` is ``demo`` or ``diagnostic``: each type is a table of its own, so
a booking is named by its type and its id; any other type answers 404.

Reading needs accounts.view_all_bookings, changing the tutor
accounts.assign_booking_tutor; only the ADMIN role may hold either (a superuser
holds both, decision D1). Moving a booking needs accounts.reschedule_booking
too (the Admin only, Q23) and cancelling accounts.cancel_booking: a BDE holds
that one for their own leads' bookings (Q22), but never reaches these
Admin routes, which also need view_all_bookings. Reasons are codes from a
fixed list (Q9), never free text (decision M1). Nothing in a request widens what is shown: every
caller holding the permission sees every booking, and nobody else sees any.
The tutor is changed only by bookings.booking_service, which checks the tutor
and the booking again under its locks whatever the picker showed. Errors
answer ``{"error": CODE, "message": ...}``.
"""
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.pagination import page_params
from core.permissions import ByMethod, HasAppPermission

from . import coordination
from .booking_service import (
    BookingError,
    LeadTimeConflict,
    TutorNotAssignable,
    TutorUnavailable,
    assign_tutor,
    cancel_booking,
    reschedule_booking,
    unassign_tutor,
)
from .models import BookingSlot, booking_model
from .public_views import PATH_TYPES
from .scheduling import BOOKING_TIMEZONE_NAME
from .serializers import CancelSerializer, RescheduleSerializer, TutorAssignmentSerializer

User = get_user_model()

VIEW_ALL_BOOKINGS = HasAppPermission('accounts.view_all_bookings')
ASSIGN_BOOKING_TUTOR = HasAppPermission('accounts.assign_booking_tutor')
CANCEL_BOOKING = HasAppPermission('accounts.cancel_booking')
RESCHEDULE_BOOKING = HasAppPermission('accounts.reschedule_booking')


def _error(code, message, http_status, **extra):
    return Response({'error': code, 'message': message, **extra}, status=http_status)


def _no_booking():
    return _error('NOT_FOUND', 'No such booking.', status.HTTP_404_NOT_FOUND)


def _bookings(booking_type):
    """The bookings of a ``demo`` or ``diagnostic`` path segment, as their rows read them; any other is 404."""
    try:
        model = booking_model(PATH_TYPES[booking_type])
    except KeyError:
        raise NotFound()
    return coordination.listed(model)


class BookingListView(APIView):
    """
    GET /api/bookings/<type>/?status=&assigned=&tutor=&slot=&from=&to=&when=&report=&q=&page=&page_size=
    Every booking of the type, soonest slot first (``when=past``: most recent first),
    always paged: {"results", "count", "page", "page_size", "timezone"}. The
    filters are coordination.parse_filters'; an unknown value answers 400
    INVALID_INPUT naming the parameters, never a guessed filter.
    """
    permission_classes = [IsAuthenticated, VIEW_ALL_BOOKINGS]

    def get(self, request, booking_type, *args, **kwargs):
        rows = _bookings(booking_type)
        filters, invalid = coordination.parse_filters(request.query_params)
        if invalid:
            return _error('INVALID_INPUT', 'Check the booking filters.', status.HTTP_400_BAD_REQUEST, fields=invalid)
        now = timezone.now()
        bookings = coordination.filtered(rows, now, **filters)
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
    """GET /api/bookings/<type>/<id>/ -- one booking in full."""
    permission_classes = [IsAuthenticated, VIEW_ALL_BOOKINGS]

    def get(self, request, booking_type, pk, *args, **kwargs):
        booking = _bookings(booking_type).filter(pk=pk).first()
        if booking is None:
            return _no_booking()
        return Response(coordination.booking_detail(booking, timezone.now(), request.user, request), status=status.HTTP_200_OK)


class BookingTutorsView(APIView):
    """
    GET /api/bookings/<type>/<id>/tutors/
    Every active tutor for the booking's slot, AVAILABLE or UNAVAILABLE with
    the reason, its current tutor marked; and whether its tutor may be changed
    at all (a cancelled booking or a started slot keeps the one it has).
    """
    permission_classes = [IsAuthenticated, VIEW_ALL_BOOKINGS]

    def get(self, request, booking_type, pk, *args, **kwargs):
        booking = _bookings(booking_type).filter(pk=pk).first()
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
    PUT    /api/bookings/<type>/<id>/tutor/ {"tutor_id": "<account id>"}
           Assign the tutor, or replace the one assigned (the same one again
           changes nothing). 409 TUTOR_UNAVAILABLE with ``conflict`` when they
           already teach a class or another booking then; 400 INVALID_TUTOR
           for an account that is not an active tutor; 409 BOOKING_CANCELLED,
           BOOKING_COMPLETED, BOOKING_RESCHEDULED, BOOKING_STARTED (its tutor
           has started it) or SLOT_ENDED when the booking's tutor can no
           longer change. ``conflict`` names a booking
           by ``booking_type`` and ``booking_id``.
    DELETE /api/bookings/<type>/<id>/tutor/
           Unassign it, under the same rules.
    Both answer the booking in full with ``changed``.
    """
    permission_classes = [IsAuthenticated, ByMethod(PUT=ASSIGN_BOOKING_TUTOR, DELETE=ASSIGN_BOOKING_TUTOR)]

    def put(self, request, booking_type, pk, *args, **kwargs):
        rows = _bookings(booking_type)
        booking = rows.filter(pk=pk).first()
        if booking is None:
            return _no_booking()
        serializer = TutorAssignmentSerializer(data=request.data)
        if not serializer.is_valid():
            return _error('VALIDATION_ERROR', 'Choose a tutor.', status.HTTP_400_BAD_REQUEST, fields=serializer.errors)
        tutor = User.objects.filter(pk=serializer.validated_data['tutor_id']).first()
        if tutor is None:
            return _error(TutorNotAssignable.code, TutorNotAssignable.message, TutorNotAssignable.http_status)
        return self._changed(request, rows, lambda: assign_tutor(booking, tutor, actor=request.user))

    def delete(self, request, booking_type, pk, *args, **kwargs):
        rows = _bookings(booking_type)
        booking = rows.filter(pk=pk).first()
        if booking is None:
            return _no_booking()
        return self._changed(request, rows, lambda: unassign_tutor(booking, actor=request.user))

    @staticmethod
    def _changed(request, rows, change):
        try:
            booking, changed = change()
        except TutorUnavailable as exc:
            return _error(exc.code, exc.message, exc.http_status, conflict=coordination.conflict_reason(exc.conflict))
        except BookingError as exc:
            return _error(exc.code, exc.message, exc.http_status)
        booking = rows.get(pk=booking.pk)
        return Response(
            {**coordination.booking_detail(booking, timezone.now(), request.user, request), 'changed': changed},
            status=status.HTTP_200_OK,
        )


class BookingHistoryView(APIView):
    """
    GET /api/bookings/<type>/<id>/history/
    The booking's timeline (coordination.booking_history): the events of every
    booking in its reschedule chain, oldest first, with who made each change.
    """
    permission_classes = [IsAuthenticated, VIEW_ALL_BOOKINGS]

    def get(self, request, booking_type, pk, *args, **kwargs):
        booking = _bookings(booking_type).filter(pk=pk).first()
        if booking is None:
            return _no_booking()
        return Response(coordination.booking_history(booking, timezone.now()), status=status.HTTP_200_OK)


class RescheduleOptionsView(APIView):
    """
    GET /api/bookings/<type>/<id>/reschedule-options/
    The slots the booking may move to (coordination.reschedule_options): the
    public pages' window with seats, why a slot is out of reach, and whether
    its tutor is free there. ``reschedulable`` is false, with the reason, for a
    booking that can no longer move.
    """
    permission_classes = [IsAuthenticated, VIEW_ALL_BOOKINGS, RESCHEDULE_BOOKING]

    def get(self, request, booking_type, pk, *args, **kwargs):
        booking = _bookings(booking_type).filter(pk=pk).first()
        if booking is None:
            return _no_booking()
        return Response(coordination.reschedule_options(booking, timezone.now()), status=status.HTTP_200_OK)


class BookingRescheduleView(APIView):
    """
    POST /api/bookings/<type>/<id>/reschedule/ {"date": "YYYY-MM-DD", "time": "HH:MM", "reason": <code>}
    Move the booking (booking_service.reschedule_booking): 201 with the
    replacement booking in full, the one it replaced, and whether the tutor
    carried over (``tutor``, Q24). 400 VALIDATION_ERROR or DATE_OUT_OF_WINDOW;
    409 BOOKING_COMPLETED, BOOKING_CANCELLED, BOOKING_RESCHEDULED,
    BOOKING_STARTED (its tutor has started it; a booking whose scheduled time
    passed with no start may still move), SLOT_UNAVAILABLE, SLOT_FULL,
    SAME_SLOT, LEAD_ALREADY_BOOKED or LEAD_TIME_CONFLICT (with ``conflict``,
    Q26); 503 when the slot is busy.
    """
    permission_classes = [IsAuthenticated, VIEW_ALL_BOOKINGS, RESCHEDULE_BOOKING]

    def post(self, request, booking_type, pk, *args, **kwargs):
        rows = _bookings(booking_type)
        booking = rows.filter(pk=pk).first()
        if booking is None:
            return _no_booking()
        serializer = RescheduleSerializer(data=request.data)
        if not serializer.is_valid():
            return _error('VALIDATION_ERROR', 'Choose a new date, time and reason.', status.HTTP_400_BAD_REQUEST,
                          fields=serializer.errors)
        data = serializer.validated_data
        try:
            result = reschedule_booking(booking, data['date'], data['time'], reason_code=data['reason'], actor=request.user)
        except LeadTimeConflict as exc:
            return _error(exc.code, exc.message, exc.http_status, conflict=coordination.lead_conflict_reason(exc.booking))
        except BookingError as exc:
            return _error(exc.code, exc.message, exc.http_status)
        now = timezone.now()
        return Response(
            {
                'booking': coordination.booking_detail(rows.get(pk=result.booking.pk), now, request.user, request),
                'previous': {'id': str(result.previous.id), 'status': result.previous.status},
                'tutor': coordination.tutor_outcome(result),
            },
            status=status.HTTP_201_CREATED,
        )


class BookingCancelView(APIView):
    """
    POST /api/bookings/<type>/<id>/cancel/ {"reason": <code>}
    Cancel the booking (booking_service.cancel_booking); NO_SHOW marks a
    no-show, only once its scheduled time has passed (D12), whether or not its
    tutor started it. Answers the booking in full
    with ``changed`` (false for one already cancelled). 400 VALIDATION_ERROR;
    409 BOOKING_COMPLETED, BOOKING_RESCHEDULED or NO_SHOW_BEFORE_START.
    """
    permission_classes = [IsAuthenticated, VIEW_ALL_BOOKINGS, CANCEL_BOOKING]

    def post(self, request, booking_type, pk, *args, **kwargs):
        rows = _bookings(booking_type)
        booking = rows.filter(pk=pk).first()
        if booking is None:
            return _no_booking()
        serializer = CancelSerializer(data=request.data)
        if not serializer.is_valid():
            return _error('VALIDATION_ERROR', 'Choose a reason.', status.HTTP_400_BAD_REQUEST, fields=serializer.errors)
        try:
            booking, changed = cancel_booking(booking, reason_code=serializer.validated_data['reason'], actor=request.user)
        except BookingError as exc:
            return _error(exc.code, exc.message, exc.http_status)
        return Response(
            {**coordination.booking_detail(rows.get(pk=booking.pk), timezone.now(), request.user, request), 'changed': changed},
            status=status.HTTP_200_OK,
        )
