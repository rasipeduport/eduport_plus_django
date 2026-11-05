"""
The Hub's parent communication endpoints (Phase 3.1 reading, 3.2 the parent's confirmation):

    GET  /api/communications/bookings/<type>/<id>/                       one booking's communication (communications.overview)
    GET  /api/communications/bookings/<type>/<id>/preview/?step=<STEP>   what its message for a step would say now
    POST /api/communications/bookings/<type>/<id>/confirmation-request/  ask the parent to confirm
    POST /api/communications/bookings/<type>/<id>/parent-confirmation/   record the parent's answer

``<type>`` is ``demo`` or ``diagnostic``. Every endpoint works within the
caller's scope: accounts.view_all_communications -- every booking (the
Admin; a superuser holds every permission, decision D1) -- or
accounts.view_own_lead_communications -- the bookings of the caller's own
leads only (a BDE). Nothing in a request widens that: for a BDE, another
BDE's booking, one of a lead nobody owns, one of the other type and one that
does not exist are all answered alike, 404 "No such booking", and the
services check the lead is theirs again under the booking's lock. Asking for
confirmation (and seeing what it would say) also needs
accounts.send_lead_communications; recording the answer
accounts.record_parent_confirmation. Tutors, mentors and the Sales TL hold
none of these -- the communication carries the parent's phone number and
every message sent to them.

The rules are the services' (communications.services, bookings.booking_service),
answered as they refuse: ``{"error": CODE, "message": ...}`` with their status.
"""
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.authz import has_app_permission
from bookings.booking_service import BookingBusy, BookingError, record_parent_confirmation
from bookings.models import booking_model
from bookings.public_views import PATH_TYPES
from core.permissions import HasAnyAppPermission, HasAppPermission

from .models import Step
from .overview import booking_communication
from .rendering import Requirement
from .serializers import ParentAnswerSerializer
from .services import CommunicationError, MessageBlocked, preview, request_confirmation

VIEW_ALL_COMMUNICATIONS = 'accounts.view_all_communications'
VIEW_OWN_LEAD_COMMUNICATIONS = 'accounts.view_own_lead_communications'
SEND_COMMUNICATIONS = 'accounts.send_lead_communications'
RECORD_CONFIRMATION = 'accounts.record_parent_confirmation'
IN_SCOPE = HasAnyAppPermission(VIEW_ALL_COMMUNICATIONS, VIEW_OWN_LEAD_COMMUNICATIONS)
# The steps that send a message, which a preview may name: all but the 15-minute call.
MESSAGE_STEPS = [step for step in Step.values if step != Step.PRE_ACTIVITY_CALL]


def visible_bookings(request, booking_type):
    """
    The bookings of a ``demo`` or ``diagnostic`` path segment the caller may see
    the communication of -- every one, or their own leads' -- or None for any
    other segment.
    """
    try:
        model = booking_model(PATH_TYPES[booking_type])
    except KeyError:
        return None
    bookings = model.objects.select_related('slot', 'lead__owner_bde', 'assigned_tutor', 'parent_confirmation_by')
    if has_app_permission(request.user, VIEW_ALL_COMMUNICATIONS, request):
        return bookings
    return bookings.filter(lead__owner_bde=request.user)


def _visible(request, booking_type, pk):
    bookings = visible_bookings(request, booking_type)
    return bookings.filter(pk=pk).first() if bookings is not None else None


def _owner_bde(request):
    """
    Whose leads the caller acts on -- checked again by the service under the
    booking's lock -- or None for one who may act on every booking.
    """
    return None if has_app_permission(request.user, VIEW_ALL_COMMUNICATIONS, request) else request.user


def _communication(request, booking_type, pk, **extra):
    """The booking's communication as it now stands, with ``extra`` beside it."""
    booking = visible_bookings(request, booking_type).get(pk=pk)
    return {**booking_communication(booking, timezone.now(), request.user, request), **extra}


def _requirements(requirements):
    return [{'code': requirement, 'label': Requirement(requirement).label} for requirement in requirements]


def _error(code, message, http_status, **extra):
    return Response({'error': code, 'message': message, **extra}, status=http_status)


def _no_booking():
    return _error('NOT_FOUND', 'No such booking.', status.HTTP_404_NOT_FOUND)


def _refusal(exc):
    """A service's refusal as the API answers it."""
    if isinstance(exc, BookingBusy):
        return _error('BOOKING_BUSY', 'This booking is being changed right now. Try again in a moment.',
                      status.HTTP_503_SERVICE_UNAVAILABLE)
    if isinstance(exc, MessageBlocked):
        return _error(exc.code, exc.message, exc.http_status, missing=_requirements(exc.missing))
    return _error(exc.code, exc.message, exc.http_status)


class BookingCommunicationView(APIView):
    """GET /api/communications/bookings/<type>/<id>/ -- the booking's communication, read-only."""
    permission_classes = [IsAuthenticated, IN_SCOPE]

    def get(self, request, booking_type, pk, *args, **kwargs):
        booking = _visible(request, booking_type, pk)
        if booking is None:
            return _no_booking()
        return Response(booking_communication(booking, timezone.now(), request.user, request), status=status.HTTP_200_OK)


class BookingMessagePreviewView(APIView):
    """
    GET /api/communications/bookings/<type>/<id>/preview/?step=<STEP>
    What the booking's message for ``step`` would say now (services.preview),
    exactly as WhatsApp would show it: ``text``, null while it lacks something
    -- ``requirements`` lists each with whether it is met. Writes nothing.
    400 INVALID_INPUT for a step that sends no message.
    """
    permission_classes = [IsAuthenticated, HasAppPermission(SEND_COMMUNICATIONS), IN_SCOPE]

    def get(self, request, booking_type, pk, *args, **kwargs):
        step = (request.query_params.get('step') or '').strip().upper()
        if step not in MESSAGE_STEPS:
            return _error('INVALID_INPUT', 'Choose a step that sends a message.', status.HTTP_400_BAD_REQUEST,
                          fields=['step'])
        booking = _visible(request, booking_type, pk)
        if booking is None:
            return _no_booking()
        shown = preview(booking, step, timezone.now())
        return Response(
            {
                'step': step,
                'step_label': Step(step).label,
                'ready': shown.text is not None,
                'text': shown.text,
                'requirements': [
                    {'code': requirement, 'label': Requirement(requirement).label, 'met': met}
                    for requirement, met in shown.requirements
                ],
            },
            status=status.HTTP_200_OK,
        )


class ConfirmationRequestView(APIView):
    """
    POST /api/communications/bookings/<type>/<id>/confirmation-request/
    Ask the parent to confirm (services.request_confirmation): the request is
    written Pending, and the sending engine sends it. Asking again returns the
    request already written, never a second. Answers the booking's
    communication in full with ``created`` (201, or 200 when it already was).
    409 BOOKING_NOT_UPCOMING, CONFIRMATION_NOT_NEEDED, NOT_PLANNED, or
    MESSAGE_BLOCKED with what is ``missing`` (each {code, label}).
    """
    permission_classes = [IsAuthenticated, HasAppPermission(SEND_COMMUNICATIONS), IN_SCOPE]

    def post(self, request, booking_type, pk, *args, **kwargs):
        booking = _visible(request, booking_type, pk)
        if booking is None:
            return _no_booking()
        try:
            _message, created = request_confirmation(booking, actor=request.user, owner_bde=_owner_bde(request))
        except (CommunicationError, BookingError) as exc:
            return _refusal(exc)
        return Response(_communication(request, booking_type, pk, created=created),
                        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class ParentConfirmationView(APIView):
    """
    POST /api/communications/bookings/<type>/<id>/parent-confirmation/
         {"outcome": "CONFIRMED" | "NOT_CONFIRMED", "reason"?: <code>, "confirm_cancellation"?: true}
    Record the parent's answer (booking_service.record_parent_confirmation).
    Not Confirmed needs a reason from the list and ``confirm_cancellation``:
    it cancels the booking, in the same step. Answers the booking's
    communication in full with ``changed`` (false for the answer already
    recorded). 400 VALIDATION_ERROR, INVALID_CONFIRMATION, INVALID_REASON or
    CANCELLATION_NOT_CONFIRMED; 409 for a booking cancelled, completed, moved
    or started.
    """
    permission_classes = [IsAuthenticated, HasAppPermission(RECORD_CONFIRMATION), IN_SCOPE]

    def post(self, request, booking_type, pk, *args, **kwargs):
        booking = _visible(request, booking_type, pk)
        if booking is None:
            return _no_booking()
        serializer = ParentAnswerSerializer(data=request.data)
        if not serializer.is_valid():
            return _error('VALIDATION_ERROR', "Check the parent's answer.", status.HTTP_400_BAD_REQUEST,
                          fields=serializer.errors)
        answer = serializer.validated_data
        try:
            _booking, changed = record_parent_confirmation(
                booking, answer['outcome'], reason_code=answer['reason'],
                confirm_cancellation=answer['confirm_cancellation'], actor=request.user, owner_bde=_owner_bde(request),
            )
        except BookingError as exc:
            return _refusal(exc)
        return Response(_communication(request, booking_type, pk, changed=changed), status=status.HTTP_200_OK)
