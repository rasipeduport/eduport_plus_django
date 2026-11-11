import logging

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from django.db import transaction
from django.contrib.auth import get_user_model
from accounts.authz import has_app_permission
from core.permissions import ByMethod, HasAppPermission
from activity.utils import log_activity
from .models import Invitation, InvitationStatusChoices, InvitationRoleChoices
from .sheets import GoogleSheetsService
from students.models import Student
from students.quota_sync import quota_for_code

User = get_user_model()

logger = logging.getLogger(__name__)

# Staff accounts are managed in Team. Student credentials are issued at
# enrollment or authorized Sheets import. Legacy email invitations remain
# historical records and cannot provision accounts through Google.
STAFF_INVITATIONS_RETIRED = {
    "error": "STAFF_INVITATIONS_RETIRED",
    "message": "Staff are no longer invited. Create their account in Team with a username and a temporary password.",
}


def _sheet_quota_for(student_code):
    """
    The class quota the enrolment sheet states for ``student_code``, as the
    integer ``Student.total_class_quota`` is initialised with.

    Read SERVER-SIDE, from the sheet, on purpose: the quota must not be
    accepted from the request body, or the retired manual top-up would be back
    in a new shape (and would be overwritten by the next sync anyway).

    Returns 0 -- never None -- for a code the sheet has no number for, since
    the column is NOT NULL and "nothing paid for" is the safe starting point.
    A Sheets failure also yields 0 rather than blocking the invitation: the
    hourly sync corrects it, and refusing to enrol a student because Google is
    briefly unavailable would be the worse trade.
    """
    try:
        rows = GoogleSheetsService.fetch_enrollment_rows()
    except Exception as exc:
        logger.warning(
            "Could not read the enrolment sheet while inviting %s; starting the "
            "student at 0 classes. The scheduled quota sync will correct it. (%s)",
            student_code, exc,
        )
        return 0

    quota = quota_for_code(rows, student_code)
    if quota is None:
        logger.info(
            "Enrolment sheet states no numeric \"classes paid for\" value for %s; "
            "starting the student at 0 classes.", student_code,
        )
        return 0
    return quota


def _find_student_invitation(email, student_code, status_filter=None):
    """
    Find the invitation for one specific child (a parent email may own several).
    Optionally restrict to a given status (e.g. PENDING).
    """
    qs = Invitation.objects.filter(
        email=email,
        role=InvitationRoleChoices.STUDENT,
        extra_data__student_code=student_code,
    )
    if status_filter is not None:
        qs = qs.filter(status=status_filter)
    return qs.first()

class LookupStudentView(APIView):
    """
    Step 1: whoever may invite students (accounts.create_invitation) enters a student code.
    Backend fetches the data from the Google Sheet (range A3:AB of 'enrollment data' tab) on demand.
    Returns the mapped data directly without writing to the database yet.
    """
    permission_classes = [IsAuthenticated, HasAppPermission('accounts.create_invitation')]

    def post(self, request, *args, **kwargs):
        student_code = request.data.get("student_code")
        if not student_code:
            return Response(
                {"error": "INVALID_INPUT", "message": "student_code is required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Query Google Sheets using the production mapping. One fetch, then
        # both reads off the same snapshot: the profile fields and the class
        # quota the student will be created with.
        try:
            rows = GoogleSheetsService.fetch_enrollment_rows()
            student_data = GoogleSheetsService.lookup_student_by_code(student_code, rows=rows)
        except Exception as e:
            return Response(
                {"error": "SHEETS_API_ERROR", "message": f"Google Sheets lookup failed: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        if student_data:
            # Informational for the enrolment form. The value the Student is
            # actually created with is re-read server-side at invitation time
            # (_sheet_quota_for), never taken back from the client.
            quota = quota_for_code(rows, student_data.get("student_code") or student_code)
            student_data["classes_paid_for"] = 0 if quota is None else quota

        if not student_data:
            return Response(
                {"error": "STUDENT_NOT_FOUND", "message": f"Student with code '{student_code}' not found in the Google Sheet."},
                status=status.HTTP_404_NOT_FOUND
            )

        email = student_data.get("email") or ''
        student_code = student_data.get("student_code")
        if student_code and Student.objects.filter(student_code=student_code).exists():
            return Response({"error": "STUDENT_ALREADY_ONBOARDED", "message": "Student already enrolled. Issue Learn credentials from their invitation row."}, status=400)
        # A pending invitation for THIS child can be edited rather than recreated.
        invitation = _find_student_invitation(email, student_code)
        if invitation:
            if invitation.status == InvitationStatusChoices.ACCEPTED:
                return Response(
                    {
                        "error": "INVITATION_ALREADY_ACCEPTED",
                        "message": f"An invitation for '{email}' (code {student_code}) has already been accepted.",
                        "student_data": student_data
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

            return Response(
                {
                    "status": "exists",
                    "message": "A pending invitation already exists for this student. You can update it by submitting details.",
                    "student_data": student_data,
                    "invitation": {
                        "id": invitation.id,
                        "email": invitation.email,
                        "role": invitation.role,
                        "status": invitation.status,
                        "extra_data": invitation.extra_data
                    }
                },
                status=status.HTTP_200_OK
            )

        # No invitation exists for this child, return the sheet data to proceed.
        return Response(
            {
                "status": "found",
                "message": "Student record found in Google Sheets.",
                "student_data": student_data
            },
            status=status.HTTP_200_OK
        )



def invitation_data(inv):
    student = inv.student
    # Historical rows can be explicitly transitioned by Admin without
    # re-enrolling or duplicating academic/payment records.
    if not student and inv.role == 'STUDENT':
        student = Student.objects.filter(student_code=(inv.extra_data or {}).get('student_code')).first()
    return {
        'id': str(inv.pk), 'email': inv.email, 'role': inv.role, 'status': inv.status,
        'student_id': str(student.pk) if student else None,
        'student_name': student.full_name if student else (inv.extra_data or {}).get('full_name', ''),
        'student_code': student.student_code if student else (inv.extra_data or {}).get('student_code', ''),
        'username': inv.account.username if inv.account_id else None,
        'credentials_available': bool(inv.account_id and inv.account.must_change_password and inv.credential_ciphertext),
        'legacy': not bool(inv.account_id), 'activated_at': inv.activated_at,
        'created_at': inv.created_at, 'extra_data': inv.extra_data,
        'invited_by': str(inv.invited_by_id) if inv.invited_by_id else None,
        'invited_by_profile': {'id': str(inv.invited_by_id), 'full_name': inv.invited_by.full_name, 'email': inv.invited_by.email} if inv.invited_by_id else None,
    }


class CreateInvitationView(APIView):
    permission_classes = [IsAuthenticated, ByMethod(
        GET=HasAppPermission('accounts.view_invitations'),
        POST=HasAppPermission('accounts.create_invitation'),
        PATCH=HasAppPermission('accounts.change_invitation'),
        DELETE=HasAppPermission('accounts.withdraw_invitation'),
    )]

    def get(self, request):
        return Response([invitation_data(inv) for inv in Invitation.objects.select_related(
            'student', 'account', 'invited_by').all()])

    @transaction.atomic
    def post(self, request):
        """Keep the authorized Sheets enrollment import, now issuing credentials
        immediately rather than provisioning academics at a Google login.
        Phase 1 tuition enrollment calls the same credential service directly.
        """
        if str(request.data.get('role', 'STUDENT')).upper() != 'STUDENT':
            return Response(STAFF_INVITATIONS_RETIRED, status=400)
        from .credentials import new_account, create_invitation, issue_existing_student
        from accounts.services import parse_admission_date
        code = str(request.data.get('student_code', '')).strip()
        if not code:
            return Response({'error': 'INVALID_INPUT', 'message': 'student_code is required.'}, status=400)
        # Serialize absent-row creation; class quota is always read server-side.
        from django.db import connection
        with connection.cursor() as cursor:
            cursor.execute('SELECT pg_advisory_xact_lock(hashtext(%s), hashtext(%s))', ['learn-sheet-student', code])
        student = Student.objects.filter(student_code=code).first()
        if student:
            inv = issue_existing_student(student.pk, request.user, request)
            return Response({'invitation': invitation_data(inv)})
        data = request.data
        if not data.get('full_name'):
            return Response({'error': 'INVALID_INPUT', 'message': 'full_name is required.'}, status=400)
        assignments = {}
        for field, role in [('mentor', 'MENTOR'), ('tutor', 'TUTOR')]:
            pk = request.data.get(f'{field}_id')
            if pk and not User.objects.filter(pk=pk, role=role, is_active=True, deactivated_at__isnull=True).exists():
                return Response({'error': f'INVALID_{role}', 'message': f'Select an active {field}.'}, status=400)
            assignments[f'{field}_id'] = pk or None
        account, password = new_account(code, data.get('full_name') or code, request.user)
        student = Student.objects.create(
            profile=account, student_code=code, full_name=data.get('full_name') or code,
            **{key: data.get(key) or None for key in ['mobile_number', 'country', 'state', 'school_name', 'grade', 'syllabus']},
            admission_date=parse_admission_date(data.get('admission_date')),
            total_class_quota=_sheet_quota_for(code), **assignments,
            meet_link=request.data.get('meet_link') or None)
        legacy = Invitation.objects.filter(role='STUDENT', student__isnull=True, extra_data__student_code=code).first()
        inv = create_invitation(student, account, password, request.user, invitation=legacy,
                                extra_data={'source': 'SHEETS_ENROLLMENT', 'total_class_quota': str(student.total_class_quota)})
        return Response({'status': 'created', 'message': 'Learn invitation created. Retrieve initial credentials in Invitations.', 'invitation': invitation_data(inv)}, status=201)

    def patch(self, request):
        return Response({'error': 'EMAIL_INVITATIONS_RETIRED', 'message': 'Learn invitations use student usernames. Email changes do not issue or resend credentials.'}, status=410)

    def delete(self, request):
        inv = Invitation.objects.filter(pk=request.data.get('id')).first() if request.data.get('id') else Invitation.objects.filter(email=request.data.get('email')).first()
        if not inv:
            return Response({'error': 'NOT_FOUND'}, status=404)
        if inv.student_id or inv.account_id or inv.status == 'ACCEPTED':
            return Response({'error': 'INVITATION_RETAINED', 'message': 'Enrolled student credentials and invitation history cannot be withdrawn.'}, status=400)
        log_activity('invitation.delete', 'invitation', inv.pk, request=request)
        inv.delete()
        return Response({'status': 'deleted', 'message': f"Invitation for {request.data.get('email')} has been withdrawn."})


class InvitationCredentialsView(APIView):
    permission_classes = [IsAuthenticated, HasAppPermission('accounts.view_invitations'),
                          HasAppPermission('accounts.change_invitation')]

    @transaction.atomic
    def post(self, request, pk):
        from .credentials import reveal_credentials
        inv = Invitation.objects.filter(pk=pk).first()
        if not inv or not inv.account_id:
            return Response({'error': 'CREDENTIALS_UNAVAILABLE'}, status=404)
        # Consistent account -> invitation locking with password change.
        User.objects.select_for_update().get(pk=inv.account_id)
        inv = Invitation.objects.select_for_update(of=('self',)).select_related('account', 'student').get(pk=pk)
        password = reveal_credentials(inv)
        if password is None:
            return Response({'error': 'CREDENTIALS_ACTIVATED', 'message': 'The account is activated. Its temporary password has been erased.'}, status=409)
        log_activity('invitation.credentials_revealed', 'invitation', inv.pk,
                     student=inv.student, request=request, entity_label=inv.student.student_code)
        response = Response({'username': inv.account.username, 'temporary_password': password,
                             'student_code': inv.student.student_code})
        response['Cache-Control'] = 'no-store, private'
        response['Pragma'] = 'no-cache'
        return response


class IssueStudentCredentialsView(APIView):
    permission_classes = [IsAuthenticated, HasAppPermission('accounts.create_invitation')]

    def post(self, request, pk):
        from .credentials import issue_existing_student
        try:
            inv = issue_existing_student(pk, request.user, request)
        except Student.DoesNotExist:
            return Response({'error': 'NOT_FOUND'}, status=404)
        return Response(invitation_data(inv))
