from datetime import datetime

from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.pagination import page_params
from core.permissions import ByMethod, HasAppPermission
from core.timezones import DATE_PATTERN

from . import enquiries
from .booking_service import BookingBusy, set_slots_closed
from .leads import InvalidLeadDetails
from .models import SLOT_CAPACITY, SLOT_MINUTES, SlotTime
from .public_views import PATH_TYPES
from .scheduling import BOOKING_TIMEZONE_NAME, PAST, booking_window, day_slots, parent_state
from .serializers import BookingLinkSerializer, EnquiryCreateSerializer, SlotChangeSerializer
from .services import links_for, owns_booking_links

VIEW_OWN_ENQUIRIES = HasAppPermission('accounts.view_own_enquiries')


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


def _bde_error(code, message, http_status, **extra):
    return Response({'error': code, 'message': message, **extra}, status=http_status)


class BdeWorkspaceView(APIView):
    """
    The BDE's own enquiries (bookings.enquiries). Guarded by catalogue
    permissions only the BDE role may hold; a superuser holds them as well
    (decision D1) without being a BDE, owns no enquiries and may not add one,
    so the BDE check below answers NOT_A_BDE before anything is read.
    Nothing in a request chooses whose enquiries are read: always the caller's.
    """

    @staticmethod
    def non_bde_refusal(request):
        """The NOT_A_BDE answer for an account that is not an active BDE, else None."""
        if owns_booking_links(request.user):
            return None
        return _bde_error(
            'NOT_A_BDE', 'Enquiries belong to BDE accounts, and this account is not one.', status.HTTP_403_FORBIDDEN,
        )


class BdeDashboardView(BdeWorkspaceView):
    """
    GET /api/bde/dashboard/
    The BDE dashboard: how many enquiries the caller owns, their demo and
    diagnostic bookings, the next bookings and the latest enquiries.
    """
    permission_classes = [IsAuthenticated, VIEW_OWN_ENQUIRIES]

    def get(self, request, *args, **kwargs):
        refusal = self.non_bde_refusal(request)
        if refusal:
            return refusal
        return Response(enquiries.dashboard(request.user), status=status.HTTP_200_OK)


class BdeEnquiriesView(BdeWorkspaceView):
    """
    GET  /api/bde/enquiries/?q=&status=&source=&page=&page_size=
         The caller's enquiries, newest to them first, always paged:
         {"results", "count", "page", "page_size"}. ``q`` matches the parent's
         or student's name or the phone number; ``status`` is an
         EnquiryStatus, ``source`` one of enquiries.SOURCE_FILTERS.
    POST /api/bde/enquiries/
         Add an enquiry by hand (EnquiryCreateSerializer); 201 with the
         enquiry, or 409 ENQUIRY_EXISTS when the phone number and student
         already make one -- carrying ``enquiry_id`` only when it is the
         caller's own.
    """
    permission_classes = [IsAuthenticated, ByMethod(
        GET=VIEW_OWN_ENQUIRIES,
        POST=HasAppPermission('accounts.add_enquiry'),
    )]

    def get(self, request, *args, **kwargs):
        refusal = self.non_bde_refusal(request)
        if refusal:
            return refusal
        params = request.query_params
        state = (params.get('status') or '').strip().upper()
        source = (params.get('source') or '').strip().upper()
        if state and state not in enquiries.EnquiryStatus.values:
            return _bde_error('INVALID_INPUT', 'Unknown enquiry status.', status.HTTP_400_BAD_REQUEST, fields=['status'])
        if source and source not in enquiries.SOURCE_FILTERS:
            return _bde_error('INVALID_INPUT', 'Unknown enquiry source.', status.HTTP_400_BAD_REQUEST, fields=['source'])

        now = timezone.now()
        leads = enquiries.search(enquiries.own_leads(request.user), params.get('q'))
        if source:
            leads = enquiries.filter_source(leads, source)
        leads = enquiries.listed(leads, now)
        if state:
            leads = leads.filter(enquiry_status=state)

        page, page_size = page_params(request)
        offset = (page - 1) * page_size
        return Response(
            {
                'results': enquiries.enquiry_rows(leads[offset:offset + page_size], now),
                'count': leads.count(),
                'page': page,
                'page_size': page_size,
            },
            status=status.HTTP_200_OK,
        )

    def post(self, request, *args, **kwargs):
        refusal = self.non_bde_refusal(request)
        if refusal:
            return refusal
        serializer = EnquiryCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return _bde_error('VALIDATION_ERROR', 'Check the enquiry details.', status.HTTP_400_BAD_REQUEST,
                              fields=serializer.errors)
        try:
            lead = enquiries.add_enquiry(request.user, serializer.validated_data, request=request)
        except InvalidLeadDetails as exc:
            return _bde_error('VALIDATION_ERROR', exc.message, status.HTTP_400_BAD_REQUEST,
                              fields={exc.field: [exc.message]})
        except enquiries.EnquiryExists as exc:
            if exc.lead is not None:
                return _bde_error('ENQUIRY_EXISTS', 'This child is already in your enquiries.',
                                  status.HTTP_409_CONFLICT, enquiry_id=str(exc.lead.pk))
            return _bde_error(
                'ENQUIRY_EXISTS',
                'An enquiry for this child and phone number is already registered. '
                'Ask an administrator if it should be yours.',
                status.HTTP_409_CONFLICT,
            )
        now = timezone.now()
        lead = enquiries.listed(enquiries.own_leads(request.user), now).get(pk=lead.pk)
        return Response(enquiries.enquiry_detail(lead, now), status=status.HTTP_201_CREATED)


class BdeEnquiryDetailView(BdeWorkspaceView):
    """
    GET /api/bde/enquiries/<id>/
    One of the caller's enquiries in full, with its bookings. Another BDE's
    enquiry, or one nobody owns, is answered exactly as one that does not exist.
    """
    permission_classes = [IsAuthenticated, VIEW_OWN_ENQUIRIES]

    def get(self, request, pk, *args, **kwargs):
        refusal = self.non_bde_refusal(request)
        if refusal:
            return refusal
        now = timezone.now()
        lead = enquiries.listed(enquiries.own_leads(request.user).filter(pk=pk), now).first()
        if lead is None:
            return _bde_error('NOT_FOUND', 'No such enquiry.', status.HTTP_404_NOT_FOUND)
        return Response(enquiries.enquiry_detail(lead, now), status=status.HTTP_200_OK)


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
