import shutil
import tempfile
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from activity.models import ActivityLog
from homework.models import Homework
from students.models import Student, StatusChoices
from sessions.models import Session, SessionStatusChoices
from .models import (
    Exam, ExamStatusChoices, ExamFile,
    AdditionalExam, AdditionalExamStatusChoices, AdditionalExamFile,
)
from .services import RECENT_PAGE_SIZE, build_scorecard, derive_chapter_names, entries_in_window, serialize_entry, validate_score, score_entry

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


class StudentScoresTests(ExamTestBase):
    """GET /api/student/scores/: the scorecard's completed results, merged and paged."""

    def scored_exam(self, days_ago, score=1, max_score=2, student=None, **kw):
        end = timezone.now() - timedelta(days=days_ago)
        return self.make_exam(student=student or self.student, status='ATTENDED', score=score, max_score=max_score,
                              start_time=end - timedelta(hours=1), end_time=end, chapter_name=f'Exam {days_ago}d', **kw)

    def scored_additional(self, days_ago, score=1, max_score=2, student=None):
        return self.make_additional(student=student or self.student, status='SCORED', score=score, max_score=max_score,
                                    scored_at=timezone.now() - timedelta(days=days_ago), title=f'Worksheet {days_ago}d')

    def scored_homework(self, days_ago, score=1, max_score=2):
        session = Session.objects.create(student=self.student, title=f'HW session {days_ago}', tutor=self.tutor,
                                         start_time=timezone.now() - timedelta(days=days_ago + 1),
                                         end_time=timezone.now() - timedelta(days=days_ago + 1, hours=-1),
                                         status=SessionStatusChoices.ATTENDED, homework_link='https://hw.example/x')
        return Homework.objects.create(session=session, student=self.student, assigned_by=self.mentor, status='SCORED',
                                       score=score, max_score=max_score, scored_at=timezone.now() - timedelta(days=days_ago))

    def test_recent_entries_carry_ids_for_all_three_kinds(self):
        ex = self.scored_exam(1)
        add = self.scored_additional(2)
        hw = self.scored_homework(3)
        self.as_student()
        recent = self.client.get(reverse('student-scorecard')).data['recent']
        self.assertEqual([(e['category'], e['id']) for e in recent],
                         [('exam', str(ex.id)), ('additional_exam', str(add.id)), ('homework', str(hw.id))])

    def test_merged_newest_first_and_paged(self):
        # 10 completed items, interleaved kinds, distinct ages 1..10 days.
        made = {}
        for d in range(1, 11):
            if d % 3 == 0:
                made[d] = ('homework', self.scored_homework(d))
            elif d % 3 == 1:
                made[d] = ('exam', self.scored_exam(d))
            else:
                made[d] = ('additional_exam', self.scored_additional(d))
        self.as_student()
        p1 = self.client.get(reverse('student-scores'), {'range': 'all'})
        self.assertEqual(p1.status_code, 200)
        n = RECENT_PAGE_SIZE
        self.assertEqual((p1.data['count'], p1.data['page'], p1.data['page_size']), (10, 1, n))
        self.assertEqual([(e['category'], e['id']) for e in p1.data['results']],
                         [(made[d][0], str(made[d][1].id)) for d in range(1, n + 1)])
        self.assertEqual(set(p1.data['results'][0]), {'id', 'category', 'label', 'score', 'max_score', 'pct', 'scored_at'})
        p2 = self.client.get(reverse('student-scores'), {'range': 'all', 'page': 2}).data
        self.assertEqual((p2['count'], p2['page'], p2['page_size']), (10, 2, n))
        self.assertEqual([e['id'] for e in p2['results']], [str(made[d][1].id) for d in range(n + 1, min(2 * n, 10) + 1)])
        self.assertFalse({e['id'] for e in p1.data['results']} & {e['id'] for e in p2['results']})
        # Page 1 is exactly the scorecard's recent list.
        card = self.client.get(reverse('student-scorecard'), {'range': 'all'}).data
        self.assertEqual(card['recent'], p1.data['results'])
        self.assertEqual(card['total_count'], p1.data['count'])
        # page_size is honoured and capped.
        self.assertEqual(len(self.client.get(reverse('student-scores'), {'range': 'all', 'page_size': 2}).data['results']), 2)
        self.assertEqual(self.client.get(reverse('student-scores'), {'range': 'all', 'page_size': 999}).data['page_size'], 200)

    def test_range_filtering_matches_scorecard(self):
        self.scored_exam(2)            # week
        self.scored_homework(10)       # month
        self.scored_additional(40)     # all
        self.as_student()
        for range_key, expected in (('week', 1), ('month', 2), ('all', 3), ('bogus', 2)):
            res = self.client.get(reverse('student-scores'), {'range': range_key}).data
            card = self.client.get(reverse('student-scorecard'), {'range': range_key}).data
            self.assertEqual(res['count'], expected, range_key)
            self.assertEqual(len(res['results']), expected, range_key)
            self.assertEqual(res['count'], card['total_count'], range_key)
            self.assertEqual(res['results'], card['recent'], range_key)

    def test_entries_in_window_uses_the_scorecard_window(self):
        now = timezone.now()
        entries = [
            score_entry('exam', 'A', 1, 2, now - timedelta(days=2), entry_id='a'),
            score_entry('homework', 'B', 1, 2, now - timedelta(days=10), entry_id='b'),
            score_entry('additional_exam', 'C', 1, 2, now - timedelta(days=40), entry_id='c'),
        ]
        for range_key in ('week', 'month', 'all'):
            card = build_scorecard(entries, range_key, now=now, zone='Asia/Kolkata')
            listed = entries_in_window(entries, range_key, now=now, zone='Asia/Kolkata')
            self.assertEqual([e['id'] for e in listed], [e['id'] for e in card['recent']], range_key)
            self.assertEqual(len(listed), card['total_count'], range_key)

    def test_unscored_rows_are_excluded(self):
        self.scored_exam(1)
        self.make_exam()                                                   # scheduled
        self.make_exam(status='CANCELLED', cancellation_reason='x')
        self.make_additional()                                             # assigned
        self.make_additional(status='SUBMITTED', submitted_at=timezone.now())
        self.make_additional(status='SCORED', score=1, max_score=2)        # scored but no scored_at
        self.as_student()
        res = self.client.get(reverse('student-scores'), {'range': 'all'}).data
        self.assertEqual(res['count'], 1)
        self.assertEqual(res['results'][0]['category'], 'exam')

    def test_persona_and_staff_rules_match_scorecard(self):
        mine = self.scored_exam(1)
        theirs = self.scored_exam(1, student=self.foreign, mentor=self.mentor2)
        # The other family sees only its own student's scores.
        self.client.force_authenticate(user=self.other_parent)
        self.client.cookies['ep-student-id'] = str(self.foreign.id)
        res = self.client.get(reverse('student-scores'), {'range': 'all'}).data
        self.assertEqual([e['id'] for e in res['results']], [str(theirs.id)])
        # A cookie naming someone else's student is ignored, never honoured.
        self.client.cookies['ep-student-id'] = str(mine.student_id)
        res = self.client.get(reverse('student-scores'), {'range': 'all'}).data
        self.assertEqual([e['id'] for e in res['results']], [str(theirs.id)])
        # Staff get the same answer as the scorecard: forbidden.
        for user in (self.mentor, self.admin, self.tutor):
            self.client.force_authenticate(user=user)
            self.assertEqual(self.client.get(reverse('student-scores')).status_code, 403, user.role)
            self.assertEqual(self.client.get(reverse('student-scorecard')).status_code, 403, user.role)


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
        self.assertAlmostEqual(score_entry('exam', 'x', 1, 3, timezone.now())['pct'], 100 / 3)

    def test_build_scorecard_month(self):
        now = timezone.now()
        entries = [
            score_entry('exam', 'A', 40, 50, now - timedelta(days=2)),   # 80
            score_entry('exam', 'B', 30, 50, now - timedelta(days=10)),  # 60
            score_entry('exam', 'C', 50, 50, now - timedelta(days=45)),  # previous 30-day window
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

    def test_averages_round_once(self):
        # 1/8 = 12.5 and 3/8 = 37.5 average to exactly 25. Rounding each item
        # first (13 + 38) would give 25.5 -> 26.
        now = timezone.now()
        entries = [
            score_entry('exam', 'A', 1, 8, now - timedelta(days=1)),
            score_entry('exam', 'B', 3, 8, now - timedelta(days=1)),
            score_entry('exam', 'P', 7, 40, now - timedelta(days=9)),  # previous week: 17.5
        ]
        card = build_scorecard(entries, 'week', now=now, zone='Asia/Kolkata')
        self.assertEqual(card['overall'], 25)
        self.assertEqual(card['categories'][1]['avg'], 25)
        self.assertEqual([b['exam'] for b in card['buckets'] if b['exam'] is not None], [25])
        # Delta from the unrounded means: 25.0 - 17.5 = 7.5 -> 8 (26 - 17.5 would give 9).
        self.assertEqual(card['delta'], 8)
        # Per-item display values are still rounded half-up, and still integers.
        self.assertEqual([e['pct'] for e in card['recent']], [13, 38])
        self.assertTrue(all(isinstance(e['pct'], int) for e in card['recent']))

    def test_month_window_is_exactly_30_days(self):
        tz = ZoneInfo('Asia/Kolkata')
        now = datetime(2026, 10, 6, 15, 0, tzinfo=tz)
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        window_start = today - timedelta(days=29)
        inside = score_entry('exam', 'In', 40, 50, window_start + timedelta(minutes=1))    # 80, day 30 of 30
        outside = score_entry('exam', 'Out', 10, 50, window_start - timedelta(minutes=1))  # 20, day 31
        card = build_scorecard([inside, outside], 'month', now=now, zone='Asia/Kolkata')
        self.assertEqual(card['overall'], 80)
        self.assertEqual(card['total_count'], 1)
        self.assertEqual(card['lifetime_count'], 2)
        self.assertEqual([e['label'] for e in card['recent']], ['In'])
        # The day-31 score is the previous window, so it drives the delta only.
        self.assertEqual(card['delta'], 60)
        # Five 6-day buckets tile the 30 days exactly, oldest first.
        keys = [b['key'] for b in card['buckets']]
        self.assertEqual(keys, [(window_start + timedelta(days=6 * k)).date().isoformat() for k in range(5)])
        self.assertEqual(card['buckets'][0]['label'], '7 Sep')
        self.assertEqual([b['exam'] for b in card['buckets']], [80, None, None, None, None])
        # A score on the window's first and last day both land in a bucket.
        latest = score_entry('exam', 'Now', 50, 50, now - timedelta(hours=1))
        card = build_scorecard([inside, latest], 'month', now=now, zone='Asia/Kolkata')
        self.assertEqual([b['exam'] for b in card['buckets']], [80, None, None, None, 100])
        self.assertEqual(card['overall'], 90)

    def test_endpoint_includes_scored_additional_excludes_unattended(self):
        now = timezone.now()
        self.make_exam(status='ATTENDED', score=9, max_score=10, start_time=now - timedelta(days=1), end_time=now - timedelta(hours=23))
        self.make_exam()  # scheduled, no score
        self.make_additional(status='SCORED', score=1, max_score=10, scored_at=now - timedelta(hours=2))
        self.make_additional(status='SCORED', score=5, max_score=10)                       # no scored_at: ignored
        self.make_additional(status='SUBMITTED', submitted_at=now)                         # not scored
        self.make_additional(status='SCORED', score=10, max_score=10, scored_at=now - timedelta(days=40))  # outside month
        self.as_student()
        res = self.client.get(reverse('student-scorecard'), {'range': 'bogus'})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data['range'], 'month')
        self.assertEqual(res.data['overall'], 50)       # (9 + 1) / (10 + 10)
        self.assertEqual(res.data['total_count'], 2)
        self.assertEqual(res.data['lifetime_count'], 3)
        self.assertEqual([c['category'] for c in res.data['categories']], ['homework', 'exam', 'additional_exam'])
        add = res.data['categories'][2]
        self.assertEqual((add['label'], add['avg'], add['count']), ('Additional Exams', 10, 1))
        self.assertEqual(res.data['recent'][0]['label'], 'Worksheet 1')
        self.assertEqual(res.data['recent'][0]['category'], 'additional_exam')
        self.assertIn('additional_exam', res.data['buckets'][-1])
        allc = self.client.get(reverse('student-scorecard'), {'range': 'all'}).data
        self.assertEqual((allc['total_count'], allc['overall']), (3, 67))  # 20 / 30

    def test_aggregates_are_marks_based(self):
        now = timezone.now()
        d = now - timedelta(days=1)
        entries = [
            score_entry('exam', 'E1', 25, 50, d),
            score_entry('exam', 'E2', 10, 100, d),
            score_entry('homework', 'Homework', 9, 10, d),
            score_entry('homework', 'Homework', 1, 90, d),
            score_entry('additional_exam', 'Worksheet', 1, 100, d),
            score_entry('additional_exam', 'Worksheet', 49, 50, d),
            score_entry('exam', 'Prev', 30, 60, now - timedelta(days=9)),  # previous week: 50
        ]
        card = build_scorecard(entries, 'week', now=now, zone='Asia/Kolkata')
        cats = {c['category']: c for c in card['categories']}
        # 25/50 + 10/100 -> 35/150 = 23.33 -> 23 (an item-mean would say 30).
        self.assertEqual((cats['exam']['avg'], cats['exam']['count']), (23, 2))
        # 9/10 + 1/90 -> 10/100 = 10 (item-mean 45.6).
        self.assertEqual((cats['homework']['avg'], cats['homework']['count']), (10, 2))
        # 1/100 + 49/50 -> 50/150 = 33.33 -> 33 (item-mean 49.5).
        self.assertEqual((cats['additional_exam']['avg'], cats['additional_exam']['count']), (33, 2))
        # Overall across all three: 95/400 = 23.75 -> 24 (item-mean 30.9).
        self.assertEqual(card['overall'], 24)
        # Same bucket holds every item, so the bucket values match the tiles.
        filled = [b for b in card['buckets'] if b['exam'] is not None]
        self.assertEqual(len(filled), 1)
        self.assertEqual((filled[0]['exam'], filled[0]['homework'], filled[0]['additional_exam']), (23, 10, 33))
        # Delta: 23.75 - 50 = -26.25 -> -26, from the unrounded marks-based figures.
        self.assertEqual(card['delta'], -26)
        # Individual recent scores keep their own percentage.
        # Individual scores keep their own percentage (the full window, not just the recent slice).
        listed = [serialize_entry(e) for e in entries_in_window(entries, 'week', now=now, zone='Asia/Kolkata')]
        by_label = {(e['label'], e['score']): e['pct'] for e in listed}
        self.assertEqual(by_label[('E1', 25)], 50)
        self.assertEqual(by_label[('E2', 10)], 10)
        self.assertEqual(by_label[('Worksheet', 1)], 1)

    def test_empty_categories_are_null(self):
        now = timezone.now()
        card = build_scorecard([score_entry('exam', 'E', 25, 50, now - timedelta(days=1))], 'week', now=now, zone='Asia/Kolkata')
        cats = {c['category']: c for c in card['categories']}
        self.assertEqual((cats['homework']['avg'], cats['homework']['count']), (None, 0))
        self.assertEqual((cats['additional_exam']['avg'], cats['additional_exam']['count']), (None, 0))
        self.assertEqual(cats['exam']['avg'], 50)
        self.assertTrue(all(b['homework'] is None and b['additional_exam'] is None for b in card['buckets']))
        self.assertIsNone(card['delta'])
        empty = build_scorecard([], 'week', now=now)
        self.assertIsNone(empty['overall'])
        self.assertTrue(all(c['avg'] is None and c['count'] == 0 for c in empty['categories']))
