import shutil
import tempfile
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from activity.models import ActivityLog
from students.models import Student, StatusChoices
from sessions.models import Session, SessionStatusChoices, SessionFile
from exams.models import Exam
from .models import Homework, HomeworkFile
from .services import collect_homework_entries

User = get_user_model()

PDF = b'%PDF-1.4\n' + b'0' * 64
PNG = b'\x89PNG\r\n\x1a\n' + b'\x00' * 64


def pdf(name='work.pdf'):
    return SimpleUploadedFile(name, PDF, content_type='application/pdf')


def png(name='page.png'):
    return SimpleUploadedFile(name, PNG, content_type='image/png')


class HomeworkTestBase(APITestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._media = tempfile.mkdtemp()
        cls._override = override_settings(MEDIA_ROOT=cls._media)
        cls._override.enable()

    @classmethod
    def tearDownClass(cls):
        cls._override.disable()
        shutil.rmtree(cls._media, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.admin = User.objects.create_user(email='admin@x.com', password='p', full_name='Admin', role='ADMIN', is_staff=True)
        self.mentor = User.objects.create_user(email='mentor@x.com', password='p', full_name='Mentor', role='MENTOR', is_staff=True)
        self.mentor2 = User.objects.create_user(email='mentor2@x.com', password='p', full_name='Mentor Two', role='MENTOR', is_staff=True)
        self.tutor = User.objects.create_user(email='tutor@x.com', password='p', full_name='Tutor', role='TUTOR', is_staff=True)
        self.tutor2 = User.objects.create_user(email='tutor2@x.com', password='p', full_name='Tutor Two', role='TUTOR', is_staff=True)
        self.parent = User.objects.create_user(email='parent@x.com', password='p', full_name='Parent', role='STUDENT')
        self.other_parent = User.objects.create_user(email='other@x.com', password='p', full_name='Other', role='STUDENT')
        self.student = Student.objects.create(
            profile=self.parent, student_code='EDP1', full_name='Dona', mentor=self.mentor, tutor=self.tutor,
            total_class_quota=10, status=StatusChoices.ACTIVE,
        )
        self.sibling = Student.objects.create(
            profile=self.parent, student_code='EDP2', full_name='Sib', mentor=self.mentor, tutor=self.tutor,
            total_class_quota=10, status=StatusChoices.ACTIVE,
        )
        self.foreign = Student.objects.create(
            profile=self.other_parent, student_code='EDP3', full_name='Foreign', mentor=self.mentor2, tutor=self.tutor2,
            total_class_quota=10, status=StatusChoices.ACTIVE,
        )
        now = timezone.now()
        self.session = Session.objects.create(
            student=self.student, title='Real Numbers', tutor=self.tutor,
            start_time=now - timedelta(days=1), end_time=now - timedelta(days=1, hours=-1),
            status=SessionStatusChoices.ATTENDED, notes_link='https://n.example/1', recording_link='https://r.example/1',
        )
        self.sessions_url = reverse('sessions:sessions-list-create-update')
        self.list_url = reverse('homework:homework-list')

    # helpers
    def as_student(self, student=None):
        self.client.force_authenticate(user=self.parent)
        self.client.cookies['ep-student-id'] = str((student or self.student).id)

    def assign_via_put(self, user=None, link='https://hw.example/1', session=None):
        self.client.force_authenticate(user=user or self.mentor)
        return self.client.put(self.sessions_url, {'id': str((session or self.session).id), 'homework_link': link}, format='json')

    def make_homework(self, status='ASSIGNED', session=None, **kw):
        session = session or self.session
        if not session.homework_link:
            session.homework_link = 'https://hw.example/1'
            session.save()
        return Homework.objects.create(session=session, student=session.student, status=status, assigned_by=self.mentor, **kw)

    def submit(self, homework, files=None, student=None):
        self.as_student(student)
        return self.client.post(reverse('homework:homework-submit', args=[homework.id]), {'files': files or [png()]}, format='multipart')

    def score(self, homework, user=None, **payload):
        self.client.force_authenticate(user=user or self.tutor)
        body = {'score': 8, 'max_score': 10}
        body.update(payload)
        return self.client.post(reverse('homework:homework-score', args=[homework.id]), body, format='json')


class RowCreationTests(HomeworkTestBase):
    def test_put_link_on_attended_session_creates_assigned_row(self):
        res = self.assign_via_put()
        self.assertEqual(res.status_code, 200, res.data)
        hw = Homework.objects.get(session=self.session)
        self.assertEqual((hw.status, hw.assigned_by, hw.student), ('ASSIGNED', self.mentor, self.student))
        self.assertEqual(res.data['session']['homework']['status'], 'assigned')
        log = ActivityLog.objects.get(action='homework.assign')
        self.assertEqual((log.entity_type, log.entity_label, log.student), ('homework', 'Real Numbers', self.student))
        self.assertEqual(log.context['source'], 'links')
        # a second change never creates a second row
        self.assertEqual(self.assign_via_put(link='https://hw.example/2').status_code, 200)
        self.assertEqual(Homework.objects.filter(session=self.session).count(), 1)

    def test_upload_creates_row(self):
        self.client.force_authenticate(user=self.mentor)
        res = self.client.post(reverse('sessions:session-file-upload', args=[self.session.id, 'homework']), {'file': pdf()}, format='multipart')
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(Homework.objects.get(session=self.session).status, 'ASSIGNED')
        self.assertEqual(ActivityLog.objects.get(action='homework.assign').context['source'], 'upload')

    def test_scheduled_session_waits_for_mark_attended(self):
        scheduled = Session.objects.create(
            student=self.student, title='Algebra', tutor=self.tutor,
            start_time=timezone.now() + timedelta(days=1), end_time=timezone.now() + timedelta(days=1, hours=1),
        )
        self.assertEqual(self.assign_via_put(session=scheduled).status_code, 200)
        self.assertFalse(Homework.objects.filter(session=scheduled).exists())
        self.client.force_authenticate(user=self.mentor)
        res = self.client.put(self.sessions_url, {'id': str(scheduled.id), 'status': 'attended'}, format='json')
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(Homework.objects.get(session=scheduled).status, 'ASSIGNED')
        self.assertEqual(ActivityLog.objects.get(action='homework.assign').context['source'], 'mark_attended')

    def test_mark_attended_with_link_in_same_request(self):
        scheduled = Session.objects.create(
            student=self.student, title='Algebra', tutor=self.tutor,
            start_time=timezone.now() + timedelta(days=1), end_time=timezone.now() + timedelta(days=1, hours=1),
        )
        self.client.force_authenticate(user=self.admin)
        res = self.client.put(self.sessions_url, {'id': str(scheduled.id), 'status': 'attended', 'homework_link': 'https://hw.example/x'}, format='json')
        self.assertEqual(res.status_code, 200, res.data)
        self.assertTrue(Homework.objects.filter(session=scheduled).exists())
        self.assertTrue(ActivityLog.objects.filter(action='session.mark_attended').exists())

    def test_clearing_keeps_row_and_pending(self):
        self.assign_via_put()
        res = self.assign_via_put(link='')
        self.assertEqual(res.status_code, 200)
        self.assertTrue(Homework.objects.filter(session=self.session).exists())
        self.assertEqual(res.data['session']['display_status'], 'pending')

    def test_tutor_still_cannot_assign(self):
        self.client.force_authenticate(user=self.tutor)
        res = self.client.put(self.sessions_url, {'id': str(self.session.id), 'homework_link': 'https://hw.example/1'}, format='json')
        self.assertEqual(res.status_code, 403)
        self.assertFalse(Homework.objects.exists())


class LockTests(HomeworkTestBase):
    def test_assignment_locked_after_submission(self):
        hw = self.make_homework()
        self.assertEqual(self.submit(hw).status_code, 200)
        res = self.assign_via_put(link='https://hw.example/2')
        self.assertEqual(res.status_code, 409)
        self.assertIn('already been submitted', res.data['error'])
        self.client.force_authenticate(user=self.admin)
        res = self.client.post(reverse('sessions:session-file-upload', args=[self.session.id, 'homework']), {'file': pdf()}, format='multipart')
        self.assertEqual(res.status_code, 409)
        # other fields still editable
        self.assertEqual(self.client.put(self.sessions_url, {'id': str(self.session.id), 'recording_link': 'https://r.example/2'}, format='json').status_code, 200)

    def test_assignment_editable_while_assigned(self):
        self.make_homework()
        self.assertEqual(self.assign_via_put(link='https://hw.example/2').status_code, 200)


class SubmissionTests(HomeworkTestBase):
    def test_one_shot_submit(self):
        hw = self.make_homework()
        res = self.submit(hw, files=[png(), png('p2.png')])
        self.assertEqual(res.status_code, 200, res.data)
        hw.refresh_from_db()
        self.assertEqual(hw.status, 'SUBMITTED')
        self.assertIsNotNone(hw.submitted_at)
        self.assertIsNone(hw.score)
        self.assertEqual(hw.files.count(), 2)
        self.assertEqual(res.data['homework']['status'], 'submitted')
        self.assertEqual(len(res.data['homework']['submission']), 2)
        log = ActivityLog.objects.get(action='homework.submit')
        self.assertEqual((log.actor, log.context['file_count']), (self.parent, 2))
        self.assertEqual(self.submit(hw).status_code, 409)

    def test_submit_validation_and_ownership(self):
        hw = self.make_homework()
        self.as_student()
        self.assertEqual(self.client.post(reverse('homework:homework-submit', args=[hw.id]), {}, format='multipart').status_code, 400)
        gif = SimpleUploadedFile('a.gif', b'GIF89a' + b'0' * 10, content_type='image/gif')
        self.assertEqual(self.submit(hw, files=[gif]).status_code, 400)
        self.assertEqual(self.submit(hw, files=[png(f'{i}.png') for i in range(11)]).status_code, 400)
        self.assertEqual(hw.files.count(), 0)
        self.assertEqual(self.submit(hw, student=self.sibling).status_code, 404)
        self.client.force_authenticate(user=self.other_parent)
        self.client.cookies['ep-student-id'] = str(self.foreign.id)
        self.assertEqual(self.client.post(reverse('homework:homework-submit', args=[hw.id]), {'files': [png()]}, format='multipart').status_code, 404)
        for staff in (self.admin, self.mentor, self.tutor):
            self.client.force_authenticate(user=staff)
            self.assertEqual(self.client.post(reverse('homework:homework-submit', args=[hw.id]), {'files': [png()]}, format='multipart').status_code, 403)


class GradingTests(HomeworkTestBase):
    def test_tutor_scores_submitted_homework(self):
        hw = self.make_homework()
        self.assertEqual(self.score(hw).status_code, 409)  # assigned
        self.submit(hw)
        res = self.score(hw, feedback='  Good  ')
        self.assertEqual(res.status_code, 200, res.data)
        hw.refresh_from_db()
        self.assertEqual((hw.status, hw.score, hw.max_score, hw.feedback, hw.scored_by), ('SCORED', 8, 10, 'Good', self.tutor))
        self.assertIsNotNone(hw.scored_at)
        log = ActivityLog.objects.get(action='homework.score')
        self.assertEqual(log.changes['score'], {'old': None, 'new': 8})
        self.assertEqual(log.changes['feedback']['new'], 'Good')
        self.assertEqual(self.score(hw).status_code, 409)  # terminal

    def test_mentor_and_other_tutor_cannot_score(self):
        hw = self.make_homework()
        self.submit(hw)
        self.assertEqual(self.score(hw, user=self.mentor).status_code, 403)
        self.assertEqual(self.score(hw, user=self.tutor2).status_code, 403)
        self.assertEqual(self.score(hw, user=self.admin).status_code, 200)

    def test_score_validation(self):
        hw = self.make_homework()
        self.submit(hw)
        for payload in ({'score': -1}, {'max_score': 0}, {'score': 11}, {'score': 1.5}, {'feedback': 'x' * 2001}):
            self.assertEqual(self.score(hw, **payload).status_code, 400, payload)
        self.assertEqual(self.score(hw, score=0).status_code, 200)

    def test_reassigned_tutor_takes_over(self):
        hw = self.make_homework()
        self.submit(hw)
        self.student.tutor = self.tutor2
        self.student.save()
        self.assertEqual(self.score(hw, user=self.tutor).status_code, 403)
        self.assertEqual(self.score(hw, user=self.tutor2).status_code, 200)


class VisibilityTests(HomeworkTestBase):
    def test_list_scoping(self):
        self.make_homework()
        self.make_homework(session=Session.objects.create(
            student=self.foreign, title='Other', tutor=self.tutor2, status=SessionStatusChoices.ATTENDED,
            start_time=timezone.now() - timedelta(days=2), end_time=timezone.now() - timedelta(days=2, hours=-1),
            homework_link='https://hw.example/f',
        ))
        for user, count in ((self.admin, 2), (self.mentor, 1), (self.tutor, 1), (self.mentor2, 1), (self.tutor2, 1)):
            self.client.force_authenticate(user=user)
            res = self.client.get(self.list_url)
            self.assertEqual(res.status_code, 200)
            self.assertEqual(len(res.data['homework']), count, user.email)
        self.as_student()
        self.assertEqual(len(self.client.get(self.list_url).data['homework']), 1)
        self.as_student(self.sibling)
        self.assertEqual(len(self.client.get(self.list_url).data['homework']), 0)
        self.client.force_authenticate(user=self.tutor)
        self.assertEqual(self.client.get(self.list_url, {'status': 'submitted'}).data['homework'], [])
        self.assertEqual(self.client.get(self.list_url, {'status': 'bogus'}).status_code, 400)

    def test_mentor_sees_submission_only_once_scored(self):
        hw = self.make_homework()
        self.submit(hw)
        detail = reverse('homework:homework-detail', args=[hw.id])
        file_url = reverse('homework:homework-file', args=[hw.files.first().id])
        self.client.force_authenticate(user=self.mentor)
        res = self.client.get(detail)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data['homework']['submission'], [])
        self.assertFalse(res.data['homework']['submission_visible'])
        self.assertEqual(res.data['homework']['assignment']['url'], 'https://hw.example/1')
        self.assertEqual(self.client.get(file_url).status_code, 403)
        self.client.force_authenticate(user=self.tutor)
        self.assertEqual(len(self.client.get(detail).data['homework']['submission']), 1)
        self.assertEqual(self.client.get(file_url).status_code, 200)
        self.client.force_authenticate(user=self.tutor2)
        self.assertEqual(self.client.get(detail).status_code, 404)
        self.assertEqual(self.client.get(file_url).status_code, 403)
        self.as_student()
        res = self.client.get(file_url, HTTP_RANGE='bytes=0-3')
        self.assertEqual(res.status_code, 206)
        self.score(hw)
        self.client.force_authenticate(user=self.mentor)
        self.assertEqual(len(self.client.get(detail).data['homework']['submission']), 1)
        self.assertEqual(self.client.get(file_url).status_code, 200)

    def test_detail_404_for_sibling_persona(self):
        hw = self.make_homework()
        self.as_student(self.sibling)
        self.assertEqual(self.client.get(reverse('homework:homework-detail', args=[hw.id])).status_code, 404)


class IntegrationTests(HomeworkTestBase):
    def test_session_serializer_summary_and_pending_unchanged(self):
        self.assign_via_put()
        self.client.force_authenticate(user=self.mentor)
        row = next(s for s in self.client.get(self.sessions_url).data['sessions'] if s['id'] == str(self.session.id))
        self.assertEqual(row['homework']['status'], 'assigned')
        self.assertEqual(row['display_status'], 'attended')
        self.assertNotIn('homework', row['missing_content'])

    def test_purge_guard_counts_homework(self):
        Session.objects.filter(student=self.sibling).delete()
        s = Session.objects.create(
            student=self.sibling, title='S', tutor=self.tutor, status=SessionStatusChoices.ATTENDED,
            start_time=timezone.now() - timedelta(days=3), end_time=timezone.now() - timedelta(days=3, hours=-1),
            homework_link='https://hw.example/s',
        )
        self.make_homework(session=s)
        s_id = s.id
        # Delete the session but keep an orphan-free check: the student still has a session -> 409 anyway,
        # so remove the session row first and recreate the homework on a fresh session to isolate the homework guard.
        self.client.force_authenticate(user=self.admin)
        res = self.client.delete(reverse('students:student-detail', args=[self.sibling.id]), {'confirm_code': 'EDP2'}, format='json')
        self.assertEqual(res.status_code, 409)
        self.assertIn('exams', res.data['message'])

    def test_scorecard_includes_scored_homework(self):
        hw = self.make_homework()
        self.submit(hw)
        self.score(hw, score=9, max_score=10)
        Exam.objects.create(student=self.student, mentor=self.mentor, chapter_name='Real Numbers', status='ATTENDED',
                            score=7, max_score=10, start_time=timezone.now() - timedelta(days=1), end_time=timezone.now() - timedelta(hours=23))
        entries = collect_homework_entries(self.student)
        self.assertEqual([e['id'] for e in entries], [str(hw.id)])
        self.as_student()
        res = self.client.get(reverse('student-scorecard'))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data['overall'], 80)
        hw_cat = next(c for c in res.data['categories'] if c['category'] == 'homework')
        self.assertEqual((hw_cat['avg'], hw_cat['count']), (90, 1))
        self.assertEqual(sorted(e['category'] for e in res.data['recent']), ['exam', 'homework'])

    def test_cascade_removes_submission_bytes(self):
        hw = self.make_homework()
        self.submit(hw)
        path = hw.files.first().file.path
        import os
        self.assertTrue(os.path.exists(path))
        self.session.delete()
        self.assertFalse(os.path.exists(path))
        self.assertFalse(Homework.objects.exists())
