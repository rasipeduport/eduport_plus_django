from django.urls import reverse
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APITestCase
from rest_framework import status
from unittest.mock import patch
from datetime import timedelta
from invitations.models import Invitation, InvitationStatusChoices, InvitationRoleChoices
from students.models import Student, StatusChoices
from sessions.models import Session, SessionStatusChoices
from activity.models import ActivityLog

User = get_user_model()


class GoogleAuthenticationTests(APITestCase):
    """
    Learn's Google sign-in (kept until Phase 7). The retired ``mock:`` credential
    is replaced by stubbing the token verification: ``google_login`` takes the
    same ``<label>:<email>:<name>:<picture>`` spec the fixtures always used and
    feeds those claims to the view as if Google had verified them.
    """

    def google_login(self, claims_spec):
        parts = claims_spec.split(":", 3)
        claims = {
            "email": parts[1],
            "name": parts[2] if len(parts) > 2 else parts[1].split("@")[0],
            "picture": parts[3] if len(parts) > 3 else None,
        }
        with patch('accounts.views.verify_google_token', return_value=claims):
            return self.client.post(self.login_url, {"credential": "stub-google-id-token"})

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
        response = self.google_login(mock_token)
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
        response = self.google_login(mock_token)
        
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data["error"], "ACCESS_RESTRICTED")
        
        # Verify no User profile was created
        self.assertFalse(User.objects.filter(email=email).exists())


    def test_login_first_time_student_onboards_and_creates_records(self):
        # 1. Login with whitelisted student email
        mock_token = f"mock:{self.student_email}:Jane Google Profile:https://lh3.googleusercontent.com/a"
        response = self.google_login(mock_token)
        
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
        log = ActivityLog.objects.filter(actor=user, action="user.onboarded").first()
        self.assertIsNotNone(log)
        self.assertEqual(log.entity_type, "profile")
        self.assertEqual(log.entity_id, str(user.id))
        self.assertEqual(log.student, student)

    def test_a_staff_invitation_is_not_redeemed_through_google(self):
        mock_token = f"mock:{self.mentor_email}:Mark Mentor:https://lh3.googleusercontent.com/b"
        response = self.google_login(mock_token)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data["error"], "GOOGLE_SIGN_IN_STUDENTS_ONLY")
        # Nothing provisioned or logged, the invitation still pending, no session.
        self.assertFalse(User.objects.filter(email=self.mentor_email).exists())
        self.mentor_invitation.refresh_from_db()
        self.assertEqual(self.mentor_invitation.status, InvitationStatusChoices.PENDING)
        self.assertFalse(ActivityLog.objects.filter(action="user.onboarded").exists())
        self.assertEqual(self.client.get(self.me_url).status_code, status.HTTP_403_FORBIDDEN)

    def test_staff_accounts_cannot_sign_in_with_google(self):
        # Every staff role, a superuser, and a student-role account holding the
        # Django-admin flag -- each with the invitation that once let it in.
        accounts = [
            self.test_mentor,
            self.test_tutor,
            User.objects.create_user(email="admin.ann@eduport.com", full_name="Admin Ann", role="ADMIN"),
            User.objects.create_superuser(
                username="root", email="root@eduport.com", full_name="Root", password="Root-Secret-Phrase-9"
            ),
            User.objects.create_user(email="odd.flag@gmail.com", full_name="Odd Flag", role="STUDENT", is_staff=True),
        ]
        for account in accounts:
            with self.subTest(email=account.email):
                Invitation.objects.create(
                    email=account.email, role=account.role, status=InvitationStatusChoices.ACCEPTED
                )
                response = self.google_login(f"mock:{account.email}:{account.full_name}:")
                self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
                self.assertEqual(response.data["error"], "GOOGLE_SIGN_IN_STUDENTS_ONLY")
                self.assertNotIn("_auth_user_id", self.client.session)
                self.assertEqual(self.client.get(self.me_url).status_code, status.HTTP_403_FORBIDDEN)
                refusal = ActivityLog.objects.get(action="user.sign_in_failed", actor=account)
                self.assertEqual(refusal.context["reason"], "google_staff_account")
        self.assertFalse(ActivityLog.objects.filter(action="user.sign_in").exists())

    def test_subsequent_login_direct_session(self):
        # Onboard first
        mock_token = f"mock:{self.student_email}:Jane Google:https://lh3.googleusercontent.com/a"
        self.google_login(mock_token)
        
        # Clear client session
        self.client.logout()

        # Login again
        response = self.google_login(mock_token)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "authenticated")
        self.assertFalse(response.data["is_new_user"])

        # Check ActivityLog for second login
        user = User.objects.get(email=self.student_email)
        login_log = ActivityLog.objects.filter(actor=user, action="user.sign_in").first()
        self.assertIsNotNone(login_log)

    def test_disabled_user_login_rejected(self):
        # Onboard first
        mock_token = f"mock:{self.student_email}:Jane Google:https://lh3.googleusercontent.com/a"
        self.google_login(mock_token)
        
        # Disable user
        user = User.objects.get(email=self.student_email)
        user.is_active = False
        user.save()

        # Attempt login again
        response = self.google_login(mock_token)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data["error"], "USER_DISABLED")

    def test_logout_clears_session(self):
        # Login student
        mock_token = f"mock:{self.student_email}:Jane Google:https://lh3.googleusercontent.com/a"
        self.google_login(mock_token)
        
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
        self.google_login(mock_token)

        response = self.client.get(self.me_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["user"]["email"], self.student_email)
        self.assertEqual(response.data["student_profile"]["student_code"], self.student_code)
        # Learn renders session times in the student's zone, so /me must carry it.
        self.assertIn("timezone", response.data["student_profile"])

    def test_me_carries_the_student_timezone(self):
        mock_token = f"mock:{self.student_email}:Jane Google:https://lh3.googleusercontent.com/a"
        self.google_login(mock_token)
        Student.objects.filter(student_code=self.student_code).update(timezone='Asia/Dubai')

        response = self.client.get(self.me_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["student_profile"]["timezone"], 'Asia/Dubai')
        self.assertEqual(response.data["student_profiles"][0]["timezone"], 'Asia/Dubai')

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

    # --- retired (D3): Team replaced the full staff records, the details edit
    # and the status endpoint. They answer 410 and log who called.

    RETIRED_CALLS = (
        ('get', '/api/admins/', None),
        ('get', '/api/mentors/?all=true', None),
        ('get', '/api/tutors/?all=true', None),
        ('patch', '/api/users/{mentor}/', {'full_name': 'Renamed Mentor'}),
        ('post', '/api/users/{tutor}/status/', {'action': 'deactivate'}),
    )

    def call_retired(self, method, url, body):
        url = url.format(mentor=self.mentor.id, tutor=self.tutor.id)
        if method == 'get':
            return url, self.client.get(url)
        return url, getattr(self.client, method)(url, body, format='json')

    def test_retired_staff_endpoints_answer_410_and_log_the_caller(self):
        for caller in (self.admin, self.mentor):
            self.client.force_authenticate(user=caller)
            for method, url, body in self.RETIRED_CALLS:
                with self.subTest(caller=caller.role, url=url):
                    with self.assertLogs('accounts.retired_endpoints', 'WARNING') as logs:
                        path, response = self.call_retired(method, url, body)
                    self.assertEqual(response.status_code, status.HTTP_410_GONE)
                    self.assertEqual(response.data['error'], 'ENDPOINT_RETIRED')
                    self.assertIn(path.split('?')[0], logs.output[0])
                    self.assertIn(str(caller.id), logs.output[0])

    def test_retired_endpoints_change_nothing(self):
        for method, url, body in self.RETIRED_CALLS:
            self.call_retired(method, url, body)
        self.mentor.refresh_from_db()
        self.tutor.refresh_from_db()
        self.assertEqual(self.mentor.full_name, 'Active Mentor')
        self.assertTrue(self.tutor.is_active)
        self.assertIsNone(self.tutor.deactivated_at)
        self.assertFalse(ActivityLog.objects.filter(action__in=('user.update_details', 'user.deactivate')).exists())

    def test_mentor_list_default_returns_only_active_retains_compat(self):
        response = self.client.get('/api/mentors/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mentors = response.data.get("mentors", [])
        
        emails = [m["email"] for m in mentors]
        self.assertIn("mentor@eduport.com", emails)
        self.assertNotIn("ghost_mentor@eduport.com", emails)

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
    The staff directory endpoints need accounts.view_staff_directory (every
    class-running staff role). They list colleagues, so students and roles
    without the permission do not reach them at all. The full-record mode is
    retired (D3): Team lists staff records.
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

    def test_roles_without_the_permission_cannot_read_directories(self):
        for role in ('BDE', 'SALES_TL'):
            account = User.objects.create_user(
                email=f"dir_{role.lower()}@eduport.com", password="password123", full_name=role, role=role
            )
            self.client.force_authenticate(user=account)
            for url in (self.MENTORS_URL, self.TUTORS_URL):
                with self.subTest(role=role, url=url):
                    self.assertEqual(self.client.get(url).status_code, status.HTTP_403_FORBIDDEN)

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


class StaffLifecycleTests(APITestCase):
    """
    The staff-exit handover (parity with the Hub's user-exit flow): the bulk
    reassign that re-points a departing mentor's or tutor's ACTIVE students and
    their open scheduled sessions, and what deactivation then does to the
    assignment dropdowns. Deactivation and reactivation themselves are Team's
    endpoints, tested in accounts.tests_team.TeamStatusTests.
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

    def deactivate(self, user, **body):
        return self.client.post(f'/api/team/{user.id}/deactivate/', body, format='json')

    def reassign_url(self, user):
        return f'/api/users/{user.id}/reassign/'

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
        res = self.deactivate(self.tutor)
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        log = ActivityLog.objects.filter(action='staff.reassign_all', entity_id=str(self.tutor.id)).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.entity_type, 'profile')
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

    def test_deactivated_tutor_hidden_from_dropdown_but_in_team_records(self):
        self.deactivate(self.tutor2)

        slim = self.client.get('/api/tutors/')
        slim_emails = [t["email"] for t in slim.data["tutors"]]
        self.assertNotIn("lc_tutor2@eduport.com", slim_emails)

        team = self.client.get('/api/team/', {"role": "TUTOR"})
        rows = {t["email"]: t for t in team.data}
        self.assertIn("lc_tutor2@eduport.com", rows)
        self.assertIsNotNone(rows["lc_tutor2@eduport.com"]["deactivated_at"])

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
