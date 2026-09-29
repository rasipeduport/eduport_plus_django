import os
import shutil
import tempfile
import uuid
from datetime import timedelta
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.utils import timezone
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from students.models import Student, StatusChoices
from invitations.models import Invitation, InvitationStatusChoices, InvitationRoleChoices
from activity.models import ActivityLog
from sessions.models import Session, SessionStatusChoices, SessionFile

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
            action='user.sign_in', entity_type='profile', entity_id='user_123', entity_label='Test Admin'
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
        # The default feed is a change log: the sign-in is recorded but held back.
        self.assertEqual(res.data['count'], 2)
        self.assertNotIn('user.sign_in', [r['action'] for r in res.data['results']])
        self.assertIn('actor_options', res.data)

        # Test keyword search
        res = self.client.get(self.activity_logs_url, {"q": "Maths"})
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['count'], 1)
        self.assertEqual(res.data['results'][0]['action'], 'session.create')

        # Asking for a sign-in by name still returns it.
        res = self.client.get(self.activity_logs_url, {"action": "user.sign_in"})
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['count'], 1)

        # Test student history filter
        res = self.client.get(self.activity_logs_url, {"student_id": str(self.student.id)})
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['count'], 1)
        self.assertEqual(res.data['results'][0]['entity_label'], 'Maths Session')

        # The mentor may open the feed but only ever sees their own entries:
        # the invitation they sent, not the admin's session on their student.
        self.client.force_authenticate(user=self.mentor)
        res = self.client.get(self.activity_logs_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual([r['action'] for r in res.data['results']], ['invitation.create'])
        res = self.client.get(self.activity_logs_url, {"student_id": str(self.student.id)})
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['count'], 0)

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
        """
        The allocated tutor gets 403 from the generic session PUT for anything
        other than the notes link (see PostSessionWorkflowTests for notes).
        """
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

    def test_session_tutor_change_logs_names_in_changes_and_ids_in_context(self):
        """
        An expanded activity row renders `changes`, so a tutor swap has to read
        "Tutor: A -> B" there. The raw ids stay available in `context`, which is
        how the Hub splits the two.
        """
        replacement = User.objects.create_user(
            email='replacement_tutor@eduport.com',
            password='testpassword',
            full_name='Replacement Tutor',
            role='TUTOR',
            is_staff=True,
        )

        self.client.force_authenticate(user=self.mentor)
        res = self.client.put(
            self.sessions_url,
            {"id": str(self.session.id), "tutor": str(replacement.id)},
            format='json',
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        log = ActivityLog.objects.filter(
            action='session.update', entity_id=str(self.session.id)
        ).first()
        self.assertIsNotNone(log)

        self.assertEqual(
            log.changes["tutor"],
            {"old": self.tutor.full_name, "new": replacement.full_name},
        )
        # Guard against regressing to raw UUIDs in the rendered diff.
        self.assertNotIn(str(self.tutor.id), str(log.changes["tutor"]))
        self.assertNotIn(str(replacement.id), str(log.changes["tutor"]))

        self.assertEqual(log.context.get("old_tutor_id"), str(self.tutor.id))
        self.assertEqual(log.context.get("new_tutor_id"), str(replacement.id))

    def test_session_update_without_tutor_change_carries_no_tutor_ids(self):
        self.client.force_authenticate(user=self.mentor)
        res = self.client.put(
            self.sessions_url,
            {"id": str(self.session.id), "title": "Retitled Class"},
            format='json',
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        log = ActivityLog.objects.filter(
            action='session.update', entity_id=str(self.session.id)
        ).first()
        self.assertIsNotNone(log)
        self.assertNotIn("tutor", log.changes)
        self.assertNotIn("old_tutor_id", log.context or {})


from datetime import datetime, timezone as dt_timezone


class SessionLocalTimeSchedulingTests(APITestCase):
    """
    Hub parity for the "New Session" sheet: a class is entered as the
    student's local wall-clock time plus an IANA zone, and the API converts it
    to the UTC instant (rejecting DST gaps, resolving fall-back repeats to the
    earlier instant). The legacy UTC ``start_time`` shape still works.
    """

    def setUp(self):
        self.mentor = User.objects.create_user(email='tz_mentor@eduport.com', password='x', full_name='Tz Mentor', role='MENTOR', is_staff=True)
        self.tutor = User.objects.create_user(email='tz_tutor@eduport.com', password='x', full_name='Tz Tutor', role='TUTOR', is_staff=True)
        self.student = Student.objects.create(
            profile=User.objects.create_user(email='tz_student@eduport.com', password='x', full_name='Tz Stu', role='STUDENT'),
            student_code='EDPTZ', full_name='Tz Stu', mentor=self.mentor, tutor=self.tutor,
            total_class_quota=10, status=StatusChoices.ACTIVE,
        )
        self.sessions_url = reverse('sessions:sessions-list-create-update')
        self.client.force_authenticate(user=self.mentor)

    def create(self, zone, items, series=False, title='Real Numbers'):
        payload = {"student_id": str(self.student.id), "base_title": title, "series": series, "items": items}
        if zone is not None:
            payload["timezone"] = zone
        return self.client.post(self.sessions_url, payload, format='json')

    def test_local_time_is_converted_in_the_given_zone(self):
        res = self.create('Asia/Dubai', [{"local_date": "2026-10-05", "local_time": "17:00", "duration_hours": 1}])
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
        session = Session.objects.get(id=res.data['sessions'][0]['id'])
        # 5 PM Gulf (UTC+4) is 1 PM UTC; a 1-hour class ends an hour later.
        self.assertEqual(session.start_time, datetime(2026, 10, 5, 13, 0, tzinfo=dt_timezone.utc))
        self.assertEqual(session.end_time, datetime(2026, 10, 5, 14, 0, tzinfo=dt_timezone.utc))

    def test_series_keeps_each_local_start_across_a_clock_change(self):
        # UK clocks go back on 25 Oct 2026: 10:00 BST is 09:00Z, 10:00 GMT is 10:00Z.
        res = self.create('Europe/London', [
            {"local_date": "2026-10-24", "local_time": "10:00", "duration_hours": 1},
            {"local_date": "2026-10-26", "local_time": "10:00", "duration_hours": 1},
        ], series=True)
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
        starts = sorted(Session.objects.filter(student=self.student).values_list('start_time', flat=True))
        self.assertEqual(starts, [
            datetime(2026, 10, 24, 9, 0, tzinfo=dt_timezone.utc),
            datetime(2026, 10, 26, 10, 0, tzinfo=dt_timezone.utc),
        ])
        titles = set(Session.objects.filter(student=self.student).values_list('title', flat=True))
        self.assertEqual(titles, {'Real Numbers - Class 1', 'Real Numbers - Class 2'})

    def test_time_inside_a_spring_forward_gap_is_rejected(self):
        # US clocks jump from 02:00 to 03:00 on 8 Mar 2026, so 02:30 never happens.
        res = self.create('America/New_York', [{"local_date": "2026-03-08", "local_time": "02:30", "duration_hours": 1}])
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('does not exist', res.data['error'])
        self.assertEqual(Session.objects.filter(student=self.student).count(), 0)

    def test_ambiguous_fall_back_time_resolves_to_the_earlier_instant(self):
        # 01:30 on 1 Nov 2026 happens twice in New York; the first (EDT) wins.
        res = self.create('America/New_York', [{"local_date": "2026-11-01", "local_time": "01:30", "duration_hours": 1}])
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
        session = Session.objects.get(id=res.data['sessions'][0]['id'])
        self.assertEqual(session.start_time, datetime(2026, 11, 1, 5, 30, tzinfo=dt_timezone.utc))

    def test_unknown_timezone_is_rejected(self):
        res = self.create('Mars/Olympus_Mons', [{"local_date": "2026-10-05", "local_time": "17:00", "duration_hours": 1}])
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('Unknown time zone', res.data['error'])

    def test_local_time_requires_a_zone_and_both_parts(self):
        res = self.create(None, [{"local_date": "2026-10-05", "local_time": "17:00", "duration_hours": 1}])
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('timezone is required', res.data['error'])

        res = self.create('Asia/Dubai', [{"local_date": "2026-10-05", "duration_hours": 1}])
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('supplied together', res.data['error'])

        res = self.create('Asia/Dubai', [{"local_date": "2026-02-30", "local_time": "17:00", "duration_hours": 1}])
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('not a real date', res.data['error'])

    def test_legacy_utc_start_time_still_accepted(self):
        start = timezone.now() + timedelta(days=3)
        res = self.create(None, [{"start_time": start.isoformat(), "duration_hours": 0.5}])
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)

        res = self.create(None, [{"duration_hours": 0.5}])
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('start_time', res.data['error'])

    def test_title_is_title_cased_like_the_hub(self):
        res = self.create('Asia/Kolkata', [{"local_date": "2026-10-05", "local_time": "09:00", "duration_hours": 1}], title='  real   NUMBERS ')
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
        self.assertEqual(res.data['sessions'][0]['title'], 'Real Numbers')


class SessionMeetLinkExposureTests(APITestCase):
    """
    The Sessions list nests the student's Meet room (students.meet_link) so
    staff can join from the table. It rides on the existing row scoping only:
    a tutor or mentor receives links solely for the students allocated to
    them, a student only their own, and no other endpoint serves it.
    """

    LINK_A = 'https://meet.google.com/aaa-bbbb-ccc'

    def setUp(self):
        self.admin = User.objects.create_user(email='ml_admin@eduport.com', password='x', full_name='Ml Admin', role='ADMIN', is_staff=True)
        self.mentor_a = User.objects.create_user(email='ml_ma@eduport.com', password='x', full_name='Ml Mentor A', role='MENTOR', is_staff=True)
        self.tutor_a = User.objects.create_user(email='ml_ta@eduport.com', password='x', full_name='Ml Tutor A', role='TUTOR', is_staff=True)
        self.tutor_b = User.objects.create_user(email='ml_tb@eduport.com', password='x', full_name='Ml Tutor B', role='TUTOR', is_staff=True)
        self.user_a = User.objects.create_user(email='ml_sa@eduport.com', password='x', full_name='Ml Stu A', role='STUDENT')
        self.user_b = User.objects.create_user(email='ml_sb@eduport.com', password='x', full_name='Ml Stu B', role='STUDENT')
        self.student_a = Student.objects.create(
            profile=self.user_a, student_code='MLA', full_name='Ml Stu A', mentor=self.mentor_a, tutor=self.tutor_a,
            meet_link=self.LINK_A, status=StatusChoices.ACTIVE,
        )
        self.student_b = Student.objects.create(
            profile=self.user_b, student_code='MLB', full_name='Ml Stu B', tutor=self.tutor_b,
            meet_link=None, status=StatusChoices.ACTIVE,
        )
        now = timezone.now()
        for student, tutor in ((self.student_a, self.tutor_a), (self.student_b, self.tutor_b)):
            Session.objects.create(student=student, tutor=tutor, title=f'{student.student_code} class',
                                   start_time=now, end_time=now + timedelta(hours=1))
        self.sessions_url = reverse('sessions:sessions-list-create-update')

    def links_by_student(self, user):
        self.client.force_authenticate(user=user)
        res = self.client.get(self.sessions_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        return {s['students']['student_code']: s['students']['meet_link'] for s in res.data['sessions']}

    def test_each_session_carries_its_own_students_link(self):
        self.assertEqual(self.links_by_student(self.admin), {'MLA': self.LINK_A, 'MLB': None})

    def test_tutor_and_mentor_only_receive_links_for_allocated_students(self):
        self.assertEqual(self.links_by_student(self.tutor_a), {'MLA': self.LINK_A})
        self.assertEqual(self.links_by_student(self.mentor_a), {'MLA': self.LINK_A})
        # Tutor B's only student has no room configured, and Student A's link
        # must not appear anywhere in their payload.
        self.assertEqual(self.links_by_student(self.tutor_b), {'MLB': None})
        res = self.client.get(self.sessions_url)
        self.assertNotIn(self.LINK_A, str(res.data))

    def test_student_only_receives_their_own_link(self):
        self.assertEqual(self.links_by_student(self.user_a), {'MLA': self.LINK_A})
        self.assertEqual(self.links_by_student(self.user_b), {'MLB': None})


class SessionConflictStatusTests(APITestCase):
    """
    Only an active (SCHEDULED) session blocks a slot. An ATTENDED session has
    already happened and a CANCELLED one never will, so neither may stop a
    new single session or a new series from being booked over its time.
    Mirrors the reported case: "Demo2" (Attended, 2:40-4:40 PM) must not
    block a new Scheduled class at 2:15-3:15 PM.
    """

    def setUp(self):
        self.mentor = User.objects.create_user(email='cs_mentor@eduport.com', password='x', full_name='Cs Mentor', role='MENTOR', is_staff=True)
        self.tutor = User.objects.create_user(email='cs_tutor@eduport.com', password='x', full_name='Cs Tutor', role='TUTOR', is_staff=True)
        self.student = Student.objects.create(
            profile=User.objects.create_user(email='cs_student@eduport.com', password='x', full_name='Cs Stu', role='STUDENT'),
            student_code='EDPCS', full_name='Cs Stu', mentor=self.mentor, tutor=self.tutor,
            total_class_quota=10, status=StatusChoices.ACTIVE,
        )
        self.sessions_url = reverse('sessions:sessions-list-create-update')
        self.client.force_authenticate(user=self.mentor)
        # Existing "Demo2": 2:40 PM - 4:40 PM, a few days out.
        self.demo2_start = (timezone.now() + timedelta(days=3)).replace(hour=14, minute=40, second=0, microsecond=0)
        self.demo2_end = self.demo2_start + timedelta(hours=2)
        # Candidate new class: 2:15 PM - 3:15 PM, overlapping Demo2 by 35 minutes.
        self.new_start = self.demo2_start - timedelta(minutes=25)

    def existing(self, status_value):
        return Session.objects.create(
            student=self.student, tutor=self.tutor, title='Demo2',
            start_time=self.demo2_start, end_time=self.demo2_end, status=status_value,
        )

    def book(self, items, series=False, title='Algebra'):
        payload = {"student_id": str(self.student.id), "base_title": title, "series": series, "items": items}
        return self.client.post(self.sessions_url, payload, format='json')

    def book_single(self):
        return self.book([{"start_time": self.new_start.isoformat(), "duration_hours": 1}])

    def test_scheduled_existing_session_blocks_overlapping_new_session(self):
        self.existing(SessionStatusChoices.SCHEDULED)
        res = self.book_single()
        self.assertEqual(res.status_code, status.HTTP_409_CONFLICT)
        self.assertIn('conflicts with "Demo2"', res.data['error'])
        self.assertEqual(Session.objects.filter(title='Algebra').count(), 0)

    def test_attended_existing_session_does_not_block_new_session(self):
        self.existing(SessionStatusChoices.ATTENDED)
        res = self.book_single()
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
        self.assertEqual(len(res.data['sessions']), 1)
        created = Session.objects.get(title='Algebra')
        self.assertEqual(created.status, SessionStatusChoices.SCHEDULED)
        self.assertEqual(created.start_time, self.new_start)

    def test_cancelled_existing_session_does_not_block_new_session(self):
        self.existing(SessionStatusChoices.CANCELLED)
        res = self.book_single()
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
        self.assertEqual(len(res.data['sessions']), 1)
        self.assertEqual(Session.objects.filter(title='Algebra', status=SessionStatusChoices.SCHEDULED).count(), 1)

    def test_series_creation_is_allowed_over_attended_session(self):
        self.existing(SessionStatusChoices.ATTENDED)
        res = self.book([
            {"start_time": self.new_start.isoformat(), "duration_hours": 1},
            {"start_time": (self.new_start + timedelta(days=1)).isoformat(), "duration_hours": 1},
        ], series=True)
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
        self.assertEqual(len(res.data['sessions']), 2)
        created = Session.objects.filter(title__startswith='Algebra - Class').order_by('class_number')
        self.assertEqual([s.title for s in created], ['Algebra - Class 1', 'Algebra - Class 2'])
        self.assertEqual(len({s.series_id for s in created}), 1)

    def test_series_creation_is_still_blocked_by_scheduled_session(self):
        self.existing(SessionStatusChoices.SCHEDULED)
        res = self.book([
            {"start_time": (self.new_start - timedelta(days=1)).isoformat(), "duration_hours": 1},
            {"start_time": self.new_start.isoformat(), "duration_hours": 1},
        ], series=True)
        self.assertEqual(res.status_code, status.HTTP_409_CONFLICT)
        self.assertIn('Class 2 conflicts with "Demo2"', res.data['error'])
        self.assertEqual(Session.objects.filter(title__startswith='Algebra').count(), 0)


class PostSessionWorkflowTests(APITestCase):
    """
    Post-session workflow. Attendance (``status``) and content completion
    (notes + recording + homework) are separate facts: a mentor may mark a
    class attended before its material exists, and the row then reads
    ``display_status == 'pending'`` until the last link lands -- at which
    point it reads ``attended`` with no further action. Tutors own the notes
    link and nothing else. Rating never takes part. Scheduling conflicts are
    covered separately in SessionConflictStatusTests and are unaffected.
    """

    LINKS = {
        "recording_link": "https://example.com/rec",
        "notes_link": "https://example.com/notes",
        "homework_link": "https://example.com/hw",
    }

    def setUp(self):
        self.admin = User.objects.create_user(email='ps_admin@eduport.com', password='x', full_name='Ps Admin', role='ADMIN', is_staff=True)
        self.mentor = User.objects.create_user(email='ps_mentor@eduport.com', password='x', full_name='Ps Mentor', role='MENTOR', is_staff=True)
        self.tutor = User.objects.create_user(email='ps_tutor@eduport.com', password='x', full_name='Ps Tutor', role='TUTOR', is_staff=True)
        self.other_tutor = User.objects.create_user(email='ps_tutor2@eduport.com', password='x', full_name='Ps Tutor Two', role='TUTOR', is_staff=True)
        self.student_user = User.objects.create_user(email='ps_student@eduport.com', password='x', full_name='Ps Stu', role='STUDENT')
        self.student = Student.objects.create(
            profile=self.student_user, student_code='EDPPS1', full_name='Ps Stu',
            mentor=self.mentor, tutor=self.tutor, total_class_quota=20, status=StatusChoices.ACTIVE,
        )
        self.other_student = Student.objects.create(
            profile=User.objects.create_user(email='ps_student2@eduport.com', password='x', full_name='Ps Stu Two', role='STUDENT'),
            student_code='EDPPS2', full_name='Ps Stu Two',
            mentor=self.mentor, tutor=self.other_tutor, total_class_quota=20, status=StatusChoices.ACTIVE,
        )
        self.sessions_url = reverse('sessions:sessions-list-create-update')
        self.next_slot = (timezone.now() + timedelta(days=2)).replace(minute=0, second=0, microsecond=0)

    # -- helpers ---------------------------------------------------------

    def make_session(self, status_value=SessionStatusChoices.SCHEDULED, student=None, title='Demo2', **fields):
        """One session per two-hour slot so nothing in a test overlaps by accident."""
        student = student or self.student
        start = self.next_slot
        self.next_slot = start + timedelta(hours=2)
        return Session.objects.create(
            student=student, tutor=student.tutor, title=title,
            start_time=start, end_time=start + timedelta(hours=1), status=status_value, **fields,
        )

    def put(self, user, payload):
        self.client.force_authenticate(user=user)
        return self.client.put(self.sessions_url, payload, format='json')

    def list_as(self, user, **params):
        self.client.force_authenticate(user=user)
        return self.client.get(self.sessions_url, params)

    def create_payload(self, offset_days=10):
        start = (timezone.now() + timedelta(days=offset_days)).replace(minute=0, second=0, microsecond=0)
        return {
            "student_id": str(self.student.id), "base_title": "Algebra", "series": False,
            "items": [{"start_time": start.isoformat(), "duration_hours": 1}],
        }

    @staticmethod
    def ids(res):
        return {row['id'] for row in res.data['sessions']}

    def row(self, res, session):
        return next(r for r in res.data['sessions'] if r['id'] == str(session.id))

    # -- 1-3: creation permissions ------------------------------------------

    def test_admin_can_create_session(self):
        self.client.force_authenticate(user=self.admin)
        res = self.client.post(self.sessions_url, self.create_payload(), format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
        self.assertEqual(Session.objects.filter(title='Algebra', status=SessionStatusChoices.SCHEDULED).count(), 1)

    def test_mentor_can_create_session(self):
        self.client.force_authenticate(user=self.mentor)
        res = self.client.post(self.sessions_url, self.create_payload(), format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
        self.assertEqual(Session.objects.filter(title='Algebra').count(), 1)

    def test_tutor_cannot_create_session(self):
        self.client.force_authenticate(user=self.tutor)
        res = self.client.post(self.sessions_url, self.create_payload(), format='json')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(Session.objects.filter(title='Algebra').count(), 0)

    # -- 4-7: tutor may add notes and nothing else -----------------------------

    def test_tutor_can_add_notes_to_authorized_session(self):
        session = self.make_session()
        res = self.put(self.tutor, {"id": str(session.id), "notes_link": "  https://example.com/notes "})
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
        session.refresh_from_db()
        self.assertEqual(session.notes_link, 'https://example.com/notes')
        self.assertEqual(session.status, SessionStatusChoices.SCHEDULED)
        self.assertEqual(res.data['session']['notes_link'], 'https://example.com/notes')
        # Same activity entry a mentor's link edit produces -- no parallel log.
        log = ActivityLog.objects.filter(action='session.update_links', entity_id=str(session.id)).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.actor_role, 'TUTOR')
        self.assertEqual(log.changes['notes_link'], {"old": None, "new": 'https://example.com/notes'})
        self.assertEqual(ActivityLog.objects.filter(entity_id=str(session.id)).count(), 1)

    def test_tutor_can_update_existing_notes(self):
        session = self.make_session(notes_link='https://example.com/old')
        res = self.put(self.tutor, {"id": str(session.id), "notes_link": "https://example.com/new"})
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
        session.refresh_from_db()
        self.assertEqual(session.notes_link, 'https://example.com/new')

    def test_tutor_cannot_add_notes_for_another_tutors_student(self):
        session = self.make_session(student=self.other_student)
        res = self.put(self.tutor, {"id": str(session.id), "notes_link": "https://example.com/notes"})
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        session.refresh_from_db()
        self.assertIsNone(session.notes_link)

    def test_tutor_cannot_add_notes_to_cancelled_session(self):
        session = self.make_session(SessionStatusChoices.CANCELLED, cancellation_reason='x')
        res = self.put(self.tutor, {"id": str(session.id), "notes_link": "https://example.com/notes"})
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        session.refresh_from_db()
        self.assertIsNone(session.notes_link)

    def test_tutor_notes_require_a_value(self):
        session = self.make_session()
        for bad in ("", "   ", None, 123):
            res = self.put(self.tutor, {"id": str(session.id), "notes_link": bad})
            self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST, msg=f"notes_link={bad!r}")
        res = self.put(self.tutor, {"id": str(session.id)})
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        session.refresh_from_db()
        self.assertIsNone(session.notes_link)
        self.assertFalse(ActivityLog.objects.filter(entity_id=str(session.id)).exists())

    def test_tutor_cannot_add_recording(self):
        session = self.make_session()
        res = self.put(self.tutor, {"id": str(session.id), "recording_link": "https://example.com/rec"})
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        session.refresh_from_db()
        self.assertIsNone(session.recording_link)

    def test_tutor_cannot_add_homework(self):
        session = self.make_session()
        res = self.put(self.tutor, {"id": str(session.id), "homework_link": "https://example.com/hw"})
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        session.refresh_from_db()
        self.assertIsNone(session.homework_link)

    def test_tutor_cannot_mark_session_attended(self):
        session = self.make_session()
        # Smuggling the status in next to a legitimate notes link is refused as
        # a whole: nothing is written.
        res = self.put(self.tutor, {"id": str(session.id), "status": "ATTENDED", "notes_link": "https://example.com/notes"})
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        res = self.put(self.tutor, {"id": str(session.id), "status": "ATTENDED"})
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        session.refresh_from_db()
        self.assertEqual(session.status, SessionStatusChoices.SCHEDULED)
        self.assertIsNone(session.notes_link)

    # -- 8-13: mentor adds recording/homework and marks attended ---------------

    def test_mentor_can_add_recording(self):
        session = self.make_session()
        res = self.put(self.mentor, {"id": str(session.id), "recording_link": "https://example.com/rec"})
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
        session.refresh_from_db()
        self.assertEqual(session.recording_link, 'https://example.com/rec')
        self.assertTrue(ActivityLog.objects.filter(action='session.update_links', entity_id=str(session.id)).exists())

    def test_mentor_can_add_homework(self):
        session = self.make_session()
        res = self.put(self.mentor, {"id": str(session.id), "homework_link": "https://example.com/hw"})
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
        session.refresh_from_db()
        self.assertEqual(session.homework_link, 'https://example.com/hw')

    def test_mentor_can_mark_attended_with_all_content_present(self):
        session = self.make_session(**self.LINKS)
        res = self.put(self.mentor, {"id": str(session.id), "status": "ATTENDED"})
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
        session.refresh_from_db()
        self.assertEqual(session.status, SessionStatusChoices.ATTENDED)
        self.assertEqual(res.data['session']['status'], 'attended')
        self.assertEqual(res.data['session']['display_status'], 'attended')
        self.assertTrue(res.data['session']['content_complete'])
        self.assertEqual(res.data['session']['missing_content'], [])
        self.assertTrue(ActivityLog.objects.filter(action='session.mark_attended', entity_id=str(session.id)).exists())

    def _mark_attended_missing(self, missing_key):
        links = {k: v for k, v in self.LINKS.items() if k != f"{missing_key}_link"}
        session = self.make_session(**links)
        res = self.put(self.mentor, {"id": str(session.id), "status": "ATTENDED"})
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
        session.refresh_from_db()
        self.assertEqual(session.status, SessionStatusChoices.ATTENDED)
        self.assertIsNone(getattr(session, f"{missing_key}_link"))
        self.assertEqual(res.data['session']['status'], 'attended')
        self.assertEqual(res.data['session']['display_status'], 'pending')
        self.assertFalse(res.data['session']['content_complete'])
        self.assertEqual(res.data['session']['missing_content'], [missing_key])
        return session

    def test_mentor_can_mark_attended_with_notes_missing(self):
        self._mark_attended_missing('notes')

    def test_mentor_can_mark_attended_with_recording_missing(self):
        self._mark_attended_missing('recording')

    def test_mentor_can_mark_attended_with_homework_missing(self):
        self._mark_attended_missing('homework')

    def test_mentor_can_mark_attended_with_nothing_present(self):
        session = self.make_session()
        res = self.put(self.mentor, {"id": str(session.id), "status": "ATTENDED"})
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
        self.assertEqual(res.data['session']['display_status'], 'pending')
        self.assertEqual(res.data['session']['missing_content'], ['notes', 'recording', 'homework'])

    def test_mark_attended_can_carry_recording_and_homework(self):
        """The SPA's Mark Attended sends the mentor's two links in the same call."""
        session = self.make_session()
        res = self.put(self.mentor, {
            "id": str(session.id), "status": "ATTENDED",
            "recording_link": self.LINKS['recording_link'], "homework_link": self.LINKS['homework_link'],
        })
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
        self.assertEqual(res.data['session']['missing_content'], ['notes'])
        self.assertEqual(res.data['session']['display_status'], 'pending')
        # One activity entry: the mark-attended, with the links in its diff.
        logs = ActivityLog.objects.filter(entity_id=str(session.id))
        self.assertEqual(logs.count(), 1)
        self.assertEqual(logs[0].action, 'session.mark_attended')
        self.assertIn('recording_link', logs[0].changes)

    # -- 14-17: derived display state -------------------------------------------

    def test_attended_with_missing_content_reads_pending_in_list(self):
        session = self.make_session(SessionStatusChoices.ATTENDED, recording_link=self.LINKS['recording_link'], homework_link=self.LINKS['homework_link'])
        for user in (self.admin, self.mentor, self.tutor):
            row = self.row(self.list_as(user), session)
            self.assertEqual(row['status'], 'attended', msg=user.role)
            self.assertEqual(row['display_status'], 'pending', msg=user.role)
            self.assertEqual(row['missing_content'], ['notes'], msg=user.role)
            self.assertFalse(row['content_complete'], msg=user.role)

    def test_attended_with_all_content_reads_attended(self):
        session = self.make_session(SessionStatusChoices.ATTENDED, **self.LINKS)
        row = self.row(self.list_as(self.admin), session)
        self.assertEqual(row['display_status'], 'attended')
        self.assertTrue(row['content_complete'])
        self.assertEqual(row['missing_content'], [])

    def test_scheduled_and_cancelled_are_never_pending(self):
        scheduled = self.make_session(SessionStatusChoices.SCHEDULED)
        cancelled = self.make_session(SessionStatusChoices.CANCELLED, cancellation_reason='x')
        res = self.list_as(self.admin)
        self.assertEqual(self.row(res, scheduled)['display_status'], 'scheduled')
        self.assertEqual(self.row(res, cancelled)['display_status'], 'cancelled')

    def test_adding_final_missing_field_flips_pending_to_attended(self):
        session = self.make_session(SessionStatusChoices.ATTENDED, recording_link=self.LINKS['recording_link'], homework_link=self.LINKS['homework_link'])
        self.assertEqual(self.row(self.list_as(self.mentor), session)['display_status'], 'pending')
        res = self.put(self.tutor, {"id": str(session.id), "notes_link": self.LINKS['notes_link']})
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
        self.assertEqual(res.data['session']['display_status'], 'attended')
        self.assertTrue(res.data['session']['content_complete'])
        # Nothing but the link was written: attendance stays as the mentor set it.
        session.refresh_from_db()
        self.assertEqual(session.status, SessionStatusChoices.ATTENDED)
        row = self.row(self.list_as(self.mentor), session)
        self.assertEqual(row['display_status'], 'attended')
        self.assertEqual(row['missing_content'], [])

    def test_mentor_adding_final_missing_field_flips_pending_to_attended(self):
        session = self.make_session(SessionStatusChoices.ATTENDED, notes_link=self.LINKS['notes_link'], recording_link=self.LINKS['recording_link'])
        res = self.put(self.mentor, {"id": str(session.id), "homework_link": self.LINKS['homework_link']})
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
        self.assertEqual(res.data['session']['display_status'], 'attended')

    def test_rating_does_not_affect_completion(self):
        unrated_complete = self.make_session(SessionStatusChoices.ATTENDED, **self.LINKS)
        rated_incomplete = self.make_session(SessionStatusChoices.ATTENDED, rating=5, recording_link=self.LINKS['recording_link'], homework_link=self.LINKS['homework_link'])
        res = self.list_as(self.admin)
        self.assertEqual(self.row(res, unrated_complete)['display_status'], 'attended')
        self.assertIsNone(self.row(res, unrated_complete)['rating'])
        self.assertEqual(self.row(res, rated_incomplete)['display_status'], 'pending')
        # A student rating an incomplete class does not complete it either.
        self.client.force_authenticate(user=self.student_user)
        res = self.client.put(self.sessions_url, {"id": str(rated_incomplete.id), "rating": 3}, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
        self.assertEqual(res.data['session']['display_status'], 'pending')

    def test_student_list_carries_content_state(self):
        """The Learn app shows each attended class's missing material from the same fields."""
        session = self.make_session(SessionStatusChoices.ATTENDED, notes_link=self.LINKS['notes_link'])
        row = self.row(self.list_as(self.student_user), session)
        self.assertEqual(row['status'], 'attended')
        self.assertEqual(row['missing_content'], ['recording', 'homework'])

    def test_blank_links_are_stored_as_null(self):
        """Whitespace-only links are 'missing', not 'available' -- one representation for empty."""
        session = self.make_session(SessionStatusChoices.ATTENDED, **self.LINKS)
        res = self.put(self.mentor, {"id": str(session.id), "recording_link": "   ", "homework_link": ""})
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
        session.refresh_from_db()
        self.assertIsNone(session.recording_link)
        self.assertIsNone(session.homework_link)
        self.assertEqual(res.data['session']['missing_content'], ['recording', 'homework'])
        self.assertEqual(res.data['session']['display_status'], 'pending')

    def test_staff_links_must_be_strings_or_null(self):
        session = self.make_session()
        res = self.put(self.mentor, {"id": str(session.id), "recording_link": 42})
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    # -- 21-25: ?content= filter ------------------------------------------------

    def seed_content_matrix(self):
        L = self.LINKS
        self.s_complete = self.make_session(SessionStatusChoices.ATTENDED, title='Complete', **L)
        self.s_no_notes = self.make_session(SessionStatusChoices.ATTENDED, title='No Notes', recording_link=L['recording_link'], homework_link=L['homework_link'])
        self.s_no_rec = self.make_session(SessionStatusChoices.ATTENDED, title='No Rec', notes_link=L['notes_link'], homework_link=L['homework_link'])
        self.s_no_hw = self.make_session(SessionStatusChoices.ATTENDED, title='No Hw', notes_link=L['notes_link'], recording_link=L['recording_link'])
        self.s_nothing = self.make_session(SessionStatusChoices.ATTENDED, title='Nothing')
        # Scheduled / cancelled classes with no links must never count as missing.
        self.s_scheduled = self.make_session(SessionStatusChoices.SCHEDULED, title='Upcoming')
        self.s_cancelled = self.make_session(SessionStatusChoices.CANCELLED, title='Gone', cancellation_reason='x')
        # Another tutor's student, missing everything: visible to admin, not to self.tutor.
        self.s_other = self.make_session(SessionStatusChoices.ATTENDED, student=self.other_student, title='Other')

    def sid(self, *sessions):
        return {str(s.id) for s in sessions}

    def test_missing_notes_filter(self):
        self.seed_content_matrix()
        res = self.list_as(self.admin, content='missing_notes')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(self.ids(res), self.sid(self.s_no_notes, self.s_nothing, self.s_other))

    def test_missing_recording_filter(self):
        self.seed_content_matrix()
        res = self.list_as(self.admin, content='missing_recording')
        self.assertEqual(self.ids(res), self.sid(self.s_no_rec, self.s_nothing, self.s_other))

    def test_missing_homework_filter(self):
        self.seed_content_matrix()
        res = self.list_as(self.admin, content='missing_homework')
        self.assertEqual(self.ids(res), self.sid(self.s_no_hw, self.s_nothing, self.s_other))

    def test_missing_content_filter(self):
        self.seed_content_matrix()
        res = self.list_as(self.admin, content='missing_content')
        self.assertEqual(self.ids(res), self.sid(self.s_no_notes, self.s_no_rec, self.s_no_hw, self.s_nothing, self.s_other))
        for row in res.data['sessions']:
            self.assertEqual(row['display_status'], 'pending')

    def test_complete_content_filter(self):
        self.seed_content_matrix()
        res = self.list_as(self.admin, content='complete')
        self.assertEqual(self.ids(res), self.sid(self.s_complete))
        self.assertEqual(res.data['sessions'][0]['display_status'], 'attended')

    def test_content_filter_keeps_role_scoping(self):
        self.seed_content_matrix()
        res = self.list_as(self.tutor, content='missing_content')
        self.assertEqual(self.ids(res), self.sid(self.s_no_notes, self.s_no_rec, self.s_no_hw, self.s_nothing))
        res = self.list_as(self.other_tutor, content='missing_notes')
        self.assertEqual(self.ids(res), self.sid(self.s_other))

    def test_content_filter_unknown_value_is_400_and_blank_is_ignored(self):
        self.seed_content_matrix()
        res = self.list_as(self.admin, content='banana')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        res = self.list_as(self.admin, content='')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res.data['sessions']), 8)

    def test_content_filter_applies_before_pagination(self):
        self.seed_content_matrix()
        res = self.list_as(self.admin, content='missing_content', page=1, page_size=2)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['count'], 5)
        self.assertEqual(len(res.data['sessions']), 2)

    # -- 26-28: scheduling is independent of the content state -------------------
    # (SessionConflictStatusTests already covers attended / cancelled / scheduled;
    # this pins down that a *pending* attended class is no different.)

    def test_pending_attended_session_does_not_block_new_session(self):
        pending = self.make_session(SessionStatusChoices.ATTENDED)  # attended, nothing uploaded
        self.assertEqual(pending.display_status, 'pending')
        self.client.force_authenticate(user=self.mentor)
        payload = {
            "student_id": str(self.student.id), "base_title": "Over Pending", "series": False,
            "items": [{"start_time": (pending.start_time + timedelta(minutes=15)).isoformat(), "duration_hours": 1}],
        }
        res = self.client.post(self.sessions_url, payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)

    def test_scheduled_session_still_blocks_reschedule_onto_it(self):
        blocker = self.make_session(SessionStatusChoices.SCHEDULED, title='Blocker')
        other = self.make_session(SessionStatusChoices.SCHEDULED, title='Mover')
        res = self.put(self.mentor, {"id": str(other.id), "start_time": blocker.start_time.isoformat(), "duration_hours": 1})
        self.assertEqual(res.status_code, status.HTTP_409_CONFLICT)


_MEDIA_TMP = tempfile.mkdtemp(prefix='eduplus-test-media-')

PDF_BYTES = b'%PDF-1.4\n1 0 obj << /Type /Catalog >> endobj\n%%EOF\n'
PNG_BYTES = b'\x89PNG\r\n\x1a\n' + b'\x00' * 64
MP4_BYTES = b'\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom' + bytes(range(256)) * 4


@override_settings(MEDIA_ROOT=_MEDIA_TMP)
class SessionContentUploadTests(APITestCase):
    """
    File uploads for the three content links. An upload stores the bytes
    under MEDIA_ROOT, writes the authenticated download URL into the same
    link column a pasted URL would use, and from then on counts as
    "available" for Pending/Attended and the ?content= filter exactly like a
    URL. Who may upload to a field mirrors who may set that link via PUT.
    """

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(_MEDIA_TMP, ignore_errors=True)

    def setUp(self):
        self.admin = User.objects.create_user(email='up_admin@eduport.com', password='x', full_name='Up Admin', role='ADMIN', is_staff=True)
        self.mentor = User.objects.create_user(email='up_mentor@eduport.com', password='x', full_name='Up Mentor', role='MENTOR', is_staff=True)
        self.other_mentor = User.objects.create_user(email='up_mentor2@eduport.com', password='x', full_name='Up Mentor Two', role='MENTOR', is_staff=True)
        self.tutor = User.objects.create_user(email='up_tutor@eduport.com', password='x', full_name='Up Tutor', role='TUTOR', is_staff=True)
        self.other_tutor = User.objects.create_user(email='up_tutor2@eduport.com', password='x', full_name='Up Tutor Two', role='TUTOR', is_staff=True)
        self.student_user = User.objects.create_user(email='up_student@eduport.com', password='x', full_name='Up Stu', role='STUDENT')
        self.other_student_user = User.objects.create_user(email='up_student2@eduport.com', password='x', full_name='Up Stu Two', role='STUDENT')
        self.student = Student.objects.create(
            profile=self.student_user, student_code='EDPUP1', full_name='Up Stu',
            mentor=self.mentor, tutor=self.tutor, total_class_quota=20, status=StatusChoices.ACTIVE,
        )
        self.other_student = Student.objects.create(
            profile=self.other_student_user, student_code='EDPUP2', full_name='Up Stu Two',
            mentor=self.other_mentor, tutor=self.other_tutor, total_class_quota=20, status=StatusChoices.ACTIVE,
        )
        start = timezone.now() - timedelta(days=1)
        self.session = Session.objects.create(
            student=self.student, tutor=self.tutor, title='Upload Class',
            start_time=start, end_time=start + timedelta(hours=1), status=SessionStatusChoices.ATTENDED,
        )
        self.sessions_url = reverse('sessions:sessions-list-create-update')

    # -- helpers ---------------------------------------------------------

    def upload_url(self, field, session=None):
        return reverse('sessions:session-file-upload', args=[(session or self.session).id, field])

    def upload(self, user, field, name='notes.pdf', content=PDF_BYTES, content_type='application/pdf', session=None):
        self.client.force_authenticate(user=user)
        payload = {'file': SimpleUploadedFile(name, content, content_type=content_type)}
        return self.client.post(self.upload_url(field, session), payload, format='multipart')

    def download(self, user, file_id, **headers):
        self.client.force_authenticate(user=user)
        return self.client.get(reverse('sessions:session-file', args=[file_id]), **headers)

    @staticmethod
    def stored_path(session_file):
        return session_file.file.path

    # -- upload: happy paths & permissions ---------------------------------

    def test_tutor_upload_notes_pdf_sets_link_and_stores_file(self):
        res = self.upload(self.tutor, 'notes')
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
        sf = SessionFile.objects.get(session=self.session, field='notes')
        self.assertEqual(sf.file_name, 'notes.pdf')
        self.assertEqual(sf.content_type, 'application/pdf')
        self.assertEqual(sf.size_bytes, len(PDF_BYTES))
        self.assertEqual(sf.uploaded_by, self.tutor)
        self.assertTrue(os.path.exists(self.stored_path(sf)))
        self.assertTrue(self.stored_path(sf).startswith(_MEDIA_TMP))
        with open(self.stored_path(sf), 'rb') as fh:
            self.assertEqual(fh.read(), PDF_BYTES)

        self.session.refresh_from_db()
        expected_link = 'http://testserver' + reverse('sessions:session-file', args=[sf.id])
        self.assertEqual(self.session.notes_link, expected_link)
        self.assertTrue(sf.matches_link(self.session.notes_link))

        body = res.data['session']
        self.assertEqual(body['notes_link'], expected_link)
        self.assertEqual(body['content_files']['notes']['file_name'], 'notes.pdf')
        self.assertEqual(body['content_files']['notes']['url'], expected_link)
        self.assertIsNone(body['content_files']['recording'])
        self.assertEqual(res.data['file']['url'], expected_link)

        log = ActivityLog.objects.get(action='session.update_links', entity_id=str(self.session.id))
        self.assertEqual(log.actor_role, 'TUTOR')
        self.assertEqual(log.changes['notes_link'], {"old": None, "new": expected_link})
        self.assertEqual(log.context['uploaded_file'], 'notes.pdf')

    def test_mentor_uploads_recording_video_and_homework_image(self):
        res = self.upload(self.mentor, 'recording', name='class.mp4', content=MP4_BYTES, content_type='video/mp4')
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
        res = self.upload(self.mentor, 'homework', name='hw.png', content=PNG_BYTES, content_type='image/png')
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
        self.session.refresh_from_db()
        files = {sf.field: sf for sf in self.session.files.all()}
        self.assertEqual(set(files), {'recording', 'homework'})
        self.assertEqual(files['recording'].content_type, 'video/mp4')
        self.assertEqual(files['recording'].extension, '.mp4')
        self.assertTrue(files['recording'].matches_link(self.session.recording_link))
        self.assertTrue(files['homework'].matches_link(self.session.homework_link))

    def test_admin_can_upload_any_field(self):
        for field, name, content, ctype in (
            ('notes', 'n.pdf', PDF_BYTES, 'application/pdf'),
            ('recording', 'r.mp4', MP4_BYTES, 'video/mp4'),
            ('homework', 'h.png', PNG_BYTES, 'image/png'),
        ):
            res = self.upload(self.admin, field, name=name, content=content, content_type=ctype)
            self.assertEqual(res.status_code, status.HTTP_200_OK, (field, res.data))

    def test_tutor_cannot_upload_recording_or_homework(self):
        for field in ('recording', 'homework'):
            res = self.upload(self.tutor, field, name='x.png', content=PNG_BYTES, content_type='image/png')
            self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN, field)
        self.assertFalse(SessionFile.objects.exists())

    def test_tutor_cannot_upload_notes_for_another_tutors_student(self):
        start = timezone.now() - timedelta(days=1)
        other = Session.objects.create(
            student=self.other_student, tutor=self.other_tutor, title='Other',
            start_time=start, end_time=start + timedelta(hours=1), status=SessionStatusChoices.ATTENDED,
        )
        res = self.upload(self.tutor, 'notes', session=other)
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(SessionFile.objects.exists())

    def test_other_mentor_and_student_cannot_upload(self):
        res = self.upload(self.other_mentor, 'recording', name='r.mp4', content=MP4_BYTES, content_type='video/mp4')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        res = self.upload(self.student_user, 'notes')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(SessionFile.objects.exists())

    # -- upload: validation ---------------------------------------------------

    def test_unsupported_type_is_rejected(self):
        res = self.upload(self.mentor, 'homework', name='hw.txt', content=b'hello', content_type='text/plain')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('Unsupported file type', res.data['error'])
        res = self.upload(self.mentor, 'homework', name='hw.html', content=b'<html>', content_type='text/html')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(SessionFile.objects.exists())

    def test_mislabelled_file_is_rejected(self):
        """A renamed HTML file declared as a PDF must not be stored and served back as one."""
        res = self.upload(self.mentor, 'homework', name='hw.pdf', content=b'<html><script>1</script>', content_type='application/pdf')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('does not look like', res.data['error'])
        res = self.upload(self.mentor, 'homework', name='pic.png', content=PDF_BYTES, content_type='image/png')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(SessionFile.objects.exists())

    def test_size_limit_per_kind(self):
        with override_settings(SESSION_CONTENT_MAX_BYTES={'document': 10, 'image': 10, 'video': 10 * 1024}):
            res = self.upload(self.mentor, 'homework', name='big.pdf', content=PDF_BYTES, content_type='application/pdf')
            self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertIn('larger than', res.data['error'])
            res = self.upload(self.mentor, 'recording', name='v.mp4', content=MP4_BYTES, content_type='video/mp4')
            self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)

    def test_missing_file_empty_file_unknown_field_and_cancelled_session(self):
        self.client.force_authenticate(user=self.mentor)
        res = self.client.post(self.upload_url('notes'), {}, format='multipart')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        res = self.upload(self.mentor, 'notes', content=b'')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        res = self.upload(self.mentor, 'rating')
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)
        self.session.status = SessionStatusChoices.CANCELLED
        self.session.cancellation_reason = 'x'
        self.session.save()
        res = self.upload(self.mentor, 'notes')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(SessionFile.objects.exists())

    def test_reupload_replaces_previous_file(self):
        self.upload(self.mentor, 'homework', name='v1.png', content=PNG_BYTES, content_type='image/png')
        first = SessionFile.objects.get(session=self.session, field='homework')
        first_path = self.stored_path(first)
        res = self.upload(self.mentor, 'homework', name='v2.pdf', content=PDF_BYTES, content_type='application/pdf')
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
        self.assertEqual(SessionFile.objects.filter(session=self.session, field='homework').count(), 1)
        second = SessionFile.objects.get(session=self.session, field='homework')
        self.assertNotEqual(first.id, second.id)
        self.assertFalse(os.path.exists(first_path))
        self.assertTrue(os.path.exists(self.stored_path(second)))
        self.session.refresh_from_db()
        self.assertTrue(second.matches_link(self.session.homework_link))

    # -- download -------------------------------------------------------------

    def test_download_streams_inline_to_allowed_users(self):
        self.upload(self.mentor, 'recording', name='class.mp4', content=MP4_BYTES, content_type='video/mp4')
        sf = SessionFile.objects.get(field='recording')
        for user in (self.admin, self.mentor, self.tutor, self.student_user):
            res = self.download(user, sf.id)
            self.assertEqual(res.status_code, status.HTTP_200_OK, user.role)
            self.assertEqual(res['Content-Type'], 'video/mp4')
            self.assertEqual(res['Content-Length'], str(len(MP4_BYTES)))
            self.assertEqual(res['Accept-Ranges'], 'bytes')
            self.assertTrue(res['Content-Disposition'].startswith('inline;'))
            self.assertIn('class.mp4', res['Content-Disposition'])
            self.assertEqual(res['X-Content-Type-Options'], 'nosniff')
            self.assertEqual(b''.join(res.streaming_content), MP4_BYTES)

    def test_download_is_denied_outside_the_session_scope(self):
        self.upload(self.mentor, 'notes')
        sf = SessionFile.objects.get(field='notes')
        for user in (self.other_mentor, self.other_tutor, self.other_student_user):
            res = self.download(user, sf.id)
            self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN, user.email)
        self.client.force_authenticate(user=None)
        res = self.client.get(reverse('sessions:session-file', args=[sf.id]))
        self.assertIn(res.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))
        res = self.download(self.admin, uuid.uuid4())
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_download_honours_byte_ranges(self):
        self.upload(self.mentor, 'recording', name='class.mp4', content=MP4_BYTES, content_type='video/mp4')
        sf = SessionFile.objects.get(field='recording')
        size = len(MP4_BYTES)

        res = self.download(self.student_user, sf.id, HTTP_RANGE='bytes=10-19')
        self.assertEqual(res.status_code, 206)
        self.assertEqual(res['Content-Range'], f'bytes 10-19/{size}')
        self.assertEqual(res['Content-Length'], '10')
        self.assertEqual(b''.join(res.streaming_content), MP4_BYTES[10:20])

        res = self.download(self.student_user, sf.id, HTTP_RANGE='bytes=100-')
        self.assertEqual(res.status_code, 206)
        self.assertEqual(b''.join(res.streaming_content), MP4_BYTES[100:])
        self.assertEqual(res['Content-Range'], f'bytes 100-{size - 1}/{size}')

        res = self.download(self.student_user, sf.id, HTTP_RANGE='bytes=-5')
        self.assertEqual(res.status_code, 206)
        self.assertEqual(b''.join(res.streaming_content), MP4_BYTES[-5:])

        res = self.download(self.student_user, sf.id, HTTP_RANGE=f'bytes={size + 5}-')
        self.assertEqual(res.status_code, 416)
        self.assertEqual(res['Content-Range'], f'bytes */{size}')

    # -- interplay with the link columns & completion ---------------------------

    def test_upload_counts_as_available_for_completion_and_filters(self):
        self.session.recording_link = 'https://example.com/rec'
        self.session.homework_link = 'https://drive.google.com/hw'
        self.session.save()
        self.client.force_authenticate(user=self.mentor)
        before = self.client.get(self.sessions_url).data['sessions'][0]
        self.assertEqual(before['display_status'], 'pending')
        self.assertEqual(before['missing_content'], ['notes'])

        res = self.upload(self.tutor, 'notes')
        self.assertEqual(res.data['session']['display_status'], 'attended')
        self.assertTrue(res.data['session']['content_complete'])

        self.client.force_authenticate(user=self.mentor)
        self.assertEqual(len(self.client.get(self.sessions_url, {'content': 'missing_notes'}).data['sessions']), 0)
        self.assertEqual(len(self.client.get(self.sessions_url, {'content': 'complete'}).data['sessions']), 1)

    def test_mixed_uploads_and_url_complete_the_session(self):
        """Notes = uploaded PDF, Recording = uploaded video, Homework = Drive URL -> Attended."""
        self.upload(self.tutor, 'notes')
        self.upload(self.mentor, 'recording', name='class.mp4', content=MP4_BYTES, content_type='video/mp4')
        self.client.force_authenticate(user=self.mentor)
        res = self.client.put(self.sessions_url, {"id": str(self.session.id), "homework_link": "https://drive.google.com/hw"}, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
        self.assertEqual(res.data['session']['display_status'], 'attended')
        self.assertEqual(res.data['session']['missing_content'], [])
        self.assertEqual(SessionFile.objects.filter(session=self.session).count(), 2)

    def test_replacing_an_upload_with_a_url_removes_the_file(self):
        self.upload(self.mentor, 'homework', name='hw.png', content=PNG_BYTES, content_type='image/png')
        sf = SessionFile.objects.get(field='homework')
        path = self.stored_path(sf)
        self.client.force_authenticate(user=self.mentor)
        res = self.client.put(self.sessions_url, {"id": str(self.session.id), "homework_link": "https://classroom.google.com/hw"}, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
        self.assertFalse(SessionFile.objects.filter(id=sf.id).exists())
        self.assertFalse(os.path.exists(path))
        self.assertIsNone(res.data['session']['content_files']['homework'])
        self.assertEqual(res.data['session']['homework_link'], 'https://classroom.google.com/hw')

    def test_saving_the_same_file_url_back_keeps_the_upload(self):
        """The links dialog re-sends unchanged fields; that must not drop the upload."""
        self.upload(self.mentor, 'homework', name='hw.png', content=PNG_BYTES, content_type='image/png')
        sf = SessionFile.objects.get(field='homework')
        self.session.refresh_from_db()
        self.client.force_authenticate(user=self.mentor)
        res = self.client.put(
            self.sessions_url,
            {"id": str(self.session.id), "homework_link": self.session.homework_link, "recording_link": "https://example.com/rec"},
            format='json',
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
        self.assertTrue(SessionFile.objects.filter(id=sf.id).exists())
        self.assertTrue(os.path.exists(self.stored_path(sf)))

    def test_clearing_the_link_and_tutor_url_replace_remove_uploads(self):
        self.upload(self.tutor, 'notes')
        sf = SessionFile.objects.get(field='notes')
        path = self.stored_path(sf)
        self.client.force_authenticate(user=self.tutor)
        res = self.client.put(self.sessions_url, {"id": str(self.session.id), "notes_link": "https://docs.google.com/n"}, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
        self.assertFalse(SessionFile.objects.filter(id=sf.id).exists())
        self.assertFalse(os.path.exists(path))

        self.upload(self.mentor, 'recording', name='r.mp4', content=MP4_BYTES, content_type='video/mp4')
        sf = SessionFile.objects.get(field='recording')
        path = self.stored_path(sf)
        self.client.force_authenticate(user=self.mentor)
        res = self.client.put(self.sessions_url, {"id": str(self.session.id), "recording_link": None}, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
        self.assertFalse(SessionFile.objects.filter(id=sf.id).exists())
        self.assertFalse(os.path.exists(path))
        self.assertEqual(res.data['session']['missing_content'], ['recording', 'homework'])

    def test_deleting_the_session_removes_its_files(self):
        self.upload(self.tutor, 'notes')
        self.upload(self.mentor, 'homework', name='hw.png', content=PNG_BYTES, content_type='image/png')
        paths = [self.stored_path(sf) for sf in SessionFile.objects.filter(session=self.session)]
        self.assertEqual(len(paths), 2)
        self.session.delete()
        self.assertFalse(SessionFile.objects.exists())
        for path in paths:
            self.assertFalse(os.path.exists(path))

    def test_url_links_are_untouched_by_the_upload_machinery(self):
        self.client.force_authenticate(user=self.mentor)
        res = self.client.put(self.sessions_url, {"id": str(self.session.id), "recording_link": "https://example.com/rec"}, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
        self.assertEqual(res.data['session']['recording_link'], 'https://example.com/rec')
        self.assertEqual(res.data['session']['content_files'], {'notes': None, 'recording': None, 'homework': None})
        self.assertFalse(SessionFile.objects.exists())
