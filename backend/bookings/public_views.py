"""
The public booking and lead APIs, called only by the marketing site's server
(bookings.authentication):

    GET  /api/public/booking-calendar/<demo|diagnostic>/
    POST /api/public/bookings/<demo|diagnostic>/
    POST /api/public/leads/            a lead form's submission
    POST /api/public/demo-invites/state/   what a Demo invitation's page shows
    POST /api/public/demo-invites/book/    a Demo booked with an invitation

Errors answer ``{"error": CODE, "message": ...}``; the marketing server maps
the booking codes onto the booking pages' own (SLOT_FULL, DATE_OUT_OF_WINDOW,
CAPACITY_CHECK_UNAVAILABLE). Its lead forms answer the parent from Google
Sheets alone, so what this lead API answers never reaches a parent. A Demo
invitation's token travels in the request body, never the path, so no access
log keeps it.
"""
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView

from .authentication import BookingServiceAuthentication, IsBookingService
from .booking_service import BookingError, BookingRequest, InviteNotFound, create_booking, create_invited_demo_booking
from .demo_invites import public_state
from .lead_intake import TooManyLeads, record_form_lead
from .leads import InvalidLeadDetails
from .models import SLOT_CAPACITY, SLOT_MINUTES, BookingType
from .public_serializers import BookingRequestSerializer, DemoInviteBookingSerializer, LeadFormSerializer
from .scheduling import BOOKING_TIMEZONE_NAME, calendar
from .throttles import BookingCalendarThrottle, BookingCreateThrottle, LeadCreateThrottle

PATH_TYPES = {'demo': BookingType.DEMO, 'diagnostic': BookingType.DIAGNOSTIC}
NO_STORE = {'Cache-Control': 'no-store'}


def _booking_type(value):
    try:
        return PATH_TYPES[value]
    except KeyError:
        raise NotFound()


class PublicBookingCalendarView(APIView):
    """The bookable window of one booking type: every date, every active time and its status."""
    authentication_classes = [BookingServiceAuthentication]
    permission_classes = [IsBookingService]
    throttle_classes = [BookingCalendarThrottle]

    def get(self, request, booking_type):
        booking_type = _booking_type(booking_type)
        return Response(
            {
                'booking_type': booking_type,
                'timezone': BOOKING_TIMEZONE_NAME,
                'slot_minutes': SLOT_MINUTES,
                'capacity': SLOT_CAPACITY,
                'dates': calendar(booking_type),
            },
            headers=NO_STORE,
        )


class PublicBookingCreateView(APIView):
    """
    Book one slot: 201 for a new booking, 200 for a repeated submission, which
    gets the booking it already made. ``ref`` is the BDE link token from the
    page's URL; nothing else names a BDE, and a token that cannot attribute
    the booking never blocks it.
    """
    authentication_classes = [BookingServiceAuthentication]
    permission_classes = [IsBookingService]
    throttle_classes = [BookingCreateThrottle]

    def post(self, request, booking_type):
        booking_type = _booking_type(booking_type)
        serializer = BookingRequestSerializer(data=request.data, context={'booking_type': booking_type})
        if not serializer.is_valid():
            return Response(
                {'error': 'VALIDATION_ERROR', 'message': 'Check the booking details.', 'fields': serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )
        data = serializer.validated_data
        try:
            booking, created = create_booking(BookingRequest(
                booking_type=booking_type,
                date=data['date'],
                time=data['time'],
                parent_name=data['parent_name'],
                phone_dial_code=data['phone']['dial_code'],
                phone_number=data['phone']['number'],
                student_name=data['student_name'],
                school=data['school'],
                student_class=data['student_class'],
                syllabus=data['syllabus'],
                country=data['country'],
                display_time=data['display_time'],
                ref=request.data.get('ref') if hasattr(request.data, 'get') else None,
            ))
        except BookingError as exc:
            return Response({'error': exc.code, 'message': exc.message}, status=exc.http_status)
        except InvalidLeadDetails as exc:
            return Response(
                {'error': 'VALIDATION_ERROR', 'message': exc.message, 'fields': {exc.field: [exc.message]}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(
            {'booking_id': str(booking.id), 'created': created},
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class PublicDemoInviteStateView(APIView):
    """
    POST /api/public/demo-invites/state/ {"token"}
    What the invitation page shows (bookings.demo_invites.public_state):
    ``{"status": ACTIVE | USED | EXPIRED | REVOKED | UNAVAILABLE, "expires_at"}``,
    404 INVITE_NOT_FOUND for a token that names no invitation. Nothing about
    the child or the parent, and nothing changes: opening or previewing an
    invitation never uses it.
    """
    authentication_classes = [BookingServiceAuthentication]
    permission_classes = [IsBookingService]
    # Read as often as the page is opened, like the calendar beside it.
    throttle_classes = [BookingCalendarThrottle]

    def post(self, request):
        token = request.data.get('token') if hasattr(request.data, 'get') else None
        state = public_state(token)
        if state is None:
            return Response(
                {'error': InviteNotFound.code, 'message': InviteNotFound.message},
                status=InviteNotFound.http_status, headers=NO_STORE,
            )
        return Response(state, headers=NO_STORE)


class PublicDemoInviteBookView(APIView):
    """
    POST /api/public/demo-invites/book/ {"token", "date", "time", "display_time"}
    Book a Demo with an invitation (booking_service.create_invited_demo_booking):
    201 for a new booking, 200 for a repeated submission, which gets the
    booking it already made. The invitation names the lead; nothing about the
    child or the parent is sent or changed. 404 INVITE_NOT_FOUND; 409
    INVITE_USED, INVITE_EXPIRED, INVITE_REVOKED, DEMO_ALREADY_BOOKED,
    DEMO_NOT_OFFERED or any refusal a public booking meets.
    """
    authentication_classes = [BookingServiceAuthentication]
    permission_classes = [IsBookingService]
    throttle_classes = [BookingCreateThrottle]

    def post(self, request):
        serializer = DemoInviteBookingSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {'error': 'VALIDATION_ERROR', 'message': 'Check the booking details.', 'fields': serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )
        data = serializer.validated_data
        try:
            booking, created = create_invited_demo_booking(
                data['token'], data['date'], data['time'], display_time=data['display_time'],
            )
        except BookingError as exc:
            return Response({'error': exc.code, 'message': exc.message}, status=exc.http_status)
        return Response(
            {'booking_id': str(booking.id), 'created': created},
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class PublicLeadCreateView(APIView):
    """
    A lead form's submission (bookings.lead_intake.record_form_lead): 201 for
    a new lead, nobody's until an administrator assigns it; 200 for a child
    who already has a lead, which is left as it is -- so the marketing server
    may retry a submission without ever making a second lead.
    """
    authentication_classes = [BookingServiceAuthentication]
    permission_classes = [IsBookingService]
    throttle_classes = [LeadCreateThrottle]

    def post(self, request):
        serializer = LeadFormSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {'error': 'VALIDATION_ERROR', 'message': 'Check the lead details.', 'fields': serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )
        data = serializer.validated_data
        details = {
            'parent_name': data['parent_name'],
            'phone_dial_code': data['phone']['dial_code'],
            'phone_number': data['phone']['number'],
            'student_name': data['student_name'],
            'school_name': data['school'],
            'grade': data['grade'],
            'syllabus': data['syllabus'],
            'country': data['country'],
        }
        try:
            lead, created = record_form_lead(details, source=data['source'], utm=data.get('utm'))
        except InvalidLeadDetails as exc:
            return Response(
                {'error': 'VALIDATION_ERROR', 'message': exc.message, 'fields': {exc.field: [exc.message]}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except TooManyLeads:
            return Response(
                {'error': 'TOO_MANY_LEADS', 'message': 'Too many leads from this phone number today.'},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
        return Response(
            {'lead_id': str(lead.pk), 'created': created},
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )
