from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from django.db import transaction
from django.contrib.auth import get_user_model
from core.permissions import ByMethod, HasAppPermission
from activity.utils import log_activity
from .models import Invitation
from students.models import Student

User = get_user_model()

# Student Learn accounts and their invitations are created only by enrollment
# (sales.enrollment, through invitations.credentials). Staff accounts are made
# in Team. The manual flow -- a student code looked up on the enrolment sheet,
# then an invitation created by hand, or credentials issued to a legacy row --
# is retired; the command-line issue_learn_credentials keeps the bulk
# transition of legacy students. Legacy email invitations remain historical
# records.
MANUAL_INVITATIONS_RETIRED = {
    "error": "MANUAL_INVITATIONS_RETIRED",
    "message": "Student invitations are now created automatically during enrollment.",
}


def invitation_data(inv):
    student = inv.student
    # A historical row names its student by code until the command-line
    # transition (issue_learn_credentials) links it, without re-enrolling or
    # duplicating academic/payment records.
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
        POST=HasAppPermission('accounts.view_invitations'),
        PATCH=HasAppPermission('accounts.change_invitation'),
        DELETE=HasAppPermission('accounts.withdraw_invitation'),
    )]

    def get(self, request):
        return Response([invitation_data(inv) for inv in Invitation.objects.select_related(
            'student', 'account', 'invited_by').all()])

    def post(self, request):
        return Response(MANUAL_INVITATIONS_RETIRED, status=status.HTTP_410_GONE)

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

