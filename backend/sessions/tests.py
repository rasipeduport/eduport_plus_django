import uuid
from datetime import timedelta
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from students.models import Student, StatusChoices
from invitations.models import Invitation, InvitationStatusChoices, InvitationRoleChoices
from activity.models import ActivityLog
from sessions.models import Session, SessionStatusChoices

User = get_user_model()

class EduportPlusBackendAPITests(APITestCase):
    def setUp(self):
        # Create users of various roles
        self.admin = User.objects.create_user(
            email='admin@eduport.com',
            password='testpassword',
            full_name='Test Admin',
            role='ADMIN',
            is_staff=True
        )
        self.mentor = User.objects.create_user(
            email='mentor@eduport.com',
            password='testpassword',
            full_name='Test Mentor',
            role='MENTOR',
            is_staff=True
        )
        self.tutor = User.objects.create_user(
            email='tutor@eduport.com',
            password='testpassword',
            full_name='Test Tutor',
            role='TUTOR',
            is_staff=True
        )
        self.student_user = User.objects.create_user(
            email='student@eduport.com',
            password='testpassword',
            full_name='Test Student',
            role='STUDENT',
            is_staff=False
        )

        # Create Student profile
        self.student = Student.objects.create(
            profile=self.student_user,
            student_code='EDP00001',
            full_name='Test Student',
            mentor=self.mentor,
            tutor=self.tutor,
            total_class_quota=10,
            meet_link='https://meet.google.com/abc-defg-hij',
            status=StatusChoices.ACTIVE
        )

        # Create some other students to test counts
        self.student2_user = User.objects.create_user(
            email='student2@eduport.com',
            password='testpassword',
            full_name='Test Student 2',
            role='STUDENT'
        )
        self.student2 = Student.objects.create(
            profile=self.student2_user,
            student_code='EDP00002',
            full_name='Test Student 2',
            mentor=self.mentor,
            tutor=self.tutor,
            total_class_quota=5,
            status=StatusChoices.ACTIVE
        )

        # Base URLs
        self.sessions_url = reverse('sessions:sessions-list-create-update')
        self.cancel_series_url = reverse('sessions:cancel-series')
        self.stats_url = reverse('staff-dashboard-stats')
        self.student_dashboard_url = reverse('student-dashboard')
        self.mentors_url = reverse('mentor-list')
        self.tutors_url = reverse('tutor-list')
        self.activity_logs_url = reverse('activity:activity-logs-list')

    def test_mentor_and_tutor_list_counts(self):
        """
        Verify that mentors and tutors endpoints return assigned student counts.
        """
        self.client.force_authenticate(user=self.admin)
        
        # Test Mentor list
        res = self.client.get(self.mentors_url + '?all=true')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        mentors_list = res.data.get('mentors', [])
        # Find our mentor
        m_data = next(m for m in mentors_list if m['id'] == str(self.mentor.id))
        self.assertEqual(m_data['assigned_students_count'], 2)

        # Test Tutor list
        res = self.client.get(self.tutors_url + '?all=true')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        tutors_list = res.data.get('tutors', [])
        t_data = next(t for t in tutors_list if t['id'] == str(self.tutor.id))
        self.assertEqual(t_data['assigned_students_count'], 2)

    def test_staff_dashboard_stats(self):
        """
        Verify staff dashboard statistics include signup data and recent signups.
        """
        self.client.force_authenticate(user=self.admin)
        res = self.client.get(self.stats_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIn('signup_data', res.data)
        self.assertIn('recent_signups', res.data)
        self.assertEqual(len(res.data['recent_signups']), 2) # Both students created in setUp
        self.assertEqual(res.data['students'], 2)

    def test_student_dashboard(self):
        """
        Verify student dashboard details, including next/last session summaries.
        """
        # Create an attended session (last class)
        past_time = timezone.now() - timedelta(days=1)
        Session.objects.create(
            student=self.student,
            tutor=self.tutor,
            start_time=past_time,
            end_time=past_time + timedelta(hours=1),
            title='Past Class',
            status=SessionStatusChoices.ATTENDED
        )

        # Create a scheduled session (next class)
        future_time = timezone.now() + timedelta(days=1)
        next_class = Session.objects.create(
            student=self.student,
            tutor=self.tutor,
            start_time=future_time,
            end_time=future_time + timedelta(hours=1.5),
            title='Next Class',
            status=SessionStatusChoices.SCHEDULED
        )

        self.client.force_authenticate(user=self.student_user)
        res = self.client.get(self.student_dashboard_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['student_name'], self.student.full_name)
        self.assertEqual(res.data['scheduled_count'], 1)
        self.assertEqual(res.data['attended_count'], 1)
        self.assertIsNotNone(res.data['next_session'])
        self.assertEqual(res.data['next_session']['id'], str(next_class.id))
        self.assertEqual(res.data['last_session']['title'], 'Past Class')

    def test_student_can_rate_own_session(self):
        past_time = timezone.now() - timedelta(days=1)
        sess = Session.objects.create(
            student=self.student,
            tutor=self.tutor,
            start_time=past_time,
            end_time=past_time + timedelta(hours=1),
            title='Past Class',
            status=SessionStatusChoices.ATTENDED,
        )
        self.client.force_authenticate(user=self.student_user)
        res = self.client.put(self.sessions_url, {"id": str(sess.id), "rating": 5}, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        sess.refresh_from_db()
        self.assertEqual(sess.rating, 5)

    def test_student_cannot_rate_other_students_session(self):
        past_time = timezone.now() - timedelta(days=1)
        other = Session.objects.create(
            student=self.student2,
            tutor=self.tutor,
            start_time=past_time,
            end_time=past_time + timedelta(hours=1),
            title='Other Class',
            status=SessionStatusChoices.ATTENDED,
        )
        self.client.force_authenticate(user=self.student_user)
        res = self.client.put(self.sessions_url, {"id": str(other.id), "rating": 4}, format='json')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        other.refresh_from_db()
        self.assertIsNone(other.rating)

    def test_student_put_ignores_non_rating_fields(self):
        past_time = timezone.now() - timedelta(days=1)
        sess = Session.objects.create(
            student=self.student,
            tutor=self.tutor,
            start_time=past_time,
            end_time=past_time + timedelta(hours=1),
            title='Past Class',
            status=SessionStatusChoices.ATTENDED,
        )
        self.client.force_authenticate(user=self.student_user)
        # Attempt to also change status and title; only rating should apply.
        res = self.client.put(
            self.sessions_url,
            {"id": str(sess.id), "rating": 3, "status": "CANCELLED", "title": "Hacked"},
            format='json',
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        sess.refresh_from_db()
        self.assertEqual(sess.rating, 3)
        self.assertEqual(sess.status, SessionStatusChoices.ATTENDED)
        self.assertEqual(sess.title, 'Past Class')

    def test_student_put_requires_valid_rating(self):
        past_time = timezone.now() - timedelta(days=1)
        sess = Session.objects.create(
            student=self.student,
            tutor=self.tutor,
            start_time=past_time,
            end_time=past_time + timedelta(hours=1),
            title='Past Class',
            status=SessionStatusChoices.ATTENDED,
        )
        self.client.force_authenticate(user=self.student_user)
        res = self.client.put(self.sessions_url, {"id": str(sess.id), "rating": 9}, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_session_crud_and_quota_validation(self):
        """
        Verify session creation checks quota and scheduling conflicts.
        """
        self.client.force_authenticate(user=self.mentor)
        
        # 1. Create session under quota
        start_time1 = timezone.now() + timedelta(days=2)
        payload = {
            "student_id": str(self.student.id),
            "base_title": "Maths Mastery",
            "series": False,
            "items": [
                {
                    "start_time": start_time1.isoformat(),
                    "duration_hours": 1.5
                }
            ]
        }
        res = self.client.post(self.sessions_url, payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.data['success'])
        self.assertEqual(len(res.data['sessions']), 1)
        session_id = res.data['sessions'][0]['id']
        self.assertEqual(str(res.data['sessions'][0]['tutor']), str(self.tutor.id)) # tutor snapshotted

        # 2. Try creating session that conflicts with the one we just created
        payload_conflict = {
            "student_id": str(self.student.id),
            "base_title": "Physics",
            "series": False,
            "items": [
                {
                    "start_time": (start_time1 + timedelta(minutes=30)).isoformat(),
                    "duration_hours": 1
                }
            ]
        }
        res = self.client.post(self.sessions_url, payload_conflict, format='json')
        self.assertEqual(res.status_code, status.HTTP_409_CONFLICT)
        self.assertIn('conflicts', res.data['error'])

        # 3. Try creating session that exceeds quota (remaining is 10 - 1.5 = 8.5)
        payload_exceeds = {
            "student_id": str(self.student.id),
            "base_title": "Super Series",
            "series": True,
            "items": [
                {"start_time": (start_time1 + timedelta(days=i)).isoformat(), "duration_hours": 2}
                for i in range(1, 6) # 5 classes * 2 hours = 10 hours (only 8.5 remains)
            ]
        }
        res = self.client.post(self.sessions_url, payload_exceeds, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('credits', res.data['error'])

        # 4. Update session (reschedule)
        new_start = start_time1 + timedelta(days=10)
        update_payload = {
            "id": session_id,
            "start_time": new_start.isoformat(),
            "duration_hours": 1
        }


        # 5. List sessions
        res = self.client.get(self.sessions_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(any(s['id'] == session_id for s in res.data['sessions']))

    def test_cancel_series_renumbering_and_makeup(self):
        """
        Verify that cancelling a session inside a series shifts subsequent sessions
        and schedules a new make-up session at the end.
        """
        self.client.force_authenticate(user=self.mentor)
        series_id = uuid.uuid4()
        base_time = timezone.now() + timedelta(days=5)

        # Create 3 scheduled sessions in a series
        s1 = Session.objects.create(
            student=self.student, tutor=self.tutor, series_id=series_id, class_number=1,
            title="Algebra - Class 1", start_time=base_time, end_time=base_time + timedelta(hours=1)
        )
        s2 = Session.objects.create(
            student=self.student, tutor=self.tutor, series_id=series_id, class_number=2,
            title="Algebra - Class 2", start_time=base_time + timedelta(days=1), end_time=base_time + timedelta(days=1, hours=1)
        )
        s3 = Session.objects.create(
            student=self.student, tutor=self.tutor, series_id=series_id, class_number=3,
            title="Algebra - Class 3", start_time=base_time + timedelta(days=2), end_time=base_time + timedelta(days=2, hours=1)
        )

        makeup_time = base_time + timedelta(days=4)

        # Cancel Class 1
        cancel_payload = {
            "session_id": str(s1.id),
            "cancellation_reason": "Student sick",
            "new_last_start_time": makeup_time.isoformat(),
            "new_last_duration_hours": 1
        }
        res = self.client.post(self.cancel_series_url, cancel_payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['renumberedCount'], 2)

        # Refresh from database
        s1.refresh_from_db()
        s2.refresh_from_db()
        s3.refresh_from_db()

        self.assertEqual(s1.status, SessionStatusChoices.CANCELLED)
        
        # s2 (Class 2) shifted to Class 1
        self.assertEqual(s2.class_number, 1)
        self.assertEqual(s2.title, "Algebra - Class 1")

        # s3 (Class 3) shifted to Class 2
        self.assertEqual(s3.class_number, 2)
        self.assertEqual(s3.title, "Algebra - Class 2")

        # Make-up class created with class_number=3
        makeup_class = Session.objects.get(id=res.data['newSession']['id'])
        self.assertEqual(makeup_class.class_number, 3)
        self.assertEqual(makeup_class.title, "Algebra - Class 3")
        self.assertEqual(makeup_class.start_time, makeup_time)

    def test_cancel_series_alias_url(self):
        """
        Verify that cancelling a session via the frontend-compatibility alias URL
        ('/api/sessions/cancel/') also shifts subsequent sessions.
        """
        self.client.force_authenticate(user=self.mentor)
        series_id = uuid.uuid4()
        base_time = timezone.now() + timedelta(days=5)

        s1 = Session.objects.create(
            student=self.student, tutor=self.tutor, series_id=series_id, class_number=1,
            title="Chemistry - Class 1", start_time=base_time, end_time=base_time + timedelta(hours=1)
        )
        s2 = Session.objects.create(
            student=self.student, tutor=self.tutor, series_id=series_id, class_number=2,
            title="Chemistry - Class 2", start_time=base_time + timedelta(days=1), end_time=base_time + timedelta(days=1, hours=1)
        )

        cancel_payload = {
            "session_id": str(s1.id),
            "cancellation_reason": "Test alias URL",
            "new_last_start_time": (base_time + timedelta(days=3)).isoformat(),
            "new_last_duration_hours": 1
        }
        res = self.client.post('/api/sessions/cancel/', cancel_payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        
        s1.refresh_from_db()
        s2.refresh_from_db()
        self.assertEqual(s1.status, SessionStatusChoices.CANCELLED)
        self.assertEqual(s2.class_number, 1)

    def test_activity_logs_and_history_filters(self):
        """
        Verify activity logs page returns audit trails with pagination and filtering.
        """
        # Create some activity logs
        ActivityLog.objects.create(
            actor=self.admin, actor_name='Test Admin', actor_email='admin@eduport.com', actor_role='ADMIN',
            action='LOGIN', entity_type='SESSION', entity_id='sess_123', entity_label='User Session'
        )
        ActivityLog.objects.create(
            actor=self.mentor, actor_name='Test Mentor', actor_email='mentor@eduport.com', actor_role='MENTOR',
            action='invitation.create', entity_type='invitation', entity_id='invite_456', entity_label='student@eduport.com'
        )
        ActivityLog.objects.create(
            actor=self.admin, actor_name='Test Admin', actor_email='admin@eduport.com', actor_role='ADMIN',
            action='session.create', entity_type='session', entity_id='sess_456', entity_label='Maths Session',
            student=self.student
        )

        # Test global logs (admin access)
        self.client.force_authenticate(user=self.admin)
        res = self.client.get(self.activity_logs_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['count'], 3)
        self.assertIn('actor_options', res.data)

        # Test keyword search
        res = self.client.get(self.activity_logs_url, {"q": "Maths"})
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['count'], 1)
        self.assertEqual(res.data['results'][0]['action'], 'session.create')

        # Test filter by action
        res = self.client.get(self.activity_logs_url, {"action": "LOGIN"})
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['count'], 1)

        # Test student history filter (accessible to Mentor)
        self.client.force_authenticate(user=self.mentor)
        res = self.client.get(self.activity_logs_url, {"student_id": str(self.student.id)})
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['count'], 1)
        self.assertEqual(res.data['results'][0]['entity_label'], 'Maths Session')

        # Verify Student is not allowed to query global logs
        self.client.force_authenticate(user=self.student_user)
        res = self.client.get(self.activity_logs_url)
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)


class RoleScopingSecurityTests(APITestCase):
    """
    RLS -> DRF parity: a mentor/tutor may only read and act on the students and
    sessions allocated to them. These guard the row-scoping that Postgres RLS
    used to enforce in the lead app.
    """

    def setUp(self):
        self.mentor_a = User.objects.create_user(email='ma@eduport.com', password='x', full_name='Mentor A', role='MENTOR', is_staff=True)
        self.mentor_b = User.objects.create_user(email='mb@eduport.com', password='x', full_name='Mentor B', role='MENTOR', is_staff=True)
        self.tutor_a = User.objects.create_user(email='ta@eduport.com', password='x', full_name='Tutor A', role='TUTOR', is_staff=True)
        self.tutor_b = User.objects.create_user(email='tb@eduport.com', password='x', full_name='Tutor B', role='TUTOR', is_staff=True)

        self.user_a = User.objects.create_user(email='sa@eduport.com', password='x', full_name='Stu A', role='STUDENT')
        self.user_b = User.objects.create_user(email='sb@eduport.com', password='x', full_name='Stu B', role='STUDENT')

        self.student_a = Student.objects.create(
            profile=self.user_a, student_code='EDPA', full_name='Stu A',
            mentor=self.mentor_a, tutor=self.tutor_a, total_class_quota=10, status=StatusChoices.ACTIVE,
        )
        self.student_b = Student.objects.create(
            profile=self.user_b, student_code='EDPB', full_name='Stu B',
            mentor=self.mentor_b, tutor=self.tutor_b, total_class_quota=10, status=StatusChoices.ACTIVE,
        )
        self.students_url = reverse('students:student-list')
        self.sessions_url = reverse('sessions:sessions-list-create-update')

    def test_mentor_lists_only_own_students(self):
        self.client.force_authenticate(user=self.mentor_a)
        res = self.client.get(self.students_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        codes = {s['student_code'] for s in res.data}
        self.assertEqual(codes, {'EDPA'})

    def test_tutor_lists_only_own_students(self):
        self.client.force_authenticate(user=self.tutor_b)
        res = self.client.get(self.students_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        codes = {s['student_code'] for s in res.data}
        self.assertEqual(codes, {'EDPB'})

    def test_mentor_cannot_update_other_mentors_student(self):
        self.client.force_authenticate(user=self.mentor_a)
        res = self.client.put(self.students_url, {"id": str(self.student_b.id), "total_class_quota": 99}, format='json')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        self.student_b.refresh_from_db()
        self.assertEqual(self.student_b.total_class_quota, 10)

    def test_mentor_cannot_create_session_for_other_mentors_student(self):
        self.client.force_authenticate(user=self.mentor_a)
        future = timezone.now() + timedelta(days=1)
        payload = {
            "student_id": str(self.student_b.id),
            "base_title": "Sneaky",
            "items": [{"start_time": future.isoformat(), "duration_hours": 1}],
        }
        res = self.client.post(self.sessions_url, payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(Session.objects.filter(student=self.student_b).exists())

    def test_tutor_cannot_create_sessions(self):
        self.client.force_authenticate(user=self.tutor_a)
        future = timezone.now() + timedelta(days=1)
        payload = {
            "student_id": str(self.student_a.id),
            "base_title": "Tutor Attempt",
            "items": [{"start_time": future.isoformat(), "duration_hours": 1}],
        }
        res = self.client.post(self.sessions_url, payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_mentor_sees_only_own_students_sessions(self):
        now = timezone.now()
        Session.objects.create(student=self.student_a, tutor=self.tutor_a, start_time=now, end_time=now + timedelta(hours=1), title='A class')
        Session.objects.create(student=self.student_b, tutor=self.tutor_b, start_time=now, end_time=now + timedelta(hours=1), title='B class')

        self.client.force_authenticate(user=self.mentor_a)
        res = self.client.get(self.sessions_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        titles = {s['title'] for s in res.data['sessions']}
        self.assertEqual(titles, {'A class'})

    def test_mentor_cannot_cancel_other_mentors_series(self):
        now = timezone.now()
        sess = Session.objects.create(
            student=self.student_b, tutor=self.tutor_b, start_time=now, end_time=now + timedelta(hours=1),
            title='B class', status=SessionStatusChoices.SCHEDULED,
        )
        self.client.force_authenticate(user=self.mentor_a)
        res = self.client.post('/api/sessions/cancel/', {"session_id": str(sess.id), "cancellation_reason": "nope"}, format='json')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)


class SessionWritePermissionAndValidationTests(APITestCase):
    """
    Phase 0 hardening: tutors are read-only on sessions (403 on PUT and
    cancel-series, matching the lead app), and staff updates validate status
    and rating server-side instead of persisting whatever arrives.
    """

    def setUp(self):
        self.mentor = User.objects.create_user(email='pm@eduport.com', password='x', full_name='Perm Mentor', role='MENTOR', is_staff=True)
        self.tutor = User.objects.create_user(email='pt@eduport.com', password='x', full_name='Perm Tutor', role='TUTOR', is_staff=True)
        self.student_user = User.objects.create_user(email='ps@eduport.com', password='x', full_name='Perm Stu', role='STUDENT')
        self.student = Student.objects.create(
            profile=self.student_user, student_code='EDPP', full_name='Perm Stu',
            mentor=self.mentor, tutor=self.tutor, total_class_quota=10, status=StatusChoices.ACTIVE,
        )
        start = timezone.now() + timedelta(days=1)
        self.session = Session.objects.create(
            student=self.student, tutor=self.tutor, title='Perm Class',
            start_time=start, end_time=start + timedelta(hours=1),
            status=SessionStatusChoices.SCHEDULED,
        )
        self.sessions_url = reverse('sessions:sessions-list-create-update')
        self.cancel_series_url = reverse('sessions:cancel-series')

    def test_tutor_put_is_forbidden(self):
        """Even the allocated tutor gets 403 from the generic session PUT."""
        self.client.force_authenticate(user=self.tutor)
        res = self.client.put(
            self.sessions_url,
            {"id": str(self.session.id), "title": "Tutor Edit", "status": "CANCELLED", "cancellation_reason": "x"},
            format='json',
        )
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        self.session.refresh_from_db()
        self.assertEqual(self.session.title, 'Perm Class')
        self.assertEqual(self.session.status, SessionStatusChoices.SCHEDULED)

    def test_tutor_cancel_series_is_forbidden(self):
        """The allocated tutor gets 403 from cancel-series and its alias."""
        self.client.force_authenticate(user=self.tutor)
        payload = {"session_id": str(self.session.id), "cancellation_reason": "tutor tries"}
        for url in (self.cancel_series_url, '/api/sessions/cancel/'):
            res = self.client.post(url, payload, format='json')
            self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN, msg=url)
        self.session.refresh_from_db()
        self.assertEqual(self.session.status, SessionStatusChoices.SCHEDULED)

    def test_staff_status_must_be_a_known_choice(self):
        self.client.force_authenticate(user=self.mentor)
        res = self.client.put(self.sessions_url, {"id": str(self.session.id), "status": "BANANA"}, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.session.refresh_from_db()
        self.assertEqual(self.session.status, SessionStatusChoices.SCHEDULED)

    def test_staff_status_rejects_non_string_values(self):
        self.client.force_authenticate(user=self.mentor)
        for bad in (None, 123, ["ATTENDED"], ""):
            res = self.client.put(self.sessions_url, {"id": str(self.session.id), "status": bad}, format='json')
            self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST, msg=f"status={bad!r}")
        self.session.refresh_from_db()
        self.assertEqual(self.session.status, SessionStatusChoices.SCHEDULED)

    def test_staff_rating_rejects_invalid_values(self):
        self.client.force_authenticate(user=self.mentor)
        for bad in ("great", 4.5, None, True):
            res = self.client.put(self.sessions_url, {"id": str(self.session.id), "rating": bad}, format='json')
            self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST, msg=f"rating={bad!r}")
        self.session.refresh_from_db()
        self.assertIsNone(self.session.rating)

    def test_staff_rating_rejects_out_of_range_values(self):
        self.client.force_authenticate(user=self.mentor)
        for bad in (0, 6, -1, 9):
            res = self.client.put(self.sessions_url, {"id": str(self.session.id), "rating": bad}, format='json')
            self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST, msg=f"rating={bad!r}")
        self.session.refresh_from_db()
        self.assertIsNone(self.session.rating)

    def test_staff_rating_accepts_valid_value(self):
        self.client.force_authenticate(user=self.mentor)
        res = self.client.put(self.sessions_url, {"id": str(self.session.id), "rating": 4}, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.session.refresh_from_db()
        self.assertEqual(self.session.rating, 4)

    def test_mentor_mark_attended_flow_unchanged(self):
        """The hub SPA marks attended via PUT with status + all three links."""
        self.client.force_authenticate(user=self.mentor)
        res = self.client.put(
            self.sessions_url,
            {
                "id": str(self.session.id),
                "status": "ATTENDED",
                "recording_link": "https://example.com/rec",
                "notes_link": "https://example.com/notes",
                "homework_link": "https://example.com/hw",
            },
            format='json',
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.session.refresh_from_db()
        self.assertEqual(self.session.status, SessionStatusChoices.ATTENDED)
        self.assertEqual(self.session.recording_link, 'https://example.com/rec')
        self.assertEqual(self.session.notes_link, 'https://example.com/notes')
        self.assertEqual(self.session.homework_link, 'https://example.com/hw')

    def test_mentor_cancel_with_null_reason_is_rejected(self):
        """A null cancellation_reason is a 400, not a server error."""
        self.client.force_authenticate(user=self.mentor)
        res = self.client.put(
            self.sessions_url,
            {"id": str(self.session.id), "status": "CANCELLED", "cancellation_reason": None},
            format='json',
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.session.refresh_from_db()
        self.assertEqual(self.session.status, SessionStatusChoices.SCHEDULED)

    def test_mentor_cancel_with_reason_still_works(self):
        self.client.force_authenticate(user=self.mentor)
        res = self.client.put(
            self.sessions_url,
            {"id": str(self.session.id), "status": "CANCELLED", "cancellation_reason": "Family emergency"},
            format='json',
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.session.refresh_from_db()
        self.assertEqual(self.session.status, SessionStatusChoices.CANCELLED)
        self.assertEqual(self.session.cancellation_reason, 'Family emergency')
