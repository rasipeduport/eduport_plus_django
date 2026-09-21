from django.urls import reverse
from django.contrib.auth import get_user_model
from django.core import mail
from rest_framework.test import APITestCase
from rest_framework import status
from unittest.mock import patch
from .models import Invitation, InvitationStatusChoices, InvitationRoleChoices
from students.models import Student

User = get_user_model()

class InvitationFlowTests(APITestCase):
    def setUp(self):
        # Create users of different roles
        self.admin_user = User.objects.create_user(
            email="admin@eduport.com",
            password="password123",
            full_name="Admin User",
            role="ADMIN"
        )
        self.mentor_user = User.objects.create_user(
            email="mentor@eduport.com",
            password="password123",
            full_name="Mentor User",
            role="MENTOR"
        )
        self.student_user = User.objects.create_user(
            email="existing_student@gmail.com",
            password="password123",
            full_name="Student User",
            role="STUDENT"
        )
        self.lookup_url = reverse('invitations:lookup-student')
        self.create_url = reverse('invitations:create-student-invitation')

    # --- LOOKUP STUDENT TESTS ---

    def test_lookup_unauthenticated_rejected(self):
        response = self.client.post(self.lookup_url, {"student_code": "EDP00099"})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_lookup_student_role_rejected(self):
        self.client.force_authenticate(user=self.student_user)
        response = self.client.post(self.lookup_url, {"student_code": "EDP00099"})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_lookup_mentor_role_allowed(self):
        self.client.force_authenticate(user=self.mentor_user)
        response = self.client.post(self.lookup_url, {})
        # Missing student_code returns 400 but validates role permission
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch('invitations.views.GoogleSheetsService.lookup_student_by_code')
    def test_lookup_student_found_returns_details_without_db_write(self, mock_lookup):
        mock_lookup.return_value = {
            "student_code": "EDP00099",
            "email": "new_student@gmail.com",
            "full_name": "Jane Doe",
            "mobile_number": "+919876543210"
        }
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.post(self.lookup_url, {"student_code": "EDP00099"})
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "found")
        self.assertEqual(response.data["student_data"]["full_name"], "Jane Doe")
        
        # Verify NO DB entry was created
        self.assertFalse(Invitation.objects.filter(email="new_student@gmail.com").exists())

    @patch('invitations.views.GoogleSheetsService.lookup_student_by_code')
    def test_lookup_tutor_role_forbidden(self, mock_lookup):
        tutor_user = User.objects.create_user(
            email="tutor@eduport.com",
            password="password123",
            full_name="Tutor User",
            role="TUTOR"
        )
        mock_lookup.return_value = {
            "student_code": "EDP00099",
            "email": "new_student_tutor@gmail.com",
            "full_name": "Jane Doe Tutor",
            "mobile_number": "+919876543210"
        }
        self.client.force_authenticate(user=tutor_user)
        response = self.client.post(self.lookup_url, {"student_code": "EDP00099"})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(Invitation.objects.filter(email="new_student_tutor@gmail.com").exists())


    @patch('invitations.views.GoogleSheetsService.lookup_student_by_code')
    def test_lookup_staff_email_blocks(self, mock_lookup):
        # A sheet record whose email belongs to a registered STAFF account is blocked.
        mock_lookup.return_value = {
            "student_code": "EDP00099",
            "email": "mentor@eduport.com",  # Email of self.mentor_user (role MENTOR)
            "full_name": "Student User"
        }
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.post(self.lookup_url, {"student_code": "EDP00099"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"], "USER_ALREADY_REGISTERED")

    @patch('invitations.views.GoogleSheetsService.lookup_student_by_code')
    def test_lookup_registered_student_parent_allowed(self, mock_lookup):
        # A registered STUDENT (parent) can be looked up to add another child.
        mock_lookup.return_value = {
            "student_code": "EDP00200",
            "email": "existing_student@gmail.com",  # Email of self.student_user (role STUDENT)
            "full_name": "Second Child"
        }
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.post(self.lookup_url, {"student_code": "EDP00200"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "found")

    @patch('invitations.views.GoogleSheetsService.lookup_student_by_code')
    def test_lookup_already_onboarded_student_blocks(self, mock_lookup):
        # A code that already has a Student row cannot be invited again.
        Student.objects.create(
            profile=self.student_user,
            student_code="EDP00300",
            full_name="Enrolled Kid",
        )
        mock_lookup.return_value = {
            "student_code": "EDP00300",
            "email": "existing_student@gmail.com",
            "full_name": "Enrolled Kid"
        }
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.post(self.lookup_url, {"student_code": "EDP00300"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"], "STUDENT_ALREADY_ONBOARDED")

    # --- CREATE INVITATION TESTS ---

    def test_create_unauthenticated_rejected(self):
        response = self.client.post(self.create_url, {"email": "test@gmail.com"})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_create_student_role_rejected(self):
        self.client.force_authenticate(user=self.student_user)
        response = self.client.post(self.create_url, {"email": "test@gmail.com"})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_create_invitation_success_and_saves_in_db(self):
        self.client.force_authenticate(user=self.admin_user)
        payload = {
            "student_code": "EDP00099",
            "email": "invited_student@gmail.com",
            "full_name": "Sarah Connor",
            "mobile_number": "+919876543210",
            "grade": "10",
            "syllabus": "CBSE",
            "meet_link": "https://meet.google.com/abc-defg-hij"
        }
        response = self.client.post(self.create_url, payload)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["status"], "created")
        
        # Verify db entry
        invitation = Invitation.objects.filter(email="invited_student@gmail.com").first()
        self.assertIsNotNone(invitation)
        self.assertEqual(invitation.status, InvitationStatusChoices.PENDING)
        self.assertEqual(invitation.extra_data["student_code"], "EDP00099")
        self.assertEqual(invitation.extra_data["meet_link"], "https://meet.google.com/abc-defg-hij")
        self.assertEqual(invitation.invited_by, self.admin_user)

        # Verify email was sent and contains the correct Learn redirect link
        self.assertEqual(len(mail.outbox), 1)
        sent_email = mail.outbox[0]
        self.assertEqual(sent_email.to, ["invited_student@gmail.com"])
        self.assertIn("Student", sent_email.subject)
        self.assertIn("http://localhost:3001/login?email=invited_student@gmail.com", sent_email.body)

    def test_create_invitation_invalid_mentor_returns_400(self):
        self.client.force_authenticate(user=self.admin_user)
        payload = {
            "student_code": "EDP00099",
            "email": "invited_student@gmail.com",
            "full_name": "Sarah Connor",
            "mentor_id": "00000000-0000-0000-0000-000000000000" # Invalid UUID
        }
        response = self.client.post(self.create_url, payload)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"], "INVALID_MENTOR")

    def test_create_invitation_updates_pending_invitation(self):
        # Create an existing pending invitation
        existing_inv = Invitation.objects.create(
            email="pending_inv@gmail.com",
            role=InvitationRoleChoices.STUDENT,
            status=InvitationStatusChoices.PENDING,
            extra_data={"student_code": "EDP00099", "grade": "9"}
        )
        self.client.force_authenticate(user=self.mentor_user)
        payload = {
            "student_code": "EDP00099",
            "email": "pending_inv@gmail.com",
            "full_name": "Sarah Connor Updated",
            "grade": "10"
        }
        response = self.client.post(self.create_url, payload)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "updated")
        
        existing_inv.refresh_from_db()
        self.assertEqual(existing_inv.extra_data["grade"], "10")
        self.assertEqual(existing_inv.extra_data["full_name"], "Sarah Connor Updated")
        self.assertEqual(existing_inv.invited_by, self.mentor_user)

    def test_list_edit_and_delete_invitation(self):
        self.client.force_authenticate(user=self.admin_user)
        
        # 1. Create a whitelisted invitation to test with
        existing_inv = Invitation.objects.create(
            email="test_invite@gmail.com",
            role=InvitationRoleChoices.STUDENT,
            status=InvitationStatusChoices.PENDING,
            extra_data={"student_code": "EDP00099"}
        )
        
        # 2. Test List GET /api/invitations/
        list_url = reverse('invitations:create-invitation')
        response = self.client.get(list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["email"], "test_invite@gmail.com")
        
        # 3. Test Patch edit email PATCH /api/invitations/
        patch_payload = {
            "old_email": "test_invite@gmail.com",
            "new_email": "corrected_invite@gmail.com"
        }
        response = self.client.patch(list_url, patch_payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(Invitation.objects.filter(email="corrected_invite@gmail.com").exists())
        self.assertFalse(Invitation.objects.filter(email="test_invite@gmail.com").exists())
        
        # 4. Test Withdraw delete DELETE /api/invitations/
        delete_payload = {
            "email": "corrected_invite@gmail.com"
        }
        response = self.client.delete(list_url, delete_payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(Invitation.objects.filter(email="corrected_invite@gmail.com").exists())

    def test_mentor_invite_staff_role_forbidden(self):
        self.client.force_authenticate(user=self.mentor_user)
        payload = {
            "email": "staff_invite@gmail.com",
            "role": "TUTOR",
            "full_name": "Sarah Staff"
        }
        response = self.client.post(self.create_url, payload)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(Invitation.objects.filter(email="staff_invite@gmail.com").exists())

    def test_mentor_patch_non_student_invitation_forbidden(self):
        # Create non-student invitation
        Invitation.objects.create(
            email="staff_invite@gmail.com",
            role=InvitationRoleChoices.TUTOR,
            status=InvitationStatusChoices.PENDING
        )
        self.client.force_authenticate(user=self.mentor_user)
        list_url = reverse('invitations:create-invitation')
        patch_payload = {
            "old_email": "staff_invite@gmail.com",
            "new_email": "corrected_staff@gmail.com"
        }
        response = self.client.patch(list_url, patch_payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(Invitation.objects.filter(email="staff_invite@gmail.com").exists())

    def test_mentor_delete_non_student_invitation_forbidden(self):
        # Create non-student invitation
        Invitation.objects.create(
            email="staff_invite@gmail.com",
            role=InvitationRoleChoices.TUTOR,
            status=InvitationStatusChoices.PENDING
        )
        self.client.force_authenticate(user=self.mentor_user)
        list_url = reverse('invitations:create-invitation')
        delete_payload = {
            "email": "staff_invite@gmail.com"
        }
        response = self.client.delete(list_url, delete_payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(Invitation.objects.filter(email="staff_invite@gmail.com").exists())

    def test_create_second_student_invitation_for_same_email(self):
        # First child invited for a parent email.
        first = Invitation.objects.create(
            email="parent@gmail.com",
            role=InvitationRoleChoices.STUDENT,
            status=InvitationStatusChoices.PENDING,
            extra_data={"student_code": "EDP00001", "full_name": "Child One"},
        )
        self.client.force_authenticate(user=self.admin_user)

        # Second child, SAME email, DIFFERENT code -> a brand new invitation.
        payload = {
            "student_code": "EDP00002",
            "email": "parent@gmail.com",
            "full_name": "Child Two",
        }
        response = self.client.post(self.create_url, payload)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["status"], "created")

        invites = Invitation.objects.filter(email="parent@gmail.com").order_by("created_at")
        self.assertEqual(invites.count(), 2)
        codes = sorted(i.extra_data["student_code"] for i in invites)
        self.assertEqual(codes, ["EDP00001", "EDP00002"])

    def test_create_second_student_for_registered_parent_allowed(self):
        # The parent has already logged in (registered as a STUDENT user).
        payload = {
            "student_code": "EDP00010",
            "email": "existing_student@gmail.com",  # self.student_user, role STUDENT
            "full_name": "Another Child",
        }
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.post(self.create_url, payload)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(
            Invitation.objects.filter(
                email="existing_student@gmail.com",
                extra_data__student_code="EDP00010",
            ).exists()
        )

    def test_create_student_invitation_for_staff_email_blocked(self):
        payload = {
            "student_code": "EDP00020",
            "email": "mentor@eduport.com",  # registered MENTOR
            "full_name": "Should Fail",
        }
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.post(self.create_url, payload)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"], "USER_ALREADY_REGISTERED")

    def test_create_invitation_for_onboarded_code_blocked(self):
        Student.objects.create(
            profile=self.student_user,
            student_code="EDP00030",
            full_name="Enrolled",
        )
        payload = {
            "student_code": "EDP00030",
            "email": "newparent@gmail.com",
            "full_name": "Enrolled",
        }
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.post(self.create_url, payload)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"], "STUDENT_ALREADY_ONBOARDED")

    def test_withdraw_by_id_targets_correct_child(self):
        # Two children share a parent email; withdraw must hit the right row.
        a = Invitation.objects.create(
            email="twins@gmail.com", role=InvitationRoleChoices.STUDENT,
            status=InvitationStatusChoices.PENDING,
            extra_data={"student_code": "EDP00041"},
        )
        b = Invitation.objects.create(
            email="twins@gmail.com", role=InvitationRoleChoices.STUDENT,
            status=InvitationStatusChoices.PENDING,
            extra_data={"student_code": "EDP00042"},
        )
        self.client.force_authenticate(user=self.admin_user)
        list_url = reverse('invitations:create-invitation')
        response = self.client.delete(list_url, {"id": str(a.id)}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(Invitation.objects.filter(id=a.id).exists())
        self.assertTrue(Invitation.objects.filter(id=b.id).exists())

    def test_create_staff_invitation_sends_hub_email(self):
        self.client.force_authenticate(user=self.admin_user)
        payload = {
            "email": "invited_tutor@eduport.com",
            "role": "TUTOR",
            "full_name": "Tutor Tim",
            "mobile_number": "+919876543211"
        }
        # Clear outbox
        mail.outbox.clear()
        
        response = self.client.post(self.create_url, payload)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        
        # Verify email was sent and contains the Hub URL instead of Learn URL
        self.assertEqual(len(mail.outbox), 1)
        sent_email = mail.outbox[0]
        self.assertEqual(sent_email.to, ["invited_tutor@eduport.com"])
        self.assertIn("Tutor", sent_email.subject)
        self.assertIn("http://localhost:3000/login?email=invited_tutor@eduport.com", sent_email.body)



class InvitationStaffAssignmentValidationTests(APITestCase):
    """
    New students can only be assigned to ACTIVE staff of the right role
    (Hub parity: the invitations route requires role='mentor'/'tutor' AND
    deactivated_at IS NULL) — otherwise a deactivated staff member could
    keep receiving new students, defeating the soft-deactivation invariant.
    """

    def setUp(self):
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
