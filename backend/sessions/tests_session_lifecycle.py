"""
Start Session and the completion a tutor's notes make (sessions.lifecycle),
and the session edits that may no longer touch a started, past or attended
class (sessions.views, the reassignment views).

A class is started by its assigned tutor, the student's mentor or an
administrator, from 5 minutes before its scheduled start until its scheduled
end, by the server's clock; a start opens the tutor's notes and never
completes it on its own. It is completed only by its assigned tutor's own
notes submitted after its originally scheduled end on a class someone
started, however long after (tests_session_outcomes); staff
attendance, notes and recordings never complete it; and it always counts as
the class that was booked. A tutor whose student moved on keeps their own
classes to complete.
"""
import shutil
import tempfile
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from activity.models import ActivityLog
from homework.models import Homework
from students.models import StatusChoices, Student

from . import lifecycle
from .models import Session, SessionStatusChoices

User = get_user_model()

SCHEDULED = SessionStatusChoices.SCHEDULED
ATTENDED = SessionStatusChoices.ATTENDED
CANCELLED = SessionStatusChoices.CANCELLED

PDF_BYTES = b'%PDF-1.4\n1 0 obj << /Type /Catalog >> endobj\n%%EOF\n'
_MEDIA_TMP = tempfile.mkdtemp(prefix='session-lifecycle-media-')


@override_settings(MEDIA_ROOT=_MEDIA_TMP)
class SessionLifecycleWorld(APITestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(_MEDIA_TMP, ignore_errors=True)

    def setUp(self):
        def staff(email, name, role):
            return User.objects.create_user(email=email, password='x', full_name=name, role=role, is_staff=role != 'STUDENT')

        self.admin = staff('lc_admin@eduport.com', 'Lc Admin', 'ADMIN')
        self.mentor = staff('lc_mentor@eduport.com', 'Lc Mentor', 'MENTOR')
        self.other_mentor = staff('lc_mentor2@eduport.com', 'Lc Mentor Two', 'MENTOR')
        self.tutor = staff('lc_tutor@eduport.com', 'Lc Tutor', 'TUTOR')
        self.other_tutor = staff('lc_tutor2@eduport.com', 'Lc Tutor Two', 'TUTOR')
        self.bde = staff('lc_bde@eduport.com', 'Lc Bde', 'BDE')
        self.student_user = staff('lc_student@eduport.com', 'Lc Stu', 'STUDENT')
        self.student = Student.objects.create(
            profile=self.student_user, student_code='EDPLC1', full_name='Lc Stu',
            mentor=self.mentor, tutor=self.tutor, total_class_quota=40, status=StatusChoices.ACTIVE,
        )
        self.sessions_url = reverse('sessions:sessions-list-create-update')
        self.now = timezone.now().replace(microsecond=0)

    # -- helpers ---------------------------------------------------------

    def make(self, starts_in, hours=1, status_value=SCHEDULED, tutor=None, started=False, starter=None, **fields):
        """
        A class starting ``starts_in`` from now (negative = in the past),
        optionally started at its scheduled time by ``starter`` (its tutor by default).
        """
        start = self.now + starts_in
        tutor = tutor or self.tutor
        if started:
            fields.setdefault('started_at', start)
            fields.setdefault('started_by', starter or tutor)
        return Session.objects.create(
            student=self.student, tutor=tutor, title='Algebra',
            start_time=start, end_time=start + timedelta(hours=hours), status=status_value, **fields,
        )

    def start(self, user, session):
        self.client.force_authenticate(user=user)
        return self.client.post(reverse('sessions:session-start', args=[session.id]), format='json')

    def put(self, user, payload):
        self.client.force_authenticate(user=user)
        return self.client.put(self.sessions_url, payload, format='json')

    def notes(self, user, session, link='https://example.com/notes'):
        return self.put(user, {'id': str(session.id), 'notes_link': link})

    def upload_notes(self, user, session):
        self.client.force_authenticate(user=user)
        url = reverse('sessions:session-file-upload', args=[session.id, 'notes'])
        payload = {'file': SimpleUploadedFile('notes.pdf', PDF_BYTES, content_type='application/pdf')}
        return self.client.post(url, payload, format='multipart')

    def logs(self, session, action):
        return ActivityLog.objects.filter(entity_id=str(session.id), action=action)


class StartSessionTests(SessionLifecycleWorld):
    def test_start_opens_exactly_five_minutes_before_the_scheduled_start(self):
        session = self.make(timedelta(days=1))
        opens = session.start_time - timedelta(minutes=5)
        with self.assertRaises(lifecycle.SessionStateError) as refused:
            with transaction.atomic():
                lifecycle.start_session(session, self.tutor, now=opens - timedelta(seconds=1))
        self.assertEqual(refused.exception.code, lifecycle.START_TOO_EARLY)
        with transaction.atomic():
            started, changed = lifecycle.start_session(session, self.tutor, now=opens)
        self.assertTrue(changed)
        self.assertEqual(started.started_at, opens)

    def test_the_api_tells_each_session_when_its_start_opens(self):
        session = self.make(timedelta(days=1))
        self.client.force_authenticate(user=self.tutor)
        row = next(r for r in self.client.get(self.sessions_url).data['sessions'] if r['id'] == str(session.id))
        self.assertEqual(row['start_opens_at'], (session.start_time - timedelta(minutes=5)).isoformat())
        self.assertIsNone(row['started_at'])
        self.assertIsNone(row['completed_at'])
        self.assertEqual(row['duration_hours'], 1.0)

    def test_starting_before_the_window_is_refused_by_the_backend(self):
        session = self.make(timedelta(minutes=10))
        res = self.start(self.tutor, session)
        self.assertEqual(res.status_code, status.HTTP_409_CONFLICT, res.data)
        self.assertEqual(res.data['code'], lifecycle.START_TOO_EARLY)
        self.assertEqual(res.data['opens_at'], (session.start_time - timedelta(minutes=5)).isoformat())
        session.refresh_from_db()
        self.assertIsNone(session.started_at)
        self.assertFalse(self.logs(session, 'session.start').exists())

    def test_the_assigned_tutor_starts_it_by_the_server_clock(self):
        session = self.make(timedelta(minutes=3))
        before = timezone.now()
        self.client.force_authenticate(user=self.tutor)
        res = self.client.post(
            reverse('sessions:session-start', args=[session.id]),
            {'started_at': '2020-01-01T00:00:00Z'},  # ignored: the server's clock decides
            format='json',
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
        self.assertTrue(res.data['changed'])
        session.refresh_from_db()
        self.assertGreaterEqual(session.started_at, before)
        self.assertLessEqual(session.started_at, timezone.now())
        self.assertEqual(session.started_by, self.tutor)
        self.assertEqual(session.status, SCHEDULED)
        self.assertEqual(res.data['session']['started_by_profile']['id'], str(self.tutor.id))
        log = self.logs(session, 'session.start').get()
        self.assertEqual(log.actor_role, 'TUTOR')
        self.assertEqual(log.context['duration_hours'], 1.0)

    def test_a_class_under_way_can_still_be_started_until_its_scheduled_end(self):
        session = self.make(-timedelta(minutes=50))
        self.assertEqual(self.start(self.tutor, session).status_code, status.HTTP_200_OK)

    def test_a_class_whose_time_has_passed_cannot_be_started(self):
        session = self.make(-timedelta(hours=2))
        res = self.start(self.tutor, session)
        self.assertEqual(res.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(res.data['code'], lifecycle.START_WINDOW_CLOSED)

    def test_repeated_starts_change_nothing(self):
        session = self.make(timedelta(minutes=2))
        first = self.start(self.tutor, session)
        session.refresh_from_db()
        started_at = session.started_at
        second = self.start(self.tutor, session)
        self.assertEqual(second.status_code, status.HTTP_200_OK, second.data)
        self.assertFalse(second.data['changed'])
        session.refresh_from_db()
        self.assertTrue(first.data['changed'])
        self.assertEqual(session.started_at, started_at)
        self.assertEqual(self.logs(session, 'session.start').count(), 1)

    def test_another_tutor_cannot_start_it(self):
        session = self.make(timedelta(minutes=2))
        res = self.start(self.other_tutor, session)
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(res.data['code'], lifecycle.NOT_ASSIGNED)
        session.refresh_from_db()
        self.assertIsNone(session.started_at)

    def test_the_students_tutor_cannot_start_a_class_assigned_to_someone_else(self):
        session = self.make(timedelta(minutes=2), tutor=self.other_tutor)
        res = self.start(self.tutor, session)
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(self.start(self.other_tutor, session).status_code, status.HTTP_200_OK)

    def test_the_students_mentor_and_an_administrator_can_start_it(self):
        for user in (self.mentor, self.admin):
            with self.subTest(role=user.role):
                session = self.make(timedelta(minutes=2, days=1 if user is self.admin else 0))
                if user is self.admin:
                    # The same window holds for them: not before 5 minutes ahead.
                    self.assertEqual(self.start(user, session).data['code'], lifecycle.START_TOO_EARLY)
                    session.start_time = self.now + timedelta(minutes=4)
                    session.end_time = session.start_time + timedelta(hours=1)
                    session.save(update_fields=['start_time', 'end_time'])
                res = self.start(user, session)
                self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
                self.assertTrue(res.data['changed'])
                session.refresh_from_db()
                self.assertEqual(session.started_by, user)
                self.assertIsNotNone(session.started_at)
                # A start is operational: it never completes the class.
                self.assertEqual(session.status, SCHEDULED)
                self.assertIsNone(session.completed_at)
                self.assertEqual(self.logs(session, 'session.start').get().actor_role, user.role)

    def test_a_mentor_of_another_student_cannot_start_it(self):
        session = self.make(timedelta(minutes=2))
        res = self.start(self.other_mentor, session)
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(res.data['code'], lifecycle.NOT_ASSIGNED)

    def test_bde_and_student_cannot_start_it(self):
        session = self.make(timedelta(minutes=2))
        for user in (self.bde, self.student_user):
            with self.subTest(role=user.role):
                self.assertEqual(self.start(user, session).status_code, status.HTTP_403_FORBIDDEN)
        session.refresh_from_db()
        self.assertIsNone(session.started_at)

    def test_the_first_start_is_kept_whoever_starts_again(self):
        session = self.make(timedelta(minutes=2))
        self.assertTrue(self.start(self.mentor, session).data['changed'])
        for user in (self.tutor, self.admin, self.mentor):
            with self.subTest(role=user.role):
                res = self.start(user, session)
                self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
                self.assertFalse(res.data['changed'])
        session.refresh_from_db()
        self.assertEqual(session.started_by, self.mentor)
        self.assertEqual(self.logs(session, 'session.start').count(), 1)

    def test_a_cancelled_session_cannot_be_started(self):
        session = self.make(timedelta(minutes=2), status_value=CANCELLED, cancellation_reason='Sick')
        res = self.start(self.tutor, session)
        self.assertEqual(res.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(res.data['code'], lifecycle.SESSION_CANCELLED)

    def test_an_attended_session_cannot_be_started(self):
        session = self.make(-timedelta(minutes=30), status_value=ATTENDED)
        res = self.start(self.tutor, session)
        self.assertEqual(res.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(res.data['code'], lifecycle.SESSION_ATTENDED)

    def test_an_unknown_session_is_404(self):
        self.client.force_authenticate(user=self.tutor)
        res = self.client.post(reverse('sessions:session-start', args=['00000000-0000-0000-0000-000000000000']))
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)


class TutorNotesCompletionTests(SessionLifecycleWorld):
    def test_the_tutors_notes_complete_the_class_whoever_started_it(self):
        for starter in (self.tutor, self.mentor, self.admin):
            with self.subTest(started_by=starter.role):
                session = self.make(-timedelta(hours=2))
                # Started at its time by the tutor, the mentor or an administrator, through the real Start.
                with transaction.atomic():
                    lifecycle.start_session(session, starter, now=session.start_time)
                res = self.notes(self.tutor, session)
                self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
                self.assertTrue(res.data['completed'])
                session.refresh_from_db()
                self.assertEqual(session.started_by, starter)
                self.assertEqual(session.completed_by, self.tutor)
                self.assertEqual(session.status, ATTENDED)
                self.assertEqual(session.duration_hours, 1.0)

    def test_staff_attendance_without_the_tutors_notes_never_counts(self):
        for starter in (self.tutor, self.mentor, self.admin, None):
            with self.subTest(started_by=starter.role if starter else 'nobody'):
                session = self.make(-timedelta(hours=2), started=starter is not None, starter=starter)
                res = self.put(self.mentor, {
                    'id': str(session.id), 'status': 'ATTENDED',
                    'recording_link': 'https://rec.example/1', 'homework_link': 'https://hw.example/1',
                })
                self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
                session.refresh_from_db()
                self.assertEqual(session.status, ATTENDED)
                self.assertIsNone(session.completed_at)
                self.assertIsNone(session.completed_by)
                self.assertFalse(self.logs(session, 'session.complete').exists())

    def test_staff_notes_and_recordings_never_qualify_whoever_started_it(self):
        for starter in (self.mentor, self.admin):
            with self.subTest(started_by=starter.role):
                session = self.make(-timedelta(hours=2), started=True, starter=starter)
                for user in (self.mentor, self.admin):
                    res = self.put(user, {'id': str(session.id), 'notes_link': 'https://example.com/staff-notes',
                                          'recording_link': 'https://rec.example/1'})
                    self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
                session.refresh_from_db()
                self.assertIsNone(session.completed_at)
                self.assertEqual(session.status, SCHEDULED)
                # Still open to the tutor's own notes, which then complete it.
                self.assertTrue(self.notes(self.tutor, session).data['completed'])

    def test_repeated_tutor_notes_after_a_staff_start_complete_it_once(self):
        session = self.make(-timedelta(hours=2), started=True, starter=self.admin)
        results = [self.notes(self.tutor, session, link=f'https://example.com/notes-{i}').data['completed'] for i in range(3)]
        self.assertEqual(results, [True, False, False])
        self.assertEqual(self.logs(session, 'session.complete').count(), 1)
        session.refresh_from_db()
        self.assertEqual(session.notes_link, 'https://example.com/notes-2')

    def test_notes_after_start_and_end_complete_the_session(self):
        session = self.make(-timedelta(hours=2), started=True)
        res = self.notes(self.tutor, session)
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
        self.assertTrue(res.data['completed'])
        session.refresh_from_db()
        self.assertEqual(session.status, ATTENDED)
        self.assertEqual(session.completed_by, self.tutor)
        self.assertGreaterEqual(session.completed_at, session.end_time)
        self.assertEqual(res.data['session']['completed_by_profile']['id'], str(self.tutor.id))
        log = self.logs(session, 'session.complete').get()
        self.assertEqual(log.changes['status'], {'old': SCHEDULED, 'new': ATTENDED})
        self.assertEqual(log.actor_role, 'TUTOR')
        self.assertTrue(self.logs(session, 'session.update_links').exists())

    def test_notes_on_a_class_nobody_started_are_refused_and_nothing_is_stored(self):
        cases = {
            'scheduled': self.make(-timedelta(hours=3)),
            'staff marked attended': self.make(-timedelta(hours=5), status_value=ATTENDED),
            'staff notes already on it': self.make(-timedelta(hours=7), notes_link='https://example.com/staff'),
        }
        for label, session in cases.items():
            with self.subTest(label):
                before = (session.status, session.notes_link)
                for send in (self.notes, lambda user, s: self.upload_notes(user, s)):
                    res = send(self.tutor, session)
                    self.assertEqual(res.status_code, status.HTTP_409_CONFLICT, res.data)
                    self.assertEqual(res.data['code'], lifecycle.SESSION_NOT_STARTED)
                session.refresh_from_db()
                self.assertEqual((session.status, session.notes_link), before)
                self.assertIsNone(session.completed_at)
                self.assertEqual(session.files.count(), 0)
                self.assertFalse(self.logs(session, 'session.complete').exists())
                self.assertFalse(self.logs(session, 'session.update_links').exists())

    def test_the_tutors_notes_before_the_scheduled_end_are_refused_started_or_not(self):
        cases = {
            'started, under way': (self.make(-timedelta(minutes=20), started=True), lifecycle.CLASS_NOT_ENDED),
            'not started, under way': (self.make(-timedelta(minutes=20), hours=2), lifecycle.SESSION_NOT_STARTED),
            'not started, tomorrow': (self.make(timedelta(days=1)), lifecycle.SESSION_NOT_STARTED),
        }
        for label, (session, code) in cases.items():
            with self.subTest(label):
                res = self.notes(self.tutor, session)
                self.assertEqual(res.status_code, status.HTTP_409_CONFLICT, res.data)
                self.assertEqual(res.data['code'], code)
                session.refresh_from_db()
                self.assertIsNone(session.notes_link)
                self.assertIsNone(session.completed_at)
                self.assertEqual(session.status, SCHEDULED)

    def test_admin_and_mentor_notes_never_count_as_the_tutors_completion(self):
        for user in (self.admin, self.mentor):
            with self.subTest(role=user.role):
                session = self.make(-timedelta(hours=3), started=True)
                res = self.notes(user, session)
                self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
                session.refresh_from_db()
                self.assertEqual(session.notes_link, 'https://example.com/notes')
                self.assertEqual(session.status, SCHEDULED)
                self.assertIsNone(session.completed_at)
                self.assertIsNone(session.completed_by)
                # Staff edits never touch the tutor's start either.
                self.assertEqual(session.started_by, self.tutor)

    def test_notes_edited_after_completion_do_not_complete_it_again(self):
        session = self.make(-timedelta(hours=2), started=True)
        self.notes(self.tutor, session)
        session.refresh_from_db()
        completed_at = session.completed_at
        res = self.notes(self.tutor, session, link='https://example.com/notes-v2')
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
        self.assertFalse(res.data['completed'])
        again = self.notes(self.tutor, session, link='https://example.com/notes-v2')
        self.assertFalse(again.data['completed'])
        session.refresh_from_db()
        self.assertEqual(session.notes_link, 'https://example.com/notes-v2')
        self.assertEqual(session.completed_at, completed_at)
        self.assertEqual(self.logs(session, 'session.complete').count(), 1)

    def test_resubmitting_notes_already_on_the_class_completes_it(self):
        # Notes put there before this rule (or by staff): the tutor's own submission still completes it.
        session = self.make(-timedelta(hours=2), started=True, notes_link='https://example.com/notes')
        res = self.notes(self.tutor, session)
        self.assertTrue(res.data['completed'])
        self.assertFalse(self.logs(session, 'session.update_links').exists())
        self.assertEqual(self.logs(session, 'session.complete').count(), 1)

    def test_another_tutor_cannot_complete_it(self):
        session = self.make(-timedelta(hours=2), started=True)
        res = self.notes(self.other_tutor, session)
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        session.refresh_from_db()
        self.assertIsNone(session.completed_at)
        self.assertIsNone(session.notes_link)

    def test_a_cancelled_session_never_completes_through_notes(self):
        session = self.make(-timedelta(hours=2), started=True, status_value=CANCELLED, cancellation_reason='No-show')
        res = self.notes(self.tutor, session)
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        session.refresh_from_db()
        self.assertEqual(session.status, CANCELLED)
        self.assertIsNone(session.completed_at)

    def test_uploaded_notes_complete_a_started_class(self):
        session = self.make(-timedelta(hours=2), started=True)
        res = self.upload_notes(self.tutor, session)
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
        self.assertTrue(res.data['completed'])
        session.refresh_from_db()
        self.assertEqual(session.status, ATTENDED)
        self.assertEqual(session.completed_by, self.tutor)
        self.assertEqual(session.files.count(), 1)

    def test_uploaded_notes_before_the_end_are_refused_and_nothing_is_stored(self):
        session = self.make(-timedelta(minutes=20), started=True)
        res = self.upload_notes(self.tutor, session)
        self.assertEqual(res.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(res.data['code'], lifecycle.CLASS_NOT_ENDED)
        self.assertEqual(session.files.count(), 0)

    def test_another_tutor_cannot_upload_notes_to_it(self):
        session = self.make(-timedelta(hours=2), started=True)
        self.assertEqual(self.upload_notes(self.other_tutor, session).status_code, status.HTTP_403_FORBIDDEN)

    def test_the_booked_duration_stays_whatever_the_notes_delay(self):
        # Started late by an administrator, completed two days later: still the class booked.
        session = self.make(-timedelta(days=2), hours=1.5, started=True, starter=self.admin,
                            started_at=self.now - timedelta(days=2) + timedelta(minutes=40))
        res = self.notes(self.tutor, session)
        self.assertTrue(res.data['completed'])
        session.refresh_from_db()
        # Completed two days after the class: still the 1.5-hour class that was booked.
        self.assertGreater(session.completed_at - session.end_time, timedelta(days=1))
        self.assertEqual(session.duration_hours, 1.5)
        self.assertEqual(res.data['session']['duration_hours'], 1.5)
        self.assertEqual(self.logs(session, 'session.complete').get().context['duration_hours'], 1.5)

    def test_every_allowed_duration_counts_as_booked(self):
        for hours in (0.5, 1, 1.5, 2):
            with self.subTest(hours=hours):
                session = self.make(-timedelta(days=1, hours=hours * 3), hours=hours, started=True)
                self.notes(self.tutor, session)
                session.refresh_from_db()
                self.assertEqual(session.duration_hours, hours)

    def test_completion_gives_assigned_homework_its_row(self):
        session = self.make(-timedelta(hours=2), started=True, homework_link='https://hw.example/1')
        self.notes(self.tutor, session)
        homework = Homework.objects.get(session=session)
        self.assertEqual(homework.status, 'ASSIGNED')
        self.assertEqual(ActivityLog.objects.get(action='homework.assign').context['source'], 'tutor_completion')

    def test_the_tutors_notes_still_complete_a_class_staff_marked_attended(self):
        session = self.make(-timedelta(hours=2), started=True)
        self.assertEqual(self.put(self.mentor, {'id': str(session.id), 'status': 'ATTENDED'}).status_code, status.HTTP_200_OK)
        session.refresh_from_db()
        self.assertIsNone(session.completed_at)
        res = self.notes(self.tutor, session)
        self.assertTrue(res.data['completed'])
        session.refresh_from_db()
        self.assertEqual((session.status, session.completed_by), (ATTENDED, self.tutor))
        self.assertEqual(self.logs(session, 'session.complete').get().changes, {})

    def test_a_started_class_stays_with_its_tutor_through_a_reassignment(self):
        session = self.make(-timedelta(minutes=30), started=True)
        self.client.force_authenticate(user=self.admin)
        res = self.client.post('/api/students/reassign/', {
            'id': str(self.student.id), 'mentor': str(self.mentor.id), 'tutor': str(self.other_tutor.id),
        }, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
        session.refresh_from_db()
        self.assertEqual(session.tutor, self.tutor)
        # The tutor still sees it to submit its notes; the new tutor cannot complete it.
        self.client.force_authenticate(user=self.tutor)
        self.assertIn(str(session.id), {r['id'] for r in self.client.get(self.sessions_url).data['sessions']})
        session.end_time = self.now - timedelta(minutes=1)
        session.save(update_fields=['end_time'])
        self.assertEqual(self.notes(self.other_tutor, session).status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(self.notes(self.tutor, session).data['completed'])
        # Completed, it stays in the former tutor's list: it is their class.
        self.client.force_authenticate(user=self.tutor)
        self.assertIn(str(session.id), {r['id'] for r in self.client.get(self.sessions_url).data['sessions']})


class SessionIntegrityTests(SessionLifecycleWorld):
    def test_a_class_cannot_be_marked_attended_before_its_scheduled_end(self):
        for starts_in in (timedelta(days=1), -timedelta(minutes=30)):
            with self.subTest(starts_in=starts_in):
                session = self.make(starts_in)
                res = self.put(self.mentor, {'id': str(session.id), 'status': 'ATTENDED'})
                self.assertEqual(res.status_code, status.HTTP_409_CONFLICT, res.data)
                self.assertEqual(res.data['code'], lifecycle.CLASS_NOT_ENDED)
                session.refresh_from_db()
                self.assertEqual(session.status, SCHEDULED)

    def test_staff_marking_attended_after_the_end_records_attendance_only(self):
        session = self.make(-timedelta(hours=2))
        res = self.put(self.mentor, {'id': str(session.id), 'status': 'ATTENDED'})
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
        session.refresh_from_db()
        self.assertEqual(session.status, ATTENDED)
        self.assertIsNone(session.completed_at)
        self.assertIsNone(session.started_at)

    def test_reschedule_and_attendance_go_separately(self):
        session = self.make(-timedelta(hours=2))
        res = self.put(self.mentor, {
            'id': str(session.id), 'status': 'ATTENDED',
            'start_time': (self.now - timedelta(hours=5)).isoformat(), 'duration_hours': 2,
        })
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_an_attended_status_is_final(self):
        session = self.make(-timedelta(hours=2), status_value=ATTENDED)
        for payload in ({'status': 'SCHEDULED'}, {'status': 'CANCELLED', 'cancellation_reason': 'Oops'}):
            with self.subTest(payload=payload):
                res = self.put(self.admin, {'id': str(session.id), **payload})
                self.assertEqual(res.status_code, status.HTTP_409_CONFLICT, res.data)
                self.assertEqual(res.data['code'], lifecycle.SESSION_ATTENDED)
        session.refresh_from_db()
        self.assertEqual(session.status, ATTENDED)

    def test_a_cancelled_class_is_never_marked_attended(self):
        session = self.make(-timedelta(hours=2), status_value=CANCELLED, cancellation_reason='Sick')
        res = self.put(self.mentor, {'id': str(session.id), 'status': 'ATTENDED'})
        self.assertEqual(res.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(res.data['code'], lifecycle.SESSION_CANCELLED)

    def test_a_started_class_cancelled_keeps_its_start_and_is_not_reinstated(self):
        session = self.make(-timedelta(minutes=30), started=True)
        res = self.put(self.mentor, {'id': str(session.id), 'status': 'CANCELLED', 'cancellation_reason': 'No-show'})
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
        session.refresh_from_db()
        self.assertEqual(session.started_by, self.tutor)
        res = self.put(self.mentor, {'id': str(session.id), 'status': 'SCHEDULED'})
        self.assertEqual(res.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(res.data['code'], lifecycle.SESSION_STARTED)

    def test_a_cancelled_class_nobody_started_can_still_be_reinstated(self):
        session = self.make(timedelta(days=3), status_value=CANCELLED, cancellation_reason='Sick')
        res = self.put(self.mentor, {'id': str(session.id), 'status': 'SCHEDULED'})
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)

    def test_started_and_attended_classes_cannot_be_rescheduled(self):
        started = self.make(-timedelta(minutes=10), started=True)
        attended = self.make(-timedelta(days=1), status_value=ATTENDED)
        new_time = (self.now + timedelta(days=5)).isoformat()
        for session, code in ((started, lifecycle.SESSION_STARTED), (attended, lifecycle.SESSION_ATTENDED)):
            with self.subTest(code=code):
                res = self.put(self.mentor, {'id': str(session.id), 'start_time': new_time, 'duration_hours': 2})
                self.assertEqual(res.status_code, status.HTTP_409_CONFLICT, res.data)
                self.assertEqual(res.data['code'], code)
                before = (session.start_time, session.end_time)
                session.refresh_from_db()
                self.assertEqual((session.start_time, session.end_time), before)

    def test_rescheduling_a_class_still_to_come_works_as_before(self):
        session = self.make(timedelta(days=1))
        new_start = self.now + timedelta(days=4)
        res = self.put(self.mentor, {'id': str(session.id), 'start_time': new_start.isoformat(), 'duration_hours': 1.5})
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
        session.refresh_from_db()
        self.assertEqual((session.start_time, session.duration_hours), (new_start, 1.5))

    def test_the_tutor_of_a_started_or_past_class_cannot_change(self):
        started = self.make(-timedelta(minutes=10), started=True)
        past = self.make(-timedelta(days=1))
        for session, code in ((started, lifecycle.SESSION_STARTED), (past, lifecycle.SESSION_ENDED)):
            with self.subTest(code=code):
                res = self.put(self.admin, {'id': str(session.id), 'tutor': str(self.other_tutor.id)})
                self.assertEqual(res.status_code, status.HTTP_409_CONFLICT, res.data)
                self.assertEqual(res.data['code'], code)
                session.refresh_from_db()
                self.assertEqual(session.tutor, self.tutor)

    def test_the_tutor_of_a_class_still_to_come_can_change(self):
        session = self.make(timedelta(days=2))
        res = self.put(self.admin, {'id': str(session.id), 'tutor': str(self.other_tutor.id)})
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)

    def test_student_reassignment_hands_over_only_classes_to_come_nobody_started(self):
        upcoming = self.make(timedelta(days=2))
        past = self.make(-timedelta(days=2))
        started = self.make(-timedelta(minutes=15), started=True)
        attended = self.make(-timedelta(days=3), status_value=ATTENDED)
        self.client.force_authenticate(user=self.admin)
        res = self.client.post('/api/students/reassign/', {
            'id': str(self.student.id), 'mentor': str(self.mentor.id), 'tutor': str(self.other_tutor.id),
        }, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
        self.assertEqual(res.data['result']['sessions_repointed'], 1)
        self.assertEqual(Session.objects.get(pk=upcoming.pk).tutor, self.other_tutor)
        for session in (past, started, attended):
            self.assertEqual(Session.objects.get(pk=session.pk).tutor, self.tutor)

    def test_staff_handover_hands_over_only_classes_to_come_nobody_started(self):
        upcoming = self.make(timedelta(days=2))
        past = self.make(-timedelta(days=2))
        started = self.make(-timedelta(minutes=15), started=True)
        self.client.force_authenticate(user=self.admin)
        res = self.client.post(f'/api/users/{self.tutor.id}/reassign/', {'new_tutor': str(self.other_tutor.id)}, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
        self.assertEqual(Session.objects.get(pk=upcoming.pk).tutor, self.other_tutor)
        self.assertEqual(Session.objects.get(pk=past.pk).tutor, self.tutor)
        self.assertEqual(Session.objects.get(pk=started.pk).tutor, self.tutor)

    def test_past_classes_never_complete_or_change_on_their_own(self):
        session = self.make(-timedelta(days=5))
        # Its time passed, it was read and offered for Start: still not completed,
        # never marked anything by the clock -- Not Started until someone records its outcome.
        self.client.force_authenticate(user=self.mentor)
        row = next(r for r in self.client.get(self.sessions_url).data['sessions'] if r['id'] == str(session.id))
        self.assertEqual((row['status'], row['class_state']), ('scheduled', 'not_started'))
        self.assertEqual(self.start(self.tutor, session).data['code'], lifecycle.START_WINDOW_CLOSED)
        self.assertEqual(self.notes(self.tutor, session).data['code'], lifecycle.SESSION_NOT_STARTED)
        session.refresh_from_db()
        self.assertEqual(session.status, SCHEDULED)
        self.assertIsNone(session.completed_at)

    def test_a_past_started_class_stays_with_its_tutor_who_still_completes_it(self):
        session = self.make(-timedelta(days=1), started=True)
        self.client.force_authenticate(user=self.admin)
        res = self.client.post('/api/students/reassign/', {
            'id': str(self.student.id), 'mentor': str(self.mentor.id), 'tutor': str(self.other_tutor.id),
        }, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
        self.client.force_authenticate(user=self.tutor)
        self.assertIn(str(session.id), {r['id'] for r in self.client.get(self.sessions_url).data['sessions']})
        self.assertEqual(self.notes(self.other_tutor, session).status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(self.notes(self.tutor, session).data['completed'])

    def test_cancellation_and_series_cancellation_still_work(self):
        session = self.make(timedelta(days=1))
        res = self.put(self.mentor, {'id': str(session.id), 'status': 'CANCELLED', 'cancellation_reason': 'Sick'})
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
        other = self.make(timedelta(days=2))
        self.client.force_authenticate(user=self.mentor)
        res = self.client.post(reverse('sessions:cancel-series'), {'session_id': str(other.id), 'cancellation_reason': 'Sick'}, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)

    def test_recording_and_homework_stay_with_staff_on_started_classes(self):
        session = self.make(-timedelta(minutes=10), started=True)
        res = self.put(self.mentor, {
            'id': str(session.id), 'recording_link': 'https://rec.example/1', 'homework_link': 'https://hw.example/1',
        })
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
        session.refresh_from_db()
        self.assertEqual((session.recording_link, session.homework_link), ('https://rec.example/1', 'https://hw.example/1'))
        self.assertEqual(session.started_by, self.tutor)

    def test_the_database_holds_a_completion_to_attended_and_after_the_end(self):
        # Not attended: refused.
        scheduled = self.make(-timedelta(hours=2))
        scheduled.completed_at = self.now
        with self.assertRaises(IntegrityError), transaction.atomic():
            scheduled.save(update_fields=['completed_at'])
        # Before the scheduled end: refused.
        early = self.make(-timedelta(minutes=10), status_value=ATTENDED, started=True)
        early.completed_at = self.now
        with self.assertRaises(IntegrityError), transaction.atomic():
            early.save(update_fields=['completed_at'])
        # Never without a start.
        unstarted = self.make(-timedelta(hours=2), status_value=ATTENDED)
        unstarted.completed_at = self.now
        with self.assertRaises(IntegrityError), transaction.atomic():
            unstarted.save(update_fields=['completed_at'])
        # Started, attended, after the end -- however long after: held (there is no deadline).
        for ago in (timedelta(hours=2), timedelta(days=3), timedelta(days=60)):
            held = self.make(-ago, status_value=ATTENDED, started=True)
            held.completed_at = self.now
            held.save(update_fields=['completed_at'])


class FormerTutorTests(SessionLifecycleWorld):
    """
    A tutor whose student moved to another tutor keeps their own classes, so
    they can still submit notes that complete the started ones, even after
    staff marked them attended.
    """

    def reassign(self):
        self.client.force_authenticate(user=self.admin)
        res = self.client.post('/api/students/reassign/', {
            'id': str(self.student.id), 'mentor': str(self.mentor.id), 'tutor': str(self.other_tutor.id),
        }, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
        self.student.refresh_from_db()
        self.assertEqual(self.student.tutor, self.other_tutor)

    def listed(self, user):
        self.client.force_authenticate(user=user)
        return {r['id'] for r in self.client.get(self.sessions_url).data['sessions']}

    def mark_attended(self, session):
        res = self.put(self.mentor, {'id': str(session.id), 'status': 'ATTENDED'})
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)

    def test_a_class_staff_marked_attended_stays_the_former_tutors_to_complete(self):
        before = self.make(-timedelta(hours=36), started=True)
        after = self.make(-timedelta(days=1), started=True)
        self.mark_attended(before)
        self.reassign()
        self.mark_attended(after)
        for label, session in (('attended before the change', before), ('attended after it', after)):
            with self.subTest(label):
                session.refresh_from_db()
                # Staff attendance is recorded on its own: not the tutor's completion.
                self.assertEqual((session.status, session.tutor), (ATTENDED, self.tutor))
                self.assertIsNone(session.completed_at)
                self.assertIn(str(session.id), self.listed(self.tutor))
                # The new tutor has the student's history but cannot complete the former tutor's class.
                self.assertIn(str(session.id), self.listed(self.other_tutor))
                self.assertEqual(self.notes(self.other_tutor, session).status_code, status.HTTP_403_FORBIDDEN)

                res = self.notes(self.tutor, session)
                self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
                self.assertTrue(res.data['completed'])
                session.refresh_from_db()
                self.assertEqual((session.status, session.completed_by), (ATTENDED, self.tutor))
                # Both records stand: the mentor's attendance and the tutor's completion.
                self.assertEqual(self.logs(session, 'session.mark_attended').get().actor, self.mentor)
                completion = self.logs(session, 'session.complete').get()
                self.assertEqual((completion.actor, completion.changes), (self.tutor, {}))

    def test_a_former_tutor_uploads_notes_to_a_staff_attended_class_and_can_open_them(self):
        session = self.make(-timedelta(days=1), started=True)
        self.mark_attended(session)
        self.reassign()
        self.assertEqual(self.upload_notes(self.other_tutor, session).status_code, status.HTTP_403_FORBIDDEN)
        res = self.upload_notes(self.tutor, session)
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
        self.assertTrue(res.data['completed'])
        session.refresh_from_db()
        self.assertEqual((session.status, session.completed_by), (ATTENDED, self.tutor))
        self.client.force_authenticate(user=self.tutor)
        res = self.client.get(reverse('sessions:session-file', args=[session.files.get().id]))
        self.assertEqual(res.status_code, status.HTTP_200_OK)

    def test_a_former_tutor_keeps_only_their_own_classes_that_were_not_cancelled(self):
        past = self.make(-timedelta(days=3))
        attended = self.make(-timedelta(days=2))
        self.mark_attended(attended)
        completed = self.make(-timedelta(days=1), started=True)
        self.notes(self.tutor, completed)
        cancelled = self.make(-timedelta(days=4), status_value=CANCELLED)
        upcoming = self.make(timedelta(days=2))
        someone_elses = self.make(-timedelta(days=5), tutor=self.other_tutor)
        self.reassign()
        self.assertEqual(Session.objects.get(pk=upcoming.pk).tutor, self.other_tutor)

        mine = self.listed(self.tutor)
        self.assertLessEqual({str(s.id) for s in (past, attended, completed)}, mine)
        self.assertFalse({str(s.id) for s in (cancelled, upcoming, someone_elses)} & mine)
        everything = {str(s.id) for s in (past, attended, completed, cancelled, upcoming, someone_elses)}
        self.assertLessEqual(everything, self.listed(self.other_tutor))
        # A completed class stays an edit for its tutor: never completed twice.
        res = self.notes(self.tutor, completed, link='https://example.com/notes-v2')
        self.assertFalse(res.data['completed'])
        self.assertEqual(self.logs(completed, 'session.complete').count(), 1)
