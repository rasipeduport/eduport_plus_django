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
    POST   /api/bookings/diagnostic/<id>/demo-invite/   the parent's invitation to book a Demo from it
    POST   /api/bookings/demo/<id>/redemo/ {reason}     ask for a completed Demo to be taught again

    GET    /api/bookings/redemos/?q=&status=            every Re-Demo request, paged (bookings.redemos)
    GET    /api/bookings/redemos/<id>/                  one in full, with its Demos and chain
    GET    /api/bookings/redemos/<id>/tutors/           every active tutor, free or not in the booking window
    GET    /api/bookings/redemos/<id>/slots/?tutor_id=  the slots it may be booked in with that tutor
    POST   /api/bookings/redemos/<id>/schedule/ {tutor_id, date, time, remarks}  book the Re-Demo
    PUT    /api/bookings/redemos/<id>/remarks/ {remarks}  the administrators' remarks for its tutor

Its report, read-only, is under ``…/report/`` (reports.management_views).

``<type>`` is ``demo`` or ``diagnostic``: each type is a table of its own, so
a booking is named by its type and its id; any other type answers 404.

Reading needs accounts.view_all_bookings, changing the tutor
accounts.assign_booking_tutor; only the ADMIN role may hold either (a superuser
holds both, decision D1). Moving a booking needs accounts.reschedule_booking
too (the Admin only, Q23) and cancelling accounts.cancel_booking: a BDE holds
that one for their own leads' bookings (Q22), but never reaches these
Admin routes, which also need view_all_bookings. Sending a Demo invitation
needs accounts.send_lead_communications too: the link goes to the parent
(bookings.demo_invites). Asking for a Re-Demo needs
accounts.reschedule_booking (a Re-Demo, like a move, gives the child's Demo a
new slot), and scheduling a Re-Demo -- its tutor, slot and remarks -- or
changing its remarks accounts.assign_booking_tutor; reading one,
view_all_bookings. Cancel and reschedule reasons are
codes from a fixed list (Q9), never free text (decision M1); a Re-Demo's
reason and remarks are staff's words, kept on the request alone. Nothing in a request widens what is shown: every
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

from . import coordination, redemos
from .booking_service import (
    BookingError,
    LeadTimeConflict,
    TutorNotAssignable,
    TutorUnavailable,
    assign_tutor,
    cancel_booking,
    is_assignable_tutor,
    request_redemo,
    reschedule_booking,
    schedule_redemo,
    unassign_tutor,
)
from .demo_invites import invite_body, issue_invite
from .models import BookingSlot, BookingType, ReDemoStatus, booking_model
from .public_views import PATH_TYPES
from .scheduling import BOOKING_TIMEZONE_NAME
from .serializers import (
    CancelSerializer,
    RedemoRemarksSerializer,
    RedemoRequestSerializer,
    RedemoScheduleSerializer,
    RescheduleSerializer,
    TutorAssignmentSerializer,
)

User = get_user_model()

VIEW_ALL_BOOKINGS = HasAppPermission('accounts.view_all_bookings')
ASSIGN_BOOKING_TUTOR = HasAppPermission('accounts.assign_booking_tutor')
CANCEL_BOOKING = HasAppPermission('accounts.cancel_booking')
RESCHEDULE_BOOKING = HasAppPermission('accounts.reschedule_booking')
SEND_LEAD_COMMUNICATIONS = HasAppPermission('accounts.send_lead_communications')


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


class BookingDemoInviteView(APIView):
    """
    POST /api/bookings/diagnostic/<id>/demo-invite/
    The Diagnostic's invitation for its parent to book a Demo
    (bookings.demo_invites.issue_invite), for any lead -- one nobody owns
    included: 201 with a new one, 200 with the active one, so Copy, WhatsApp
    and Preview all pass on the same link until it expires. Answers
    ``{"invite": {"url", "status", "expires_at", ...}, "created"}``; 409
    NO_REPORT, DEMO_NOT_OFFERED or DEMO_ALREADY_BOOKED when the child may not
    be invited now. Only a Diagnostic sends one: any other type is 404.
    """
    permission_classes = [IsAuthenticated, VIEW_ALL_BOOKINGS, SEND_LEAD_COMMUNICATIONS]

    def post(self, request, booking_type, pk, *args, **kwargs):
        if booking_type != 'diagnostic':
            return _no_booking()
        booking = _bookings(booking_type).filter(pk=pk).first()
        if booking is None:
            return _no_booking()
        try:
            invite, created = issue_invite(booking, request.user, request=request)
        except BookingError as exc:
            return _error(exc.code, exc.message, exc.http_status)
        return Response(
            {'invite': invite_body(invite), 'created': created},
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class BookingRedemoView(APIView):
    """
    POST /api/bookings/demo/<id>/redemo/ {"reason": "..."}
    Ask for the completed Demo to be taught again (booking_service.request_redemo),
    for any lead -- one nobody owns included: 201 with the request in full
    (bookings.redemos.redemo_detail). The Demo is RE-DEMO REQUIRED at once.
    400 VALIDATION_ERROR or REASON_REQUIRED; 409 REDEMO_NOT_ELIGIBLE (not a
    completed Demo) or REDEMO_ALREADY_REQUESTED. Only a Demo is taught again:
    any other type is 404.
    """
    permission_classes = [IsAuthenticated, VIEW_ALL_BOOKINGS, RESCHEDULE_BOOKING]

    def post(self, request, booking_type, pk, *args, **kwargs):
        if PATH_TYPES.get(booking_type) != BookingType.DEMO:
            return _no_booking()
        booking = _bookings(booking_type).filter(pk=pk).first()
        if booking is None:
            return _no_booking()
        serializer = RedemoRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return _error('VALIDATION_ERROR', 'Give the reason for the Re-Demo.', status.HTTP_400_BAD_REQUEST,
                          fields=serializer.errors)
        try:
            redemo = request_redemo(booking, serializer.validated_data['reason'], actor=request.user)
        except BookingError as exc:
            return _error(exc.code, exc.message, exc.http_status)
        return Response(
            redemos.redemo_detail(_redemos().get(pk=redemo.pk), timezone.now(), request.user, request),
            status=status.HTTP_201_CREATED,
        )


def _redemos():
    return redemos.listed()


def _no_redemo():
    return _error('NOT_FOUND', 'No such Re-Demo request.', status.HTTP_404_NOT_FOUND)


class RedemoListView(APIView):
    """
    GET /api/bookings/redemos/?q=&status=&page=&page_size=
    Every Re-Demo request, newest first, always paged: {"results", "count",
    "page", "page_size", "timezone"}. ``q`` is the enquiry search (parent or
    child name, phone digits); ``status`` one of ReDemoStatus -- an unknown
    one answers 400 INVALID_INPUT. Where a request stands is read from its
    rows (bookings.redemo_chain), so the status filter reads every request
    the search leaves: Re-Demos are few.
    """
    permission_classes = [IsAuthenticated, VIEW_ALL_BOOKINGS]

    def get(self, request, *args, **kwargs):
        wanted = (request.query_params.get('status') or '').strip().upper()
        if wanted and wanted not in ReDemoStatus.values:
            return _error('INVALID_INPUT', 'Check the Re-Demo filters.', status.HTTP_400_BAD_REQUEST, fields=['status'])
        q = (request.query_params.get('q') or '').strip()
        if len(q) > coordination.MAX_SEARCH_LENGTH:
            return _error('INVALID_INPUT', 'Check the Re-Demo filters.', status.HTTP_400_BAD_REQUEST, fields=['q'])
        now = timezone.now()
        found = redemos.search(_redemos(), q).order_by('-requested_at', 'id')
        page, page_size = page_params(request)
        offset = (page - 1) * page_size
        if wanted:
            rows = redemos.redemo_rows(found, now, status=wanted)
            count, results = len(rows), rows[offset:offset + page_size]
        else:
            count, results = found.count(), redemos.redemo_rows(found[offset:offset + page_size], now)
        return Response(
            {'results': results, 'count': count, 'page': page, 'page_size': page_size, 'timezone': BOOKING_TIMEZONE_NAME},
            status=status.HTTP_200_OK,
        )


class RedemoDetailView(APIView):
    """GET /api/bookings/redemos/<id>/ -- one Re-Demo request in full (bookings.redemos.redemo_detail)."""
    permission_classes = [IsAuthenticated, VIEW_ALL_BOOKINGS]

    def get(self, request, pk, *args, **kwargs):
        redemo = _redemos().filter(pk=pk).first()
        if redemo is None:
            return _no_redemo()
        return Response(redemos.redemo_detail(redemo, timezone.now(), request.user, request), status=status.HTTP_200_OK)


class RedemoTutorsView(APIView):
    """
    GET /api/bookings/redemos/<id>/tutors/
    Every active tutor for scheduling the request: AVAILABLE with how many
    Demo slots in the booking window they are free for, or UNAVAILABLE, each
    with their Meet link and the original Demo's tutor marked; and whether
    the request may be scheduled now (``schedulable``, else ``refusal``).
    """
    permission_classes = [IsAuthenticated, VIEW_ALL_BOOKINGS]

    def get(self, request, pk, *args, **kwargs):
        redemo = _redemos().filter(pk=pk).first()
        if redemo is None:
            return _no_redemo()
        schedulable, refusal = redemos.schedulable(redemo)
        return Response(
            {
                'redemo_id': str(redemo.id),
                'timezone': BOOKING_TIMEZONE_NAME,
                'schedulable': schedulable,
                'refusal': refusal,
                'tutors': redemos.tutor_options(redemo, timezone.now()),
            },
            status=status.HTTP_200_OK,
        )


class RedemoSlotsView(APIView):
    """
    GET /api/bookings/redemos/<id>/slots/?tutor_id=<account id>
    The Demo slots the Re-Demo may be booked in with that tutor
    (bookings.redemos.slot_options): a reschedule picker's dates and slots
    for the lead, a slot the tutor is not free for refused as TUTOR_BUSY.
    400 INVALID_TUTOR for an account that is not an active tutor.
    """
    permission_classes = [IsAuthenticated, VIEW_ALL_BOOKINGS, ASSIGN_BOOKING_TUTOR]

    def get(self, request, pk, *args, **kwargs):
        redemo = _redemos().filter(pk=pk).first()
        if redemo is None:
            return _no_redemo()
        serializer = TutorAssignmentSerializer(data=request.query_params)
        tutor = User.objects.filter(pk=serializer.validated_data['tutor_id']).first() if serializer.is_valid() else None
        if not is_assignable_tutor(tutor):
            return _error(TutorNotAssignable.code, TutorNotAssignable.message, TutorNotAssignable.http_status)
        schedulable, refusal = redemos.schedulable(redemo)
        return Response(
            {
                'redemo_id': str(redemo.id),
                'timezone': BOOKING_TIMEZONE_NAME,
                'tutor': {'id': str(tutor.pk), 'full_name': tutor.full_name or tutor.email,
                          'tutor_meet_link': tutor.tutor_meet_link},
                'schedulable': schedulable,
                'refusal': refusal,
                'dates': redemos.slot_options(redemo, tutor, timezone.now()),
            },
            status=status.HTTP_200_OK,
        )


class RedemoScheduleView(APIView):
    """
    POST /api/bookings/redemos/<id>/schedule/
        {"tutor_id", "date": "YYYY-MM-DD", "time": "HH:MM", "remarks": "..."}
    Book the Re-Demo with that tutor in that Demo slot, the remarks kept for
    them (booking_service.schedule_redemo): 201 with the request in full and
    the new booking's id. The booking is a Demo like any other from then on,
    moved, reassigned or cancelled from its own sheet. 400 VALIDATION_ERROR,
    INVALID_TUTOR, DATE_OUT_OF_WINDOW or REMARKS_TOO_LONG; 409
    REDEMO_SCHEDULED, REDEMO_COMPLETED, TUTOR_UNAVAILABLE (with
    ``conflict``), SLOT_UNAVAILABLE, SLOT_FULL, LEAD_ALREADY_BOOKED or
    LEAD_TIME_CONFLICT (with ``conflict``).
    """
    permission_classes = [IsAuthenticated, VIEW_ALL_BOOKINGS, ASSIGN_BOOKING_TUTOR]

    def post(self, request, pk, *args, **kwargs):
        redemo = _redemos().filter(pk=pk).first()
        if redemo is None:
            return _no_redemo()
        serializer = RedemoScheduleSerializer(data=request.data)
        if not serializer.is_valid():
            return _error('VALIDATION_ERROR', 'Choose a tutor, a date and a time.', status.HTTP_400_BAD_REQUEST,
                          fields=serializer.errors)
        data = serializer.validated_data
        tutor = User.objects.filter(pk=data['tutor_id']).first()
        if tutor is None:
            return _error(TutorNotAssignable.code, TutorNotAssignable.message, TutorNotAssignable.http_status)
        try:
            booking = schedule_redemo(
                redemo, tutor, data['date'], data['time'], actor=request.user, remarks=data.get('remarks'),
            )
        except TutorUnavailable as exc:
            return _error(exc.code, exc.message, exc.http_status, conflict=coordination.conflict_reason(exc.conflict))
        except LeadTimeConflict as exc:
            return _error(exc.code, exc.message, exc.http_status, conflict=coordination.lead_conflict_reason(exc.booking))
        except BookingError as exc:
            return _error(exc.code, exc.message, exc.http_status)
        return Response(
            {**redemos.redemo_detail(_redemos().get(pk=redemo.pk), timezone.now(), request.user, request),
             'booking_id': str(booking.id)},
            status=status.HTTP_201_CREATED,
        )


class RedemoRemarksView(APIView):
    """
    PUT /api/bookings/redemos/<id>/remarks/ {"remarks": "..."}
    The administrators' remarks for the Re-Demo's tutor ('' clears them):
    answers the request in full with ``changed``. Shown to the tutor teaching
    it (bookings.tutor_bookings), never to the BDE.
    """
    permission_classes = [IsAuthenticated, VIEW_ALL_BOOKINGS, ASSIGN_BOOKING_TUTOR]

    def put(self, request, pk, *args, **kwargs):
        redemo = _redemos().filter(pk=pk).first()
        if redemo is None:
            return _no_redemo()
        serializer = RedemoRemarksSerializer(data=request.data)
        if not serializer.is_valid():
            return _error('VALIDATION_ERROR', 'Check the remarks.', status.HTTP_400_BAD_REQUEST, fields=serializer.errors)
        try:
            redemo, changed = redemos.set_remarks(redemo, serializer.validated_data['remarks'], request.user,
                                                 request=request)
        except BookingError as exc:
            return _error(exc.code, exc.message, exc.http_status)
        return Response(
            {**redemos.redemo_detail(_redemos().get(pk=redemo.pk), timezone.now(), request.user, request),
             'changed': changed},
            status=status.HTTP_200_OK,
        )
