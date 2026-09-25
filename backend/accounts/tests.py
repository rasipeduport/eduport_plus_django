from django.urls import reverse
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase, APIClient
from rest_framework import status
from unittest.mock import patch
from datetime import timedelta
from invitations.models import Invitation, InvitationStatusChoices, InvitationRoleChoices
from students.models import Student, StatusChoices
from sessions.models import Session, SessionStatusChoices
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

    def test_admin_list_includes_pending_invitations_as_ghosts(self):
        """Hub parity: the staff tables list pending invites above the accounts."""
        response = self.client.get('/api/admins/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        admins = response.data.get("admins", [])

        emails = [a["email"] for a in admins]
        self.assertIn("admin@eduport.com", emails)
        self.assertIn("ghost_admin@eduport.com", emails)

        active_admin = next(a for a in admins if a["email"] == "admin@eduport.com")
        self.assertEqual(active_admin["kind"], "active")

        ghost_admin = next(a for a in admins if a["email"] == "ghost_admin@eduport.com")
        self.assertEqual(ghost_admin["kind"], "ghost")
        self.assertEqual(ghost_admin["role"], "admin")
        self.assertEqual(str(self.ghost_admin.id), ghost_admin["id"])

        # Ghosts sort ahead of the real accounts.
        self.assertLess(emails.index("ghost_admin@eduport.com"), emails.index("admin@eduport.com"))

    def test_staff_list_excludes_accepted_invitations(self):
        """An accepted invite is already represented by the account it created."""
        self.ghost_admin.status = InvitationStatusChoices.ACCEPTED
        self.ghost_admin.save(update_fields=["status"])

        response = self.client.get('/api/admins/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        emails = [a["email"] for a in response.data.get("admins", [])]
        self.assertNotIn("ghost_admin@eduport.com", emails)

    def test_staff_list_ghosts_are_scoped_to_their_role(self):
        response = self.client.get('/api/mentors/?all=true')
        emails = [m["email"] for m in response.data.get("mentors", [])]
        self.assertIn("ghost_mentor@eduport.com", emails)
        self.assertNotIn("ghost_admin@eduport.com", emails)
        self.assertNotIn("ghost_tutor@eduport.com", emails)

    def test_mentor_list_all_includes_pending_invitations_as_ghosts(self):
        response = self.client.get('/api/mentors/?all=true')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mentors = response.data.get("mentors", [])

        emails = [m["email"] for m in mentors]
        self.assertIn("mentor@eduport.com", emails)
        self.assertIn("ghost_mentor@eduport.com", emails)

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

    def test_user_delete_endpoint_removed(self):
        """
        Staff are soft-deactivated, never hard-deleted (parity with the Hub,
        which has no user DELETE route at all). The method must not exist.
        """
        for target in (self.mentor, self.tutor, self.admin):
            with self.subTest(role=target.role):
                response = self.client.delete(f'/api/users/{target.id}/')
                self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
                self.assertTrue(User.objects.filter(id=target.id).exists())



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

        # Deactivated staff of every role, in the consistent lifecycle state
        # (deactivated_at set AND is_active=False): hidden from the slim
        # assignable dropdowns, but included in the admin's full records so
        # they can be shown with a badge and reactivated.
        self.inactive_admin = User.objects.create_user(
            email="inactive_admin@eduport.com",
            password="password123",
            full_name="Inactive Admin",
            role="ADMIN",
            is_active=False,
            deactivated_at=timezone.now()
        )
        self.inactive_mentor = User.objects.create_user(
            email="inactive_mentor@eduport.com",
            password="password123",
            full_name="Inactive Mentor",
            role="MENTOR",
            is_active=False,
            deactivated_at=timezone.now()
        )
        self.inactive_tutor = User.objects.create_user(
            email="inactive_tutor@eduport.com",
            password="password123",
            full_name="Inactive Tutor",
            role="TUTOR",
            is_active=False,
            deactivated_at=timezone.now()
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

    def test_desynced_lifecycle_flags_never_assignable(self):
        """
        A user whose flags disagree (is_active=False with no deactivated_at,
        only creatable through the Django admin) must still be excluded from
        the assignable dropdowns.
        """
        User.objects.create_user(
            email="desynced_mentor@eduport.com",
            password="password123",
            full_name="Desynced Mentor",
            role="MENTOR",
            is_active=False
        )
        self.client.force_authenticate(user=self.admin)
        response = self.client.get(self.MENTORS_URL)
        self.assertNotIn("desynced_mentor@eduport.com", self.emails(response, "mentors"))

    def test_deactivated_staff_included_in_full_directory_with_badge_field(self):
        """
        Parity with the Hub staff pages: the admin's full records include
        deactivated staff (marked via deactivated_at) so they can be shown
        with a badge and reactivated — only the assignable dropdowns hide them.
        """
        self.client.force_authenticate(user=self.admin)
        for url, key, active, inactive in (
            (self.MENTORS_URL, "mentors", "dir_mentor@eduport.com", "inactive_mentor@eduport.com"),
            (self.TUTORS_URL, "tutors", "dir_tutor@eduport.com", "inactive_tutor@eduport.com"),
        ):
            with self.subTest(url=url):
                response = self.client.get(url, {"all": "true"})
                rows = {row["email"]: row for row in response.data.get(key, [])}
                self.assertIn(active, rows)
                self.assertIsNone(rows[active]["deactivated_at"])
                self.assertIn(inactive, rows)
                self.assertIsNotNone(rows[inactive]["deactivated_at"])

    def test_deactivated_admin_included_in_admin_directory_with_badge_field(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.get(self.ADMINS_URL)
        rows = {row["email"]: row for row in response.data.get("admins", [])}
        self.assertIn("dir_admin@eduport.com", rows)
        self.assertIsNone(rows["dir_admin@eduport.com"]["deactivated_at"])
        self.assertIn("inactive_admin@eduport.com", rows)
        self.assertIsNotNone(rows["inactive_admin@eduport.com"]["deactivated_at"])


class StaffLifecycleTests(APITestCase):
    """
    Soft-deactivation lifecycle (parity with the Hub's user-exit flow):
    admin-only status endpoint, mentors/tutors only (admins are peers),
    handover guard on ACTIVE students, bulk reassign that re-points open
    scheduled sessions, session lockout, and reactivation.
    """

    def setUp(self):
        self.admin = User.objects.create_user(
            email="lc_admin@eduport.com", password="password123",
            full_name="Lifecycle Admin", role="ADMIN"
        )
        self.other_admin = User.objects.create_user(
            email="lc_admin2@eduport.com", password="password123",
            full_name="Other Admin", role="ADMIN"
        )
        self.mentor = User.objects.create_user(
            email="lc_mentor@eduport.com", password="password123",
            full_name="Departing Mentor", role="MENTOR"
        )
        self.mentor2 = User.objects.create_user(
            email="lc_mentor2@eduport.com", password="password123",
            full_name="Replacement Mentor", role="MENTOR"
        )
        self.tutor = User.objects.create_user(
            email="lc_tutor@eduport.com", password="password123",
            full_name="Departing Tutor", role="TUTOR"
        )
        self.tutor2 = User.objects.create_user(
            email="lc_tutor2@eduport.com", password="password123",
            full_name="Replacement Tutor", role="TUTOR"
        )
        self.student_user = User.objects.create_user(
            email="lc_student@eduport.com", password="password123",
            full_name="Lifecycle Student", role="STUDENT"
        )

        self.active_student = Student.objects.create(
            profile=self.student_user, student_code="LC001",
            full_name="Active Student", mentor=self.mentor, tutor=self.tutor,
            status=StatusChoices.ACTIVE
        )
        self.inactive_student = Student.objects.create(
            profile=self.student_user, student_code="LC002",
            full_name="Inactive Student", mentor=self.mentor, tutor=self.tutor,
            status=StatusChoices.INACTIVE, status_note="Paused"
        )
        self.expired_student = Student.objects.create(
            profile=self.student_user, student_code="LC003",
            full_name="Expired Student", mentor=self.mentor, tutor=self.tutor,
            status=StatusChoices.EXPIRED, status_note="Left"
        )

        future = timezone.now() + timedelta(days=1)
        past = timezone.now() - timedelta(days=1)
        self.scheduled_session = Session.objects.create(
            student=self.active_student, tutor=self.tutor,
            start_time=future, end_time=future + timedelta(hours=1),
            title="Open Class", status=SessionStatusChoices.SCHEDULED
        )
        self.attended_session = Session.objects.create(
            student=self.active_student, tutor=self.tutor,
            start_time=past, end_time=past + timedelta(hours=1),
            title="Done Class", status=SessionStatusChoices.ATTENDED
        )
        self.inactive_student_session = Session.objects.create(
            student=self.inactive_student, tutor=self.tutor,
            start_time=future, end_time=future + timedelta(hours=1),
            title="Paused Student Class", status=SessionStatusChoices.SCHEDULED
        )

        self.client.force_authenticate(user=self.admin)

    def status_url(self, user):
        return f'/api/users/{user.id}/status/'

    def reassign_url(self, user):
        return f'/api/users/{user.id}/reassign/'

    # --- deactivate ----------------------------------------------------------

    def test_deactivate_blocked_while_active_students_assigned(self):
        res = self.client.post(self.status_url(self.mentor), {"action": "deactivate"}, format='json')
        self.assertEqual(res.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(res.data.get("error"), "HANDOVER_REQUIRED")
        self.mentor.refresh_from_db()
        self.assertIsNone(self.mentor.deactivated_at)
        self.assertTrue(self.mentor.is_active)

    def test_inactive_and_expired_assignments_do_not_block_deactivation(self):
        """The handover guard counts ACTIVE students only (Hub parity)."""
        self.active_student.mentor = self.mentor2
        self.active_student.tutor = self.tutor2
        self.active_student.save()
        # mentor/tutor now hold only INACTIVE and EXPIRED students.
        for target in (self.mentor, self.tutor):
            with self.subTest(role=target.role):
                res = self.client.post(self.status_url(target), {"action": "deactivate"}, format='json')
                self.assertEqual(res.status_code, status.HTTP_200_OK)

    def test_deactivate_sets_lifecycle_fields_and_logs(self):
        res = self.client.post(
            self.status_url(self.tutor2),
            {"action": "deactivate", "reason": "  Left the company  "},
            format='json'
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.tutor2.refresh_from_db()
        self.assertIsNotNone(self.tutor2.deactivated_at)
        self.assertEqual(self.tutor2.deactivated_by, self.admin)
        self.assertEqual(self.tutor2.deactivation_reason, "Left the company")
        self.assertFalse(self.tutor2.is_active)
        # Role is kept for historical attribution.
        self.assertEqual(self.tutor2.role, "TUTOR")

        log = ActivityLog.objects.filter(action='user.deactivate', entity_id=str(self.tutor2.id)).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.changes["status"], {"old": "active", "new": "deactivated"})
        self.assertEqual(log.context.get("reason"), "Left the company")

    def test_deactivated_staff_session_is_locked_out(self):
        """
        A deactivated user's still-live session must die on their next request
        (is_active=False makes ModelBackend.get_user return None).
        """
        live = APIClient()
        self.assertTrue(live.login(email="lc_tutor2@eduport.com", password="password123"))
        self.assertEqual(live.get('/api/auth/me/').status_code, status.HTTP_200_OK)

        res = self.client.post(self.status_url(self.tutor2), {"action": "deactivate"}, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        blocked = live.get('/api/auth/me/')
        self.assertIn(blocked.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))

    # --- reactivate ----------------------------------------------------------

    def test_reactivate_clears_lifecycle_fields_and_logs(self):
        self.client.post(self.status_url(self.tutor2), {"action": "deactivate", "reason": "x"}, format='json')
        res = self.client.post(self.status_url(self.tutor2), {"action": "reactivate"}, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.tutor2.refresh_from_db()
        self.assertIsNone(self.tutor2.deactivated_at)
        self.assertIsNone(self.tutor2.deactivated_by)
        self.assertIsNone(self.tutor2.deactivation_reason)
        self.assertTrue(self.tutor2.is_active)

        log = ActivityLog.objects.filter(action='user.reactivate', entity_id=str(self.tutor2.id)).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.changes["status"], {"old": "deactivated", "new": "active"})

    # --- guards --------------------------------------------------------------

    def test_admin_target_is_refused(self):
        """Admins are peers: one admin never deactivates another (Hub parity)."""
        res = self.client.post(self.status_url(self.other_admin), {"action": "deactivate"}, format='json')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        self.other_admin.refresh_from_db()
        self.assertIsNone(self.other_admin.deactivated_at)

    def test_student_target_is_refused(self):
        res = self.client.post(self.status_url(self.student_user), {"action": "deactivate"}, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_non_admin_caller_is_refused(self):
        for caller in (self.mentor, self.tutor, self.student_user):
            with self.subTest(role=caller.role):
                self.client.force_authenticate(user=caller)
                res = self.client.post(self.status_url(self.tutor2), {"action": "deactivate"}, format='json')
                self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_unknown_target_is_404(self):
        import uuid as uuid_mod
        res = self.client.post(f'/api/users/{uuid_mod.uuid4()}/status/', {"action": "deactivate"}, format='json')
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_invalid_action_and_reason_are_rejected(self):
        res = self.client.post(self.status_url(self.tutor2), {"action": "obliterate"}, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        res = self.client.post(
            self.status_url(self.tutor2),
            {"action": "deactivate", "reason": "x" * 501},
            format='json'
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    # --- reassign ------------------------------------------------------------

    def test_reassign_moves_active_students_and_open_sessions_only(self):
        res = self.client.post(
            self.reassign_url(self.tutor),
            {"new_tutor": str(self.tutor2.id)},
            format='json'
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        summary = res.data["result"]
        self.assertEqual(summary["students_tutor_reassigned"], 1)
        self.assertEqual(summary["sessions_repointed"], 1)

        # ACTIVE student and their open session move; history and non-active
        # students keep the departing tutor for attribution.
        self.active_student.refresh_from_db()
        self.scheduled_session.refresh_from_db()
        self.attended_session.refresh_from_db()
        self.inactive_student.refresh_from_db()
        self.inactive_student_session.refresh_from_db()
        self.assertEqual(self.active_student.tutor, self.tutor2)
        self.assertEqual(self.scheduled_session.tutor, self.tutor2)
        self.assertEqual(self.attended_session.tutor, self.tutor)
        self.assertEqual(self.inactive_student.tutor, self.tutor)
        self.assertEqual(self.inactive_student_session.tutor, self.tutor)

        # The handover unblocks deactivation.
        res = self.client.post(self.status_url(self.tutor), {"action": "deactivate"}, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        log = ActivityLog.objects.filter(action='staff.reassign_all', entity_id=str(self.tutor.id)).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.context.get("students_tutor_reassigned"), 1)

    def test_reassign_mentor_students(self):
        res = self.client.post(
            self.reassign_url(self.mentor),
            {"new_mentor": str(self.mentor2.id)},
            format='json'
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["result"]["students_mentor_reassigned"], 1)
        self.active_student.refresh_from_db()
        self.inactive_student.refresh_from_db()
        self.expired_student.refresh_from_db()
        self.assertEqual(self.active_student.mentor, self.mentor2)
        self.assertEqual(self.inactive_student.mentor, self.mentor)
        self.assertEqual(self.expired_student.mentor, self.mentor)

    def test_reassign_requires_valid_active_replacement_of_same_role(self):
        # Missing replacement.
        res = self.client.post(self.reassign_url(self.mentor), {}, format='json')
        self.assertEqual(res.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(res.data.get("error"), "INVALID_REPLACEMENT")
        # Wrong role.
        res = self.client.post(self.reassign_url(self.mentor), {"new_mentor": str(self.tutor2.id)}, format='json')
        self.assertEqual(res.status_code, status.HTTP_409_CONFLICT)
        # Deactivated replacement.
        self.mentor2.deactivated_at = timezone.now()
        self.mentor2.is_active = False
        self.mentor2.save()
        res = self.client.post(self.reassign_url(self.mentor), {"new_mentor": str(self.mentor2.id)}, format='json')
        self.assertEqual(res.status_code, status.HTTP_409_CONFLICT)
        # Nothing moved.
        self.active_student.refresh_from_db()
        self.assertEqual(self.active_student.mentor, self.mentor)

    def test_reassign_non_admin_caller_is_refused(self):
        for caller in (self.mentor2, self.tutor2, self.student_user):
            with self.subTest(role=caller.role):
                self.client.force_authenticate(user=caller)
                res = self.client.post(
                    self.reassign_url(self.tutor), {"new_tutor": str(self.tutor2.id)}, format='json'
                )
                self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_reassign_unknown_target_is_404(self):
        import uuid as uuid_mod
        res = self.client.post(f'/api/users/{uuid_mod.uuid4()}/reassign/', {}, format='json')
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    # --- directory integration ----------------------------------------------

    def test_deactivated_tutor_hidden_from_dropdown_but_in_full_records(self):
        self.client.post(self.status_url(self.tutor2), {"action": "deactivate"}, format='json')

        slim = self.client.get('/api/tutors/')
        slim_emails = [t["email"] for t in slim.data["tutors"]]
        self.assertNotIn("lc_tutor2@eduport.com", slim_emails)

        full = self.client.get('/api/tutors/', {"all": "true"})
        rows = {t["email"]: t for t in full.data["tutors"]}
        self.assertIn("lc_tutor2@eduport.com", rows)
        self.assertIsNotNone(rows["lc_tutor2@eduport.com"]["deactivated_at"])

    def test_deactivate_blocked_for_tutor_with_active_students(self):
        """The handover guard applies to tutors exactly as to mentors."""
        res = self.client.post(self.status_url(self.tutor), {"action": "deactivate"}, format='json')
        self.assertEqual(res.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(res.data.get("error"), "HANDOVER_REQUIRED")
        self.tutor.refresh_from_db()
        self.assertIsNone(self.tutor.deactivated_at)
        self.assertTrue(self.tutor.is_active)

    def test_reassign_rejects_malformed_replacement_id(self):
        """A malformed body id must 400 (Hub parity: zod uuid), never 500."""
        res = self.client.post(self.reassign_url(self.mentor), {"new_mentor": "not-a-uuid"}, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        res = self.client.post(self.reassign_url(self.tutor), {"new_tutor": 42}, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_failed_handover_commits_nothing(self):
        """
        Hub parity: reassign_all_for_staff is all-or-nothing. When one staff
        user holds both roles' assignments and only the mentor replacement is
        valid, the whole handover must roll back — no half-moved students.
        """
        self.active_student.tutor = self.mentor
        self.active_student.save()
        self.scheduled_session.tutor = self.mentor
        self.scheduled_session.save()

        res = self.client.post(
            self.reassign_url(self.mentor),
            {"new_mentor": str(self.mentor2.id)},  # no new_tutor
            format='json'
        )
        self.assertEqual(res.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(res.data.get("error"), "INVALID_REPLACEMENT")

        self.active_student.refresh_from_db()
        self.scheduled_session.refresh_from_db()
        self.assertEqual(self.active_student.mentor, self.mentor)
        self.assertEqual(self.active_student.tutor, self.mentor)
        self.assertEqual(self.scheduled_session.tutor, self.mentor)

    def test_reassign_refuses_desynced_replacement(self):
        """A replacement whose lifecycle flags disagree is never assignable."""
        self.mentor2.is_active = False  # deactivated_at deliberately left NULL
        self.mentor2.save()
        res = self.client.post(
            self.reassign_url(self.mentor), {"new_mentor": str(self.mentor2.id)}, format='json'
        )
        self.assertEqual(res.status_code, status.HTTP_409_CONFLICT)


class LifecycleConsistencyTests(APITestCase):
    """
    The is_active <-> deactivated_at invariant survives every write path:
    the Django admin's is_active toggle and the migration backfill for rows
    disabled before soft-deactivation existed.
    """

    def test_user_admin_save_model_syncs_lifecycle_flags(self):
        from django.contrib.admin.sites import AdminSite
        from django.test import RequestFactory
        from accounts.admin import UserAdmin

        admin_user = User.objects.create_user(
            email="sync_admin@eduport.com", password="password",
            full_name="Sync Admin", role="ADMIN", is_staff=True, is_superuser=True
        )
        target = User.objects.create_user(
            email="sync_target@eduport.com", password="password",
            full_name="Sync Target", role="MENTOR"
        )
        model_admin = UserAdmin(User, AdminSite())
        request = RequestFactory().post('/admin/')
        request.user = admin_user

        target.is_active = False
        model_admin.save_model(request, target, form=None, change=True)
        target.refresh_from_db()
        self.assertFalse(target.is_active)
        self.assertIsNotNone(target.deactivated_at)
        self.assertEqual(target.deactivated_by, admin_user)
        self.assertEqual(target.deactivation_reason, 'Disabled via Django admin')

        target.is_active = True
        model_admin.save_model(request, target, form=None, change=True)
        target.refresh_from_db()
        self.assertTrue(target.is_active)
        self.assertIsNone(target.deactivated_at)
        self.assertIsNone(target.deactivated_by)
        self.assertIsNone(target.deactivation_reason)

    def test_backfill_marks_preexisting_disabled_users(self):
        import importlib
        from django.apps import apps as global_apps

        legacy = User.objects.create_user(
            email="legacy_disabled@eduport.com", password="password",
            full_name="Legacy Disabled", role="TUTOR", is_active=False
        )
        untouched = User.objects.create_user(
            email="legacy_active@eduport.com", password="password",
            full_name="Legacy Active", role="TUTOR"
        )
        self.assertIsNone(legacy.deactivated_at)

        migration = importlib.import_module('accounts.migrations.0002_user_soft_deactivation')
        migration.backfill_deactivated_at(global_apps, None)

        legacy.refresh_from_db()
        untouched.refresh_from_db()
        self.assertIsNotNone(legacy.deactivated_at)
        self.assertIn('Backfilled', legacy.deactivation_reason)
        self.assertIsNone(untouched.deactivated_at)
