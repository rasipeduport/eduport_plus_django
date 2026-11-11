from django.urls import reverse
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import override_settings
from rest_framework.test import APITestCase
from rest_framework import status
from .models import Invitation, InvitationStatusChoices, InvitationRoleChoices
from students.models import Student

User = get_user_model()
TEST_KEYS = ['MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=']


def stub_enrolment_sheet(test):
    sheet = patch('invitations.views.GoogleSheetsService.fetch_enrollment_rows', return_value=[])
    sheet.start(); test.addCleanup(sheet.stop)


@override_settings(LEARN_INVITATION_KEYS=TEST_KEYS)
class InvitationFlowTests(APITestCase):
    def setUp(self):
        stub_enrolment_sheet(self)
        self.admin = User.objects.create_user(email='invite-admin@example.test', role='ADMIN', password='Test-Password-2026')
        self.client.force_authenticate(self.admin)
        self.payload = {'student_code': 'EDP10001', 'full_name': 'Student', 'role': 'STUDENT'}

    def create(self, **kwargs):
        return self.client.post('/api/invitations/', {**self.payload, **kwargs}, format='json')

    def test_manual_sheet_enrollment_issues_credentials_without_email(self):
        response = self.create()
        self.assertEqual(response.status_code, 201, response.content)
        student = Student.objects.get()
        inv = Invitation.objects.get(student=student)
        self.assertEqual(inv.account_id, student.profile_id)
        self.assertTrue(student.profile.must_change_password)
        self.assertEqual(inv.status, 'PENDING')
        self.assertIsNone(student.profile.email)
        self.assertEqual(len(mail.outbox), 0)

    def test_repeated_import_keeps_original_credentials_and_academics(self):
        self.create(); original = Invitation.objects.get()
        student = Student.objects.get(); student.total_class_quota = 8; student.save()
        again = self.create()
        self.assertEqual(again.status_code, 200)
        inv = Invitation.objects.get()
        self.assertEqual((inv.pk, inv.credential_ciphertext), (original.pk, original.credential_ciphertext))
        self.assertEqual(Student.objects.get().total_class_quota, 8)

    def test_staff_invites_stay_retired(self):
        self.assertEqual(self.create(role='MENTOR').json()['error'], 'STAFF_INVITATIONS_RETIRED')
        self.assertEqual(Invitation.objects.count(), 0)

    def test_google_account_and_staff_contact_do_not_block_invitation(self):
        self.assertEqual(self.create(email=self.admin.email).status_code, 201)
        self.assertNotEqual(Student.objects.get().profile_id, self.admin.pk)

    def test_email_based_edit_is_retired(self):
        self.create()
        response = self.client.patch('/api/invitations/', {'old_email': 'old@example.test', 'new_email': 'new@example.test'})
        self.assertEqual(response.status_code, 410)

    def test_enrolled_invitation_cannot_be_deleted(self):
        self.create(); inv = Invitation.objects.get()
        response = self.client.delete('/api/invitations/', {'id': str(inv.pk)}, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertTrue(Invitation.objects.filter(pk=inv.pk).exists())

    def test_unused_legacy_invitation_can_be_withdrawn(self):
        inv = Invitation.objects.create(email='legacy@example.test', role='STUDENT')
        self.assertEqual(self.client.delete('/api/invitations/', {'id': str(inv.pk)}, format='json').status_code, 200)

    def test_list_has_student_id_username_and_status_but_no_secret(self):
        self.create(); row = self.client.get('/api/invitations/').json()[0]
        self.assertEqual(row['student_name'], 'Student')
        self.assertEqual(row['student_code'], 'EDP10001')
        self.assertEqual(row['username'], 'edp10001')
        self.assertEqual(row['status'], 'PENDING')
        self.assertTrue(row['credentials_available'])
        self.assertNotIn('temporary_password', row)
        self.assertNotIn('credential_ciphertext', row)

    def test_unauthenticated_and_student_cannot_create(self):
        self.client.force_authenticate(None)
        self.assertIn(self.create().status_code, [401, 403])
        user = User.objects.create_user(email='student@example.test', role='STUDENT')
        self.client.force_authenticate(user)
        self.assertEqual(self.create().status_code, 403)

    @patch('invitations.views.GoogleSheetsService.lookup_student_by_code')
    def test_lookup_no_longer_requires_an_email(self, lookup):
        lookup.return_value = {'student_code': 'EDP10001', 'full_name': 'Student'}
        result = self.client.post('/api/invitations/lookup-student/', {'student_code': 'EDP10001'})
        self.assertEqual(result.status_code, 200, result.content)

    @patch('invitations.views.GoogleSheetsService.lookup_student_by_code')
    def test_lookup_does_not_reject_staff_contact_email(self, lookup):
        lookup.return_value = {'student_code': 'EDP10001', 'full_name': 'Student', 'email': self.admin.email}
        self.assertEqual(self.client.post('/api/invitations/lookup-student/', {'student_code': 'EDP10001'}).status_code, 200)


@override_settings(LEARN_INVITATION_KEYS=TEST_KEYS)
class InvitationStaffAssignmentValidationTests(APITestCase):
    """
    New students can only be assigned to ACTIVE staff of the right role
    (Hub parity: the invitations route requires role='mentor'/'tutor' AND
    deactivated_at IS NULL) — otherwise a deactivated staff member could
    keep receiving new students, defeating the soft-deactivation invariant.
    """

    def setUp(self):
        stub_enrolment_sheet(self)
        from django.utils import timezone
        self.admin_user = User.objects.create_user(
            email="assign_admin@eduport.com", password="password",
            full_name="Assign Admin", role="ADMIN"
        )
        self.active_mentor = User.objects.create_user(
            email="assign_mentor@eduport.com", password="password",
            full_name="Assign Mentor", role="MENTOR"
        )
        self.deactivated_mentor = User.objects.create_user(
            email="assign_dead_mentor@eduport.com", password="password",
            full_name="Deactivated Mentor", role="MENTOR",
            is_active=False, deactivated_at=timezone.now()
        )
        self.tutor_user = User.objects.create_user(
            email="assign_tutor@eduport.com", password="password",
            full_name="Assign Tutor", role="TUTOR"
        )
        self.create_url = reverse('invitations:create-student-invitation')
        self.client.force_authenticate(user=self.admin_user)

    def payload(self, **extra):
        base = {
            "student_code": "EDPASSIGN1",
            "email": "assign_student@gmail.com",
            "full_name": "Assign Student",
            "grade": "10",
        }
        base.update(extra)
        return base

    def test_deactivated_mentor_is_refused(self):
        res = self.client.post(self.create_url, self.payload(mentor_id=str(self.deactivated_mentor.id)))
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data["error"], "INVALID_MENTOR")

    def test_wrong_role_mentor_id_is_refused(self):
        # A tutor's id in the mentor field must not pass a bare existence check.
        res = self.client.post(self.create_url, self.payload(mentor_id=str(self.tutor_user.id)))
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data["error"], "INVALID_MENTOR")

    def test_wrong_role_tutor_id_is_refused(self):
        res = self.client.post(self.create_url, self.payload(tutor_id=str(self.active_mentor.id)))
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data["error"], "INVALID_TUTOR")

    def test_active_right_role_mentor_is_accepted(self):
        res = self.client.post(self.create_url, self.payload(mentor_id=str(self.active_mentor.id)))
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
