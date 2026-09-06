from django.urls import reverse
from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APITestCase
from rest_framework import status
from unittest.mock import patch
from invitations.models import Invitation, InvitationStatusChoices, InvitationRoleChoices
from students.models import Student
from activity.models import ActivityLog

User = get_user_model()


@override_settings(ALLOW_MOCK_AUTH=True)
class GoogleAuthenticationTests(APITestCase):
    def setUp(self):
        self.login_url = reverse('accounts:google-login')
        self.logout_url = reverse('accounts:logout')
        self.me_url = reverse('accounts:me')

        # Define email whitelist details
        self.student_email = "student.jane@gmail.com"
        self.student_code = "EDP00123"

        # Create Mentor and Tutor for Student link tests
        self.test_mentor = User.objects.create_user(
            email="test_mentor@eduport.com",
            password="password123",
            full_name="Test Mentor",
            role="MENTOR"
        )
        self.test_tutor = User.objects.create_user(
            email="test_tutor@eduport.com",
            password="password123",
            full_name="Test Tutor",
            role="TUTOR"
        )

        # Create a pending student invitation
        self.student_invitation = Invitation.objects.create(
            email=self.student_email,
            role=InvitationRoleChoices.STUDENT,
            status=InvitationStatusChoices.PENDING,
            extra_data={
                "student_code": self.student_code,
                "full_name": "Jane Student",
                "mobile_number": "+919999999999",
                "grade": "11",
                "syllabus": "ICSE",
                "school_name": "St. Xavier School",
                "country": "India",
                "state": "Maharashtra",
                "admission_date": "2026-06-19",
                "total_class_quota": 10,
                "mentor_id": str(self.test_mentor.id),
                "tutor_id": str(self.test_tutor.id),
                "meet_link": "https://meet.google.com/abc-defg-hij"
            }
        )

        # Create a pending mentor invitation
        self.mentor_email = "mentor.mark@eduport.com"
        self.mentor_invitation = Invitation.objects.create(
            email=self.mentor_email,
            role=InvitationRoleChoices.MENTOR,
            status=InvitationStatusChoices.PENDING,
            extra_data={"full_name": "Mark Mentor"}
        )

    def test_login_missing_token_returns_400(self):
        response = self.client.post(self.login_url, {})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"], "INVALID_INPUT")

    def test_login_uninvited_email_returns_403(self):
        # Use mock token fallback for uninvited email
        mock_token = "mock:uninvited@gmail.com:Uninvited User:https://example.com/pic.png"
        response = self.client.post(self.login_url, {"credential": mock_token})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data["error"], "ACCESS_RESTRICTED")
        
        # Verify no User profile was created
        self.assertFalse(User.objects.filter(email="uninvited@gmail.com").exists())

    def test_login_uninvited_but_in_google_sheet_remains_restricted(self):
        email = "sheets_student@gmail.com"
        mock_token = f"mock:{email}:Jane Google Profile:https://lh3.googleusercontent.com/a"
        
        # Verify no invitation exists beforehand
        self.assertFalse(Invitation.objects.filter(email=email).exists())
        
        # Perform login
        response = self.client.post(self.login_url, {"credential": mock_token})
        
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data["error"], "ACCESS_RESTRICTED")
        
        # Verify no User profile was created
        self.assertFalse(User.objects.filter(email=email).exists())


    def test_login_first_time_student_onboards_and_creates_records(self):
        # 1. Login with whitelisted student email
        mock_token = f"mock:{self.student_email}:Jane Google Profile:https://lh3.googleusercontent.com/a"
        response = self.client.post(self.login_url, {"credential": mock_token})
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["status"], "onboarded")
        self.assertTrue(response.data["is_new_user"])
        
        # 2. Verify User profile created
        user = User.objects.filter(email=self.student_email).first()
        self.assertIsNotNone(user)
        self.assertEqual(user.role, 'STUDENT')
        self.assertEqual(user.full_name, "Jane Google Profile") # Google profile name prioritized
        self.assertEqual(user.avatar_url, "https://lh3.googleusercontent.com/a")
        
        # 3. Verify Student record created with same code
        student = Student.objects.filter(profile=user).first()
        self.assertIsNotNone(student)
        self.assertEqual(student.student_code, self.student_code)
        self.assertEqual(student.grade, "11")
        self.assertEqual(student.school_name, "St. Xavier School")
        self.assertEqual(str(student.admission_date), "2026-06-19")
        self.assertEqual(student.total_class_quota, 10)
        self.assertEqual(student.mentor, self.test_mentor)
        self.assertEqual(student.tutor, self.test_tutor)
        self.assertEqual(student.meet_link, "https://meet.google.com/abc-defg-hij")
        
        # 4. Verify Invitation marked ACCEPTED
        self.student_invitation.refresh_from_db()
        self.assertEqual(self.student_invitation.status, InvitationStatusChoices.ACCEPTED)

        # 5. Verify Activity Log
        log = ActivityLog.objects.filter(actor=user, action="ONBOARDED").first()
        self.assertIsNotNone(log)
        self.assertEqual(log.entity_type, "USER")
        self.assertEqual(log.entity_id, str(user.id))
        self.assertEqual(log.student, student)

    def test_login_first_time_mentor_onboards_without_student_record(self):
        mock_token = f"mock:{self.mentor_email}:Mark Mentor:https://lh3.googleusercontent.com/b"
        response = self.client.post(self.login_url, {"credential": mock_token})
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["status"], "onboarded")
        
        # Verify User created
        user = User.objects.filter(email=self.mentor_email).first()
        self.assertIsNotNone(user)
        self.assertEqual(user.role, 'MENTOR')
        
        # Verify NO student record was created
        self.assertFalse(Student.objects.filter(profile=user).exists())

    def test_subsequent_login_direct_session(self):
        # Onboard first
        mock_token = f"mock:{self.student_email}:Jane Google:https://lh3.googleusercontent.com/a"
        self.client.post(self.login_url, {"credential": mock_token})
        
        # Clear client session
        self.client.logout()

        # Login again
        response = self.client.post(self.login_url, {"credential": mock_token})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "authenticated")
        self.assertFalse(response.data["is_new_user"])

        # Check ActivityLog for second login
        user = User.objects.get(email=self.student_email)
        login_log = ActivityLog.objects.filter(actor=user, action="LOGIN").first()
        self.assertIsNotNone(login_log)

    def test_disabled_user_login_rejected(self):
        # Onboard first
        mock_token = f"mock:{self.student_email}:Jane Google:https://lh3.googleusercontent.com/a"
        self.client.post(self.login_url, {"credential": mock_token})
        
        # Disable user
        user = User.objects.get(email=self.student_email)
        user.is_active = False
        user.save()

        # Attempt login again
        response = self.client.post(self.login_url, {"credential": mock_token})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data["error"], "USER_DISABLED")

    def test_logout_clears_session(self):
        # Login student
        mock_token = f"mock:{self.student_email}:Jane Google:https://lh3.googleusercontent.com/a"
        login_res = self.client.post(self.login_url, {"credential": mock_token})
        
        # Request me (should work)
        me_res = self.client.get(self.me_url)
        self.assertEqual(me_res.status_code, status.HTTP_200_OK)

        # Logout
        logout_res = self.client.post(self.logout_url)
        self.assertEqual(logout_res.status_code, status.HTTP_200_OK)

        # Request me again (should fail)
        me_res2 = self.client.get(self.me_url)
        self.assertEqual(me_res2.status_code, status.HTTP_403_FORBIDDEN)

    def test_me_returns_profile_details(self):
        # Onboard and login
        mock_token = f"mock:{self.student_email}:Jane Google:https://lh3.googleusercontent.com/a"
        self.client.post(self.login_url, {"credential": mock_token})

        response = self.client.get(self.me_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["user"]["email"], self.student_email)
        self.assertEqual(response.data["student_profile"]["student_code"], self.student_code)

class StaffManagementTests(APITestCase):
    def setUp(self):
        # Create an admin user to perform operations
        self.admin = User.objects.create_user(
            email="admin@eduport.com",
            password="password123",
            full_name="Primary Admin",
            role="ADMIN"
        )
        self.mentor = User.objects.create_user(
            email="mentor@eduport.com",
            password="password123",
            full_name="Active Mentor",
            role="MENTOR"
        )
        self.tutor = User.objects.create_user(
            email="tutor@eduport.com",
            password="password123",
            full_name="Active Tutor",
            role="TUTOR"
        )
        
        # Create pending invitations (ghost rows)
        self.ghost_admin = Invitation.objects.create(
            email="ghost_admin@eduport.com",
            role=InvitationRoleChoices.ADMIN,
            status=InvitationStatusChoices.PENDING,
            extra_data={"full_name": "Ghost Admin"}
        )
        self.ghost_mentor = Invitation.objects.create(
            email="ghost_mentor@eduport.com",
            role=InvitationRoleChoices.MENTOR,
            status=InvitationStatusChoices.PENDING,
            extra_data={"full_name": "Ghost Mentor"}
        )
        self.ghost_tutor = Invitation.objects.create(
            email="ghost_tutor@eduport.com",
            role=InvitationRoleChoices.TUTOR,
            status=InvitationStatusChoices.PENDING,
            extra_data={"full_name": "Ghost Tutor"}
        )

        self.client.force_authenticate(user=self.admin)

    def test_admin_list_returns_only_active_admins(self):
        response = self.client.get('/api/admins/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        admins = response.data.get("admins", [])
        
        emails = [a["email"] for a in admins]
        self.assertIn("admin@eduport.com", emails)
        self.assertNotIn("ghost_admin@eduport.com", emails)
        
        # Check active flags
        active_admin = next(a for a in admins if a["email"] == "admin@eduport.com")
        self.assertEqual(active_admin["kind"], "active")

    def test_mentor_list_all_returns_only_active_mentors(self):
        response = self.client.get('/api/mentors/?all=true')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mentors = response.data.get("mentors", [])
        
        emails = [m["email"] for m in mentors]
        self.assertIn("mentor@eduport.com", emails)
        self.assertNotIn("ghost_mentor@eduport.com", emails)

    def test_mentor_list_default_returns_only_active_retains_compat(self):
        response = self.client.get('/api/mentors/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mentors = response.data.get("mentors", [])
        
        emails = [m["email"] for m in mentors]
        self.assertIn("mentor@eduport.com", emails)
        self.assertNotIn("ghost_mentor@eduport.com", emails)

    def test_edit_user_details(self):
        url = f'/api/users/{self.mentor.id}/'
        payload = {"full_name": "Updated Mentor Name", "mobile_number": "+919000000000"}
        response = self.client.patch(url, payload)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.mentor.refresh_from_db()
        self.assertEqual(self.mentor.full_name, "Updated Mentor Name")
        self.assertEqual(self.mentor.mobile_number, "+919000000000")

    def test_edit_user_details_empty_name_fails(self):
        url = f'/api/users/{self.mentor.id}/'
        payload = {"full_name": "  "}
        response = self.client.patch(url, payload)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_delete_user_mentor(self):
        url = f'/api/users/{self.mentor.id}/'
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(User.objects.filter(id=self.mentor.id).exists())

    def test_delete_last_admin_fails(self):
        # Admin deletes themselves while being the only admin
        url = f'/api/users/{self.admin.id}/'
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertTrue(User.objects.filter(id=self.admin.id).exists())

    def test_delete_admin_succeeds_if_other_admin_exists(self):
        other_admin = User.objects.create_user(
            email="admin2@eduport.com",
            password="password123",
            role="ADMIN"
        )
        url = f'/api/users/{other_admin.id}/'
        
        # Invite connection test: let's make caller the inviter, or target the inviter
        # For simplicity, target's invited_by is set to caller (self.admin)
        other_admin.invited_by = self.admin
        other_admin.save()
        
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(User.objects.filter(id=other_admin.id).exists())



class StaffDirectoryAuthorizationTests(APITestCase):
    """
    Role-based access control for the staff directory endpoints. These list
    colleagues, so students must not reach them at all, and the full record
    (email, mobile, inviter) is admin-only.
    """

    MENTORS_URL = '/api/mentors/'
    TUTORS_URL = '/api/tutors/'
    ADMINS_URL = '/api/admins/'

    def setUp(self):
        self.admin = User.objects.create_user(
            email="dir_admin@eduport.com",
            password="password123",
            full_name="Directory Admin",
            role="ADMIN"
        )
        self.mentor = User.objects.create_user(
            email="dir_mentor@eduport.com",
            password="password123",
            full_name="Directory Mentor",
            role="MENTOR"
        )
        self.tutor = User.objects.create_user(
            email="dir_tutor@eduport.com",
            password="password123",
            full_name="Directory Tutor",
            role="TUTOR"
        )
        self.student_user = User.objects.create_user(
            email="dir_student@eduport.com",
            password="password123",
            full_name="Directory Student",
            role="STUDENT"
        )

        # Deactivated staff of every role: present in the table, but the
        # directory advertises itself as listing active staff only.
        self.inactive_admin = User.objects.create_user(
            email="inactive_admin@eduport.com",
            password="password123",
            full_name="Inactive Admin",
            role="ADMIN",
            is_active=False
        )
        self.inactive_mentor = User.objects.create_user(
            email="inactive_mentor@eduport.com",
            password="password123",
            full_name="Inactive Mentor",
            role="MENTOR",
            is_active=False
        )
        self.inactive_tutor = User.objects.create_user(
            email="inactive_tutor@eduport.com",
            password="password123",
            full_name="Inactive Tutor",
            role="TUTOR",
            is_active=False
        )

    def emails(self, response, key):
        return [row["email"] for row in response.data.get(key, [])]

    # --- /api/mentors/ and /api/tutors/ : staff roles only -------------------

    def test_mentor_directory_allowed_for_staff_roles(self):
        for user in (self.admin, self.mentor, self.tutor):
            with self.subTest(role=user.role):
                self.client.force_authenticate(user=user)
                response = self.client.get(self.MENTORS_URL)
                self.assertEqual(response.status_code, status.HTTP_200_OK)
                self.assertIn("dir_mentor@eduport.com", self.emails(response, "mentors"))

    def test_tutor_directory_allowed_for_staff_roles(self):
        for user in (self.admin, self.mentor, self.tutor):
            with self.subTest(role=user.role):
                self.client.force_authenticate(user=user)
                response = self.client.get(self.TUTORS_URL)
                self.assertEqual(response.status_code, status.HTTP_200_OK)
                self.assertIn("dir_tutor@eduport.com", self.emails(response, "tutors"))

    def test_student_cannot_read_mentor_directory(self):
        self.client.force_authenticate(user=self.student_user)
        response = self.client.get(self.MENTORS_URL)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertNotIn("mentors", response.data)

    def test_student_cannot_read_tutor_directory(self):
        self.client.force_authenticate(user=self.student_user)
        response = self.client.get(self.TUTORS_URL)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertNotIn("tutors", response.data)

    def test_anonymous_cannot_read_directories(self):
        for url in (self.MENTORS_URL, self.TUTORS_URL, self.ADMINS_URL):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # --- /api/admins/ : admins only -----------------------------------------

    def test_admin_directory_allowed_for_admin(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.get(self.ADMINS_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("dir_admin@eduport.com", self.emails(response, "admins"))

    def test_admin_directory_forbidden_for_other_roles(self):
        for user in (self.mentor, self.tutor, self.student_user):
            with self.subTest(role=user.role):
                self.client.force_authenticate(user=user)
                response = self.client.get(self.ADMINS_URL)
                self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
                self.assertNotIn("admins", response.data)

    # --- ?all=true : admins only --------------------------------------------

    def test_all_true_allowed_for_admin(self):
        self.client.force_authenticate(user=self.admin)
        for url, key in ((self.MENTORS_URL, "mentors"), (self.TUTORS_URL, "tutors")):
            with self.subTest(url=url):
                response = self.client.get(url, {"all": "true"})
                self.assertEqual(response.status_code, status.HTTP_200_OK)
                self.assertTrue(response.data[key])
                self.assertIn("mobile_number", response.data[key][0])

    def test_all_true_forbidden_for_non_admins(self):
        for user in (self.mentor, self.tutor, self.student_user):
            for url in (self.MENTORS_URL, self.TUTORS_URL):
                with self.subTest(role=user.role, url=url):
                    self.client.force_authenticate(user=user)
                    response = self.client.get(url, {"all": "true"})
                    self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_all_true_is_not_downgraded_to_slim_response(self):
        """A refused ?all=true must fail loudly, not return the slim payload."""
        self.client.force_authenticate(user=self.mentor)
        response = self.client.get(self.MENTORS_URL, {"all": "true"})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertNotIn("mentors", response.data)
        self.assertEqual(response.data.get("error"), "FORBIDDEN")

    # --- payload shape -------------------------------------------------------

    def test_slim_directory_exposes_no_extra_pii(self):
        """Non-admin staff get id/full_name/email only — no mobile or inviter."""
        self.client.force_authenticate(user=self.tutor)
        response = self.client.get(self.MENTORS_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["mentors"])
        for row in response.data["mentors"]:
            self.assertEqual(set(row.keys()), {"id", "full_name", "email"})

    # --- inactive staff filtering -------------------------------------------

    def test_inactive_mentor_excluded_from_slim_directory(self):
        self.client.force_authenticate(user=self.tutor)
        response = self.client.get(self.MENTORS_URL)
        emails = self.emails(response, "mentors")
        self.assertIn("dir_mentor@eduport.com", emails)
        self.assertNotIn("inactive_mentor@eduport.com", emails)

    def test_inactive_staff_excluded_from_full_directory(self):
        self.client.force_authenticate(user=self.admin)
        for url, key, active, inactive in (
            (self.MENTORS_URL, "mentors", "dir_mentor@eduport.com", "inactive_mentor@eduport.com"),
            (self.TUTORS_URL, "tutors", "dir_tutor@eduport.com", "inactive_tutor@eduport.com"),
        ):
            with self.subTest(url=url):
                response = self.client.get(url, {"all": "true"})
                emails = self.emails(response, key)
                self.assertIn(active, emails)
                self.assertNotIn(inactive, emails)

    def test_inactive_admin_excluded_from_admin_directory(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.get(self.ADMINS_URL)
        emails = self.emails(response, "admins")
        self.assertIn("dir_admin@eduport.com", emails)
        self.assertNotIn("inactive_admin@eduport.com", emails)
