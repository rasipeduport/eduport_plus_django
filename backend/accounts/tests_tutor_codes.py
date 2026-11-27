"""
Tutor IDs (accounts.tutor_codes): issued once, in order, to every tutor, by
every path that makes one; never changed, never issued twice; read by
administrators and by each tutor for themselves only. The migration tests
run the real migrations in the disposable test database.
"""
import threading
import time
import uuid
from datetime import timedelta

from django.db import DatabaseError, IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import Client, TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from activity.models import ActivityLog
from sessions.serializers import ProfileBriefSerializer

from .models import TutorCodeCounter, User
from .tests_auth import PLAIN_STORAGES, admin_change_form_data
from .tests_team import FAST_HASHING, STRONG, TEAM_URL, TEMPORARY, TeamTestCase, member_url, view_team_permission
from .tutor_codes import TUTOR_CODE_COUNTER, allocate_tutor_code, format_tutor_code, tutor_code_number

ME_URL = '/api/auth/me/'


def counter_value():
    row = TutorCodeCounter.objects.filter(pk=TUTOR_CODE_COUNTER).first()
    return row.value if row else None


def code_of(account):
    return User.objects.values_list('tutor_code', flat=True).get(pk=account.pk)


class TutorCodeIssueTests(TeamTestCase):
    """setUp's tutor1 is the first tutor: EPT0001."""

    def tutor_payload(self, username, **overrides):
        fields = {'username': username, 'email': f'{username}@eduport.com', 'full_name': username.title(),
                  'role': 'TUTOR'}
        return self.create_payload(**{**fields, **overrides})

    def test_the_format(self):
        self.assertEqual((format_tutor_code(1), format_tutor_code(42), format_tutor_code(12345)),
                         ('EPT0001', 'EPT0042', 'EPT12345'))
        self.assertEqual((tutor_code_number('EPT0042'), tutor_code_number('EDP0042'), tutor_code_number(None)),
                         (42, None, None))

    def test_the_first_tutor_is_EPT0001_and_no_one_else_has_an_id(self):
        self.assertEqual(code_of(self.tutor), 'EPT0001')
        for account in (self.root, self.admin, self.mentor, self.parent):
            self.assertIsNone(code_of(account))
        self.assertEqual(counter_value(), 1)

    def test_creating_a_tutor_returns_the_new_id(self):
        response = self.client.post(TEAM_URL, self.tutor_payload('new.tutor'), format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()['tutor_code'], 'EPT0002')
        created = User.objects.get(username='new.tutor')
        self.assertEqual(created.tutor_code, 'EPT0002')
        self.assertEqual(ActivityLog.objects.get(action='staff.create').context['tutor_code'], 'EPT0002')

    def test_ids_follow_in_order_and_other_roles_take_no_number(self):
        made = []
        for username, role in (('t2', 'TUTOR'), ('m2', 'MENTOR'), ('b2', 'BDE'), ('t3', 'TUTOR'), ('s2', 'SALES_TL')):
            response = self.client.post(TEAM_URL, self.create_payload(
                username=username, email=f'{username}@eduport.com', role=role), format='json')
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)
            made.append(response.json()['tutor_code'])
        self.assertEqual(made, ['EPT0002', None, None, 'EPT0003', None])
        logged = {row.context['username']: row.context.get('tutor_code')
                  for row in ActivityLog.objects.filter(action='staff.create')}
        self.assertEqual(logged, {'t2': 'EPT0002', 'm2': None, 'b2': None, 't3': 'EPT0003', 's2': None})
        self.assertEqual(counter_value(), 3)

    def test_a_refused_creation_issues_nothing(self):
        refused = (
            (self.tutor_payload('weak', temporary_password='short'), 'PASSWORD_POLICY'),
            (self.tutor_payload('tutor1'), 'USERNAME_TAKEN'),
            (self.tutor_payload('dup', email='mentor1@eduport.com'), 'EMAIL_IN_USE'),
        )
        for payload, error in refused:
            with self.subTest(error=error):
                self.assert_refused(self.client.post(TEAM_URL, payload, format='json'), 400, error)
        self.assertEqual(counter_value(), 1)
        response = self.client.post(TEAM_URL, self.tutor_payload('next.tutor'), format='json')
        self.assertEqual(response.json()['tutor_code'], 'EPT0002')

    def test_a_save_that_fails_gives_its_number_back(self):
        clash = User(username='tutor1', email='clash@eduport.com', full_name='Clash', role='TUTOR')
        with self.assertRaises(IntegrityError), transaction.atomic():
            clash.save()
        self.assertIsNone(clash.tutor_code)
        self.assertEqual(counter_value(), 1)
        self.assertEqual(User.objects.create_user(email='t2@eduport.com', username='t2', password=STRONG,
                                                  full_name='T2', role='TUTOR').tutor_code, 'EPT0002')

    def test_create_user_and_the_django_admin_issue_ids_too(self):
        made = User.objects.create_user(email='cli@eduport.com', username='cli', password=STRONG,
                                        full_name='Cli', role='TUTOR')
        self.assertEqual(made.tutor_code, 'EPT0002')

        browser = Client()
        browser.force_login(self.root)
        response = browser.post('/admin/accounts/user/add/', {
            'username': 'site.tutor', 'email': 'site.tutor@eduport.com', 'full_name': 'Site Tutor',
            'role': 'TUTOR', 'usable_password': 'true', 'password1': STRONG, 'password2': STRONG,
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(User.objects.get(username='site.tutor').tutor_code, 'EPT0003')


@override_settings(STORAGES=PLAIN_STORAGES)
class TutorCodeRoleChangeTests(TeamTestCase):
    def test_a_mentor_who_becomes_a_tutor_gets_the_next_id(self):
        response = self.client.patch(member_url(self.mentor), {'role': 'TUTOR'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['tutor_code'], 'EPT0002')
        self.assertEqual(code_of(self.mentor), 'EPT0002')
        self.assertEqual(ActivityLog.objects.get(action='user.role_change').context['tutor_code'], 'EPT0002')

    def test_a_former_tutor_keeps_their_id_and_gets_the_same_one_back(self):
        demoted = self.client.patch(member_url(self.tutor), {'role': 'MENTOR'}, format='json')
        self.assertEqual(demoted.status_code, status.HTTP_200_OK)
        self.assertEqual(demoted.json()['tutor_code'], 'EPT0001')
        self.assertEqual(code_of(self.tutor), 'EPT0001')
        self.assertNotIn('tutor_code', ActivityLog.objects.get(action='user.role_change').context or {})

        restored = self.client.patch(member_url(self.tutor), {'role': 'TUTOR'}, format='json')
        self.assertEqual(restored.json()['tutor_code'], 'EPT0001')
        self.assertEqual(counter_value(), 1)
        self.assertEqual(ActivityLog.objects.get(action='user.role_change', changes__role__new='TUTOR')
                         .context['tutor_code'], 'EPT0001')
        # The next new tutor still follows on.
        self.assertEqual(self.client.patch(member_url(self.mentor), {'role': 'TUTOR'}, format='json')
                         .json()['tutor_code'], 'EPT0002')

    def test_saves_that_name_their_fields_still_write_the_new_id(self):
        self.mentor.role = 'TUTOR'
        self.mentor.save(update_fields=['role'])
        self.assertEqual((self.mentor.tutor_code, code_of(self.mentor)), ('EPT0002', 'EPT0002'))

    def test_saves_that_do_not_change_the_role_leave_the_id_alone(self):
        self.tutor.full_name = 'Renamed'
        self.tutor.save()
        self.tutor.last_login = timezone.now()
        self.tutor.save(update_fields=['last_login'])
        self.assertEqual((code_of(self.tutor), counter_value()), ('EPT0001', 1))

    def test_a_django_admin_role_change_issues_and_audits_it(self):
        browser = Client()
        browser.force_login(self.root)
        change = f'/admin/accounts/user/{self.mentor.pk}/change/'
        data = admin_change_form_data(browser.get(change))
        self.assertNotIn('tutor_code', data)
        response = browser.post(change, {**data, 'role': 'TUTOR'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(code_of(self.mentor), 'EPT0002')
        context = ActivityLog.objects.get(action='user.role_change').context
        self.assertEqual((context['via'], context['tutor_code']), ('django_admin', 'EPT0002'))


@override_settings(STORAGES=PLAIN_STORAGES)
class TutorCodeImmutabilityTests(TeamTestCase):
    def test_the_team_api_never_accepts_a_tutor_id(self):
        for method, url, body in (
            ('post', TEAM_URL, self.create_payload(role='TUTOR', tutor_code='EPT0900')),
            ('patch', member_url(self.tutor), {'tutor_code': 'EPT0900'}),
            ('patch', member_url(self.mentor), {'role': 'TUTOR', 'tutor_code': 'EPT0900'}),
        ):
            with self.subTest(method=method, url=url):
                self.assert_refused(getattr(self.client, method)(url, body, format='json'), 400, 'UNKNOWN_FIELDS')
        self.assertEqual((code_of(self.tutor), code_of(self.mentor), counter_value()), ('EPT0001', None, 1))

    def test_the_database_refuses_any_change_to_an_issued_id(self):
        for value in ('EPT0099', None):
            with self.subTest(value=value), self.assertRaises(DatabaseError), transaction.atomic():
                User.objects.filter(pk=self.tutor.pk).update(tutor_code=value)
        self.tutor.tutor_code = 'EPT0098'
        with self.assertRaises(DatabaseError), transaction.atomic():
            self.tutor.save()
        self.assertEqual(code_of(self.tutor), 'EPT0001')

    def test_two_accounts_never_share_an_id(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.filter(pk=self.mentor.pk).update(tutor_code='EPT0001')

    def test_a_tutor_never_goes_without_an_id(self):
        # Paths that skip save() fail instead of making a tutor without one.
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.filter(pk=self.mentor.pk).update(role='TUTOR')
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.bulk_create([User(username='bulk', email='bulk@eduport.com', role='TUTOR')])

    def test_ids_keep_the_EPT_format(self):
        for value in ('X0001', 'EPT001', 'ept0002', 'EPT00A1'):
            with self.subTest(value=value), self.assertRaises(IntegrityError), transaction.atomic():
                User.objects.filter(pk=self.mentor.pk).update(tutor_code=value)

    def test_the_counter_never_goes_down_or_away(self):
        with self.assertRaises(DatabaseError), transaction.atomic():
            TutorCodeCounter.objects.filter(pk=TUTOR_CODE_COUNTER).update(value=0)
        with self.assertRaises(DatabaseError), transaction.atomic():
            TutorCodeCounter.objects.filter(pk=TUTOR_CODE_COUNTER).delete()
        self.assertEqual(counter_value(), 1)

    def test_the_django_admin_shows_it_read_only(self):
        browser = Client()
        browser.force_login(self.root)
        page = browser.get(f'/admin/accounts/user/{self.tutor.pk}/change/')
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'EPT0001')
        self.assertNotIn('tutor_code', page.context['adminform'].form.fields)
        listing = browser.get('/admin/accounts/user/', {'q': 'EPT0001'})
        self.assertContains(listing, 'tutor1')
        self.assertNotContains(listing, 'mentor1')


class TutorCodeNumberingTests(TeamTestCase):
    def make_tutor(self, username):
        return User.objects.create_user(email=f'{username}@eduport.com', username=username, password=STRONG,
                                        full_name=username.title(), role='TUTOR')

    def test_a_deleted_tutors_id_is_never_issued_again(self):
        second = self.make_tutor('t2')
        third = self.make_tutor('t3')
        self.assertEqual((second.tutor_code, third.tutor_code), ('EPT0002', 'EPT0003'))
        third.delete()
        self.assertEqual(self.make_tutor('t4').tutor_code, 'EPT0004')

    def test_a_counter_left_behind_continues_after_the_highest_id(self):
        # A flushed test database or a restored backup: the counter row is gone.
        self.make_tutor('t2')
        with connection.cursor() as cursor:
            cursor.execute('TRUNCATE tutor_code_counter')
        self.assertIsNone(counter_value())
        self.assertEqual(self.make_tutor('t3').tutor_code, 'EPT0003')
        self.assertEqual(counter_value(), 3)

    def test_ids_widen_past_EPT9999_and_stay_in_numeric_order(self):
        TutorCodeCounter.objects.filter(pk=TUTOR_CODE_COUNTER).update(value=9998)
        self.assertEqual(self.make_tutor('t2').tutor_code, 'EPT9999')
        self.assertEqual(self.make_tutor('t3').tutor_code, 'EPT10000')
        # Without the counter, the highest is found by number: as text, EPT9999 > EPT10000.
        with connection.cursor() as cursor:
            cursor.execute('TRUNCATE tutor_code_counter')
        self.assertEqual(self.make_tutor('t4').tutor_code, 'EPT10001')


class TutorCodeVisibilityTests(TeamTestCase):
    def test_admins_list_find_and_open_tutors_by_id(self):
        rows = {row['username']: row['tutor_code'] for row in self.client.get(TEAM_URL).json()}
        self.assertEqual(rows['tutor1'], 'EPT0001')
        self.assertIsNone(rows['mentor1'])
        for query in ('EPT0001', 'ept0001', '0001'):
            with self.subTest(query=query):
                found = self.client.get(TEAM_URL, {'q': query}).json()
                self.assertEqual([row['username'] for row in found], ['tutor1'])
        self.assertEqual(self.client.get(member_url(self.tutor)).json()['tutor_code'], 'EPT0001')

    def test_staff_granted_view_team_see_ids_in_the_directory(self):
        self.mentor.user_permissions.add(view_team_permission())
        holder = self.as_user(User.objects.get(pk=self.mentor.pk))
        rows = {row['username']: row['tutor_code'] for row in holder.get(TEAM_URL).json()}
        self.assertEqual(rows['tutor1'], 'EPT0001')

    def test_a_tutor_reads_their_own_id_and_no_one_elses(self):
        self.make('tutor2', 'TUTOR')
        tutor = self.as_user(self.tutor)
        self.assertEqual(tutor.get(ME_URL).json()['user']['tutor_code'], 'EPT0001')
        for url in (TEAM_URL, member_url(self.tutor), member_url(User.objects.get(username='tutor2'))):
            with self.subTest(url=url):
                self.assertEqual(tutor.get(url).status_code, status.HTTP_403_FORBIDDEN)

    def test_accounts_that_were_never_tutors_read_none(self):
        self.assertIsNone(self.as_user(self.mentor).get(ME_URL).json()['user']['tutor_code'])

    def test_the_sign_in_answer_carries_it(self):
        browser = APIClient()
        response = browser.post('/api/auth/login/', {'username': 'tutor1', 'password': STRONG}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['user']['tutor_code'], 'EPT0001')

    def test_mentor_readable_lists_and_learn_never_carry_it(self):
        mentor = self.as_user(self.mentor)
        listing = mentor.get('/api/tutors/')
        self.assertEqual(listing.status_code, status.HTTP_200_OK)
        for row in listing.json()['tutors']:
            self.assertEqual(set(row), {'id', 'full_name', 'email'})
        # The tutor on every class, homework and exam Learn shows.
        self.assertEqual(set(ProfileBriefSerializer(self.tutor).data), {'id', 'full_name', 'email'})


@FAST_HASHING
class TutorCodeConcurrencyTests(TransactionTestCase):
    """Parallel issuing, outside the Team API's own lock: only the Tutor ID lock keeps the numbers apart."""

    def run_together(self, jobs):
        start = threading.Barrier(len(jobs))
        errors = []

        def run(job):
            try:
                start.wait()
                job()
            except Exception as exc:  # noqa: BLE001 -- reported below
                errors.append(exc)
            finally:
                connection.close()

        threads = [threading.Thread(target=run, args=(job,)) for job in jobs]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        return errors

    def test_an_id_is_issued_only_inside_the_transaction_that_saves_it(self):
        with self.assertRaises(RuntimeError):
            allocate_tutor_code()
        self.assertIsNone(TutorCodeCounter.objects.filter(value__gt=0).first())

    def test_parallel_creations_and_role_changes_never_share_an_id(self):
        mentors = [
            User.objects.create_user(email=f'm{n}@eduport.com', username=f'm{n}', password=STRONG,
                                     full_name=f'M{n}', role='MENTOR')
            for n in range(4)
        ]

        def create(n):
            def job():
                with transaction.atomic():
                    User.objects.create_user(email=f't{n}@eduport.com', username=f't{n}', password=STRONG,
                                             full_name=f'T{n}', role='TUTOR')
                    time.sleep(0.05)  # hold the transaction open: the others must wait, not guess
            return job

        def promote(mentor):
            def job():
                with transaction.atomic():
                    account = User.objects.select_for_update().get(pk=mentor.pk)
                    account.role = 'TUTOR'
                    account.save(update_fields=['role'])
                    time.sleep(0.05)
            return job

        errors = self.run_together([create(n) for n in range(4)] + [promote(mentor) for mentor in mentors])
        self.assertEqual(errors, [])
        codes = sorted(User.objects.filter(role='TUTOR').values_list('tutor_code', flat=True))
        self.assertEqual(codes, [format_tutor_code(n) for n in range(1, 9)])
        self.assertEqual(counter_value(), 8)

    def test_parallel_team_creations_return_distinct_ids(self):
        root = User.objects.create_superuser(username='root', email='root@eduport.com', full_name='Root',
                                             password=STRONG)
        results = []

        def create(n):
            def job():
                client = APIClient()
                client.force_authenticate(root)
                results.append(client.post(TEAM_URL, {
                    'username': f'tutor{n}', 'email': f'tutor{n}@eduport.com', 'full_name': f'Tutor {n}',
                    'role': 'TUTOR', 'temporary_password': TEMPORARY,
                }, format='json'))
            return job

        self.assertEqual(self.run_together([create(n) for n in range(5)]), [])
        self.assertEqual(sorted(response.status_code for response in results), [201] * 5)
        self.assertEqual(sorted(response.json()['tutor_code'] for response in results),
                         [format_tutor_code(n) for n in range(1, 6)])


class TutorCodeMigrationTests(TransactionTestCase):
    """Migration 0034 against tutors already here: who gets an ID, in what order, and what it leaves in place."""

    BEFORE = [('accounts', '0033_user_tutor_code')]
    AFTER = [('accounts', '0034_tutor_code_backfill_and_guards')]

    def migrate(self, targets):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(targets)
        return MigrationExecutor(connection).loader.project_state(targets).apps

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())

    def account(self, apps, username, role, created_at, **extra):
        return apps.get_model('accounts', 'User').objects.create(
            username=username, email=f'{username}@eduport.com', full_name=username.title(), role=role,
            password='!', created_at=created_at, **extra,
        )

    def test_existing_tutors_get_ids_oldest_first_deactivated_ones_too(self):
        apps = self.migrate(self.BEFORE)
        start = timezone.now() - timedelta(days=60)
        admin = self.account(apps, 'admin', 'ADMIN', start)
        # Out of order on purpose; two share a creation time, so the id decides between them.
        later = self.account(apps, 'later', 'TUTOR', start + timedelta(days=2), invited_by=admin)
        first = self.account(apps, 'first', 'TUTOR', start, invited_by=admin)
        gone = self.account(apps, 'gone', 'TUTOR', start + timedelta(days=1), is_active=False,
                            deactivated_at=start + timedelta(days=5), deactivated_by=admin, invited_by=admin)
        tie_b = self.account(apps, 'tie_b', 'TUTOR', start + timedelta(days=3),
                             id=uuid.UUID('ffffffff-0000-4000-8000-000000000000'))
        tie_a = self.account(apps, 'tie_a', 'TUTOR', start + timedelta(days=3),
                             id=uuid.UUID('00000000-0000-4000-8000-000000000000'))
        mentor = self.account(apps, 'mentor', 'MENTOR', start)
        student = self.account(apps, 'student', 'STUDENT', start)

        self.migrate(self.AFTER)

        codes = dict(User.objects.values_list('username', 'tutor_code'))
        self.assertEqual(
            [codes[account.username] for account in (first, gone, later, tie_a, tie_b)],
            ['EPT0001', 'EPT0002', 'EPT0003', 'EPT0004', 'EPT0005'],
        )
        self.assertEqual([codes[account.username] for account in (admin, mentor, student)], [None, None, None])
        self.assertEqual(counter_value(), 5)

        # New tutors follow on, and the guards are in place.
        made = User.objects.create_user(email='new@eduport.com', username='new', password=STRONG,
                                        full_name='New', role='TUTOR')
        self.assertEqual(made.tutor_code, 'EPT0006')
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.filter(username='mentor').update(role='TUTOR')
        with self.assertRaises(DatabaseError), transaction.atomic():
            User.objects.filter(username='first').update(tutor_code='EPT0100')

    def test_issued_ids_are_kept_and_running_it_again_issues_nothing(self):
        apps = self.migrate(self.BEFORE)
        start = timezone.now() - timedelta(days=30)
        self.account(apps, 'kept', 'TUTOR', start + timedelta(days=1), tutor_code='EPT0007')
        self.account(apps, 'older', 'TUTOR', start)
        # A former tutor who kept their ID, now a mentor: left exactly as they are.
        self.account(apps, 'former', 'MENTOR', start, tutor_code='EPT0003')

        self.migrate(self.AFTER)
        self.assertEqual(dict(User.objects.values_list('username', 'tutor_code')),
                         {'kept': 'EPT0007', 'older': 'EPT0008', 'former': 'EPT0003'})
        self.assertEqual(counter_value(), 8)

        # Reversed (checks and triggers go, IDs stay) and applied again: nothing new is issued.
        self.migrate(self.BEFORE)
        self.assertEqual(code_of(User.objects.get(username='older')), 'EPT0008')
        self.migrate(self.AFTER)
        self.assertEqual(dict(User.objects.values_list('username', 'tutor_code')),
                         {'kept': 'EPT0007', 'older': 'EPT0008', 'former': 'EPT0003'})
        self.assertEqual(counter_value(), 8)
