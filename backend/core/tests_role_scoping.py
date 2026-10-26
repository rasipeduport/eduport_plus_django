"""
Scoping is deny-by-default.

Access follows permissions (accounts.authz): the Admin role's group sees
everything, Mentor and Tutor their allocated students' rows, superusers
everything whatever their role (decision D1), and every other role -- BDE and
Sales TL, whose groups are empty, a future one, or a bad value in the column --
nothing. These tests pin both halves: the scope helpers give each existing role
exactly what it had, and a role without permissions is refused by every API
route. Every API view must also say which permission guards it. What each kind
of caller gets from each endpoint -- lists, profiles, file downloads -- is the
authorization matrix's job (core.tests_authz_matrix).
"""
import re
import shutil
import tempfile
import uuid
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import SimpleTestCase, override_settings
from django.utils import timezone
from rest_framework.permissions import AllowAny, IsAuthenticated, OperandHolder
from rest_framework.test import APITestCase

from accounts.team import IsTeamManager, TeamAccess
from activity.models import ActivityLog
from core.authz_matrix import api_routes, api_url_patterns
from core.querysets import scope_activity, scope_exams, scope_homework, scope_sessions, scope_students
from exams.models import AdditionalExam, Exam
from homework.models import Homework
from sessions.models import Session, SessionStatusChoices
from students.models import StatusChoices, Student

User = get_user_model()

# Every (route, method) an account of any role may succeed on: the CSRF token,
# its own identity, and signing out. Anything else must be refused.
ALLOWED_FOR_ANY_ACCOUNT = {
    ('api/auth/csrf/', 'get'),
    ('api/auth/me/', 'get'),
    ('api/auth/logout/', 'post'),
}
METHODS = ('get', 'post', 'put', 'patch', 'delete')
_ROUTE_PARAM = re.compile(r'<(?:(\w+):)?\w+>')


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
            # A superuser holds every permission whatever their role (D1), so
            # one holding MENTOR, TUTOR or an unknown role sees what an admin sees.
            'super_mentor': account('super_mentor', 'MENTOR', superuser=True),
            'super_tutor': account('super_tutor', 'TUTOR', superuser=True),
            'super_unknown': account('super_unknown', 'UNASSIGNED', superuser=True),
            'parent': account('parent', 'STUDENT'),
            # Staff roles with no permission yet, and roles nothing knows.
            'bde': account('bde', 'BDE'),
            'sales_tl': account('sales_tl', 'SALES_TL'),
            'unknown': account('unknown', 'UNASSIGNED'),
            'blank': account('blank', ''),
        }
        a = self.accounts
        self.unknown_accounts = (a['bde'], a['sales_tl'], a['unknown'], a['blank'])

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


class ScopeHelperTests(RoleScopingFixture):
    """core.querysets: each existing role keeps its rows, every role without permissions gets none."""

    ADMIN_LIKE = ('admin', 'superuser', 'super_mentor', 'super_tutor', 'super_unknown')
    NOBODY = ('parent', 'bde', 'sales_tl', 'unknown', 'blank')

    def assertScoped(self, scope, queryset, rows, expected):
        expected = {**{key: set(rows) for key in self.ADMIN_LIKE}, **{key: set() for key in self.NOBODY}, **expected}
        self.assertEqual(set(expected), set(self.accounts), 'every caller kind has an expectation')
        for key, labels in expected.items():
            with self.subTest(caller=key):
                got = set(scope(queryset, self.accounts[key]).values_list('pk', flat=True))
                self.assertEqual(got, {rows[label].pk for label in labels})

    def test_students(self):
        # A tutor sees their students only while active or inactive...
        self.assertScoped(scope_students, Student.objects.all(), self.students, {
            'mentor': {'a', 'a_expired'}, 'tutor': {'a'},
        })

    def test_students_counted_whatever_their_status(self):
        # ...except where every student they have counts (the dashboard).
        def everyone(queryset, user):
            return scope_students(queryset, user, current_only=False)
        self.assertScoped(everyone, Student.objects.all(), self.students, {
            'mentor': {'a', 'a_expired'}, 'tutor': {'a', 'a_expired'},
        })

    def test_sessions(self):
        self.assertScoped(scope_sessions, Session.objects.all(), self.sessions, {'mentor': {'a'}, 'tutor': {'a'}})

    def test_homework(self):
        self.assertScoped(scope_homework, Homework.objects.all(), self.homework, {'mentor': {'a'}, 'tutor': {'a'}})

    def test_exams(self):
        # Tutors see no exams at all.
        for model, rows in ((Exam, self.exams), (AdditionalExam, self.additional_exams)):
            with self.subTest(model=model.__name__):
                self.assertScoped(scope_exams, model.objects.all(), rows, {'mentor': {'a'}, 'tutor': set()})

    def test_activity(self):
        # Mentors and tutors read only what they wrote; a role without permissions not even that.
        self.assertScoped(scope_activity, ActivityLog.objects.filter(action='test.scoping'), self.activity, {
            'mentor': {'mentor'}, 'tutor': {'tutor'},
        })


class ApiSweepTests(RoleScopingFixture):
    """Every /api/ route, every method: a role without permissions succeeds only on the account basics."""

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


# Views open to any signed-in (or anonymous) account on purpose, and why. Every
# other API view must be guarded by a permission (core.permissions).
OPEN_VIEWS = {
    # The account basics: sign in and out, the CSRF token, the caller's own identity.
    'CsrfTokenView', 'LoginView', 'GoogleLoginView', 'LogoutView', 'MeView', 'ChangePasswordView',
    'SelectStudentView',
    # File downloads: the view scopes the file's parent row itself and answers
    # "no access to this file" (FileDownloadTests).
    'SessionFileDownloadView', 'ExamFileDownloadView', 'AdditionalExamFileDownloadView', 'HomeworkFileDownloadView',
    # Retired (D3): 410 Gone for every caller, logged.
    'AdminListView', 'UserDetailView', 'StaffStatusView',
}
# Permission classes that decide by catalogue permission (accounts.authz).
PERMISSION_FACTORIES = ('HasAppPermission', 'HasAnyAppPermission', 'ByMethod', 'IsStudentUser')


def _decides_by_permission(permission):
    if isinstance(permission, OperandHolder):
        return _decides_by_permission(permission.op1_class) and _decides_by_permission(permission.op2_class)
    if permission in (TeamAccess, IsTeamManager):
        return True
    return permission.__name__.startswith(PERMISSION_FACTORIES)


def api_views():
    for route, pattern in api_url_patterns():
        yield route, pattern.callback.cls


class ViewPermissionTests(SimpleTestCase):
    """Every API view declares the permission that guards it; none admits by role."""

    def test_every_api_view_is_guarded_by_a_permission(self):
        unguarded = []
        for route, view in api_views():
            classes = list(view.permission_classes)
            if view.__name__ in OPEN_VIEWS:
                self.assertTrue(set(classes) <= {AllowAny, IsAuthenticated}, f'{view.__name__} is listed as open')
                continue
            if not any(_decides_by_permission(permission) for permission in classes if permission is not IsAuthenticated):
                unguarded.append(f'{route} ({view.__name__})')
        self.assertEqual(unguarded, [], 'API views without a permission guard')

    def test_staff_endpoints_also_require_a_signed_in_account(self):
        # IsAuthenticated first, so an anonymous caller gets "not signed in" rather than "not allowed".
        for route, view in api_views():
            if view.__name__ not in OPEN_VIEWS:
                with self.subTest(route=route):
                    self.assertIs(list(view.permission_classes)[0], IsAuthenticated)
