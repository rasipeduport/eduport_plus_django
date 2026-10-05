import datetime as dt
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone as dj_timezone
from rest_framework.test import APITestCase
from rest_framework import status
from students.models import Student
from invitations.models import Invitation, InvitationStatusChoices, InvitationRoleChoices

User = get_user_model()

class DashboardAPITests(APITestCase):
    def setUp(self):
        # Create different role users
        self.admin = User.objects.create_user(
            email="admin@eduport.com",
            password="password",
            full_name="Admin User",
            role="ADMIN"
        )
        self.mentor = User.objects.create_user(
            email="mentor@eduport.com",
            password="password",
            full_name="Mentor User",
            role="MENTOR"
        )
        self.tutor = User.objects.create_user(
            email="tutor@eduport.com",
            password="password",
            full_name="Tutor User",
            role="TUTOR"
        )
        self.student_user = User.objects.create_user(
            email="student@eduport.com",
            password="password",
            full_name="Student User",
            role="STUDENT"
        )

        # Create a Student record associated with student_user
        self.student = Student.objects.create(
            profile=self.student_user,
            student_code="EDP00009",
            full_name="Student User",
            mentor=self.mentor,
            tutor=self.tutor,
            total_class_quota=15,
            meet_link="https://meet.google.com/abc-defg-hij"
        )

        # Create a pending student invitation for stats check
        self.invitation = Invitation.objects.create(
            email="invited@gmail.com",
            role=InvitationRoleChoices.STUDENT,
            status=InvitationStatusChoices.PENDING,
            extra_data={"student_code": "EDP00010"}
        )

        self.stats_url = reverse('staff-dashboard-stats')
        self.student_db_url = reverse('student-dashboard')
        self.mentor_list_url = reverse('mentor-list')
        self.tutor_list_url = reverse('tutor-list')

    def test_stats_accessible_by_staff_only(self):
        # Unauthenticated
        response = self.client.get(self.stats_url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        # Student user (forbidden)
        self.client.force_authenticate(user=self.student_user)
        response = self.client.get(self.stats_url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        # Tutor user
        self.client.force_authenticate(user=self.tutor)
        response = self.client.get(self.stats_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["students"], 1)
        self.assertEqual(response.data["mentors"], 1)
        self.assertEqual(response.data["tutors"], 1)
        self.assertEqual(response.data["pending_invitations"], 1)

        # Mentor user
        self.client.force_authenticate(user=self.mentor)
        response = self.client.get(self.stats_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Admin user
        self.client.force_authenticate(user=self.admin)
        response = self.client.get(self.stats_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_student_dashboard_accessible_by_student_only(self):
        # Unauthenticated
        response = self.client.get(self.student_db_url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        # Admin user (forbidden)
        self.client.force_authenticate(user=self.admin)
        response = self.client.get(self.student_db_url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        # Student user
        self.client.force_authenticate(user=self.student_user)
        response = self.client.get(self.student_db_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["student_name"], "Student User")
        self.assertEqual(response.data["mentor"], "Mentor User")
        self.assertEqual(response.data["tutor"], "Tutor User")
        self.assertEqual(response.data["quota"], 15)
        self.assertEqual(response.data["meet_link"], "https://meet.google.com/abc-defg-hij")

    def test_mentor_and_tutor_lists(self):
        self.client.force_authenticate(user=self.admin)

        # Mentors list
        response = self.client.get(self.mentor_list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["mentors"]), 1)
        self.assertEqual(response.data["mentors"][0]["full_name"], "Mentor User")

        # Tutors list
        response = self.client.get(self.tutor_list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["tutors"]), 1)
        self.assertEqual(response.data["tutors"][0]["full_name"], "Tutor User")

    def test_student_list_and_update(self):
        # Authenticate as admin
        self.client.force_authenticate(user=self.admin)
        
        # Test student list (GET /api/students/)
        url = reverse('students:student-list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["student_code"], "EDP00009")
        
        # Test student update (PUT /api/students/). total_class_quota is
        # deliberately absent: it is sheet-synced and refused here (covered by
        # QuotaIsReadOnlyOverTheApiTests below).
        payload = {
            "id": str(self.student.id),
            "meet_link": "https://meet.google.com/xxx-yyyy-zzz",
            "status": "INACTIVE",
            "status_note": "A temporary pause"
        }
        response = self.client.put(url, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Verify database reflects updates
        self.student.refresh_from_db()
        self.assertEqual(self.student.meet_link, "https://meet.google.com/xxx-yyyy-zzz")
        self.assertEqual(self.student.status, "INACTIVE")
        self.assertEqual(self.student.status_note, "A temporary pause")
        # Untouched by the PUT -- only the sheet sync writes it.
        self.assertEqual(self.student.total_class_quota, 15)



class ExpiredStudentLockoutTests(APITestCase):
    """
    Only 'EXPIRED' is the terminal lockout (Hub parity): an expired persona
    cannot be selected or act anywhere, but is still returned by /me (so the
    Learn app can render "access ended" instead of the waiting room), and
    staff keep read access to it. 'INACTIVE' keeps full access.
    """

    def setUp(self):
        from datetime import timedelta
        from django.utils import timezone
        from sessions.models import Session, SessionStatusChoices

        self.mentor = User.objects.create_user(
            email="exp_mentor@eduport.com", password="password",
            full_name="Exp Mentor", role="MENTOR"
        )
        self.tutor = User.objects.create_user(
            email="exp_tutor@eduport.com", password="password",
            full_name="Exp Tutor", role="TUTOR"
        )
        self.parent = User.objects.create_user(
            email="exp_parent@eduport.com", password="password",
            full_name="Exp Parent", role="STUDENT"
        )
        self.expired_child = Student.objects.create(
            profile=self.parent, student_code="EXP001",
            full_name="Expired Child", mentor=self.mentor, tutor=self.tutor,
            status="EXPIRED", status_note="Course ended"
        )

        past = timezone.now() - timedelta(days=1)
        self.expired_session = Session.objects.create(
            student=self.expired_child, tutor=self.tutor,
            start_time=past, end_time=past + timedelta(hours=1),
            title="Old Class", status=SessionStatusChoices.ATTENDED
        )

        self.dashboard_url = reverse('student-dashboard')
        self.sessions_url = reverse('sessions:sessions-list-create-update')
        self.select_url = reverse('accounts:select-student')
        self.me_url = reverse('accounts:me')

    def add_active_child(self):
        return Student.objects.create(
            profile=self.parent, student_code="EXP002",
            full_name="Active Child", mentor=self.mentor, tutor=self.tutor,
            status="ACTIVE"
        )

    def test_sole_expired_child_dashboard_is_access_ended(self):
        self.client.force_authenticate(user=self.parent)
        res = self.client.get(self.dashboard_url)
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(res.data.get("error"), "STUDENT_ACCESS_ENDED")

    def test_expired_child_sessions_are_hidden(self):
        self.client.force_authenticate(user=self.parent)
        res = self.client.get(self.sessions_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data.get("sessions"), [])

    def test_expired_child_cannot_rate_sessions(self):
        self.client.force_authenticate(user=self.parent)
        res = self.client.put(
            self.sessions_url,
            {"id": str(self.expired_session.id), "rating": 5},
            format='json'
        )
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        self.expired_session.refresh_from_db()
        self.assertIsNone(self.expired_session.rating)

    def test_selecting_expired_child_is_refused(self):
        self.client.force_authenticate(user=self.parent)
        res = self.client.post(self.select_url, {"student_id": str(self.expired_child.id)}, format='json')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(res.data.get("error"), "STUDENT_ACCESS_ENDED")

    def test_selecting_unlinked_student_is_still_404(self):
        import uuid as uuid_mod
        self.client.force_authenticate(user=self.parent)
        res = self.client.post(self.select_url, {"student_id": str(uuid_mod.uuid4())}, format='json')
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_me_still_returns_expired_persona_with_status(self):
        """The frontend needs the expired persona to render "access ended"."""
        self.client.force_authenticate(user=self.parent)
        res = self.client.get(self.me_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        profiles = res.data.get("student_profiles", [])
        self.assertEqual(len(profiles), 1)
        self.assertEqual(profiles[0]["status"], "EXPIRED")
        # ...but it is never auto-selected.
        self.assertIsNone(res.data.get("student_profile"))

    def test_active_sibling_is_auto_selected_over_expired(self):
        """
        With one usable persona left, it is auto-selected even when the cookie
        still points at the expired one (mirrors the Learn layout's
        usable-personas handling).
        """
        active = self.add_active_child()
        self.client.force_authenticate(user=self.parent)
        self.client.cookies['ep-student-id'] = str(self.expired_child.id)
        res = self.client.get(self.dashboard_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data.get("student_name"), active.full_name)

    def test_inactive_child_keeps_full_access(self):
        """'INACTIVE' is a soft pause, not a lockout (Hub parity)."""
        self.expired_child.status = "INACTIVE"
        self.expired_child.save()
        self.client.force_authenticate(user=self.parent)
        res = self.client.get(self.dashboard_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)

    def test_mentor_still_reads_expired_student(self):
        """Staff read access to an expired student's record is unchanged."""
        self.client.force_authenticate(user=self.mentor)
        res = self.client.get('/api/students/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        codes = [s["student_code"] for s in res.data]
        self.assertIn("EXP001", codes)

    def test_tutor_list_still_excludes_expired_student(self):
        self.client.force_authenticate(user=self.tutor)
        res = self.client.get('/api/students/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        codes = [s["student_code"] for s in res.data]
        self.assertNotIn("EXP001", codes)


class StudentStatusNoteTests(APITestCase):
    """
    Marking a student inactive/expired requires a note; returning them to
    active clears it — enforced server-side (Hub parity), not just in the SPA.
    """

    def setUp(self):
        self.admin = User.objects.create_user(
            email="note_admin@eduport.com", password="password",
            full_name="Note Admin", role="ADMIN"
        )
        self.student = Student.objects.create(
            student_code="NOTE001", full_name="Note Student",
            profile=User.objects.create_user(
                email="note_student@eduport.com", password="password",
                full_name="Note Student", role="STUDENT"
            ),
            status="ACTIVE"
        )
        self.url = '/api/students/'
        self.client.force_authenticate(user=self.admin)

    def test_note_required_for_inactive_and_expired(self):
        for target_status in ("inactive", "expired"):
            for note in (None, "", "   "):
                with self.subTest(status=target_status, note=note):
                    payload = {"id": str(self.student.id), "status": target_status}
                    if note is not None:
                        payload["status_note"] = note
                    res = self.client.put(self.url, payload, format='json')
                    self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
                    self.student.refresh_from_db()
                    self.assertEqual(self.student.status, "ACTIVE")

    def test_note_trimmed_and_saved(self):
        res = self.client.put(
            self.url,
            {"id": str(self.student.id), "status": "expired", "status_note": "  Course completed  "},
            format='json'
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.student.refresh_from_db()
        self.assertEqual(self.student.status, "EXPIRED")
        self.assertEqual(self.student.status_note, "Course completed")

    def test_note_cleared_when_returned_to_active(self):
        self.student.status = "INACTIVE"
        self.student.status_note = "Paused for exams"
        self.student.save()
        res = self.client.put(
            self.url,
            {"id": str(self.student.id), "status": "active"},
            format='json'
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.student.refresh_from_db()
        self.assertEqual(self.student.status, "ACTIVE")
        self.assertIsNone(self.student.status_note)


class StudentActionsAPITests(APITestCase):
    """
    The Hub Actions menu items that got a Django backend in this pass:
    Edit Profile (PUT profile fields), Reassign Mentor / Tutor and Delete
    permanently. Existing meet-link / quota / status behaviour is covered above.
    """

    def setUp(self):
        from datetime import timedelta
        from django.utils import timezone
        from sessions.models import Session, SessionStatusChoices

        def staff(email, name, role, **extra):
            return User.objects.create_user(email=email, password="password", full_name=name, role=role, **extra)

        self.admin = staff("act_admin@eduport.com", "Act Admin", "ADMIN")
        self.mentor = staff("act_mentor1@eduport.com", "Mentor One", "MENTOR")
        self.mentor2 = staff("act_mentor2@eduport.com", "Mentor Two", "MENTOR")
        self.tutor = staff("act_tutor1@eduport.com", "Tutor One", "TUTOR")
        self.tutor2 = staff("act_tutor2@eduport.com", "Tutor Two", "TUTOR")
        self.gone_tutor = staff("act_tutor3@eduport.com", "Tutor Gone", "TUTOR", is_active=False)
        self.gone_tutor.deactivated_at = timezone.now()
        self.gone_tutor.save(update_fields=['deactivated_at'])
        self.parent = staff("act_parent@eduport.com", "Act Parent", "STUDENT")

        self.student = Student.objects.create(
            profile=self.parent, student_code="ACT001", full_name="Act Student",
            mentor=self.mentor, tutor=self.tutor, school_name="Old School",
        )
        now = timezone.now()
        self.scheduled = Session.objects.create(
            student=self.student, tutor=self.tutor, title="Upcoming",
            start_time=now + timedelta(days=1), end_time=now + timedelta(days=1, hours=1),
            status=SessionStatusChoices.SCHEDULED,
        )
        self.attended = Session.objects.create(
            student=self.student, tutor=self.tutor, title="Done",
            start_time=now - timedelta(days=1), end_time=now - timedelta(days=1) + timedelta(hours=1),
            status=SessionStatusChoices.ATTENDED,
        )

        self.list_url = reverse('students:student-list')
        self.reassign_url = reverse('students:student-reassign')
        self.detail_url = reverse('students:student-detail', kwargs={'pk': self.student.id})

    # ---- Edit Profile -----------------------------------------------------

    def test_edit_profile_updates_fields_and_logs(self):
        from activity.models import ActivityLog
        self.client.force_authenticate(user=self.admin)
        response = self.client.put(self.list_url, {
            "id": str(self.student.id),
            "full_name": "  Renamed Student ",
            "school_name": "New School",
            "grade": "10",
            "admission_date": "2024-06-01",
            "remarks_for_mentor": "Prefers evenings",
            "country": "",
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)

        self.student.refresh_from_db()
        self.assertEqual(self.student.full_name, "Renamed Student")
        self.assertEqual(self.student.school_name, "New School")
        self.assertEqual(self.student.grade, "10")
        self.assertEqual(self.student.admission_date.isoformat(), "2024-06-01")
        self.assertEqual(self.student.remarks_for_mentor, "Prefers evenings")
        self.assertIsNone(self.student.country)

        log = ActivityLog.objects.filter(action='student.update_details', student=self.student).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.changes["full_name"], {"old": "Act Student", "new": "Renamed Student"})
        self.assertEqual(log.changes["school_name"], {"old": "Old School", "new": "New School"})
        self.assertEqual(log.changes["admission_date"], {"old": None, "new": "2024-06-01"})
        # A blank value on an already-empty column is not a change.
        self.assertNotIn("country", log.changes)

    def test_edit_profile_validation(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.put(self.list_url, {"id": str(self.student.id), "full_name": "  "}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        response = self.client.put(self.list_url, {"id": str(self.student.id), "admission_date": "01/06/2024"}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        # The enrolment key is not editable through the profile sheet.
        response = self.client.put(self.list_url, {"id": str(self.student.id), "student_code": "HACK01"}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.student.refresh_from_db()
        self.assertEqual(self.student.full_name, "Act Student")
        self.assertEqual(self.student.student_code, "ACT001")

    def test_edit_profile_mentor_scoping(self):
        payload = {"id": str(self.student.id), "school_name": "Mentor School"}
        self.client.force_authenticate(user=self.mentor2)
        response = self.client.put(self.list_url, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        self.client.force_authenticate(user=self.mentor)
        response = self.client.put(self.list_url, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.student.refresh_from_db()
        self.assertEqual(self.student.school_name, "Mentor School")

    # ---- Reassign Mentor / Tutor ------------------------------------------

    def test_reassign_is_admin_only(self):
        self.client.force_authenticate(user=self.mentor)
        response = self.client.post(self.reassign_url, {
            "id": str(self.student.id), "mentor": str(self.mentor2.id), "tutor": str(self.tutor.id)
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_reassign_moves_only_scheduled_sessions(self):
        from activity.models import ActivityLog
        self.client.force_authenticate(user=self.admin)
        response = self.client.post(self.reassign_url, {
            "id": str(self.student.id), "mentor": str(self.mentor2.id), "tutor": str(self.tutor2.id)
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data["result"]["sessions_repointed"], 1)

        self.student.refresh_from_db()
        self.scheduled.refresh_from_db()
        self.attended.refresh_from_db()
        self.assertEqual(self.student.mentor, self.mentor2)
        self.assertEqual(self.student.tutor, self.tutor2)
        self.assertEqual(self.scheduled.tutor, self.tutor2)
        # History keeps the staff member who actually taught it.
        self.assertEqual(self.attended.tutor, self.tutor)

        mentor_log = ActivityLog.objects.get(action='student.reassign_mentor', student=self.student)
        self.assertEqual(mentor_log.changes["mentor"], {"old": "Mentor One", "new": "Mentor Two"})
        tutor_log = ActivityLog.objects.get(action='student.reassign_tutor', student=self.student)
        self.assertEqual(tutor_log.changes["tutor"], {"old": "Tutor One", "new": "Tutor Two"})
        self.assertEqual(tutor_log.context["sessions_repointed"], 1)

    def test_reassign_rejects_wrong_role_or_deactivated_staff(self):
        self.client.force_authenticate(user=self.admin)
        # A mentor in the tutor slot
        response = self.client.post(self.reassign_url, {
            "id": str(self.student.id), "mentor": str(self.mentor.id), "tutor": str(self.mentor2.id)
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        # A deactivated tutor
        response = self.client.post(self.reassign_url, {
            "id": str(self.student.id), "mentor": str(self.mentor.id), "tutor": str(self.gone_tutor.id)
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        # Garbage id
        response = self.client.post(self.reassign_url, {
            "id": str(self.student.id), "mentor": "not-a-uuid", "tutor": None
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        self.student.refresh_from_db()
        self.scheduled.refresh_from_db()
        self.assertEqual(self.student.tutor, self.tutor)
        self.assertEqual(self.scheduled.tutor, self.tutor)

    def test_reassign_unchanged_and_unassign(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.post(self.reassign_url, {
            "id": str(self.student.id), "mentor": str(self.mentor.id), "tutor": str(self.tutor.id)
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data.get("unchanged"))

        response = self.client.post(self.reassign_url, {
            "id": str(self.student.id), "mentor": None, "tutor": None
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.student.refresh_from_db()
        self.scheduled.refresh_from_db()
        self.assertIsNone(self.student.mentor)
        self.assertIsNone(self.student.tutor)
        self.assertIsNone(self.scheduled.tutor)

    # ---- Delete permanently ----------------------------------------------

    def test_purge_is_admin_only(self):
        self.client.force_authenticate(user=self.mentor)
        response = self.client.delete(self.detail_url, {"confirm_code": "ACT001"}, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(Student.objects.filter(pk=self.student.pk).exists())

    def test_purge_requires_matching_code(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.delete(self.detail_url, {}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        response = self.client.delete(self.detail_url, {"confirm_code": "WRONG"}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue(Student.objects.filter(pk=self.student.pk).exists())

    def test_purge_refuses_student_with_history(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.delete(self.detail_url, {"confirm_code": " ACT001 "}, format='json')
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertTrue(Student.objects.filter(pk=self.student.pk).exists())

    def test_purge_deletes_student_without_history_and_logs(self):
        from activity.models import ActivityLog
        fresh = Student.objects.create(
            profile=self.parent, student_code="ACT002", full_name="Mistake Student",
            mentor=self.mentor, tutor=self.tutor,
        )
        url = reverse('students:student-detail', kwargs={'pk': fresh.id})
        self.client.force_authenticate(user=self.admin)
        response = self.client.delete(url, {"confirm_code": "ACT002"}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)

        self.assertFalse(Student.objects.filter(pk=fresh.pk).exists())
        # The sign-in account and the sibling student are untouched.
        self.assertTrue(User.objects.filter(pk=self.parent.pk).exists())
        self.assertTrue(Student.objects.filter(pk=self.student.pk).exists())

        log = ActivityLog.objects.get(action='student.purge', entity_id=str(fresh.id))
        self.assertEqual(log.student_id, fresh.id)
        self.assertEqual(log.changes["student"]["old"], "Mistake Student (ACT002)")
        self.assertEqual(log.context["student_code"], "ACT002")

        # Its history is still readable by id after the row is gone.
        history = self.client.get(reverse('activity:activity-logs-list'), {"student_id": str(fresh.id)})
        self.assertEqual(history.status_code, status.HTTP_200_OK)
        self.assertEqual(history.data["results"][0]["action"], 'student.purge')
        self.assertIsNone(history.data["results"][0]["student_name"])


class StudentTimezoneTests(APITestCase):
    """
    The "New Session" sheet writes the zone it schedules in back to the
    student. PUT /api/students/ validates it against the zone database, blank
    clears it, and each change is logged as student.update_timezone.
    """

    def setUp(self):
        self.admin = User.objects.create_user(
            email="tz_admin@eduport.com", password="password", full_name="Tz Admin", role="ADMIN"
        )
        self.student = Student.objects.create(
            student_code="TZ001", full_name="Tz Student",
            profile=User.objects.create_user(
                email="tz_student@eduport.com", password="password", full_name="Tz Student", role="STUDENT"
            ),
        )
        self.url = reverse('students:student-list')
        self.client.force_authenticate(user=self.admin)

    def put(self, **fields):
        return self.client.put(self.url, {"id": str(self.student.id), **fields}, format='json')

    def test_list_exposes_raw_timezone(self):
        res = self.client.get(self.url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIsNone(res.data[0]["timezone"])

        self.student.timezone = "Asia/Dubai"
        self.student.save()
        res = self.client.get(self.url)
        self.assertEqual(res.data[0]["timezone"], "Asia/Dubai")

    def test_set_timezone_is_validated_and_logged(self):
        from activity.models import ActivityLog
        res = self.put(timezone=" Asia/Dubai ")
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
        self.student.refresh_from_db()
        self.assertEqual(self.student.timezone, "Asia/Dubai")
        log = ActivityLog.objects.filter(action='student.update_timezone', student=self.student).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.changes["timezone"], {"old": None, "new": "Asia/Dubai"})

        # Re-sending the same zone is not a change and logs nothing new.
        res = self.put(timezone="Asia/Dubai")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(ActivityLog.objects.filter(action='student.update_timezone', student=self.student).count(), 1)

    def test_unknown_timezone_is_rejected(self):
        for bad in ("Mars/Olympus_Mons", 123, ["Asia/Dubai"]):
            with self.subTest(value=bad):
                res = self.put(timezone=bad)
                self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertEqual(res.data["error"], "INVALID_TIMEZONE")
        self.student.refresh_from_db()
        self.assertIsNone(self.student.timezone)

    def test_blank_clears_timezone(self):
        self.student.timezone = "Asia/Dubai"
        self.student.save()
        res = self.put(timezone=None)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.student.refresh_from_db()
        self.assertIsNone(self.student.timezone)


class StudentProfileAPITests(APITestCase):
    """GET /api/students/<id>/profile/ — the Hub student profile's header and Overview."""

    def setUp(self):
        from django.utils import timezone as dj_timezone
        import datetime as dt

        self.admin = User.objects.create_user(
            email="profile-admin@eduport.com", password="pw", full_name="Admin", role="ADMIN")
        self.mentor = User.objects.create_user(
            email="profile-mentor@eduport.com", password="pw", full_name="Mentor One", role="MENTOR")
        self.other_mentor = User.objects.create_user(
            email="profile-mentor2@eduport.com", password="pw", full_name="Mentor Two", role="MENTOR")
        self.tutor = User.objects.create_user(
            email="profile-tutor@eduport.com", password="pw", full_name="Tutor One", role="TUTOR")
        self.other_tutor = User.objects.create_user(
            email="profile-tutor2@eduport.com", password="pw", full_name="Tutor Two", role="TUTOR")
        self.parent = User.objects.create_user(
            email="profile-parent@eduport.com", password="pw", full_name="Parent", role="STUDENT")

        self.student = Student.objects.create(
            profile=self.parent,
            student_code="EDP00100",
            full_name="Profile Student",
            mobile_number="+971500000000",
            country="UAE",
            state="Dubai",
            school_name="Test School",
            grade="10",
            syllabus="CBSE",
            mentor=self.mentor,
            tutor=self.tutor,
            total_class_quota=10,
        )
        self.url = reverse('students:student-profile', args=[self.student.id])

        # Two attended classes (2h), one upcoming scheduled (1h), one cancelled
        # (never counted against quota).
        from sessions.models import Session
        now = dj_timezone.now()
        self.attended = Session.objects.create(
            student=self.student, title="Past One", tutor=self.tutor,
            start_time=now - dt.timedelta(days=3), end_time=now - dt.timedelta(days=3, hours=-1),
            status='ATTENDED', notes_link="https://notes.example/1",
            recording_link="https://rec.example/1", homework_link="https://hw.example/1",
        )
        # Attended but missing content -> "pending" in the derived counters.
        Session.objects.create(
            student=self.student, title="Past Two", tutor=self.tutor,
            start_time=now - dt.timedelta(days=2), end_time=now - dt.timedelta(days=2, hours=-1),
            status='ATTENDED', notes_link="https://notes.example/2",
        )
        self.upcoming = Session.objects.create(
            student=self.student, title="Next One", tutor=self.tutor,
            start_time=now + dt.timedelta(days=2), end_time=now + dt.timedelta(days=2, hours=1),
            status='SCHEDULED',
        )
        Session.objects.create(
            student=self.student, title="Dropped", tutor=self.tutor,
            start_time=now + dt.timedelta(days=4), end_time=now + dt.timedelta(days=4, hours=2),
            status='CANCELLED', cancellation_reason="Student travelling",
        )

        from exams.models import Exam
        Exam.objects.create(
            student=self.student, mentor=self.mentor, chapter_name="Algebra",
            start_time=now - dt.timedelta(days=5), end_time=now - dt.timedelta(days=5, hours=-1),
            status='ATTENDED', score=8, max_score=10,
        )
        Exam.objects.create(
            student=self.student, mentor=self.mentor, chapter_name="Geometry",
            start_time=now + dt.timedelta(days=6), end_time=now + dt.timedelta(days=6, hours=1),
            status='SCHEDULED',
        )

    def test_admin_sees_every_field_and_the_counters(self):
        self.client.force_authenticate(user=self.admin)
        res = self.client.get(self.url)
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)

        student = res.data["student"]
        self.assertEqual(student["student_code"], "EDP00100")
        self.assertEqual(student["state"], "Dubai")
        self.assertEqual(student["profile"]["email"], "profile-parent@eduport.com")
        self.assertEqual(student["mentor_profile"]["full_name"], "Mentor One")
        self.assertEqual(student["tutor_profile"]["full_name"], "Tutor One")

        stats = res.data["stats"]
        # 3 non-cancelled classes of one hour each.
        self.assertEqual(stats["quota"], {"purchased": 10, "used_hours": 3.0, "remaining_hours": 7.0})
        self.assertEqual(stats["sessions"]["total"], 4)
        self.assertEqual(stats["sessions"]["attended"], 2)
        self.assertEqual(stats["sessions"]["scheduled"], 1)
        self.assertEqual(stats["sessions"]["cancelled"], 1)
        self.assertEqual(stats["sessions"]["upcoming"], 1)
        # One attended class is still missing its recording and homework.
        self.assertEqual(stats["sessions"]["pending"], 1)
        self.assertEqual(stats["exams"]["chapter"]["attended"], 1)
        self.assertEqual(stats["exams"]["chapter"]["scored"], 1)
        self.assertEqual(stats["exams"]["chapter"]["average_pct"], 80.0)
        self.assertEqual(stats["homework"]["total"], 0)

        highlights = res.data["highlights"]
        self.assertEqual(highlights["next_session"]["title"], "Next One")
        self.assertEqual(highlights["last_session"]["title"], "Past Two")
        self.assertEqual(highlights["next_exam"]["chapter_name"], "Geometry")

    def test_mentor_opens_own_student_with_the_full_row(self):
        """
        A mentor's payload stays exactly the list endpoint's row: their view
        hides email and state the way their columns do, but "Edit Profile"
        posts back every field it is handed, so the payload must be complete.
        """
        self.client.force_authenticate(user=self.mentor)
        res = self.client.get(self.url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        student = res.data["student"]
        self.assertEqual(student["state"], "Dubai")
        self.assertEqual(student["profile"]["email"], "profile-parent@eduport.com")
        self.assertEqual(student["mobile_number"], "+971500000000")
        self.assertIn("quota", res.data["stats"])
        self.assertIsNotNone(res.data["stats"]["exams"])

    def test_other_mentor_gets_404(self):
        self.client.force_authenticate(user=self.other_mentor)
        res = self.client.get(self.url)
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_tutor_gets_the_narrow_profile_and_no_exams(self):
        self.client.force_authenticate(user=self.tutor)
        res = self.client.get(self.url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        student = res.data["student"]
        self.assertEqual(student["full_name"], "Profile Student")
        self.assertEqual(student["grade"], "10")
        for withheld in ("mobile_number", "country", "state", "school_name",
                         "total_class_quota", "remarks_for_mentor", "admission_date"):
            self.assertNotIn(withheld, student)
        self.assertNotIn("email", student["profile"])
        # No quota block, and exams read as "no access" rather than "none".
        self.assertNotIn("quota", res.data["stats"])
        self.assertIsNone(res.data["stats"]["exams"])
        self.assertIsNone(res.data["highlights"]["next_exam"])

    def test_other_tutor_and_expired_student_get_404(self):
        self.client.force_authenticate(user=self.other_tutor)
        self.assertEqual(self.client.get(self.url).status_code, status.HTTP_404_NOT_FOUND)

        # A tutor's list is limited to active/inactive students; the profile
        # follows the same rule.
        self.student.status = 'EXPIRED'
        self.student.status_note = "Course finished"
        self.student.save()
        self.client.force_authenticate(user=self.tutor)
        self.assertEqual(self.client.get(self.url).status_code, status.HTTP_404_NOT_FOUND)
        # The admin can still open them.
        self.client.force_authenticate(user=self.admin)
        self.assertEqual(self.client.get(self.url).status_code, status.HTTP_200_OK)

    def test_students_and_anonymous_are_refused(self):
        res = self.client.get(self.url)
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        self.client.force_authenticate(user=self.parent)
        res = self.client.get(self.url)
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_unknown_student_is_404(self):
        import uuid as _uuid
        self.client.force_authenticate(user=self.admin)
        res = self.client.get(reverse('students:student-profile', args=[_uuid.uuid4()]))
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_sessions_list_filters_by_student(self):
        """The profile's Sessions tab reads ?student_id= on the sessions list."""
        other_student = Student.objects.create(
            profile=self.parent, student_code="EDP00101", full_name="Someone Else",
            mentor=self.mentor, tutor=self.tutor, total_class_quota=5,
        )
        from sessions.models import Session
        from django.utils import timezone as dj_timezone
        import datetime as dt
        Session.objects.create(
            student=other_student, title="Not Mine", tutor=self.tutor,
            start_time=dj_timezone.now() + dt.timedelta(days=1),
            end_time=dj_timezone.now() + dt.timedelta(days=1, hours=1),
        )

        self.client.force_authenticate(user=self.admin)
        res = self.client.get('/api/sessions/', {"student_id": str(self.student.id)})
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res.data["sessions"]), 4)
        self.assertNotIn("Not Mine", [s["title"] for s in res.data["sessions"]])

        res = self.client.get('/api/sessions/', {"student_id": "not-a-uuid"})
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)


class StudentNoteAPITests(APITestCase):
    """The profile's Notes tab: internal, staff-only, Hub-only."""

    def setUp(self):
        self.admin = User.objects.create_user(
            email="note-admin@eduport.com", password="pw", full_name="Admin", role="ADMIN")
        self.mentor = User.objects.create_user(
            email="note-mentor@eduport.com", password="pw", full_name="Mentor One", role="MENTOR")
        self.other_mentor = User.objects.create_user(
            email="note-mentor2@eduport.com", password="pw", full_name="Mentor Two", role="MENTOR")
        self.tutor = User.objects.create_user(
            email="note-tutor@eduport.com", password="pw", full_name="Tutor One", role="TUTOR")
        self.parent = User.objects.create_user(
            email="note-parent@eduport.com", password="pw", full_name="Parent", role="STUDENT")
        self.student = Student.objects.create(
            profile=self.parent, student_code="EDP00200", full_name="Noted Student",
            mentor=self.mentor, tutor=self.tutor, total_class_quota=8,
        )
        self.list_url = reverse('students:student-notes', args=[self.student.id])

    def _detail_url(self, note_id):
        return reverse('students:student-note-detail', args=[note_id])

    def _add(self, user, body="Needs extra attention on algebra."):
        self.client.force_authenticate(user=user)
        return self.client.post(self.list_url, {"body": body}, format='json')

    def test_every_staff_role_can_add_and_read(self):
        from activity.models import ActivityLog
        from students.models import StudentNote

        for user, role in ((self.admin, 'ADMIN'), (self.mentor, 'MENTOR'), (self.tutor, 'TUTOR')):
            with self.subTest(role=role):
                res = self._add(user, f"Note from {role}")
                self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.data)
                self.assertEqual(res.data["note"]["author_role"], role)
                self.assertEqual(res.data["note"]["author_name"], user.full_name)
                self.assertTrue(res.data["note"]["can_edit"])

        self.assertEqual(StudentNote.objects.filter(student=self.student).count(), 3)
        res = self.client.get(self.list_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        # Newest first.
        self.assertEqual([n["author_role"] for n in res.data["notes"]], ['TUTOR', 'MENTOR', 'ADMIN'])
        self.assertEqual(ActivityLog.objects.filter(action='student.note_add').count(), 3)

    def test_blank_and_overlong_notes_are_rejected(self):
        for bad in ("", "   ", None, 42, "x" * 4001):
            with self.subTest(value=bad):
                res = self._add(self.admin, bad)
                self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        from students.models import StudentNote
        self.assertEqual(StudentNote.objects.count(), 0)

    def test_only_the_author_can_edit(self):
        from activity.models import ActivityLog
        note_id = self._add(self.mentor, "First draft").data["note"]["id"]

        self.client.force_authenticate(user=self.admin)
        res = self.client.patch(self._detail_url(note_id), {"body": "Rewritten"}, format='json')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

        self.client.force_authenticate(user=self.mentor)
        res = self.client.patch(self._detail_url(note_id), {"body": "Second draft"}, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["note"]["body"], "Second draft")
        self.assertIsNotNone(res.data["note"]["edited_at"])
        log = ActivityLog.objects.filter(action='student.note_update').first()
        self.assertEqual(log.changes["note"], {"old": "First draft", "new": "Second draft"})

    def test_author_or_admin_can_delete(self):
        from students.models import StudentNote

        mentor_note = self._add(self.mentor, "Mentor's note").data["note"]["id"]
        tutor_note = self._add(self.tutor, "Tutor's note").data["note"]["id"]

        # A tutor cannot remove the mentor's note...
        self.client.force_authenticate(user=self.tutor)
        res = self.client.delete(self._detail_url(mentor_note))
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        # ...but can remove their own.
        res = self.client.delete(self._detail_url(tutor_note))
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        # An admin can remove anyone's.
        self.client.force_authenticate(user=self.admin)
        res = self.client.delete(self._detail_url(mentor_note))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(StudentNote.objects.count(), 0)

        from activity.models import ActivityLog
        self.assertEqual(ActivityLog.objects.filter(action='student.note_delete').count(), 2)

    def test_notes_follow_the_profile_scope(self):
        note_id = self._add(self.mentor).data["note"]["id"]

        # Another mentor can neither list nor touch them.
        self.client.force_authenticate(user=self.other_mentor)
        self.assertEqual(self.client.get(self.list_url).status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(self.client.post(self.list_url, {"body": "x"}, format='json').status_code,
                         status.HTTP_404_NOT_FOUND)
        self.assertEqual(self.client.patch(self._detail_url(note_id), {"body": "x"}, format='json').status_code,
                         status.HTTP_404_NOT_FOUND)
        self.assertEqual(self.client.delete(self._detail_url(note_id)).status_code,
                         status.HTTP_404_NOT_FOUND)

        # Reassigning the student closes the door on the previous mentor.
        self.student.mentor = self.other_mentor
        self.student.save()
        self.client.force_authenticate(user=self.mentor)
        self.assertEqual(self.client.get(self.list_url).status_code, status.HTTP_404_NOT_FOUND)

    def test_notes_are_never_student_facing(self):
        self._add(self.mentor)
        self.client.force_authenticate(user=self.parent)
        self.assertEqual(self.client.get(self.list_url).status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(self.client.post(self.list_url, {"body": "hi"}, format='json').status_code,
                         status.HTTP_403_FORBIDDEN)

    def test_notes_go_with_the_student(self):
        from students.models import StudentNote
        self._add(self.admin)
        self.assertEqual(StudentNote.objects.count(), 1)
        self.student.delete()
        self.assertEqual(StudentNote.objects.count(), 0)


# ---------------------------------------------------------------------------
# Enrolment-sheet quota sync (students.quota_sync)
# ---------------------------------------------------------------------------

def _sheet_row(code='', paid='', purchased=''):
    """
    One A3:AB row with only the three columns the sync cares about filled in.
    Written positionally so the test breaks if an index constant moves.
    """
    from invitations.sheets import (
        COL_CLASSES_PAID_FOR,
        COL_CLASSES_PURCHASED,
        COL_STUDENT_CODE,
    )

    row = [''] * (COL_STUDENT_CODE + 1)
    row[COL_STUDENT_CODE] = code
    row[COL_CLASSES_PAID_FOR] = paid
    row[COL_CLASSES_PURCHASED] = purchased
    return row


class QuotaSyncFromSheetTests(TestCase):
    """
    Column O ("No of classes paid for") is the only source of
    ``total_class_quota``. Column N ("Actual No of classes purchased") is
    display data in the sheet and must never reach the quota.
    """

    def setUp(self):
        self.parent = User.objects.create_user(
            email="sync-parent@eduport.com", password="pw", full_name="Parent", role="STUDENT")

    def _student(self, code, quota=0):
        return Student.objects.create(
            profile=self.parent, student_code=code, full_name=f"Student {code}",
            total_class_quota=quota,
        )

    def _sync(self, rows, **kwargs):
        from students import quota_sync
        with patch.object(
            quota_sync.GoogleSheetsService, 'fetch_enrollment_rows', return_value=rows
        ):
            return quota_sync.sync_student_quotas_from_sheet(**kwargs)

    def test_single_row_sets_the_quota(self):
        student = self._student("EPS00001", quota=0)
        report = self._sync([_sheet_row("EPS00001", paid="10")])

        student.refresh_from_db()
        self.assertEqual(student.total_class_quota, 10)
        self.assertEqual(report.students_updated, 1)
        self.assertFalse(report.failed)

    def test_duplicate_code_sums_the_paid_values(self):
        student = self._student("EPS00001", quota=0)
        report = self._sync([
            _sheet_row("EPS00001", paid="10"),
            _sheet_row("EPS00001", paid="14"),
        ])

        student.refresh_from_db()
        self.assertEqual(student.total_class_quota, 24)
        self.assertEqual(report.duplicate_codes, ["EPS00001"])

    def test_several_duplicate_rows_sum(self):
        student = self._student("EPS00001", quota=0)
        self._sync([
            _sheet_row("EPS00001", paid="15"),
            _sheet_row("EPS00001", paid="15"),
        ])

        student.refresh_from_db()
        self.assertEqual(student.total_class_quota, 30)

    def test_non_numeric_value_is_skipped_and_reported(self):
        student = self._student("EPS00001", quota=0)
        report = self._sync([
            _sheet_row("EPS00001", paid="Token"),
            _sheet_row("EPS00001", paid="10"),
        ])

        student.refresh_from_db()
        # "Token" contributes nothing -- it is not silently read as 0.
        self.assertEqual(student.total_class_quota, 10)
        self.assertEqual(report.non_numeric_values, [["EPS00001", "Token"]])

    def test_a_code_whose_only_value_is_non_numeric_is_left_alone(self):
        student = self._student("EPS00001", quota=7)
        report = self._sync([_sheet_row("EPS00001", paid="Token")])

        student.refresh_from_db()
        # Not zeroed: "Token" is not a statement that nothing was paid for.
        self.assertEqual(student.total_class_quota, 7)
        self.assertEqual(report.codes_without_numeric_value, ["EPS00001"])
        self.assertEqual(report.students_updated, 0)

    def test_explicit_zero_is_a_real_value(self):
        student = self._student("EPS00001", quota=12)
        self._sync([_sheet_row("EPS00001", paid="0")])

        student.refresh_from_db()
        self.assertEqual(student.total_class_quota, 0)

    def test_zero_contributes_zero_to_a_sum(self):
        student = self._student("EPS00001", quota=0)
        self._sync([
            _sheet_row("EPS00001", paid="0"),
            _sheet_row("EPS00001", paid="8"),
        ])

        student.refresh_from_db()
        self.assertEqual(student.total_class_quota, 8)

    def test_blank_value_is_skipped_without_zeroing(self):
        student = self._student("EPS00001", quota=9)
        report = self._sync([_sheet_row("EPS00001", paid="   ")])

        student.refresh_from_db()
        self.assertEqual(student.total_class_quota, 9)
        self.assertEqual(report.codes_without_numeric_value, ["EPS00001"])
        # A blank cell is not a data-entry error, so it is not reported as one.
        self.assertEqual(report.non_numeric_values, [])

    def test_sheet_code_with_no_student_is_skipped(self):
        report = self._sync([_sheet_row("EPS99999", paid="10")])

        self.assertEqual(report.codes_not_in_db, ["EPS99999"])
        self.assertEqual(report.students_updated, 0)

    def test_row_without_a_code_is_skipped(self):
        student = self._student("EPS00001", quota=5)
        report = self._sync([
            _sheet_row("", paid="99"),
            _sheet_row("   ", paid="99"),
            _sheet_row("EPS00001", paid="10"),
        ])

        student.refresh_from_db()
        self.assertEqual(student.total_class_quota, 10)
        self.assertEqual(report.rows_without_code, 2)

    def test_student_absent_from_the_sheet_keeps_its_quota(self):
        in_sheet = self._student("EPS00001", quota=0)
        absent = self._student("EPS00002", quota=6)
        report = self._sync([_sheet_row("EPS00001", paid="10")])

        in_sheet.refresh_from_db()
        absent.refresh_from_db()
        self.assertEqual(in_sheet.total_class_quota, 10)
        self.assertEqual(absent.total_class_quota, 6)
        self.assertEqual(report.students_not_in_sheet, 1)

    def test_sheets_failure_changes_nothing(self):
        from students import quota_sync
        student = self._student("EPS00001", quota=11)

        with patch.object(
            quota_sync.GoogleSheetsService, 'fetch_enrollment_rows',
            side_effect=RuntimeError("Google is down"),
        ):
            report = quota_sync.sync_student_quotas_from_sheet()

        student.refresh_from_db()
        self.assertEqual(student.total_class_quota, 11)
        self.assertTrue(report.failed)
        self.assertIn("Google is down", report.error)
        self.assertEqual(report.students_updated, 0)

    def test_purchased_column_is_never_used_for_the_quota(self):
        """The audited live row: EDP00041 has N=72 and O=8. It must become 8."""
        student = self._student("EDP00041", quota=10)
        self._sync([_sheet_row("EDP00041", paid="8", purchased="72")])

        student.refresh_from_db()
        self.assertEqual(student.total_class_quota, 8)

    def test_codes_match_case_and_whitespace_insensitively(self):
        student = self._student("EDP00041", quota=0)
        self._sync([_sheet_row("  edp00041 ", paid="8")])

        student.refresh_from_db()
        self.assertEqual(student.total_class_quota, 8)

    def test_unchanged_quota_is_counted_not_rewritten(self):
        student = self._student("EPS00001", quota=10)
        before = student.updated_at
        report = self._sync([_sheet_row("EPS00001", paid="10")])

        student.refresh_from_db()
        self.assertEqual(report.students_unchanged, 1)
        self.assertEqual(report.students_updated, 0)
        self.assertEqual(student.updated_at, before)

    def test_a_write_bumps_updated_at(self):
        """bulk_update skips auto_now, so the sync sets the column itself."""
        student = self._student("EPS00001", quota=0)
        before = student.updated_at
        self._sync([_sheet_row("EPS00001", paid="10")])

        student.refresh_from_db()
        self.assertGreater(student.updated_at, before)

    def test_dry_run_reports_without_writing(self):
        student = self._student("EPS00001", quota=3)
        report = self._sync([_sheet_row("EPS00001", paid="10")], dry_run=True)

        student.refresh_from_db()
        self.assertEqual(student.total_class_quota, 3)
        self.assertEqual(report.students_updated, 1)
        self.assertEqual(report.changes, [["EPS00001", 3, 10]])

    def test_one_sheet_call_per_sync(self):
        from students import quota_sync
        self._student("EPS00001")
        self._student("EPS00002")

        with patch.object(
            quota_sync.GoogleSheetsService, 'fetch_enrollment_rows',
            return_value=[_sheet_row("EPS00001", paid="1"), _sheet_row("EPS00002", paid="2")],
        ) as fetch:
            quota_sync.sync_student_quotas_from_sheet()

        self.assertEqual(fetch.call_count, 1)

    def test_management_command_and_task_share_the_service(self):
        """Neither entry point may carry its own copy of the sync logic."""
        from django.core.management import call_command
        from students import tasks

        student = self._student("EPS00001", quota=0)
        with patch(
            'students.quota_sync.GoogleSheetsService.fetch_enrollment_rows',
            return_value=[_sheet_row("EPS00001", paid="10")],
        ):
            call_command('sync_student_quotas', stdout=StringIO())
            student.refresh_from_db()
            self.assertEqual(student.total_class_quota, 10)

            Student.objects.filter(pk=student.pk).update(total_class_quota=0)
            result = tasks.sync_student_quotas()

        student.refresh_from_db()
        self.assertEqual(student.total_class_quota, 10)
        self.assertEqual(result['students_updated'], 1)
        self.assertFalse(result['failed'])

    def test_command_reports_a_sheets_failure_on_stderr(self):
        err = StringIO()
        with patch(
            'students.quota_sync.GoogleSheetsService.fetch_enrollment_rows',
            side_effect=RuntimeError("Google is down"),
        ):
            from django.core.management import call_command
            call_command('sync_student_quotas', stdout=StringIO(), stderr=err)

        self.assertIn("Quota sync failed", err.getvalue())


class QuotaIsReadOnlyOverTheApiTests(APITestCase):
    """
    The sheet is the source of truth, so the old manual top-up write path is
    refused rather than quietly overwritten by the next sync.
    """

    def setUp(self):
        self.admin = User.objects.create_user(
            email="ro-admin@eduport.com", password="pw", full_name="Admin", role="ADMIN")
        self.mentor = User.objects.create_user(
            email="ro-mentor@eduport.com", password="pw", full_name="Mentor", role="MENTOR")
        self.parent = User.objects.create_user(
            email="ro-parent@eduport.com", password="pw", full_name="Parent", role="STUDENT")
        self.student = Student.objects.create(
            profile=self.parent, student_code="EDP00200", full_name="Read Only",
            mentor=self.mentor, total_class_quota=10,
        )
        self.url = reverse('students:student-list')

    def test_admin_cannot_set_the_quota(self):
        self.client.force_authenticate(user=self.admin)
        res = self.client.put(
            self.url, {"id": str(self.student.id), "total_class_quota": 25}, format='json')

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data['error'], 'QUOTA_READ_ONLY')
        self.student.refresh_from_db()
        self.assertEqual(self.student.total_class_quota, 10)

    def test_mentor_cannot_set_the_quota(self):
        self.client.force_authenticate(user=self.mentor)
        res = self.client.put(
            self.url, {"id": str(self.student.id), "total_class_quota": 25}, format='json')

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.student.refresh_from_db()
        self.assertEqual(self.student.total_class_quota, 10)

    def test_the_refusal_does_not_half_apply_the_rest_of_the_payload(self):
        self.client.force_authenticate(user=self.admin)
        res = self.client.put(self.url, {
            "id": str(self.student.id),
            "meet_link": "https://meet.google.com/aaa-bbbb-ccc",
            "total_class_quota": 25,
        }, format='json')

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.student.refresh_from_db()
        self.assertEqual(self.student.total_class_quota, 10)
        self.assertIsNone(self.student.meet_link)

    def test_a_payload_without_quota_still_works(self):
        self.client.force_authenticate(user=self.admin)
        res = self.client.put(
            self.url,
            {"id": str(self.student.id), "meet_link": "https://meet.google.com/aaa-bbbb-ccc"},
            format='json',
        )

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.student.refresh_from_db()
        self.assertEqual(self.student.meet_link, "https://meet.google.com/aaa-bbbb-ccc")

    def test_no_quota_activity_entry_is_written_any_more(self):
        from activity.models import ActivityLog

        self.client.force_authenticate(user=self.admin)
        self.client.put(
            self.url, {"id": str(self.student.id), "total_class_quota": 25}, format='json')

        self.assertFalse(ActivityLog.objects.filter(action='student.update_quota').exists())

    def test_historical_quota_entries_still_read_back(self):
        """
        Retiring the write path must not retire the history: entries written
        before the sync existed still have to come back from /api/activity/.
        """
        from activity.models import ActivityLog

        ActivityLog.objects.create(
            actor=self.admin, actor_email=self.admin.email, actor_name="Admin",
            actor_role="ADMIN", action='student.update_quota', entity_type='student',
            entity_id=str(self.student.id), entity_label=self.student.full_name,
            student=self.student, changes={"total_class_quota": {"old": 5, "new": 10}},
        )

        self.client.force_authenticate(user=self.admin)
        res = self.client.get(reverse('activity:activity-logs-list'))
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        quota_entries = [
            e for e in res.data['results'] if e['action'] == 'student.update_quota'
        ]
        self.assertEqual(len(quota_entries), 1)
        self.assertEqual(quota_entries[0]['changes'], {"total_class_quota": {"old": 5, "new": 10}})


class SyncedQuotaFeedsTheExistingHourArithmeticTests(APITestCase):
    """
    Only the SOURCE of the quota changed. Consumption is still measured in
    hours by the duration of non-cancelled sessions, and the profile still
    reports purchased / used / remaining off that same figure.
    """

    def setUp(self):
        self.admin = User.objects.create_user(
            email="hours-admin@eduport.com", password="pw", full_name="Admin", role="ADMIN")
        self.mentor = User.objects.create_user(
            email="hours-mentor@eduport.com", password="pw", full_name="Mentor", role="MENTOR")
        self.tutor = User.objects.create_user(
            email="hours-tutor@eduport.com", password="pw", full_name="Tutor", role="TUTOR")
        self.parent = User.objects.create_user(
            email="hours-parent@eduport.com", password="pw", full_name="Parent", role="STUDENT")
        self.student = Student.objects.create(
            profile=self.parent, student_code="EDP00300", full_name="Hours Student",
            mentor=self.mentor, tutor=self.tutor, total_class_quota=0,
        )

    def _sync(self, paid):
        from students import quota_sync
        with patch.object(
            quota_sync.GoogleSheetsService, 'fetch_enrollment_rows',
            return_value=[_sheet_row("EDP00300", paid=paid)],
        ):
            return quota_sync.sync_student_quotas_from_sheet()

    def _book(self, hours, offset_days, status_value='SCHEDULED'):
        from sessions.models import Session
        start = dj_timezone.now() + dt.timedelta(days=offset_days)
        return Session.objects.create(
            student=self.student, title=f"Class {offset_days}", tutor=self.tutor,
            start_time=start, end_time=start + dt.timedelta(hours=hours), status=status_value,
        )

    def test_used_hours_stay_duration_based_after_a_sync(self):
        from sessions.services import calculate_credits_used

        self._sync("10")
        self._book(1, 1)
        self._book(1.5, 2)
        self._book(0.5, 3)
        # Cancelled hours are still released.
        self._book(2, 4, status_value='CANCELLED')

        self.student.refresh_from_db()
        self.assertEqual(self.student.total_class_quota, 10)
        self.assertEqual(calculate_credits_used(self.student), 3.0)

    def test_profile_reports_the_synced_quota(self):
        self._sync("10")
        self._book(1, 1)
        self._book(1.5, 2)
        self._book(0.5, 3)

        self.client.force_authenticate(user=self.admin)
        res = self.client.get(reverse('students:student-profile', args=[self.student.id]))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(
            res.data['stats']['quota'],
            {"purchased": 10, "used_hours": 3.0, "remaining_hours": 7.0},
        )

    def test_session_creation_is_enforced_against_the_synced_quota(self):
        self._sync("2")
        self.client.force_authenticate(user=self.mentor)
        url = reverse('sessions:sessions-list-create-update')
        start = dj_timezone.now() + dt.timedelta(days=5)

        # 2 hours of quota: a 2-hour class fits, a second one does not.
        ok = self.client.post(url, {
            "student_id": str(self.student.id), "base_title": "Fits", "series": False,
            "items": [{"start_time": start.isoformat(), "duration_hours": 2}],
        }, format='json')
        self.assertEqual(ok.status_code, status.HTTP_200_OK, ok.data)

        over = self.client.post(url, {
            "student_id": str(self.student.id), "base_title": "Over", "series": False,
            "items": [{"start_time": (start + dt.timedelta(days=1)).isoformat(),
                       "duration_hours": 0.5}],
        }, format='json')
        self.assertEqual(over.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('credits', over.data['error'])

    def test_a_sync_below_hours_already_used_keeps_the_sessions(self):
        """
        A lowered sheet figure must not touch existing bookings. The profile
        shows the overdraft, exactly as it did when a quota was lowered by hand.
        """
        self._sync("10")
        self._book(2, 1)
        self._book(2, 2)

        self._sync("2")
        self.student.refresh_from_db()
        self.assertEqual(self.student.total_class_quota, 2)

        from sessions.models import Session, SessionStatusChoices
        self.assertEqual(
            Session.objects.filter(student=self.student, status=SessionStatusChoices.SCHEDULED).count(),
            2,
        )

        self.client.force_authenticate(user=self.admin)
        res = self.client.get(reverse('students:student-profile', args=[self.student.id]))
        self.assertEqual(
            res.data['stats']['quota'],
            {"purchased": 2, "used_hours": 4.0, "remaining_hours": -2.0},
        )


class EnrolmentInitialisesQuotaFromTheSheetTests(APITestCase):
    """
    A newly enrolled student must be able to book immediately, so the quota is
    read from the sheet at invitation time rather than waiting for the next
    scheduled sync. Both paths go through ``quota_sync``, so the duplicate-row
    sum and the "Token" rule behave identically in each.
    """

    def setUp(self):
        self.admin = User.objects.create_user(
            email="enrol-admin@eduport.com", password="pw", full_name="Admin", role="ADMIN")
        self.lookup_url = reverse('invitations:lookup-student')
        self.create_url = reverse('invitations:create-invitation')
        self.client.force_authenticate(user=self.admin)

    def _profile_row(self, code, paid, purchased='', email='razi@example.com', name='Razi'):
        from invitations.sheets import (
            COL_CLASSES_PAID_FOR,
            COL_CLASSES_PURCHASED,
            COL_STUDENT_CODE,
        )

        row = [''] * (COL_STUDENT_CODE + 1)
        row[1] = name            # B full_name
        row[3] = email           # D email
        row[8] = '10'            # I grade
        row[COL_CLASSES_PURCHASED] = purchased
        row[COL_CLASSES_PAID_FOR] = paid
        row[COL_STUDENT_CODE] = code
        return row

    def _enrol(self, rows, code='EDP00041', email='razi@example.com'):
        """Invite, then sign the parent in, which is what creates the Student."""
        from accounts.services import UserProvisioningService

        with patch(
            'invitations.sheets.GoogleSheetsService.fetch_enrollment_rows', return_value=rows
        ):
            res = self.client.post(self.create_url, {
                "role": "STUDENT", "email": email,
                "student_code": code, "full_name": "Razi",
            }, format='json')
        self.assertIn(res.status_code, (status.HTTP_200_OK, status.HTTP_201_CREATED), res.data)

        parent = User.objects.create_user(
            email=email, password="pw", full_name="Razi Parent", role="STUDENT")
        UserProvisioningService.attach_pending_students(parent)
        return Student.objects.get(student_code=code)

    def test_new_student_starts_at_the_sheets_paid_figure(self):
        """The reported gap: EDP00041 with O=8 must enrol at 8, not 0."""
        student = self._enrol([self._profile_row('EDP00041', paid='8', purchased='72')])
        self.assertEqual(student.total_class_quota, 8)

    def test_purchased_column_does_not_leak_into_the_initial_quota(self):
        student = self._enrol([self._profile_row('EDP00041', paid='8', purchased='72')])
        self.assertNotEqual(student.total_class_quota, 72)

    def test_duplicate_rows_are_summed_at_enrolment_too(self):
        student = self._enrol([
            self._profile_row('EDP00041', paid='10'),
            self._profile_row('EDP00041', paid='14'),
        ])
        self.assertEqual(student.total_class_quota, 24)

    def test_token_is_ignored_at_enrolment_too(self):
        student = self._enrol([
            self._profile_row('EDP00041', paid='Token'),
            self._profile_row('EDP00041', paid='10'),
        ])
        self.assertEqual(student.total_class_quota, 10)

    def test_a_code_with_only_token_enrols_at_zero(self):
        """Nothing paid for is the safe start; the sync will not lower it further."""
        student = self._enrol([self._profile_row('EDP00041', paid='Token')])
        self.assertEqual(student.total_class_quota, 0)

    def test_explicit_zero_enrols_at_zero(self):
        student = self._enrol([self._profile_row('EDP00041', paid='0')])
        self.assertEqual(student.total_class_quota, 0)

    def test_sheets_failure_does_not_block_enrolment(self):
        """Google being down must not stop a student being invited."""
        from accounts.services import UserProvisioningService

        with patch(
            'invitations.sheets.GoogleSheetsService.fetch_enrollment_rows',
            side_effect=RuntimeError("Google is down"),
        ):
            res = self.client.post(self.create_url, {
                "role": "STUDENT", "email": "down@example.com",
                "student_code": "EDP00041", "full_name": "Razi",
            }, format='json')
        self.assertIn(res.status_code, (status.HTTP_200_OK, status.HTTP_201_CREATED), res.data)

        parent = User.objects.create_user(
            email="down@example.com", password="pw", full_name="P", role="STUDENT")
        UserProvisioningService.attach_pending_students(parent)
        student = Student.objects.get(student_code="EDP00041")
        self.assertEqual(student.total_class_quota, 0)

    def test_quota_is_never_taken_from_the_request_body(self):
        """
        The retired manual top-up must not come back through the invitation
        form: a client-supplied figure is ignored in favour of the sheet's.
        """
        from accounts.services import UserProvisioningService

        rows = [self._profile_row('EDP00041', paid='8')]
        with patch(
            'invitations.sheets.GoogleSheetsService.fetch_enrollment_rows', return_value=rows
        ):
            self.client.post(self.create_url, {
                "role": "STUDENT", "email": "razi@example.com",
                "student_code": "EDP00041", "full_name": "Razi",
                "total_class_quota": 999,
            }, format='json')

        invitation = Invitation.objects.get(extra_data__student_code='EDP00041')
        self.assertEqual(invitation.extra_data['total_class_quota'], 8)

        parent = User.objects.create_user(
            email="razi@example.com", password="pw", full_name="P", role="STUDENT")
        UserProvisioningService.attach_pending_students(parent)
        self.assertEqual(Student.objects.get(student_code='EDP00041').total_class_quota, 8)

    def test_lookup_reports_the_paid_figure_for_the_enrolment_form(self):
        rows = [self._profile_row('EDP00041', paid='8', purchased='72')]
        with patch(
            'invitations.sheets.GoogleSheetsService.fetch_enrollment_rows', return_value=rows
        ) as fetch:
            res = self.client.post(self.lookup_url, {"student_code": "EDP00041"}, format='json')

        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
        self.assertEqual(res.data['student_data']['classes_paid_for'], 8)
        # Profile fields and the quota come from ONE fetch of the same snapshot.
        self.assertEqual(fetch.call_count, 1)

    def test_an_invitation_predating_this_key_still_enrols(self):
        """Backward compatibility: extra_data written before the key existed."""
        from accounts.services import UserProvisioningService

        Invitation.objects.create(
            email="legacy@example.com", role=InvitationRoleChoices.STUDENT,
            status=InvitationStatusChoices.PENDING,
            extra_data={"student_code": "EDP00099", "full_name": "Legacy"},
        )
        parent = User.objects.create_user(
            email="legacy@example.com", password="pw", full_name="P", role="STUDENT")
        UserProvisioningService.attach_pending_students(parent)

        self.assertEqual(Student.objects.get(student_code="EDP00099").total_class_quota, 0)

    def test_periodic_sync_still_takes_over_when_the_sheet_changes(self):
        """
        Enrolment seeds the figure; the sync owns every later change. Both must
        agree while the sheet is unchanged, and the sync must win once it moves.
        """
        from students import quota_sync

        student = self._enrol([self._profile_row('EDP00041', paid='8')])
        self.assertEqual(student.total_class_quota, 8)

        # Sheet unchanged -> the sync is a no-op, not a rewrite.
        with patch.object(
            quota_sync.GoogleSheetsService, 'fetch_enrollment_rows',
            return_value=[self._profile_row('EDP00041', paid='8')],
        ):
            report = quota_sync.sync_student_quotas_from_sheet()
        self.assertEqual(report.students_unchanged, 1)
        self.assertEqual(report.students_updated, 0)

        # Sales records another payment -> the sync raises the quota.
        with patch.object(
            quota_sync.GoogleSheetsService, 'fetch_enrollment_rows',
            return_value=[
                self._profile_row('EDP00041', paid='8'),
                self._profile_row('EDP00041', paid='7'),
            ],
        ):
            report = quota_sync.sync_student_quotas_from_sheet()

        student.refresh_from_db()
        self.assertEqual(student.total_class_quota, 15)
        self.assertEqual(report.changes, [['EDP00041', 8, 15]])

    def test_enrolment_and_sync_agree_on_every_shape_of_cell(self):
        """
        The anti-duplication guard: one reduction, so both entry points must
        produce the same number for the same rows.
        """
        from students import quota_sync

        cases = [
            ([('8', '')], 8),
            ([('10', ''), ('14', '')], 24),
            ([('15', ''), ('15', '')], 30),
            ([('Token', ''), ('10', '')], 10),
            ([('0', '')], 0),
        ]
        for paid_values, expected in cases:
            with self.subTest(paid_values=paid_values):
                rows = [self._profile_row('EDP00041', paid=p, purchased=n) for p, n in paid_values]
                via_enrolment = quota_sync.quota_for_code(rows, 'EDP00041')
                self.assertEqual(0 if via_enrolment is None else via_enrolment, expected)
