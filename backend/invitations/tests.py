"""
Student invitations after the manual flow was retired: Learn accounts and
their invitations are created by enrollment only (sales.enrollment through
invitations.credentials, covered end to end in tests_credentials). The
Invitations list, the credential reveal, the retired email edit and the
withdrawal of unused legacy rows stay; the manual creation answers that it is
retired, and the sheet lookup and the per-row legacy issue are gone. The
command-line issue_learn_credentials keeps the bulk legacy transition.
"""
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core import mail
from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APITestCase

from accounts.authz import has_app_permission
from accounts.models import RoleGroup
from students.models import Student

from .credentials import create_invitation, new_account
from .models import Invitation

User = get_user_model()
TEST_KEYS = ['MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=']


@override_settings(LEARN_INVITATION_KEYS=TEST_KEYS)
class InvitationFlowTests(APITestCase):
    def setUp(self):
        sheet = patch('invitations.sheets.GoogleSheetsService.fetch_enrollment_rows', return_value=[])
        self.sheet = sheet.start()
        self.addCleanup(sheet.stop)
        self.admin = User.objects.create_user(email='invite-admin@example.test', role='ADMIN', password='Test-Password-2026')
        self.client.force_authenticate(self.admin)

    def enrolled(self, code='EDP10001', name='Student'):
        """A student as enrollment leaves them: a Learn account and its pending invitation."""
        account, password = new_account(code, name, self.admin)
        student = Student.objects.create(profile=account, student_code=code, full_name=name, total_class_quota=6)
        invitation = create_invitation(student, account, password, self.admin, extra_data={'source': 'INITIAL_SALE'})
        return student, invitation

    def counts(self):
        return (Student.objects.count(), Invitation.objects.count(), User.objects.filter(role='STUDENT').count())

    def test_manual_creation_is_retired_and_creates_nothing(self):
        before = self.counts()
        payload = {'student_code': 'EDP10002', 'full_name': 'New Student', 'role': 'STUDENT', 'meet_link': 'https://meet.google.com/abc-defg-hij'}
        for url in ('/api/invitations/', reverse('invitations:create-student-invitation')):
            for body in (payload, {**payload, 'role': 'MENTOR', 'email': 'staff@example.test'}):
                with self.subTest(url=url, role=body['role']):
                    response = self.client.post(url, body, format='json')
                    self.assertEqual(response.status_code, 410, response.content)
                    self.assertEqual(response.json()['error'], 'MANUAL_INVITATIONS_RETIRED')
                    self.assertEqual(response.json()['message'], 'Student invitations are now created automatically during enrollment.')
        self.assertEqual(self.counts(), before)
        self.assertEqual(len(mail.outbox), 0)
        self.sheet.assert_not_called()

    def test_the_sheet_lookup_and_the_legacy_issue_endpoint_are_gone(self):
        student, _ = self.enrolled()
        before = self.counts()
        self.assertEqual(self.client.post('/api/invitations/lookup-student/', {'student_code': 'EDP10001'}).status_code, 404)
        self.assertEqual(self.client.post(f'/api/invitations/students/{student.pk}/issue/').status_code, 404)
        self.assertEqual(self.counts(), before)
        self.sheet.assert_not_called()

    def test_only_invitation_viewers_reach_the_retired_creation(self):
        self.client.force_authenticate(None)
        self.assertIn(self.client.post('/api/invitations/', {'student_code': 'EDP10002'}, format='json').status_code, [401, 403])
        for role in ('STUDENT', 'MENTOR', 'TUTOR', 'BDE'):
            with self.subTest(role=role):
                self.client.force_authenticate(User.objects.create_user(email=f'{role.lower()}@example.test', role=role))
                self.assertEqual(self.client.post('/api/invitations/', {'student_code': 'EDP10002'}, format='json').status_code, 403)

    def test_email_based_edit_is_retired(self):
        self.enrolled()
        response = self.client.patch('/api/invitations/', {'old_email': 'old@example.test', 'new_email': 'new@example.test'})
        self.assertEqual(response.status_code, 410)

    def test_enrolled_invitation_cannot_be_deleted(self):
        _, inv = self.enrolled()
        response = self.client.delete('/api/invitations/', {'id': str(inv.pk)}, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertTrue(Invitation.objects.filter(pk=inv.pk).exists())

    def test_unused_legacy_invitation_can_be_withdrawn(self):
        inv = Invitation.objects.create(email='legacy@example.test', role='STUDENT')
        self.assertEqual(self.client.delete('/api/invitations/', {'id': str(inv.pk)}, format='json').status_code, 200)

    def test_list_has_student_id_username_and_status_but_no_secret(self):
        self.enrolled()
        row = self.client.get('/api/invitations/').json()[0]
        self.assertEqual(row['student_name'], 'Student')
        self.assertEqual(row['student_code'], 'EDP10001')
        self.assertEqual(row['username'], 'edp10001')
        self.assertEqual(row['status'], 'PENDING')
        self.assertTrue(row['credentials_available'])
        self.assertNotIn('temporary_password', row)
        self.assertNotIn('credential_ciphertext', row)

    def test_enrollment_and_historical_invitations_stay_listed_and_revealable(self):
        _, enrolled = self.enrolled()
        legacy = Invitation.objects.create(email='legacy@example.test', role='STUDENT',
                                           extra_data={'student_code': 'EDPOLD1', 'full_name': 'Old Student'})
        rows = {row['id']: row for row in self.client.get('/api/invitations/').json()}
        self.assertEqual(set(rows), {str(enrolled.pk), str(legacy.pk)})
        self.assertTrue(rows[str(legacy.pk)]['legacy'])
        response = self.client.post(f'/api/invitations/{enrolled.pk}/credentials/')
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['username'], 'edp10001')


@override_settings(LEARN_INVITATION_KEYS=TEST_KEYS)
class LegacyTransitionCommandTests(APITestCase):
    """The bulk legacy transition stays a command-line tool, for students imported without Learn credentials."""

    def test_the_command_issues_credentials_to_students_without_any_once(self):
        parent = User.objects.create_user(email='parent@example.test', role='STUDENT')
        student = Student.objects.create(profile=parent, student_code='EDPLEG1', full_name='Legacy Student')
        out = StringIO()
        call_command('issue_learn_credentials', '--all', stdout=out)
        self.assertIn('1 student(s) would receive invitations (dry run)', out.getvalue())
        self.assertFalse(Invitation.objects.exists())
        call_command('issue_learn_credentials', '--all', '--execute', stdout=StringIO())
        invitation = Invitation.objects.get(student=student)
        self.assertEqual(invitation.extra_data['source'], 'LEGACY_STUDENT_TRANSITION')
        call_command('issue_learn_credentials', '--all', '--execute', stdout=StringIO())
        self.assertEqual(Invitation.objects.count(), 1)


class RetiredPermissionTests(APITestCase):
    def test_no_role_and_no_account_holds_create_invitation(self):
        self.assertFalse(Permission.objects.filter(content_type__app_label='accounts', codename='create_invitation').exists())
        admin_group = RoleGroup.objects.get(role='ADMIN').group
        held = set(admin_group.permissions.values_list('codename', flat=True))
        self.assertTrue({'view_invitations', 'change_invitation', 'withdraw_invitation'} <= held)
        admin = User.objects.create_user(email='perm-admin@example.test', role='ADMIN')
        self.assertFalse(has_app_permission(admin, 'accounts.create_invitation'))
        self.assertTrue(has_app_permission(admin, 'accounts.view_invitations'))
