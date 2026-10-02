import shutil
import tempfile
import uuid
from datetime import timedelta
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from activity.models import ActivityLog
from students.models import Student, StatusChoices
from sessions.models import Session, SessionStatusChoices
from .models import (
    Exam, ExamStatusChoices, ExamFile,
    AdditionalExam, AdditionalExamStatusChoices, AdditionalExamFile,
)
from .services import build_scorecard, derive_chapter_names, validate_score, score_entry

User = get_user_model()

PDF = b'%PDF-1.4\n' + b'0' * 64
PNG = b'\x89PNG\r\n\x1a\n' + b'\x00' * 64


def pdf(name='paper.pdf'):
    return SimpleUploadedFile(name, PDF, content_type='application/pdf')


def png(name='page.png'):
    return SimpleUploadedFile(name, PNG, content_type='image/png')


class ExamTestBase(APITestCase):
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
        self.mentor = User.objects.create_user(email='mentor@x.com', password='p', full_name='Mentor One', role='MENTOR', is_staff=True)
        self.mentor2 = User.objects.create_user(email='mentor2@x.com', password='p', full_name='Mentor Two', role='MENTOR', is_staff=True)
        self.tutor = User.objects.create_user(email='tutor@x.com', password='p', full_name='Tutor', role='TUTOR', is_staff=True)
        self.parent = User.objects.create_user(email='parent@x.com', password='p', full_name='Parent', role='STUDENT')
        self.other_parent = User.objects.create_user(email='other@x.com', password='p', full_name='Other', role='STUDENT')

        self.student = Student.objects.create(
            profile=self.parent, student_code='EDP1', full_name='Dona', mentor=self.mentor, tutor=self.tutor,
            total_class_quota=10, meet_link='https://meet.google.com/aaa', status=StatusChoices.ACTIVE,
            timezone='Asia/Kolkata',
        )
        self.sibling = Student.objects.create(
            profile=self.parent, student_code='EDP2', full_name='Sib', mentor=self.mentor, tutor=self.tutor,
            total_class_quota=10, status=StatusChoices.ACTIVE,
        )
        self.foreign = Student.objects.create(
            profile=self.other_parent, student_code='EDP3', full_name='Foreign', mentor=self.mentor2, tutor=self.tutor,
            total_class_quota=10, status=StatusChoices.ACTIVE,
        )
        # Chapter sources: one single session, one fully attended series, one open series.
        now = timezone.now()
        Session.objects.create(student=self.student, title='Real Numbers', start_time=now - timedelta(days=10),
                               end_time=now - timedelta(days=10, hours=-1), status=SessionStatusChoices.ATTENDED, tutor=self.tutor)
        sid = uuid.uuid4()
        for n in (1, 2):
            Session.objects.create(student=self.student, title=f'Polynomials - Class {n}', series_id=sid, class_number=n,
                                   start_time=now - timedelta(days=8 - n), end_time=now - timedelta(days=8 - n, hours=-1),
                                   status=SessionStatusChoices.ATTENDED, tutor=self.tutor)
        sid2 = uuid.uuid4()
        Session.objects.create(student=self.student, title='Algebra - Class 1', series_id=sid2, class_number=1,
                               start_time=now - timedelta(days=3), end_time=now - timedelta(days=3, hours=-1),
                               status=SessionStatusChoices.ATTENDED, tutor=self.tutor)
        Session.objects.create(student=self.student, title='Algebra - Class 2', series_id=sid2, class_number=2,
                               start_time=now + timedelta(days=3), end_time=now + timedelta(days=3, hours=1),
                               status=SessionStatusChoices.SCHEDULED, tutor=self.tutor)

        self.exams_url = reverse('exams:exams-list-create-update')
        self.chapters_url = reverse('exams:chapter-names')
        self.add_url = reverse('additional_exams:additional-exams-list-create')
        self.future = now + timedelta(days=7)

    # helpers
    def as_student(self, student=None):
        self.client.force_authenticate(user=self.parent)
        self.client.cookies['ep-student-id'] = str((student or self.student).id)

    def create_payload(self, **overrides):
        payload = {
            "student_id": str(self.student.id),
            "chapter_name": "Real Numbers",
            "start_time": self.future.isoformat(),
            "duration_hours": 1,
        }
        payload.update(overrides)
        return payload

    def make_exam(self, **kw):
        defaults = dict(student=self.student, mentor=self.mentor, chapter_name='Real Numbers',
                        start_time=self.future, end_time=self.future + timedelta(hours=1))
        defaults.update(kw)
        return Exam.objects.create(**defaults)

    def make_additional(self, **kw):
        defaults = dict(student=self.student, mentor=self.mentor, title='Worksheet 1')
        defaults.update(kw)
        exam = AdditionalExam.objects.create(**defaults)
        f = AdditionalExamFile(additional_exam=exam, kind='question_paper', file_name='q.pdf',
                               content_type='application/pdf', size_bytes=len(PDF), extension='.pdf')
        f.file.save(f'{f.id}.pdf', pdf(), save=False)
        f.save()
        return exam

    def result_url(self, exam):
        return reverse('exams:exam-result', args=[exam.id])


class ChapterNameTests(ExamTestBase):
    def test_derived_names(self):
        self.assertEqual(derive_chapter_names(self.student), ['Polynomials', 'Real Numbers'])

    def test_endpoint_roles(self):
        self.client.force_authenticate(user=self.mentor)
        res = self.client.get(self.chapters_url, {'student_id': str(self.student.id)})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data['chapter_names'], ['Polynomials', 'Real Numbers'])
        self.client.force_authenticate(user=self.mentor2)
        self.assertEqual(self.client.get(self.chapters_url, {'student_id': str(self.student.id)}).status_code, 403)
        self.client.force_authenticate(user=self.tutor)
        self.assertEqual(self.client.get(self.chapters_url, {'student_id': str(self.student.id)}).status_code, 403)


class ChapterExamLifecycleTests(ExamTestBase):
    def test_mentor_creates_scheduled_exam_with_mentor_snapshot(self):
        self.client.force_authenticate(user=self.mentor)
        res = self.client.post(self.exams_url, self.create_payload(), format='json')
        self.assertEqual(res.status_code, 200, res.data)
        exam = Exam.objects.get()
        self.assertEqual(exam.status, 'SCHEDULED')
        self.assertEqual(exam.mentor, self.mentor)
        self.assertEqual(exam.end_time - exam.start_time, timedelta(hours=1))
        self.assertEqual(res.data['exam']['status'], 'scheduled')
        self.assertEqual(res.data['exam']['type'], 'chapter')
        log = ActivityLog.objects.get(action='exam.create')
        self.assertEqual(log.entity_type, 'exam')
        self.assertEqual(log.student, self.student)

    def test_local_time_scheduling(self):
        self.client.force_authenticate(user=self.admin)
        payload = self.create_payload(local_date=(self.future.date()).isoformat(), local_time='10:00', timezone='Asia/Kolkata')
        payload.pop('start_time')
        res = self.client.post(self.exams_url, payload, format='json')
        self.assertEqual(res.status_code, 200, res.data)
        exam = Exam.objects.get()
        self.assertEqual(exam.start_time.astimezone(ZoneInfo('Asia/Kolkata')).hour, 10)

    def test_chapter_must_be_derived(self):
        self.client.force_authenticate(user=self.mentor)
        res = self.client.post(self.exams_url, self.create_payload(chapter_name='Algebra'), format='json')
        self.assertEqual(res.status_code, 400)

    def test_duration_and_date_validation(self):
        self.client.force_authenticate(user=self.mentor)
        self.assertEqual(self.client.post(self.exams_url, self.create_payload(duration_hours=3), format='json').status_code, 400)
        self.assertEqual(self.client.post(self.exams_url, self.create_payload(start_time='nope'), format='json').status_code, 400)

    def test_expired_student_refused(self):
        self.student.status = StatusChoices.EXPIRED
        self.student.save()
        self.client.force_authenticate(user=self.admin)
        self.assertEqual(self.client.post(self.exams_url, self.create_payload(), format='json').status_code, 403)

    def test_record_result_marks_attended_and_logs(self):
        exam = self.make_exam()
        self.client.force_authenticate(user=self.mentor)
        res = self.client.post(self.result_url(exam), {
            'score': '38', 'max_score': '50', 'recording_link': 'https://drive.google.com/x', 'files': [pdf(), png()],
        }, format='multipart')
        self.assertEqual(res.status_code, 200, res.data)
        exam.refresh_from_db()
        self.assertEqual((exam.status, exam.score, exam.max_score), ('ATTENDED', 38, 50))
        self.assertEqual(exam.files.count(), 2)
        self.assertEqual(res.data['exam']['file_count'], 2)
        self.assertTrue(res.data['exam']['files'][0]['url'].startswith('http'))
        log = ActivityLog.objects.get(action='exam.mark_attended')
        self.assertEqual(log.changes['status'], {'old': 'scheduled', 'new': 'attended'})
        self.assertEqual(log.changes['score'], {'old': None, 'new': 38})
        self.assertEqual(log.context['added_files'], 2)

    def test_edit_result_diff_and_file_removal(self):
        exam = self.make_exam()
        self.client.force_authenticate(user=self.admin)
        self.client.post(self.result_url(exam), {'score': '10', 'max_score': '20', 'files': [pdf()]}, format='multipart')
        file_id = ExamFile.objects.get().id
        res = self.client.post(self.result_url(exam), {
            'score': '15', 'max_score': '20', 'recording_link': '', 'remove_file_ids': [str(file_id)],
        }, format='multipart')
        self.assertEqual(res.status_code, 200, res.data)
        exam.refresh_from_db()
        self.assertEqual(exam.score, 15)
        self.assertEqual(exam.files.count(), 0)
        log = ActivityLog.objects.get(action='exam.update_result')
        self.assertEqual(log.changes['score'], {'old': 10, 'new': 15})
        self.assertNotIn('max_score', log.changes)
        self.assertEqual(log.context['removed_files'], 1)

    def test_omitted_recording_link_is_unchanged(self):
        exam = self.make_exam(status='ATTENDED', score=5, max_score=10, recording_link='https://r.example/1')
        self.client.force_authenticate(user=self.admin)
        res = self.client.post(self.result_url(exam), {'score': '6', 'max_score': '10'}, format='multipart')
        self.assertEqual(res.status_code, 200)
        exam.refresh_from_db()
        self.assertEqual(exam.recording_link, 'https://r.example/1')

    def test_score_boundaries(self):
        exam = self.make_exam()
        self.client.force_authenticate(user=self.admin)
        for payload in ({'score': '-1', 'max_score': '10'}, {'score': '1', 'max_score': '0'},
                        {'score': '11', 'max_score': '10'}, {'score': '1.5', 'max_score': '10'}, {'score': '1'}):
            self.assertEqual(self.client.post(self.result_url(exam), payload, format='multipart').status_code, 400, payload)
        self.assertEqual(self.client.post(self.result_url(exam), {'score': '0', 'max_score': '10'}, format='multipart').status_code, 200)
        self.assertEqual(self.client.post(self.result_url(exam), {'score': '10', 'max_score': '10'}, format='multipart').status_code, 200)

    def test_recording_link_must_be_https(self):
        exam = self.make_exam()
        self.client.force_authenticate(user=self.admin)
        res = self.client.post(self.result_url(exam), {'score': '1', 'max_score': '2', 'recording_link': 'http://x'}, format='multipart')
        self.assertEqual(res.status_code, 400)

    def test_cancel_requires_reason_and_is_terminal(self):
        exam = self.make_exam()
        self.client.force_authenticate(user=self.mentor)
        res = self.client.put(self.exams_url, {'id': str(exam.id), 'status': 'cancelled'}, format='json')
        self.assertEqual(res.status_code, 400)
        res = self.client.put(self.exams_url, {'id': str(exam.id), 'status': 'cancelled', 'cancellation_reason': 'Sick'}, format='json')
        self.assertEqual(res.status_code, 200, res.data)
        exam.refresh_from_db()
        self.assertEqual(exam.status, 'CANCELLED')
        self.assertEqual(ActivityLog.objects.get(action='exam.cancel').context['reason'], 'Sick')
        # terminal
        self.assertEqual(self.client.post(self.result_url(exam), {'score': '1', 'max_score': '2'}, format='multipart').status_code, 409)
        self.assertEqual(self.client.put(self.exams_url, {'id': str(exam.id), 'start_time': self.future.isoformat(), 'duration_hours': 1}, format='json').status_code, 409)

    def test_status_cannot_be_set_to_attended_via_put(self):
        exam = self.make_exam()
        self.client.force_authenticate(user=self.admin)
        res = self.client.put(self.exams_url, {'id': str(exam.id), 'status': 'attended'}, format='json')
        self.assertEqual(res.status_code, 400)

    def test_reschedule_logs_diff_and_refuses_when_attended(self):
        exam = self.make_exam()
        self.client.force_authenticate(user=self.mentor)
        new_start = self.future + timedelta(days=1)
        res = self.client.put(self.exams_url, {'id': str(exam.id), 'start_time': new_start.isoformat(), 'duration_hours': 1.5}, format='json')
        self.assertEqual(res.status_code, 200, res.data)
        exam.refresh_from_db()
        self.assertEqual(exam.end_time - exam.start_time, timedelta(hours=1.5))
        self.assertIn('start_time', ActivityLog.objects.get(action='exam.reschedule').changes)
        # reschedule needs both fields
        self.assertEqual(self.client.put(self.exams_url, {'id': str(exam.id), 'duration_hours': 1}, format='json').status_code, 400)
        exam.status = 'ATTENDED'; exam.score = 1; exam.max_score = 2; exam.save()
        res = self.client.put(self.exams_url, {'id': str(exam.id), 'start_time': new_start.isoformat(), 'duration_hours': 1}, format='json')
        self.assertEqual(res.status_code, 409)


class ConflictTests(ExamTestBase):
    def test_exam_vs_scheduled_session(self):
        Session.objects.create(student=self.student, title='Clash', start_time=self.future, end_time=self.future + timedelta(hours=1),
                               status=SessionStatusChoices.SCHEDULED, tutor=self.tutor)
        self.client.force_authenticate(user=self.mentor)
        res = self.client.post(self.exams_url, self.create_payload(), format='json')
        self.assertEqual(res.status_code, 409)
        self.assertIn('the session "Clash"', res.data['error'])

    def test_exam_vs_student_exam_and_mentor_exam(self):
        self.make_exam()
        self.client.force_authenticate(user=self.mentor)
        self.assertEqual(self.client.post(self.exams_url, self.create_payload(), format='json').status_code, 409)
        # same mentor, different student at the same time
        self.sibling.mentor = self.mentor
        self.sibling.save()
        Session.objects.create(student=self.sibling, title='Fractions', start_time=self.future - timedelta(days=20),
                               end_time=self.future - timedelta(days=20, hours=-1), status=SessionStatusChoices.ATTENDED, tutor=self.tutor)
        res = self.client.post(self.exams_url, self.create_payload(student_id=str(self.sibling.id), chapter_name='Fractions'), format='json')
        self.assertEqual(res.status_code, 409)
        self.assertIn('another exam', res.data['error'])

    def test_attended_and_cancelled_do_not_block(self):
        self.make_exam(status='CANCELLED', cancellation_reason='x')
        self.make_exam(status='ATTENDED', score=1, max_score=2, start_time=self.future + timedelta(hours=1), end_time=self.future + timedelta(hours=2))
        self.client.force_authenticate(user=self.mentor)
        self.assertEqual(self.client.post(self.exams_url, self.create_payload(), format='json').status_code, 200)

    def test_touching_intervals_allowed_and_reschedule_excludes_self(self):
        exam = self.make_exam()
        self.client.force_authenticate(user=self.mentor)
        res = self.client.post(self.exams_url, self.create_payload(start_time=(self.future + timedelta(hours=1)).isoformat()), format='json')
        self.assertEqual(res.status_code, 200, res.data)
        res = self.client.put(self.exams_url, {'id': str(exam.id), 'start_time': self.future.isoformat(), 'duration_hours': 0.5}, format='json')
        self.assertEqual(res.status_code, 200, res.data)

    def test_session_booking_refuses_scheduled_exam(self):
        self.make_exam()
        self.client.force_authenticate(user=self.mentor)
        res = self.client.post(reverse('sessions:sessions-list-create-update'), {
            'student_id': str(self.student.id), 'base_title': 'Clash', 'series': False,
            'items': [{'start_time': self.future.isoformat(), 'duration_hours': 1}],
        }, format='json')
        self.assertEqual(res.status_code, 409)
        self.assertIn('the exam "Real Numbers"', res.data['error'])


class PermissionTests(ExamTestBase):
    def test_tutor_rejected_everywhere(self):
        exam = self.make_exam()
        self.client.force_authenticate(user=self.tutor)
        self.assertEqual(self.client.get(self.exams_url).status_code, 403)
        self.assertEqual(self.client.get(reverse('exams:exam-detail', args=[exam.id])).status_code, 403)
        self.assertEqual(self.client.post(self.exams_url, self.create_payload(), format='json').status_code, 403)
        self.assertEqual(self.client.get(self.add_url).status_code, 403)

    def test_mentor_scoped_to_own_students(self):
        self.make_exam()
        self.make_exam(student=self.foreign, mentor=self.mentor2)
        self.client.force_authenticate(user=self.mentor)
        res = self.client.get(self.exams_url)
        self.assertEqual(len(res.data['exams']), 1)
        foreign = Exam.objects.get(student=self.foreign)
        self.assertEqual(self.client.get(reverse('exams:exam-detail', args=[foreign.id])).status_code, 404)
        self.assertEqual(self.client.post(self.result_url(foreign), {'score': '1', 'max_score': '2'}, format='multipart').status_code, 403)
        self.assertEqual(self.client.post(self.exams_url, self.create_payload(student_id=str(self.foreign.id)), format='json').status_code, 403)
        self.client.force_authenticate(user=self.admin)
        self.assertEqual(len(self.client.get(self.exams_url).data['exams']), 2)

    def test_student_reads_selected_persona_only(self):
        mine = self.make_exam()
        sib = self.make_exam(student=self.sibling)
        self.as_student()
        res = self.client.get(self.exams_url)
        self.assertEqual([e['id'] for e in res.data['exams']], [str(mine.id)])
        self.assertEqual(self.client.get(reverse('exams:exam-detail', args=[sib.id])).status_code, 404)
        self.assertEqual(self.client.post(self.exams_url, self.create_payload(), format='json').status_code, 403)
        # switching persona switches the list
        self.as_student(self.sibling)
        self.assertEqual([e['id'] for e in self.client.get(self.exams_url).data['exams']], [str(sib.id)])

    def test_expired_persona_unreachable(self):
        self.make_exam()
        self.student.status = StatusChoices.EXPIRED
        self.student.save()
        self.as_student()
        # The cookie points at the expired persona; the sole usable persona
        # (the sibling, with no exams) is auto-selected instead.
        self.assertEqual(self.client.get(self.exams_url).data['exams'], [])
        res = self.client.get(reverse('student-scorecard'))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data['lifetime_count'], 0)
        # With every persona expired the trio answers access-ended.
        self.sibling.status = StatusChoices.EXPIRED
        self.sibling.save()
        self.assertEqual(self.client.get(reverse('student-scorecard')).status_code, 403)


class AdditionalExamTests(ExamTestBase):
    def test_create_requires_file_and_logs(self):
        self.client.force_authenticate(user=self.mentor)
        res = self.client.post(self.add_url, {'student_id': str(self.student.id), 'title': 'Worksheet'}, format='multipart')
        self.assertEqual(res.status_code, 400)
        res = self.client.post(self.add_url, {'student_id': str(self.student.id), 'title': 'Worksheet', 'files': [pdf(), png()]}, format='multipart')
        self.assertEqual(res.status_code, 200, res.data)
        exam = AdditionalExam.objects.get()
        self.assertEqual((exam.status, exam.mentor), ('ASSIGNED', self.mentor))
        self.assertEqual(len(res.data['additional_exam']['question_paper']), 2)
        self.assertEqual(ActivityLog.objects.get(action='additional_exam.create').context['file_count'], 2)
        self.assertEqual(self.client.post(self.add_url, {'student_id': str(self.student.id), 'title': 'x' * 201, 'files': [pdf()]}, format='multipart').status_code, 400)
        self.assertEqual(self.client.post(self.add_url, {'student_id': str(self.foreign.id), 'title': 'W', 'files': [pdf()]}, format='multipart').status_code, 403)

    def test_one_shot_submit_then_score(self):
        exam = self.make_additional()
        submit_url = reverse('additional_exams:additional-exam-submit', args=[exam.id])
        score_url = reverse('additional_exams:additional-exam-score', args=[exam.id])
        self.client.force_authenticate(user=self.mentor)
        self.assertEqual(self.client.post(score_url, {'score': 1, 'max_score': 2}, format='json').status_code, 409)
        self.as_student()
        self.assertEqual(self.client.post(submit_url, {}, format='multipart').status_code, 400)
        res = self.client.post(submit_url, {'files': [png(), png('p2.png')]}, format='multipart')
        self.assertEqual(res.status_code, 200, res.data)
        exam.refresh_from_db()
        self.assertEqual(exam.status, 'SUBMITTED')
        self.assertIsNotNone(exam.submitted_at)
        self.assertEqual(exam.files.filter(kind='answer_sheet').count(), 2)
        self.assertEqual(ActivityLog.objects.get(action='additional_exam.submit').actor, self.parent)
        self.assertEqual(self.client.post(submit_url, {'files': [png()]}, format='multipart').status_code, 409)
        # sibling persona cannot submit it
        self.as_student(self.sibling)
        self.assertEqual(self.client.post(submit_url, {'files': [png()]}, format='multipart').status_code, 404)
        # mentor scores
        self.client.force_authenticate(user=self.mentor)
        self.assertEqual(self.client.post(score_url, {'score': 3, 'max_score': 2}, format='json').status_code, 400)
        res = self.client.post(score_url, {'score': 2, 'max_score': 2, 'feedback': ' Great '}, format='json')
        self.assertEqual(res.status_code, 200, res.data)
        exam.refresh_from_db()
        self.assertEqual((exam.status, exam.score, exam.feedback, exam.scored_by), ('SCORED', 2, 'Great', self.mentor))
        log = ActivityLog.objects.get(action='additional_exam.score')
        self.assertEqual(log.changes['score'], {'old': None, 'new': 2})
        self.assertEqual(log.changes['feedback']['new'], 'Great')
        # scored is terminal
        self.assertEqual(self.client.post(score_url, {'score': 1, 'max_score': 2}, format='json').status_code, 409)

    def test_student_sees_only_own_and_tabs_data(self):
        exam = self.make_additional()
        self.make_additional(student=self.foreign, mentor=self.mentor2)
        self.as_student()
        res = self.client.get(self.add_url)
        self.assertEqual([e['id'] for e in res.data['additional_exams']], [str(exam.id)])
        res = self.client.get(reverse('additional_exams:additional-exam-detail', args=[exam.id]))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data['additional_exam']['status'], 'assigned')
        self.assertEqual(len(res.data['additional_exam']['question_paper']), 1)


class FileTests(ExamTestBase):
    def test_validation(self):
        exam = self.make_exam()
        self.client.force_authenticate(user=self.admin)
        bad = [
            SimpleUploadedFile('a.gif', b'GIF89a' + b'0' * 10, content_type='image/gif'),
            SimpleUploadedFile('a.pdf', b'<html>', content_type='application/pdf'),
            SimpleUploadedFile('a.pdf', b'', content_type='application/pdf'),
        ]
        for f in bad:
            res = self.client.post(self.result_url(exam), {'score': '1', 'max_score': '2', 'files': [f]}, format='multipart')
            self.assertEqual(res.status_code, 400, res.data)
        with override_settings(EXAM_FILE_MAX_BYTES=10):
            res = self.client.post(self.result_url(exam), {'score': '1', 'max_score': '2', 'files': [pdf()]}, format='multipart')
            self.assertEqual(res.status_code, 400)
        res = self.client.post(self.result_url(exam), {'score': '1', 'max_score': '2', 'files': [pdf(f'{i}.pdf') for i in range(11)]}, format='multipart')
        self.assertEqual(res.status_code, 400)
        self.assertEqual(Exam.objects.get().status, 'SCHEDULED')

    def test_download_permissions_and_range(self):
        exam = self.make_exam()
        self.client.force_authenticate(user=self.admin)
        self.client.post(self.result_url(exam), {'score': '1', 'max_score': '2', 'files': [pdf()]}, format='multipart')
        url = reverse('exams:exam-file', args=[ExamFile.objects.get().id])
        for user, code in ((self.admin, 200), (self.mentor, 200), (self.mentor2, 403), (self.tutor, 403), (self.other_parent, 403)):
            self.client.force_authenticate(user=user)
            self.assertEqual(self.client.get(url).status_code, code, user.email)
        self.client.force_authenticate(user=self.parent)
        res = self.client.get(url, HTTP_RANGE='bytes=0-3')
        self.assertEqual(res.status_code, 206)
        self.assertEqual(b''.join(res.streaming_content), b'%PDF')

    def test_answer_sheet_visibility_and_cascade_cleanup(self):
        exam = self.make_additional()
        self.as_student()
        self.client.post(reverse('additional_exams:additional-exam-submit', args=[exam.id]), {'files': [png()]}, format='multipart')
        sheet = AdditionalExamFile.objects.get(kind='answer_sheet')
        url = reverse('additional_exams:additional-exam-file', args=[sheet.id])
        self.client.force_authenticate(user=self.mentor)
        self.assertEqual(self.client.get(url).status_code, 200)
        self.client.force_authenticate(user=self.tutor)
        self.assertEqual(self.client.get(url).status_code, 403)
        path = sheet.file.path
        exam.delete()
        import os
        self.assertFalse(os.path.exists(path))


class IntegrationTests(ExamTestBase):
    def test_reassign_moves_open_exams_only(self):
        open_exam = self.make_exam()
        done_exam = self.make_exam(status='ATTENDED', score=1, max_score=2, start_time=self.future - timedelta(days=30), end_time=self.future - timedelta(days=30, hours=-1))
        open_add = self.make_additional()
        scored_add = self.make_additional(status='SCORED', score=1, max_score=2)
        self.client.force_authenticate(user=self.admin)
        res = self.client.post(reverse('students:student-reassign'), {'id': str(self.student.id), 'mentor': str(self.mentor2.id), 'tutor': str(self.tutor.id)}, format='json')
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data['result']['exams_repointed'], 1)
        self.assertEqual(res.data['result']['additional_exams_repointed'], 1)
        for row in (open_exam, done_exam, open_add, scored_add):
            row.refresh_from_db()
        self.assertEqual((open_exam.mentor, done_exam.mentor), (self.mentor2, self.mentor))
        self.assertEqual((open_add.mentor, scored_add.mentor), (self.mentor2, self.mentor))
        self.assertEqual(ActivityLog.objects.get(action='student.reassign_mentor').context['exams_repointed'], 1)

    def test_staff_reassign_moves_open_exams(self):
        self.make_exam()
        self.make_additional()
        self.client.force_authenticate(user=self.admin)
        res = self.client.post(reverse('user-reassign', args=[self.mentor.id]), {'new_mentor': str(self.mentor2.id), 'new_tutor': None}, format='json')
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(Exam.objects.get().mentor, self.mentor2)
        self.assertEqual(AdditionalExam.objects.get().mentor, self.mentor2)

    def test_purge_guard(self):
        Session.objects.filter(student=self.sibling).delete()
        self.make_additional(student=self.sibling)
        self.client.force_authenticate(user=self.admin)
        res = self.client.delete(reverse('students:student-detail', args=[self.sibling.id]), {'confirm_code': 'EDP2'}, format='json')
        self.assertEqual(res.status_code, 409)
        AdditionalExam.objects.all().delete()
        res = self.client.delete(reverse('students:student-detail', args=[self.sibling.id]), {'confirm_code': 'EDP2'}, format='json')
        self.assertEqual(res.status_code, 200)

    def test_dashboard_exam_slots(self):
        nxt = self.make_exam()
        last = self.make_exam(status='ATTENDED', score=1, max_score=2, start_time=self.future - timedelta(days=30), end_time=self.future - timedelta(days=30, hours=-1))
        self.make_exam(status='CANCELLED', cancellation_reason='x', start_time=self.future + timedelta(days=1), end_time=self.future + timedelta(days=1, hours=1))
        self.as_student()
        res = self.client.get(reverse('student-dashboard'))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data['next_exam']['id'], str(nxt.id))
        self.assertEqual(res.data['last_exam']['id'], str(last.id))


class ScorecardTests(ExamTestBase):
    def test_validate_score_and_entry(self):
        self.assertEqual(validate_score('7', 10), (7, 10))
        self.assertIsNone(score_entry('exam', 'x', 1, 0, timezone.now()))
        self.assertEqual(score_entry('exam', 'x', 1, 3, timezone.now())['pct'], 33)

    def test_build_scorecard_month(self):
        now = timezone.now()
        entries = [
            score_entry('exam', 'A', 40, 50, now - timedelta(days=2)),   # 80
            score_entry('exam', 'B', 30, 50, now - timedelta(days=10)),  # 60
            score_entry('exam', 'C', 50, 50, now - timedelta(days=60)),  # previous window
        ]
        card = build_scorecard(entries, 'month', now=now, zone='Asia/Kolkata')
        self.assertEqual(card['overall'], 70)
        self.assertEqual(card['delta'], -30)
        self.assertEqual(card['total_count'], 2)
        self.assertEqual(card['lifetime_count'], 3)
        self.assertEqual(len(card['buckets']), 5)
        self.assertEqual(card['categories'][1], {'category': 'exam', 'label': 'Chapter Exams', 'avg': 70, 'count': 2})
        self.assertEqual(card['recent'][0]['label'], 'A')
        week = build_scorecard(entries, 'week', now=now, zone='Asia/Kolkata')
        self.assertEqual(week['overall'], 80)
        self.assertEqual(len(week['buckets']), 7)
        allc = build_scorecard(entries, 'all', now=now, zone='Asia/Kolkata')
        self.assertEqual(allc['overall'], 80)
        self.assertIsNone(allc['delta'])
        self.assertIsNone(build_scorecard([], 'month', now=now)['overall'])

    def test_endpoint_excludes_additional_and_unattended(self):
        self.make_exam(status='ATTENDED', score=9, max_score=10, start_time=timezone.now() - timedelta(days=1), end_time=timezone.now() - timedelta(hours=23))
        self.make_exam()  # scheduled, no score
        self.make_additional(status='SCORED', score=1, max_score=10)
        self.as_student()
        res = self.client.get(reverse('student-scorecard'), {'range': 'bogus'})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data['range'], 'month')
        self.assertEqual(res.data['overall'], 90)
        self.assertEqual(res.data['lifetime_count'], 1)
