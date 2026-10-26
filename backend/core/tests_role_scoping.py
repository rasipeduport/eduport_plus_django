"""
Role scoping is deny-by-default.

Access is granted role by role: ADMIN (and superusers) see everything, MENTOR
and TUTOR their allocated students' rows, and every other role -- a future one,
or a bad value in the column -- nothing. These tests pin both halves: the
existing roles keep exactly what they had, superuser edge cases included, and an
unknown role is refused by every API route and every file download.
"""
import re
import shutil
import tempfile
import uuid
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.test import SimpleTestCase, override_settings
from django.urls import URLResolver, get_resolver, reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from activity.models import ActivityLog
from core.permissions import STAFF_ROLES
from core.querysets import (
    scope_activity_by_role,
    scope_exams_by_role,
    scope_homework_by_role,
    scope_sessions_by_role,
    scope_students_by_role,
)
from exams.models import AdditionalExam, AdditionalExamFile, Exam, ExamFile
from homework.models import Homework, HomeworkFile
from sessions.models import Session, SessionFile, SessionStatusChoices
from students.models import StatusChoices, Student
from students.services import TUTOR_VISIBLE_FIELDS, build_profile_stats, redact_student_for_role, serialize_student

User = get_user_model()

PDF = b'%PDF-1.4\n' + b'0' * 64

# Every (route, method) an account of any role may succeed on: the CSRF token,
# its own identity, and signing out. Anything else must be refused.
ALLOWED_FOR_ANY_ACCOUNT = {
    ('api/auth/csrf/', 'get'),
    ('api/auth/me/', 'get'),
    ('api/auth/logout/', 'post'),
}
METHODS = ('get', 'post', 'put', 'patch', 'delete')
_ROUTE_PARAM = re.compile(r'<(?:(\w+):)?\w+>')


def api_routes(patterns=None, prefix=''):
    """Every URL route under /api/, as written in the URLconf (with <params>)."""
    for entry in get_resolver().url_patterns if patterns is None else patterns:
        route = prefix + str(entry.pattern)
        if isinstance(entry, URLResolver):
            if route.startswith('api/'):
                yield from api_routes(entry.url_patterns, route)
        elif route.startswith('api/'):
            yield route


def concrete_path(route):
    """A requestable path for ``route``: a fresh UUID for ids, a valid word otherwise."""
    def fill(match):
        converter = match.group(1)
        if converter == 'uuid':
            return str(uuid.uuid4())
        if converter == 'int':
            return '1'
        return 'notes'
    return '/' + _ROUTE_PARAM.sub(fill, route)


class RoleScopingFixture(APITestCase):
    """
    Two allocated students per mentor/tutor pair (one active, one expired), with
    a session, homework, chapter exam and additional exam for each active one,
    and an activity row per actor. ``self.accounts`` names every caller kind.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._media = tempfile.mkdtemp(prefix='eduplus-scoping-')
        cls._override = override_settings(MEDIA_ROOT=cls._media)
        cls._override.enable()

    @classmethod
    def tearDownClass(cls):
        cls._override.disable()
        shutil.rmtree(cls._media, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        def account(key, role, superuser=False):
            return User.objects.create_user(
                email=f'{key}@scoping.test', password='p', full_name=key, role=role, is_superuser=superuser,
            )

        self.accounts = {
            'admin': account('admin', 'ADMIN'),
            'superuser': account('superuser', 'ADMIN', superuser=True),
            'mentor': account('mentor', 'MENTOR'),
            'tutor': account('tutor', 'TUTOR'),
            # A superuser holding the MENTOR or TUTOR role keeps that role's scope.
            'super_mentor': account('super_mentor', 'MENTOR', superuser=True),
            'super_tutor': account('super_tutor', 'TUTOR', superuser=True),
            # A superuser with a role nobody knows is an admin, as IsAdminUser says.
            'super_unknown': account('super_unknown', 'UNASSIGNED', superuser=True),
            'parent': account('parent', 'STUDENT'),
            'unknown': account('unknown', 'UNASSIGNED'),
            'blank': account('blank', ''),
        }
        a = self.accounts
        self.unknown_accounts = (a['unknown'], a['blank'])

        def student(code, mentor, tutor, status=StatusChoices.ACTIVE):
            return Student.objects.create(
                profile=a['parent'], student_code=code, full_name=code, mentor=mentor, tutor=tutor,
                total_class_quota=10, status=status,
            )

        self.students = {
            'a': student('SCOPE-A', a['mentor'], a['tutor']),
            'a_expired': student('SCOPE-A-EXP', a['mentor'], a['tutor'], StatusChoices.EXPIRED),
            'b': student('SCOPE-B', a['super_mentor'], a['super_tutor']),
            'b_expired': student('SCOPE-B-EXP', a['super_mentor'], a['super_tutor'], StatusChoices.EXPIRED),
        }
        s = self.students
        start = timezone.now() - timedelta(days=1)

        self.sessions = {}
        self.homework = {}
        self.exams = {}
        self.additional_exams = {}
        for key, mentor, tutor in (('a', a['mentor'], a['tutor']), ('b', a['super_mentor'], a['super_tutor'])):
            session = Session.objects.create(
                student=s[key], tutor=tutor, title=f'Class {key}', start_time=start,
                end_time=start + timedelta(hours=1), status=SessionStatusChoices.ATTENDED,
                homework_link='https://hw.example/1',
            )
            self.sessions[key] = session
            # Scored, so the mentor's "only once scored" submission rule lets them in.
            self.homework[key] = Homework.objects.create(
                session=session, student=s[key], status='SCORED', score=8, max_score=10, assigned_by=mentor,
            )
            self.exams[key] = Exam.objects.create(
                student=s[key], mentor=mentor, chapter_name='Real Numbers',
                start_time=start, end_time=start + timedelta(hours=1),
            )
            self.additional_exams[key] = AdditionalExam.objects.create(student=s[key], mentor=mentor, title='Worksheet')

        self.activity = {
            key: ActivityLog.objects.create(
                actor=a[key], actor_role=a[key].role, action='test.scoping', entity_type='test', entity_id=key,
            )
            for key in ('admin', 'mentor', 'tutor', 'super_mentor', 'unknown')
        }

    @staticmethod
    def attach(row, **fields):
        """Give a file row real bytes under MEDIA_ROOT, as an upload would."""
        for name, value in dict(file_name='file.pdf', content_type='application/pdf',
                                size_bytes=len(PDF), extension='.pdf', **fields).items():
            setattr(row, name, value)
        row.file.save(f'{row.id}.pdf', ContentFile(PDF), save=False)
        row.save()
        return row


class ScopeHelperTests(RoleScopingFixture):
    """core.querysets: each existing role keeps its rows, every other role gets none."""

    ADMIN_LIKE = ('admin', 'superuser', 'super_unknown')
    NOBODY = ('parent', 'unknown', 'blank')

    def assertScoped(self, scope, queryset, rows, expected):
        expected = {**{key: set(rows) for key in self.ADMIN_LIKE}, **{key: set() for key in self.NOBODY}, **expected}
        self.assertEqual(set(expected), set(self.accounts), 'every caller kind has an expectation')
        for key, labels in expected.items():
            with self.subTest(caller=key):
                got = set(scope(queryset, self.accounts[key]).values_list('pk', flat=True))
                self.assertEqual(got, {rows[label].pk for label in labels})

    def test_students(self):
        self.assertScoped(scope_students_by_role, Student.objects.all(), self.students, {
            'mentor': {'a', 'a_expired'}, 'tutor': {'a', 'a_expired'},
            'super_mentor': {'b', 'b_expired'}, 'super_tutor': {'b', 'b_expired'},
        })

    def test_sessions(self):
        self.assertScoped(scope_sessions_by_role, Session.objects.all(), self.sessions, {
            'mentor': {'a'}, 'tutor': {'a'}, 'super_mentor': {'b'}, 'super_tutor': {'b'},
        })

    def test_homework(self):
        self.assertScoped(scope_homework_by_role, Homework.objects.all(), self.homework, {
            'mentor': {'a'}, 'tutor': {'a'}, 'super_mentor': {'b'}, 'super_tutor': {'b'},
        })

    def test_exams(self):
        # Tutors see no exams at all -- a superuser holding the TUTOR role included.
        for model, rows in ((Exam, self.exams), (AdditionalExam, self.additional_exams)):
            with self.subTest(model=model.__name__):
                self.assertScoped(scope_exams_by_role, model.objects.all(), rows, {
                    'mentor': {'a'}, 'tutor': set(), 'super_mentor': {'b'}, 'super_tutor': set(),
                })

    def test_activity(self):
        # Mentors and tutors read only what they wrote; an unknown role not even that.
        self.assertScoped(scope_activity_by_role, ActivityLog.objects.filter(action='test.scoping'), self.activity, {
            'mentor': {'mentor'}, 'tutor': {'tutor'}, 'super_mentor': {'super_mentor'}, 'super_tutor': set(),
        })


class StudentListTests(RoleScopingFixture):
    """GET /api/students/ now goes through scope_students_by_role, with the tutor's status filter kept."""

    def test_each_role_lists_what_it_did_before(self):
        url = reverse('students:student-list')
        expected = {
            'admin': {'SCOPE-A', 'SCOPE-A-EXP', 'SCOPE-B', 'SCOPE-B-EXP'},
            'superuser': {'SCOPE-A', 'SCOPE-A-EXP', 'SCOPE-B', 'SCOPE-B-EXP'},
            'mentor': {'SCOPE-A', 'SCOPE-A-EXP'},
            'tutor': {'SCOPE-A'},
            'super_mentor': {'SCOPE-B', 'SCOPE-B-EXP'},
            # The status filter follows the role, so it applies to a superuser tutor too.
            'super_tutor': {'SCOPE-B'},
        }
        for key, codes in expected.items():
            with self.subTest(caller=key):
                self.client.force_authenticate(user=self.accounts[key])
                res = self.client.get(url)
                self.assertEqual(res.status_code, 200)
                self.assertEqual({row['student_code'] for row in res.data}, codes)

    def test_unknown_roles_are_refused(self):
        for account in self.unknown_accounts:
            with self.subTest(role=account.role):
                self.client.force_authenticate(user=account)
                self.assertEqual(self.client.get(reverse('students:student-list')).status_code, 403)


class StudentRedactionTests(RoleScopingFixture):
    """students.services: only admins, mentors and superusers get the full record."""

    def test_full_record_for_admins_mentors_and_superusers(self):
        row = serialize_student(self.students['a'])
        for key in ('admin', 'mentor', 'super_tutor', 'super_unknown'):
            with self.subTest(caller=key):
                user = self.accounts[key]
                self.assertEqual(redact_student_for_role(row, user), row)
                stats = build_profile_stats(self.students['a'], user)
                self.assertIn('quota', stats)
                self.assertIsNotNone(stats['exams'])

    def test_tutors_and_unknown_roles_get_the_tutor_view(self):
        row = serialize_student(self.students['a'])
        for account in (self.accounts['tutor'], *self.unknown_accounts):
            with self.subTest(role=account.role):
                kept = redact_student_for_role(row, account)
                self.assertLessEqual(set(kept), set(TUTOR_VISIBLE_FIELDS))
                self.assertNotIn('mobile_number', kept)
                self.assertEqual(kept['profile'], {'avatar_url': row['profile']['avatar_url']})
                stats = build_profile_stats(self.students['a'], account)
                self.assertNotIn('quota', stats)
                self.assertIsNone(stats['exams'])


class FileDownloadTests(RoleScopingFixture):
    """
    The four download views admit any signed-in account and rely on the scope
    helpers, so these are where deny-by-default changes an answer: an unknown
    role used to be scoped to everything.
    """

    def setUp(self):
        super().setUp()
        uploader = self.accounts['admin']
        self.urls = {
            'session': reverse('sessions:session-file', args=[self.attach(
                SessionFile(session=self.sessions['a'], field='notes', uploaded_by=uploader)).id]),
            'exam': reverse('exams:exam-file', args=[self.attach(
                ExamFile(exam=self.exams['a'], uploaded_by=uploader)).id]),
            'additional_exam': reverse('additional_exams:additional-exam-file', args=[self.attach(
                AdditionalExamFile(additional_exam=self.additional_exams['a'], kind='question_paper',
                                   uploaded_by=uploader)).id]),
            'homework': reverse('homework:homework-file', args=[self.attach(
                HomeworkFile(homework=self.homework['a'], uploaded_by=self.accounts['parent'])).id]),
        }

    def assertDownloads(self, account, expected):
        self.client.force_authenticate(user=account)
        for kind, code in expected.items():
            with self.subTest(caller=account.email, file=kind):
                self.assertEqual(self.client.get(self.urls[kind]).status_code, code)

    def test_unknown_roles_are_refused_every_file(self):
        for account in self.unknown_accounts:
            self.assertDownloads(account, dict.fromkeys(self.urls, 403))

    def test_existing_roles_keep_their_downloads(self):
        a = self.accounts
        everything = dict.fromkeys(self.urls, 200)
        self.assertDownloads(a['admin'], everything)
        self.assertDownloads(a['superuser'], everything)
        self.assertDownloads(a['super_unknown'], everything)
        self.assertDownloads(a['mentor'], everything)  # the homework is scored
        self.assertDownloads(a['tutor'], {'session': 200, 'exam': 403, 'additional_exam': 403, 'homework': 200})
        # Students are allocated elsewhere, so the other pair gets nothing.
        self.assertDownloads(a['super_mentor'], dict.fromkeys(self.urls, 403))
        self.assertDownloads(a['super_tutor'], dict.fromkeys(self.urls, 403))

    def test_a_mentor_still_waits_for_the_score(self):
        homework = self.homework['a']
        Homework.objects.filter(pk=homework.pk).update(status='SUBMITTED', score=None, max_score=None)
        self.assertDownloads(self.accounts['mentor'], {'homework': 403})
        self.assertDownloads(self.accounts['tutor'], {'homework': 200})


class ApiSweepTests(RoleScopingFixture):
    """Every /api/ route, every method: an unknown role succeeds only on the account basics."""

    def setUp(self):
        super().setUp()
        cache.clear()

    def tearDown(self):
        # The login and password-change throttles count in this cache.
        cache.clear()
        super().tearDown()

    def test_the_sweep_sees_the_whole_api(self):
        routes = set(api_routes())
        self.assertGreater(len(routes), 40)
        for route in ('api/students/', 'api/sessions/files/<uuid:file_id>/', 'api/team/<uuid:pk>/permissions/',
                      'api/homework/files/<uuid:file_id>/', 'api/dashboard/stats/', 'api/student/scorecard/'):
            self.assertIn(route, routes)
        for route, _method in ALLOWED_FOR_ANY_ACCOUNT:
            self.assertIn(route, routes)

    def test_unknown_roles_get_nothing_from_any_api_route(self):
        routes = sorted(set(api_routes()))
        for account in self.unknown_accounts:
            self.client.force_authenticate(user=account)
            leaks = []
            for route in routes:
                for method in METHODS:
                    if (route, method) in ALLOWED_FOR_ANY_ACCOUNT:
                        continue
                    cache.clear()  # each call answers for itself, never with an earlier call's 429
                    path = concrete_path(route)
                    if method == 'get':
                        res = self.client.get(path)
                    else:
                        res = getattr(self.client, method)(path, {}, format='json')
                    if 200 <= res.status_code < 300:
                        leaks.append(f'{method.upper()} {route} -> {res.status_code}')
            with self.subTest(role=account.role):
                self.assertEqual(leaks, [])

    def test_the_account_basics_answer_only_about_the_caller(self):
        for account in self.unknown_accounts:
            with self.subTest(role=account.role):
                self.client.force_authenticate(user=account)
                res = self.client.get('/api/auth/me/')
                self.assertEqual(res.status_code, 200)
                self.assertEqual(res.data['user']['id'], str(account.id))
                self.assertEqual(res.data['user']['permissions'], [])
                self.assertNotIn('student_profiles', res.data)


class StaffRolesTests(SimpleTestCase):
    def test_staff_roles_stay_the_three_class_running_roles(self):
        self.assertEqual(
            STAFF_ROLES, ('ADMIN', 'MENTOR', 'TUTOR'),
            'STAFF_ROLES admits a role to every student-operations endpoint, and several views treat '
            'anyone there who is neither MENTOR nor TUTOR as an admin. Give a new role permission '
            'classes of its own instead (see core/permissions.py).',
        )
