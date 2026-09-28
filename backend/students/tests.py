from django.urls import reverse
from django.contrib.auth import get_user_model
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
        
        # Test student update (PUT /api/students/)
        payload = {
            "id": str(self.student.id),
            "meet_link": "https://meet.google.com/xxx-yyyy-zzz",
            "total_class_quota": 20,
            "status": "INACTIVE",
            "status_note": "A temporary pause"
        }
        response = self.client.put(url, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Verify database reflects updates
        self.student.refresh_from_db()
        self.assertEqual(self.student.meet_link, "https://meet.google.com/xxx-yyyy-zzz")
        self.assertEqual(self.student.total_class_quota, 20)
        self.assertEqual(self.student.status, "INACTIVE")
        self.assertEqual(self.student.status_note, "A temporary pause")



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
