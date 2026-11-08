"""
The administrators' Leads API (bookings.lead_admin):

    GET  /api/leads/                 every lead, paged and filtered
    POST /api/leads/                 add a lead by hand
    GET  /api/leads/bdes/            the BDE accounts to filter by and assign to
    GET  /api/leads/<id>/            one lead in full
    PUT  /api/leads/<id>/owner/      give the lead to a BDE (bookings.ownership)
    PUT  /api/leads/<id>/student-timezone/  correct its student's time zone (bookings.student_timezones)
    GET  /api/leads/<id>/notes/      staff's notes on the lead (bookings.notes)
    POST /api/leads/<id>/notes/      add one, as an administrator
    GET  /api/admissions/dashboard/  the admissions pipeline at a glance (bookings.admissions)

Reading needs accounts.view_all_leads, adding accounts.add_lead and
assigning accounts.assign_lead_owner -- all three the ADMIN role's alone (a
superuser holds them too, D1); whoever may read a lead may read and add its
notes. Correcting a student's time zone needs accounts.change_student_timezone
as well as view_all_leads: a BDE holds the former for their own enquiries
(/api/bde/enquiries/), and never the latter. A BDE reads their own leads in the BDE
workspace (/api/bde/enquiries/) and nothing here. Errors answer
``{"error": CODE, "message": ..., "fields"?}``, as the BDE workspace does.
"""
import uuid

from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.authz import has_app_permission
from core.pagination import page_params
from core.permissions import ByMethod, HasAppPermission
from core.querysets import ACTIVITY_VIEW_PERMISSIONS

from . import admissions, enquiries, lead_admin, notes, student_timezones
from .booking_service import BookingBusy
from .lead_intake import LeadExists
from .lead_status import statuses_for
from .leads import InvalidLeadDetails
from .models import Lead, LeadNoteRole
from .ownership import OwnershipError, assign_owner
from .serializers import LeadCreateSerializer, LeadNoteSerializer, LeadOwnerSerializer, StudentTimezoneSerializer
from .student_timezones import InvalidStudentTimezone

VIEW_ALL_LEADS = 'accounts.view_all_leads'
ADD_LEAD = 'accounts.add_lead'
ASSIGN_LEAD_OWNER = 'accounts.assign_lead_owner'
VIEW_ALL_COMMUNICATIONS = 'accounts.view_all_communications'
VIEW_ALL_BOOKINGS = 'accounts.view_all_bookings'
CHANGE_STUDENT_TIMEZONE = 'accounts.change_student_timezone'


def _error(code, message, http_status, **extra):
    return Response({'error': code, 'message': message, **extra}, status=http_status)


def _invalid(field, message):
    return _error('INVALID_INPUT', message, status.HTTP_400_BAD_REQUEST, fields=[field])


def _no_lead():
    return _error('NOT_FOUND', 'No such lead.', status.HTTP_404_NOT_FOUND)


def _detail(request, lead, now):
    return lead_admin.lead_detail(
        lead, now, show_confirmation=has_app_permission(request.user, VIEW_ALL_COMMUNICATIONS, request),
    )


def _read(request, pk, now):
    lead = lead_admin.listed(Lead.objects.filter(pk=pk), now).first()
    return _detail(request, lead, now) if lead is not None else None


class LeadsView(APIView):
    """
    GET  /api/leads/?q=&source=&status=&owner=&from=&to=&page=&page_size=
         Every lead, the latest received first, always paged:
         {"results", "count", "page", "page_size"}. ``q`` matches the
         parent's or student's name, the parent's email or the phone number;
         ``source`` is one of enquiries.SOURCE_FILTERS, ``status`` a
         LeadStatus or a stage of either type (lead_status.STAGES), ``owner``
         a BDE account's id or "unassigned"; ``from`` and ``to`` the Indian
         dates (YYYY-MM-DD, inclusive) it came in on.
    POST /api/leads/
         Add a lead by hand (LeadCreateSerializer), owned by nobody: 201 with
         the lead, or 409 LEAD_EXISTS with ``lead_id`` when the phone number
         and student already make one.
    """
    permission_classes = [IsAuthenticated, ByMethod(
        GET=HasAppPermission(VIEW_ALL_LEADS),
        POST=HasAppPermission(ADD_LEAD),
    )]

    def get(self, request, *args, **kwargs):
        params = request.query_params
        state = (params.get('status') or '').strip().upper()
        source = (params.get('source') or '').strip().upper()
        owner = (params.get('owner') or '').strip().lower()
        statuses = statuses_for(state)
        if state and statuses is None:
            return _invalid('status', 'Unknown lead status.')
        if source and source not in enquiries.SOURCE_FILTERS:
            return _invalid('source', 'Unknown lead source.')
        if owner and owner != lead_admin.UNASSIGNED:
            try:
                owner = uuid.UUID(owner)
            except ValueError:
                return _invalid('owner', 'Unknown owner.')
        (received_from, received_to), invalid = lead_admin.received_dates(params)
        if invalid:
            return _invalid(invalid[0], 'Check the dates: YYYY-MM-DD, the first on or before the last.')

        now = timezone.now()
        leads = enquiries.search(Lead.objects.all(), params.get('q'))
        if source:
            leads = enquiries.filter_source(leads, source)
        if owner:
            leads = lead_admin.filter_owner(leads, owner)
        leads = lead_admin.received_between(leads, received_from, received_to)
        leads = lead_admin.listed(leads, now)
        if state:
            leads = leads.filter(lead_status__in=statuses)

        page, page_size = page_params(request)
        offset = (page - 1) * page_size
        return Response(
            {
                'results': lead_admin.lead_rows(leads[offset:offset + page_size], now),
                'count': leads.count(),
                'page': page,
                'page_size': page_size,
            },
            status=status.HTTP_200_OK,
        )

    def post(self, request, *args, **kwargs):
        serializer = LeadCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return _error('VALIDATION_ERROR', 'Check the lead details.', status.HTTP_400_BAD_REQUEST,
                          fields=serializer.errors)
        try:
            lead = lead_admin.add_lead(request.user, serializer.validated_data, request=request)
        except InvalidLeadDetails as exc:
            return _error('VALIDATION_ERROR', exc.message, status.HTTP_400_BAD_REQUEST, fields={exc.field: [exc.message]})
        except LeadExists as exc:
            return _error('LEAD_EXISTS', 'A lead for this child and phone number already exists.',
                          status.HTTP_409_CONFLICT, lead_id=str(exc.lead.pk))
        return Response(_read(request, lead.pk, timezone.now()), status=status.HTTP_201_CREATED)


class LeadBdesView(APIView):
    """
    GET /api/leads/bdes/
    The accounts the owner filter offers, and which of them a lead may be
    given to (``assignable``: active BDEs) -- names only.
    """
    permission_classes = [IsAuthenticated, HasAppPermission(VIEW_ALL_LEADS)]

    def get(self, request, *args, **kwargs):
        return Response({'results': lead_admin.bde_options()}, status=status.HTTP_200_OK)


class LeadDetailView(APIView):
    """GET /api/leads/<id>/: one lead in full, with its bookings, its owner and who added it."""
    permission_classes = [IsAuthenticated, HasAppPermission(VIEW_ALL_LEADS)]

    def get(self, request, pk, *args, **kwargs):
        lead = _read(request, pk, timezone.now())
        return Response(lead, status=status.HTTP_200_OK) if lead is not None else _no_lead()


class LeadOwnerView(APIView):
    """
    PUT /api/leads/<id>/owner/ {"bde_id": <id>, "current_owner_id": <id> | null}
    Give the lead to an active BDE: it leaves its previous owner's My Leads and
    joins theirs. ``current_owner_id`` is the owner the caller saw (null:
    nobody); when someone changed it meanwhile the answer is 409
    OWNER_CHANGED and nothing changes. Answers the lead in full with
    ``changed`` (false when it already was theirs).
    """
    permission_classes = [IsAuthenticated, HasAppPermission(ASSIGN_LEAD_OWNER)]

    def put(self, request, pk, *args, **kwargs):
        serializer = LeadOwnerSerializer(data=request.data)
        if not serializer.is_valid():
            return _error('VALIDATION_ERROR', 'Choose the BDE to assign.', status.HTTP_400_BAD_REQUEST,
                          fields=serializer.errors)
        data = serializer.validated_data
        try:
            _lead, changed = assign_owner(
                pk, data['bde_id'], actor=request.user, via='admin_leads',
                expected_owner_id=data['current_owner_id'], request=request,
            )
        except Lead.DoesNotExist:
            return _no_lead()
        except OwnershipError as exc:
            return _error(exc.code, exc.message, exc.http_status)
        except BookingBusy:
            return _error('LEAD_BUSY', 'This lead is being changed right now. Try again in a moment.',
                          status.HTTP_503_SERVICE_UNAVAILABLE)
        return Response({**_read(request, pk, timezone.now()), 'changed': changed}, status=status.HTTP_200_OK)


class LeadStudentTimezoneView(APIView):
    """
    PUT /api/leads/<id>/student-timezone/ {"student_timezone": <IANA zone> | null}
    Correct the time zone the lead's student books from
    (bookings.student_timezones) -- their own time is shown beside each
    booking's Indian one; null clears it. Answers the lead in full with
    ``changed`` (false when it already was that zone), or 400 INVALID_TIMEZONE.
    """
    permission_classes = [IsAuthenticated, HasAppPermission(VIEW_ALL_LEADS), HasAppPermission(CHANGE_STUDENT_TIMEZONE)]

    def put(self, request, pk, *args, **kwargs):
        serializer = StudentTimezoneSerializer(data=request.data)
        if not serializer.is_valid():
            return _error(InvalidStudentTimezone.code, InvalidStudentTimezone.message, status.HTTP_400_BAD_REQUEST,
                          fields=serializer.errors)
        try:
            _lead, changed = student_timezones.correct(
                pk, serializer.validated_data['student_timezone'], actor=request.user, via='admin_leads',
                request=request,
            )
        except Lead.DoesNotExist:
            return _no_lead()
        except BookingBusy:
            return _error('LEAD_BUSY', 'This lead is being changed right now. Try again in a moment.',
                          status.HTTP_503_SERVICE_UNAVAILABLE)
        return Response({**_read(request, pk, timezone.now()), 'changed': changed}, status=status.HTTP_200_OK)


class LeadNotesView(APIView):
    """
    GET  /api/leads/<id>/notes/
         The notes on the lead, oldest first, shared with its owner BDE and its
         tutors (bookings.notes): {"results", "count", "timezone"}.
    POST /api/leads/<id>/notes/ {"body": "..."}
         Add one, as an administrator; answers the notes as they now stand
         (201), or 400 VALIDATION_ERROR for an empty or overlong note.
    """
    permission_classes = [IsAuthenticated, HasAppPermission(VIEW_ALL_LEADS)]

    def get(self, request, pk, *args, **kwargs):
        lead = Lead.objects.filter(pk=pk).first()
        if lead is None:
            return _no_lead()
        return Response(notes.notes_of(lead), status=status.HTTP_200_OK)

    def post(self, request, pk, *args, **kwargs):
        lead = Lead.objects.filter(pk=pk).first()
        if lead is None:
            return _no_lead()
        serializer = LeadNoteSerializer(data=request.data)
        if not serializer.is_valid():
            return _error('VALIDATION_ERROR', notes.INVALID_NOTE, status.HTTP_400_BAD_REQUEST, fields=serializer.errors)
        notes.add_note(lead, request.user, LeadNoteRole.ADMIN, serializer.validated_data['body'])
        return Response(notes.notes_of(lead), status=status.HTTP_201_CREATED)


class AdmissionsDashboardView(APIView):
    """
    GET /api/admissions/dashboard/?from=&to=
    The admissions pipeline at a glance (bookings.admissions.dashboard): over
    the Indian dates ``from`` to ``to`` (both or neither: the last seven days),
    the leads that came in and where each stands now, and the Demo and
    Diagnostic bookings for those dates; then today's bookings, what awaits an
    administrator, the latest leads and the latest admissions activity. Bad
    dates answer 400 INVALID_INPUT naming them. The booking parts are null
    without accounts.view_all_bookings, the parents' confirmations without
    accounts.view_all_communications as well, and the activity without
    permission to read the activity log (scoped as the log is).
    """
    permission_classes = [IsAuthenticated, HasAppPermission(VIEW_ALL_LEADS)]

    def get(self, request, *args, **kwargs):
        now = timezone.now()
        (date_from, date_to), invalid = admissions.span(request.query_params, now)
        if invalid:
            return _error('INVALID_INPUT', f'Check the dates: YYYY-MM-DD, at most {admissions.MAX_DAYS} days.',
                          status.HTTP_400_BAD_REQUEST, fields=invalid)

        def holds(permission):
            return has_app_permission(request.user, permission, request)

        show_bookings = holds(VIEW_ALL_BOOKINGS)
        return Response(
            admissions.dashboard(
                now, date_from, date_to, user=request.user, request=request,
                show_bookings=show_bookings,
                show_confirmation=show_bookings and holds(VIEW_ALL_COMMUNICATIONS),
                show_activity=any(holds(permission) for permission in ACTIVITY_VIEW_PERMISSIONS),
            ),
            status=status.HTTP_200_OK,
        )
