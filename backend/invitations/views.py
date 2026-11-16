from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from django.db import transaction
from django.contrib.auth import get_user_model
from django.utils.dateparse import parse_datetime
from core.permissions import ByMethod, HasAppPermission
from activity.utils import log_activity
from .credentials import regenerable, regenerate_credentials, resettable
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
        'credentials_regenerable': regenerable(inv), 'password_resettable': resettable(inv),
        'last_password_reset_at': inv.password_reset_at,
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
        # Copy Login Details reads the password to put it on the clipboard: logged as a copy.
        purpose = request.data.get('purpose', 'reveal') if isinstance(request.data, dict) else 'reveal'
        if purpose not in ('reveal', 'copy'):
            return Response({'error': 'INVALID_INPUT', 'message': 'purpose must be reveal or copy.'}, status=400)
        inv = Invitation.objects.filter(pk=pk).first()
        if not inv or not inv.account_id:
            return Response({'error': 'CREDENTIALS_UNAVAILABLE'}, status=404)
        # Consistent account -> invitation locking with password change.
        User.objects.select_for_update().get(pk=inv.account_id)
        inv = Invitation.objects.select_for_update(of=('self',)).select_related('account', 'student').get(pk=pk)
        password = reveal_credentials(inv)
        if password is None:
            return Response({'error': 'CREDENTIALS_ACTIVATED', 'message': 'The account is activated. Its temporary password has been erased.'}, status=409)
        log_activity('invitation.credentials_copied' if purpose == 'copy' else 'invitation.credentials_revealed', 'invitation', inv.pk,
                     student=inv.student, request=request, entity_label=inv.student.student_code)
        response = Response({'username': inv.account.username, 'temporary_password': password,
                             'student_code': inv.student.student_code})
        response['Cache-Control'] = 'no-store, private'
        response['Pragma'] = 'no-cache'
        return response


class ReplacePasswordView(APIView):
    """
    POST {last_password_reset_at}: give an account a new temporary password
    (credentials.regenerate_credentials), for whoever may reveal it. Each
    subclass names the accounts it serves (`eligible`), its refusal for the
    others and its Activity Log action. The answer carries no password: the
    new one is read through the reveal endpoint above. `last_password_reset_at`
    is the value the caller was shown (null when never replaced); if the
    password has been replaced since -- a second click, another administrator
    -- nothing changes and the answer is 409 CREDENTIALS_CHANGED.
    """
    permission_classes = [IsAuthenticated, HasAppPermission('accounts.view_invitations'),
                          HasAppPermission('accounts.change_invitation')]
    eligible = refusal = changed = action = done = None

    def post(self, request, pk):
        data = request.data if isinstance(request.data, dict) else {}
        listed = data.get('last_password_reset_at')
        try:
            seen = parse_datetime(listed) if isinstance(listed, str) else None
        except ValueError:
            seen = None
        if 'last_password_reset_at' not in data or (listed is not None and (seen is None or seen.tzinfo is None)):
            return Response({'error': 'INVALID_INPUT', 'message': 'last_password_reset_at must be the value listed for this invitation, or null.'}, status=400)

        with transaction.atomic():
            inv = Invitation.objects.filter(pk=pk).first()
            if not inv or not inv.account_id:
                return Response({'error': 'CREDENTIALS_UNAVAILABLE'}, status=404)
            # Consistent account -> invitation locking with password change and reveal.
            User.objects.select_for_update().get(pk=inv.account_id)
            inv = Invitation.objects.select_for_update(of=('self',)).select_related('account', 'student').get(pk=pk)
            if not self.eligible(inv):
                return Response(self.refusal, status=409)
            if inv.password_reset_at != seen:
                return Response({'error': 'CREDENTIALS_CHANGED', 'message': self.changed,
                                 'last_password_reset_at': inv.password_reset_at}, status=409)
            unlocked = regenerate_credentials(inv)
            log_activity(self.action, 'invitation', inv.pk, student=inv.student,
                         request=request, entity_label=inv.student.student_code,
                         context={'must_change_password': True, 'unlocked': unlocked})
        return Response({'status': self.done, 'last_password_reset_at': inv.password_reset_at})


class InvitationRegenerateView(ReplacePasswordView):
    """POST /api/invitations/<id>/credentials/regenerate/: a pending account's temporary password."""
    eligible = staticmethod(regenerable)
    refusal = {'error': 'CREDENTIALS_ACTIVATED', 'message': 'The account is activated. Its temporary password can no longer be replaced.'}
    changed = 'The temporary password was replaced moments ago. Reveal the current one instead of generating another.'
    action, done = 'invitation.credentials_regenerated', 'regenerated'


class InvitationResetPasswordView(ReplacePasswordView):
    """
    POST /api/invitations/<id>/credentials/reset/: an activated account's
    password, recovered by an administrator without email. The account stays
    activated; its password stops working at once, its sessions end, and the
    student must replace the temporary password at their next sign-in.
    """
    eligible = staticmethod(resettable)
    refusal = {'error': 'ACCOUNT_NOT_ACTIVATED', 'message': 'This account is not activated yet. Regenerate its temporary password instead.'}
    changed = 'This password was reset moments ago. Reveal the temporary password instead of resetting it again.'
    action, done = 'invitation.password_reset', 'reset'
