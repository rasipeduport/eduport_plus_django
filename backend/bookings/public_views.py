"""
The public booking API, called only by the marketing site's server
(bookings.authentication):

    GET  /api/public/booking-calendar/<demo|diagnostic>/
    POST /api/public/bookings/<demo|diagnostic>/

Errors answer ``{"error": CODE, "message": ...}``; the marketing server maps
the codes onto the booking pages' own (SLOT_FULL, DATE_OUT_OF_WINDOW,
CAPACITY_CHECK_UNAVAILABLE).
"""
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView

from .authentication import BookingServiceAuthentication, IsBookingService
from .booking_service import BookingError, BookingRequest, create_booking
from .leads import InvalidLeadDetails
from .models import SLOT_CAPACITY, SLOT_MINUTES, BookingType
from .public_serializers import BookingRequestSerializer
from .scheduling import BOOKING_TIMEZONE_NAME, calendar
from .throttles import BookingCalendarThrottle, BookingCreateThrottle

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
