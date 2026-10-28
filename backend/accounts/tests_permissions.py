"""
Permission foundation (Phase A): the catalogue, the role groups migration 0008
seeds, the resolver (accounts.authz) and what guards it.

The role grants below are written out independently of the migration, so a
change to either one -- what each role may do -- fails here until both agree.
"""
import importlib
import json
import os
import tempfile
from io import StringIO
from types import SimpleNamespace

from django.apps import apps as django_apps
from django.conf import settings
from django.contrib.auth.models import AnonymousUser, Group, Permission
from django.core.exceptions import PermissionDenied
from django.core.management import CommandError, call_command
from django.db import connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import Client, RequestFactory, TestCase, TransactionTestCase, override_settings
from rest_framework.request import Request
from rest_framework.test import APIClient

from accounts.authz import acting_as, effective_permissions, has_any_app_permission, has_app_permission
from accounts.models import RoleGroup, User
from accounts.permission_catalogue import (
    CATALOGUE,
    VIEW_TEAM,
    allowed_for_role,
    grantable_permissions,
    hub_permission_meta,
)
from activity.models import ActivityLog
from core.permissions import ByMethod, HasAnyAppPermission, HasAppPermission, IsStudentUserFor
from students.models import Student

SEED = importlib.import_module('accounts.migrations.0008_role_groups')
SEED_NEW_ROLES = importlib.import_module('accounts.migrations.0009_hub_roles_bde_sales_tl')
SEED_BDE = importlib.import_module('accounts.migrations.0010_bde_booking_links_permission')
SEED_SLOTS = importlib.import_module('accounts.migrations.0011_booking_slots_permission')
SEED_ENQUIRIES = importlib.import_module('accounts.migrations.0012_bde_enquiries_permissions')
# Staff roles added by migration 0009, after the baseline below.
NEW_ROLES = ('BDE', 'SALES_TL')

PLAIN_STORAGES = {
    **settings.STORAGES,
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}
FAST_HASHING = override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])


def names(*codenames):
    return {f'accounts.{codename}' for codename in codenames}


# What each role could do before the move to permissions, written out on its
# own. Mentors carry no invitation permission (decision D4).
EXPECTED_ROLE_PERMISSIONS = {
    'ADMIN': names(
        'view_team', 'manage_team', 'view_staff_directory', 'view_staff_dashboard',
        'view_all_students', 'view_full_student_record', 'change_student_details', 'sync_student_quota',
        'reassign_student_staff', 'purge_student', 'view_student_notes', 'add_student_note', 'delete_any_student_note',
        'view_all_sessions', 'create_session', 'manage_session', 'cancel_session',
        'view_all_exams', 'create_exam', 'manage_exam', 'cancel_exam', 'record_exam_result', 'score_additional_exam',
        'view_all_homework', 'view_homework_submissions', 'score_homework',
        'view_all_activity', 'view_activity_actors',
        'view_invitations', 'create_invitation', 'change_invitation', 'withdraw_invitation',
    ),
    'MENTOR': names(
        'view_staff_directory', 'view_staff_dashboard',
        'view_mentored_students', 'view_full_student_record', 'change_student_details', 'sync_student_quota',
        'view_student_notes', 'add_student_note',
        'view_mentored_sessions', 'create_session', 'manage_session', 'cancel_session',
        'view_mentored_exams', 'create_exam', 'manage_exam', 'cancel_exam', 'record_exam_result', 'score_additional_exam',
        'view_mentored_homework', 'view_own_activity',
    ),
    'TUTOR': names(
        'view_staff_directory', 'view_staff_dashboard',
        'view_tutored_students', 'view_student_notes', 'add_student_note',
        'view_tutored_sessions', 'edit_session_notes',
        'view_tutored_homework', 'view_homework_submissions', 'score_homework', 'view_own_activity',
    ),
}
ADMIN_ONLY = names('manage_team', 'reassign_student_staff', 'purge_student', 'view_activity_actors', 'manage_booking_slots')
# What later migrations add, one module each: BDE its booking links (0010),
# ADMIN the booking slots (0011), BDE its enquiries (0012).
BOOKING_LINK_PERMISSIONS = names('view_own_booking_links')
BOOKING_SLOT_PERMISSIONS = names('manage_booking_slots')
ENQUIRY_PERMISSIONS = names('view_own_enquiries', 'add_enquiry')
# What the new roles' groups carry, each its own modules only: BDE its booking
# links and enquiries, Sales TL nothing yet.
NEW_ROLE_PERMISSIONS = {
    'BDE': BOOKING_LINK_PERMISSIONS | ENQUIRY_PERMISSIONS,
    'SALES_TL': set(),
}
# What every role group carries after 0010, after 0011, and today.
GROUP_PERMISSIONS_AT_0010 = {**EXPECTED_ROLE_PERMISSIONS, 'BDE': BOOKING_LINK_PERMISSIONS, 'SALES_TL': set()}
GROUP_PERMISSIONS_AT_0011 = {
    **GROUP_PERMISSIONS_AT_0010,
    'ADMIN': GROUP_PERMISSIONS_AT_0010['ADMIN'] | BOOKING_SLOT_PERMISSIONS,
}
EXPECTED_GROUP_PERMISSIONS = {**GROUP_PERMISSIONS_AT_0011, **NEW_ROLE_PERMISSIONS}


def permission(name):
    app_label, codename = name.split('.', 1)
    return Permission.objects.get(content_type__app_label=app_label, codename=codename)


def role_group(role):
    return RoleGroup.objects.select_related('group').get(role=role).group


@FAST_HASHING
class PermissionTestCase(TestCase):
    def setUp(self):
        self.root = User.objects.create_superuser(
            username='root', email='root@perm.test', full_name='Root', password='Root-Password-1',
        )
        self.admin = self.make('admin1', 'ADMIN')
        self.mentor = self.make('mentor1', 'MENTOR')
        self.tutor = self.make('tutor1', 'TUTOR')
        self.parent = self.make('parent1', 'STUDENT')

    def make(self, username, role, **extra):
        return User.objects.create_user(
            email=f'{username}@perm.test', username=username, password='Some-Password-1',
            full_name=username.title(), role=role, **extra,
        )

    @staticmethod
    def fresh(user):
        return User.objects.get(pk=user.pk)


# ------------------------------------------------------------------ catalogue

class CatalogueTests(PermissionTestCase):
    def test_the_catalogue_is_the_approved_45(self):
        self.assertEqual(len(CATALOGUE), 45)
        # Every permission is carried by at least one role group today.
        self.assertEqual(set().union(*EXPECTED_GROUP_PERMISSIONS.values()), set(CATALOGUE))
        for name, entry in CATALOGUE.items():
            with self.subTest(permission=name):
                self.assertTrue(name.startswith('accounts.'))
                self.assertEqual(set(entry), {'label', 'module', 'roles', 'grantable'})
                self.assertTrue(entry['label'] and entry['module'] and entry['roles'])
                self.assertNotIn('STUDENT', entry['roles'])

    def test_every_catalogue_permission_has_a_row(self):
        for name in CATALOGUE:
            with self.subTest(permission=name):
                self.assertTrue(permission(name))

    def test_hub_permission_carries_no_default_permissions(self):
        hub = Permission.objects.filter(content_type__app_label='accounts', content_type__model='hubpermission')
        self.assertEqual({f'accounts.{p.codename}' for p in hub}, set(CATALOGUE) - {VIEW_TEAM})
        self.assertFalse(hub.filter(codename__regex=r'^(add|change|delete|view)_hubpermission$').exists())

    def test_ceilings(self):
        self.assertEqual({name for name, entry in CATALOGUE.items() if entry['roles'] == ('ADMIN',)}, ADMIN_ONLY)
        for role, expected in EXPECTED_GROUP_PERMISSIONS.items():
            with self.subTest(role=role):
                self.assertLessEqual(expected, allowed_for_role(role))
        # The new roles may hold their own module's permissions and nothing else.
        for role, expected in NEW_ROLE_PERMISSIONS.items():
            with self.subTest(role=role):
                self.assertEqual(allowed_for_role(role), expected)
        self.assertEqual(allowed_for_role('STUDENT'), set())
        self.assertEqual(allowed_for_role('UNASSIGNED'), set())

    def test_only_view_team_is_individually_grantable(self):
        self.assertEqual(grantable_permissions(), {VIEW_TEAM})

    def test_the_migrations_seed_what_the_catalogue_declares(self):
        self.assertEqual(
            SEED.HUB_PERMISSIONS + SEED_BDE.HUB_PERMISSIONS + SEED_SLOTS.HUB_PERMISSIONS + SEED_ENQUIRIES.HUB_PERMISSIONS,
            hub_permission_meta(),
        )
        seeded = {role: names(*codenames) for role, _name, codenames in SEED.ROLE_GROUPS}
        self.assertEqual(seeded, EXPECTED_ROLE_PERMISSIONS)
        for seed, role, expected in ((SEED_BDE, 'BDE', BOOKING_LINK_PERMISSIONS),
                                     (SEED_SLOTS, 'ADMIN', BOOKING_SLOT_PERMISSIONS),
                                     (SEED_ENQUIRIES, 'BDE', ENQUIRY_PERMISSIONS)):
            with self.subTest(seed=seed.__name__):
                self.assertEqual(seed.ROLE, role)
                self.assertEqual(names(*(codename for codename, _name in seed.HUB_PERMISSIONS)), expected)


# ------------------------------------------------------------------- seed

class RoleGroupSeedTests(PermissionTestCase):
    def test_one_linked_group_per_staff_role(self):
        links = {link.role: link.group.name for link in RoleGroup.objects.select_related('group')}
        self.assertEqual(links, {
            'ADMIN': 'Role: Admin / Coordinator', 'MENTOR': 'Role: Mentor', 'TUTOR': 'Role: Tutor',
            'BDE': 'Role: BDE', 'SALES_TL': 'Role: Sales TL',
        })
        self.assertEqual(Group.objects.count(), 5)

    def test_the_new_roles_groups_carry_only_their_own_module(self):
        for role, expected in NEW_ROLE_PERMISSIONS.items():
            with self.subTest(role=role):
                held = {f'{p.content_type.app_label}.{p.codename}' for p in role_group(role).permissions.select_related('content_type')}
                self.assertEqual(held, expected)

    def test_each_group_carries_todays_access(self):
        for role in EXPECTED_ROLE_PERMISSIONS:
            expected = EXPECTED_GROUP_PERMISSIONS[role]
            with self.subTest(role=role):
                group = role_group(role)
                held = {f'{p.content_type.app_label}.{p.codename}' for p in group.permissions.select_related('content_type')}
                self.assertEqual(held, expected)

    def test_nobody_is_a_member_of_any_group(self):
        self.assertFalse(User.groups.through.objects.exists())


# --------------------------------------------------------------- resolver

class ResolverTests(PermissionTestCase):
    def test_each_role_holds_its_groups_permissions(self):
        bde, sales_tl = self.make('bde1', 'BDE'), self.make('salestl1', 'SALES_TL')
        for user, role in ((self.admin, 'ADMIN'), (self.mentor, 'MENTOR'), (self.tutor, 'TUTOR'),
                           (bde, 'BDE'), (sales_tl, 'SALES_TL')):
            with self.subTest(role=role):
                self.assertEqual(effective_permissions(user), EXPECTED_GROUP_PERMISSIONS[role])

    def test_superusers_hold_everything_whatever_the_role(self):
        # Decision D1.
        for role in ('ADMIN', 'MENTOR', 'TUTOR', 'STUDENT', 'UNASSIGNED'):
            with self.subTest(role=role):
                account = self.make(f'su_{role.lower()}', role, is_superuser=True)
                self.assertEqual(effective_permissions(account), set(CATALOGUE))

    def test_students_unknown_roles_inactive_and_anonymous_hold_nothing(self):
        unknown = self.make('unknown1', 'UNASSIGNED')
        inactive = self.make('inactive1', 'ADMIN', is_active=False)
        for account in (self.parent, unknown, inactive, AnonymousUser(), None):
            with self.subTest(account=account):
                self.assertEqual(effective_permissions(account), set())

    def test_an_individual_view_team_grant_counts(self):
        self.mentor.user_permissions.add(permission(VIEW_TEAM))
        self.assertIn(VIEW_TEAM, effective_permissions(self.fresh(self.mentor)))

    def test_grants_beyond_the_grantable_set_count_for_nothing(self):
        self.mentor.user_permissions.add(permission('accounts.view_all_students'), permission('accounts.change_user'))
        self.assertEqual(effective_permissions(self.fresh(self.mentor)), EXPECTED_ROLE_PERMISSIONS['MENTOR'])

    def test_a_student_holding_a_grant_still_holds_nothing(self):
        self.parent.user_permissions.add(permission(VIEW_TEAM))
        self.assertEqual(effective_permissions(self.fresh(self.parent)), set())

    def test_the_ceiling_beats_the_group(self):
        role_group('MENTOR').permissions.add(permission('accounts.manage_team'))
        self.assertNotIn('accounts.manage_team', effective_permissions(self.mentor))
        self.assertIn('accounts.manage_team', effective_permissions(self.admin))

    def test_group_changes_apply_at_once(self):
        role_group('ADMIN').permissions.remove(permission('accounts.create_session'))
        self.assertNotIn('accounts.create_session', effective_permissions(self.admin))
        role_group('TUTOR').permissions.add(permission('accounts.create_session'))
        self.assertIn('accounts.create_session', effective_permissions(self.tutor))

    def test_group_membership_counts_for_nothing(self):
        # Bypass the guard, as raw SQL would.
        with connection.cursor() as cursor:
            cursor.execute(
                f'INSERT INTO {User.groups.through._meta.db_table} (user_id, group_id) VALUES (%s, %s)',
                [self.mentor.pk, role_group('ADMIN').pk],
            )
        self.assertEqual(effective_permissions(self.fresh(self.mentor)), EXPECTED_ROLE_PERMISSIONS['MENTOR'])

    def test_unknown_names_are_held_by_nobody(self):
        self.assertFalse(has_app_permission(self.root, 'accounts.no_such_thing'))
        self.assertFalse(has_app_permission(self.root, 'accounts.change_user'))
        self.assertTrue(has_app_permission(self.root, 'accounts.purge_student'))

    def test_any_of(self):
        perms = ('accounts.view_all_students', 'accounts.view_mentored_students')
        self.assertTrue(has_any_app_permission(self.admin, perms))
        self.assertTrue(has_any_app_permission(self.mentor, perms))
        self.assertFalse(has_any_app_permission(self.tutor, perms))
        self.assertFalse(has_any_app_permission(self.tutor, ('accounts.no_such_thing',)))


class RequestCacheTests(PermissionTestCase):
    def test_one_lookup_per_user_per_request(self):
        request = RequestFactory().get('/')
        effective_permissions(self.mentor, request)
        with self.assertNumQueries(0):
            self.assertTrue(has_app_permission(self.mentor, 'accounts.create_session', request))
            self.assertTrue(has_any_app_permission(self.mentor, ('accounts.view_mentored_students',), request))
        with self.assertNumQueries(2):
            effective_permissions(self.tutor, request)  # another account: its own entry

    def test_a_drf_request_shares_its_http_requests_cache(self):
        http_request = RequestFactory().get('/')
        effective_permissions(self.admin, http_request)
        with self.assertNumQueries(0):
            effective_permissions(self.admin, Request(http_request))

    def test_the_next_request_reads_afresh(self):
        effective_permissions(self.tutor, RequestFactory().get('/'))
        role_group('TUTOR').permissions.add(permission('accounts.create_session'))
        self.assertIn('accounts.create_session', effective_permissions(self.tutor, RequestFactory().get('/')))

    def test_without_a_request_nothing_is_cached(self):
        effective_permissions(self.tutor)
        with self.assertNumQueries(2):
            effective_permissions(self.tutor)


class PermissionClassTests(PermissionTestCase):
    @staticmethod
    def request_as(user):
        request = Request(RequestFactory().get('/'))
        request.user = user
        return request

    def test_has_app_permission(self):
        check = HasAppPermission('accounts.manage_team')()
        self.assertTrue(check.has_permission(self.request_as(self.admin), None))
        self.assertTrue(check.has_permission(self.request_as(self.root), None))
        self.assertFalse(check.has_permission(self.request_as(self.mentor), None))
        self.assertFalse(check.has_permission(self.request_as(AnonymousUser()), None))
        self.assertFalse(HasAppPermission('accounts.no_such_thing')().has_permission(self.request_as(self.root), None))

    def test_has_any_app_permission(self):
        check = HasAnyAppPermission('accounts.view_all_students', 'accounts.view_mentored_students')()
        self.assertTrue(check.has_permission(self.request_as(self.mentor), None))
        self.assertFalse(check.has_permission(self.request_as(self.tutor), None))
        self.assertFalse(check.has_permission(self.request_as(AnonymousUser()), None))

    def test_names_say_what_they_check(self):
        self.assertEqual(HasAppPermission('accounts.manage_team').__name__, "HasAppPermission('accounts.manage_team')")

    def test_by_method_picks_the_methods_class(self):
        check = ByMethod(
            GET=HasAppPermission('accounts.view_student_notes'),
            POST=HasAppPermission('accounts.manage_team'),
        )()

        def request(method, user):
            request = Request(getattr(RequestFactory(), method)('/'))
            request.user = user
            return request

        self.assertTrue(check.has_permission(request('get', self.mentor), None))
        self.assertTrue(check.has_permission(request('head', self.mentor), None))  # HEAD follows GET
        self.assertFalse(check.has_permission(request('post', self.mentor), None))
        self.assertTrue(check.has_permission(request('post', self.admin), None))
        self.assertFalse(check.has_permission(request('delete', self.admin), None))  # not named: nobody
        self.assertTrue(check.has_permission(request('options', self.mentor), None))
        self.assertFalse(check.has_permission(request('options', self.parent), None))

    def test_the_student_persona_class_admits_students_for_its_methods_only(self):
        check = IsStudentUserFor('GET', 'PUT')()
        get, post = Request(RequestFactory().get('/')), Request(RequestFactory().post('/'))
        get.user = post.user = self.parent
        self.assertTrue(check.has_permission(get, None))
        self.assertFalse(check.has_permission(post, None))
        get.user = self.admin
        self.assertFalse(check.has_permission(get, None))

    def test_combined_with_a_permission_by_or(self):
        check = (HasAppPermission('accounts.view_all_sessions') | IsStudentUserFor('GET'))()
        for user, allowed in ((self.admin, True), (self.parent, True), (self.mentor, False)):
            with self.subTest(user=user.username):
                self.assertEqual(check.has_permission(self.request_as(user), None), allowed)


# ------------------------------------------------------- group membership

class GroupMembershipGuardTests(PermissionTestCase):
    def test_adding_a_user_to_a_group_is_refused_both_ways(self):
        group = role_group('ADMIN')
        # Django's add() runs in an atomic block without a savepoint, so the
        # refusal rolls back the surrounding transaction -- a savepoint per
        # attempt keeps the test's own transaction usable.
        with self.assertRaises(PermissionDenied), transaction.atomic():
            self.mentor.groups.add(group)
        with self.assertRaises(PermissionDenied), transaction.atomic():
            group.user_set.add(self.mentor)
        self.assertFalse(User.groups.through.objects.exists())

    def test_me_reports_no_groups(self):
        client = APIClient()
        client.force_authenticate(self.admin)
        self.assertEqual(client.get('/api/auth/me/').json()['user']['groups'], [])


# ------------------------------------------------------------ role changes

class RoleChangeTests(PermissionTestCase):
    def setUp(self):
        super().setUp()
        self.spare = self.make('spare1', 'MENTOR')
        self.spare.user_permissions.add(permission(VIEW_TEAM))

    def cleared_rows(self):
        return ActivityLog.objects.filter(action='user.permissions_update', context__reason='role_change')

    def test_saving_a_new_role_clears_individual_grants(self):
        account = self.fresh(self.spare)
        account.role = 'TUTOR'
        account.save()
        self.assertFalse(account.user_permissions.exists())
        row = self.cleared_rows().get()
        self.assertEqual(row.context['removed'], [VIEW_TEAM])
        self.assertEqual(row.context['via'], 'model')
        self.assertIsNone(row.actor_id)

    def test_a_save_that_does_not_write_the_role_clears_nothing(self):
        account = self.fresh(self.spare)
        account.role = 'TUTOR'
        account.full_name = 'Renamed'
        account.save(update_fields=['full_name'])
        self.assertTrue(account.user_permissions.exists())
        account = self.fresh(self.spare)
        account.full_name = 'Renamed again'
        account.save()
        self.assertTrue(account.user_permissions.exists())
        self.assertFalse(self.cleared_rows().exists())

    def test_the_team_api_clears_and_audits_with_the_actor(self):
        client = APIClient()
        client.force_authenticate(self.admin)
        response = client.patch(f'/api/team/{self.spare.pk}/', {'role': 'TUTOR'}, format='json')
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['permissions'], [])
        row = self.cleared_rows().get()
        self.assertEqual((row.actor_id, row.context['via'], row.context['removed']), (self.admin.pk, 'team', [VIEW_TEAM]))
        self.assertTrue(ActivityLog.objects.filter(action='user.role_change', entity_id=str(self.spare.pk)).exists())

    def test_a_role_change_without_grants_logs_no_permission_change(self):
        client = APIClient()
        client.force_authenticate(self.admin)
        self.assertEqual(client.patch(f'/api/team/{self.tutor.pk}/', {'role': 'MENTOR'}, format='json').status_code, 200)
        self.assertFalse(self.cleared_rows().exists())


# ------------------------------------------------------ group change audit

class GroupAuditTests(PermissionTestCase):
    def rows(self):
        return ActivityLog.objects.filter(action='role.permissions_update').order_by('created_at')

    def test_adding_and_removing_is_audited(self):
        group = role_group('TUTOR')
        group.permissions.add(permission('accounts.create_session'))
        group.permissions.remove(permission('accounts.score_homework'))
        self.assertEqual(self.rows().count(), 2)
        added = self.rows().get(context__added=['accounts.create_session'])
        removed = self.rows().get(context__removed=['accounts.score_homework'])
        self.assertEqual((added.entity_type, added.entity_id), ('role', 'TUTOR'))
        self.assertEqual(removed.context['removed'], ['accounts.score_homework'])
        self.assertEqual((added.context['via'], added.actor_id), ('model', None))
        self.assertIn('accounts.create_session', added.changes['permissions']['new'])
        self.assertNotIn('accounts.create_session', added.changes['permissions']['old'])

    def test_clearing_is_audited(self):
        role_group('TUTOR').permissions.clear()
        row = self.rows().get()
        self.assertEqual(set(row.context['removed']), EXPECTED_ROLE_PERMISSIONS['TUTOR'])

    def test_changes_from_the_permission_side_are_audited(self):
        permission('accounts.create_session').group_set.add(role_group('TUTOR'))
        row = self.rows().get()
        self.assertEqual((row.entity_id, row.context['added']), ('TUTOR', ['accounts.create_session']))

    def test_the_actor_is_named_when_known(self):
        with acting_as(self.root, 'django_admin'):
            role_group('TUTOR').permissions.add(permission('accounts.create_session'))
        row = self.rows().get()
        self.assertEqual((row.actor_id, row.context['via']), (self.root.pk, 'django_admin'))


# -------------------------------------------------------------- django admin

def change_form_data(response):
    """POST data resubmitting an admin change form as rendered."""
    from django.forms import CheckboxInput
    form = response.context['adminform'].form
    data = {}
    for name, field in form.fields.items():
        if field.disabled:
            continue
        value = form[name].value()
        widget = getattr(field.widget, 'widget', field.widget)
        if hasattr(widget, 'decompress'):
            for index, part in enumerate(widget.decompress(value)):
                data[f'{name}_{index}'] = '' if part is None else part
        elif isinstance(widget, CheckboxInput):
            if value:
                data[name] = 'on'
        elif isinstance(value, (list, tuple)):
            data[name] = [str(item) for item in value]
        else:
            data[name] = '' if value is None else value
    return data


@override_settings(STORAGES=PLAIN_STORAGES)
class DjangoAdminTests(PermissionTestCase):
    def setUp(self):
        super().setUp()
        self.browser = Client()
        self.browser.force_login(self.root)

    def change_role(self, account, role):
        url = f'/admin/accounts/user/{account.pk}/change/'
        data = change_form_data(self.browser.get(url))
        data['role'] = role
        return self.browser.post(url, data)

    def test_the_user_form_has_no_group_or_permission_pickers(self):
        form = self.browser.get(f'/admin/accounts/user/{self.mentor.pk}/change/').context['adminform'].form
        self.assertNotIn('groups', form.fields)
        self.assertNotIn('user_permissions', form.fields)

    def test_a_role_change_clears_grants_and_audits_both(self):
        spare = self.make('spare1', 'MENTOR')
        spare.user_permissions.add(permission(VIEW_TEAM))
        response = self.change_role(spare, 'TUTOR')
        self.assertEqual(response.status_code, 302)
        spare = self.fresh(spare)
        self.assertEqual(spare.role, 'TUTOR')
        self.assertFalse(spare.user_permissions.exists())
        role_row = ActivityLog.objects.get(action='user.role_change', entity_id=str(spare.pk))
        self.assertEqual((role_row.actor_id, role_row.context['via'], role_row.changes['role']),
                         (self.root.pk, 'django_admin', {'old': 'MENTOR', 'new': 'TUTOR'}))
        cleared = ActivityLog.objects.get(action='user.permissions_update', entity_id=str(spare.pk))
        self.assertEqual((cleared.actor_id, cleared.context['via'], cleared.context['removed']),
                         (self.root.pk, 'django_admin', [VIEW_TEAM]))

    def test_a_mentor_with_active_students_keeps_the_role_until_handover(self):
        Student.objects.create(profile=self.parent, student_code='PERM1', full_name='Kid', mentor=self.mentor)
        response = self.change_role(self.mentor, 'TUTOR')
        self.assertEqual(response.status_code, 200)
        self.assertIn('role', response.context['adminform'].form.errors)
        self.assertEqual(self.fresh(self.mentor).role, 'MENTOR')

    def test_the_last_active_admin_keeps_the_role(self):
        self.admin.role = 'MENTOR'
        self.admin.save()
        response = self.change_role(self.root, 'MENTOR')
        self.assertEqual(response.status_code, 200)
        self.assertIn('This is the last active administrator.', response.context['adminform'].form.errors['role'])

    def test_superuser_with_another_role_is_flagged(self):
        # Decision D1.
        odd = self.make('odd1', 'MENTOR', is_superuser=True)
        self.assertContains(self.browser.get(f'/admin/accounts/user/{odd.pk}/change/'), 'holds every permission')
        self.assertNotContains(self.browser.get(f'/admin/accounts/user/{self.mentor.pk}/change/'), 'holds every permission')

    def test_role_groups_cannot_be_added_or_deleted(self):
        group = role_group('MENTOR')
        self.assertEqual(self.browser.get('/admin/auth/group/add/').status_code, 403)
        self.assertEqual(self.browser.get(f'/admin/auth/group/{group.pk}/delete/').status_code, 403)

    def test_the_group_page_offers_only_what_the_role_may_hold(self):
        group = role_group('MENTOR')
        form = self.browser.get(f'/admin/auth/group/{group.pk}/change/').context['adminform'].form
        offered = {f'{p.content_type.app_label}.{p.codename}' for p in form.fields['permissions'].queryset}
        self.assertEqual(offered, allowed_for_role('MENTOR'))
        self.assertNotIn('name', form.fields)  # read-only

    def test_a_group_change_beyond_the_ceiling_is_refused(self):
        group = role_group('MENTOR')
        url = f'/admin/auth/group/{group.pk}/change/'
        data = change_form_data(self.browser.get(url))
        data['permissions'] = data['permissions'] + [str(permission('accounts.manage_team').pk)]
        response = self.browser.post(url, data)
        self.assertEqual(response.status_code, 200)
        self.assertIn('permissions', response.context['adminform'].form.errors)
        self.assertNotIn('accounts.manage_team', {f'accounts.{p.codename}' for p in group.permissions.all()})

    def test_a_group_change_is_audited_with_the_admin(self):
        group = role_group('MENTOR')
        url = f'/admin/auth/group/{group.pk}/change/'
        data = change_form_data(self.browser.get(url))
        dropped = permission('accounts.sync_student_quota')
        data['permissions'] = [pk for pk in data['permissions'] if pk != str(dropped.pk)]
        self.assertEqual(self.browser.post(url, data).status_code, 302)
        row = ActivityLog.objects.get(action='role.permissions_update')
        self.assertEqual((row.actor_id, row.context['via'], row.context['removed']),
                         (self.root.pk, 'django_admin', ['accounts.sync_student_quota']))


# ----------------------------------------------------------- the command

class RolePermissionsCommandTests(PermissionTestCase):
    def run_command(self, *args):
        out = StringIO()
        call_command('role_permissions', *args, stdout=out)
        return out.getvalue()

    def test_show(self):
        output = self.run_command('show')
        for name in ('Role: Admin / Coordinator', 'Role: Mentor', 'Role: Tutor', 'accounts.create_session'):
            self.assertIn(name, output)

    def test_check_passes_on_the_seed_and_warns_about_odd_superusers(self):
        self.assertIn('No problems found (0 warning(s))', self.run_command('check'))
        self.make('odd1', 'TUTOR', is_superuser=True)
        output = self.run_command('check')
        self.assertIn('has the TUTOR role but holds every permission', output)
        self.assertIn('No problems found (1 warning(s))', output)

    def test_check_fails_on_each_kind_of_problem(self):
        def membership():
            with connection.cursor() as cursor:
                cursor.execute(f'INSERT INTO {User.groups.through._meta.db_table} (user_id, group_id) VALUES (%s, %s)',
                               [self.mentor.pk, role_group('ADMIN').pk])

        problems = {
            'membership': membership,
            'beyond the ceiling': lambda: role_group('MENTOR').permissions.add(permission('accounts.manage_team')),
            'stray group': lambda: Group.objects.create(name='Stray'),
            'unknown role': lambda: self.make('unknown1', 'UNASSIGNED'),
            'unusable grant': lambda: self.mentor.user_permissions.add(permission('accounts.view_all_students')),
            'missing row': lambda: permission('accounts.purge_student').delete(),
        }
        for label, make_problem in problems.items():
            with self.subTest(problem=label):
                sid = connection.savepoint()
                try:
                    make_problem()
                    with self.assertRaises(CommandError):
                        self.run_command('check')
                finally:
                    connection.savepoint_rollback(sid)

    def test_grant_is_a_dry_run_until_applied(self):
        output = self.run_command('grant', 'tutor', 'accounts.create_session')
        self.assertIn('Re-run with --apply', output)
        self.assertNotIn('accounts.create_session', effective_permissions(self.tutor))
        self.run_command('grant', 'TUTOR', 'accounts.create_session', '--apply')
        self.assertIn('accounts.create_session', effective_permissions(self.tutor))
        row = ActivityLog.objects.get(action='role.permissions_update')
        self.assertEqual((row.context['via'], row.actor_id), ('manage.py role_permissions', None))
        self.assertIn('Nothing to do', self.run_command('grant', 'TUTOR', 'accounts.create_session', '--apply'))

    def test_grant_refuses_what_the_role_may_not_hold_or_the_catalogue_lacks(self):
        for args in (('TUTOR', 'accounts.manage_team'), ('TUTOR', 'accounts.change_user'),
                     ('STUDENT', 'accounts.create_session'), ('TUTOR', 'accounts.nothing')):
            with self.subTest(args=args), self.assertRaises(CommandError):
                self.run_command('grant', *args, '--apply')
        self.assertEqual(effective_permissions(self.tutor), EXPECTED_ROLE_PERMISSIONS['TUTOR'])

    def test_revoke(self):
        self.run_command('revoke', 'MENTOR', 'accounts.sync_student_quota', '--apply')
        self.assertNotIn('accounts.sync_student_quota', effective_permissions(self.mentor))

    def test_snapshot_and_compare(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, 'snapshot.json')
            self.run_command('snapshot', '--output', path)
            users = json.load(open(path))['users']
            self.assertEqual(users[str(self.admin.pk)]['team_access'], 'manage')
            self.assertEqual(users[str(self.mentor.pk)]['permissions'], sorted(EXPECTED_ROLE_PERMISSIONS['MENTOR']))
            self.assertIn('match', self.run_command('compare', path))
            role_group('MENTOR').permissions.remove(permission('accounts.sync_student_quota'))
            with self.assertRaises(CommandError):
                self.run_command('compare', path)


# -------------------------------------------------------------- migration

class SeedFunctionTests(PermissionTestCase):
    schema_editor = SimpleNamespace(connection=SimpleNamespace(alias='default'))

    def test_running_the_seed_again_changes_nothing(self):
        before = {g.name: set(g.permissions.values_list('pk', flat=True)) for g in Group.objects.all()}
        SEED.seed_role_groups(django_apps, self.schema_editor)
        after = {g.name: set(g.permissions.values_list('pk', flat=True)) for g in Group.objects.all()}
        self.assertEqual(before, after)

    def test_an_unlinked_group_with_a_role_groups_name_stops_the_seed(self):
        link = RoleGroup.objects.select_related('group').get(role='MENTOR')
        group = link.group
        link.delete()
        group.delete()
        Group.objects.create(name='Role: Mentor')
        with self.assertRaisesMessage(RuntimeError, 'Role: Mentor'):
            SEED.seed_role_groups(django_apps, self.schema_editor)
        self.assertFalse(RoleGroup.objects.filter(role='MENTOR').exists())

    def test_the_new_roles_seed_is_idempotent_and_never_adopts_a_group(self):
        before = set(Group.objects.values_list('name', flat=True))
        SEED_NEW_ROLES.seed_role_groups(django_apps, self.schema_editor)
        self.assertEqual(set(Group.objects.values_list('name', flat=True)), before)

        link = RoleGroup.objects.select_related('group').get(role='BDE')
        group = link.group
        link.delete()
        group.delete()
        Group.objects.create(name='Role: BDE')
        with self.assertRaisesMessage(RuntimeError, 'Role: BDE'):
            SEED_NEW_ROLES.seed_role_groups(django_apps, self.schema_editor)
        self.assertFalse(RoleGroup.objects.filter(role='BDE').exists())

    def test_running_the_bde_seed_again_changes_nothing(self):
        before = {g.name: set(g.permissions.values_list('pk', flat=True)) for g in Group.objects.all()}
        SEED_BDE.grant_bde_permissions(django_apps, self.schema_editor)
        after = {g.name: set(g.permissions.values_list('pk', flat=True)) for g in Group.objects.all()}
        self.assertEqual(before, after)

    def test_running_the_booking_slots_seed_again_changes_nothing(self):
        before = {g.name: set(g.permissions.values_list('pk', flat=True)) for g in Group.objects.all()}
        SEED_SLOTS.grant_admin_permissions(django_apps, self.schema_editor)
        after = {g.name: set(g.permissions.values_list('pk', flat=True)) for g in Group.objects.all()}
        self.assertEqual(before, after)

    def test_running_the_enquiries_seed_again_changes_nothing(self):
        before = {g.name: set(g.permissions.values_list('pk', flat=True)) for g in Group.objects.all()}
        SEED_ENQUIRIES.grant_bde_permissions(django_apps, self.schema_editor)
        after = {g.name: set(g.permissions.values_list('pk', flat=True)) for g in Group.objects.all()}
        self.assertEqual(before, after)


# --------------------------------------------------------------- new roles

class NewRoleTests(PermissionTestCase):
    """
    BDE and Sales TL: staff accounts with a role group, each reaching only its
    own modules -- BDE its booking links and enquiries, Sales TL nothing until
    its module exists.
    """

    def test_their_ceiling_beats_their_group(self):
        for role in NEW_ROLES:
            with self.subTest(role=role):
                self.assertEqual(allowed_for_role(role), NEW_ROLE_PERMISSIONS[role])
                role_group(role).permissions.add(permission('accounts.view_all_students'))
                account = self.make(f'new_{role.lower()}', role)
                self.assertEqual(effective_permissions(account), NEW_ROLE_PERMISSIONS[role])

    def test_they_sign_in_to_the_hub_holding_only_their_modules_permissions(self):
        for role in NEW_ROLES:
            with self.subTest(role=role):
                self.make(f'signin_{role.lower()}', role)
                client = APIClient()
                login = client.post('/api/auth/login/', {'username': f'signin_{role.lower()}', 'password': 'Some-Password-1'}, format='json')
                self.assertEqual(login.status_code, 200)
                me = client.get('/api/auth/me/').json()['user']
                self.assertEqual((me['role'], me['permissions']), (role, sorted(NEW_ROLE_PERMISSIONS[role])))

    def test_team_creates_and_lists_them(self):
        client = APIClient()
        client.force_authenticate(self.admin)
        for role in NEW_ROLES:
            with self.subTest(role=role):
                response = client.post('/api/team/', {
                    'username': f'team.{role.lower()}', 'email': f'team.{role.lower()}@perm.test',
                    'full_name': role, 'role': role, 'temporary_password': 'Temporary-Pass-2026!',
                }, format='json')
                self.assertEqual(response.status_code, 201, response.content)
                listed = client.get('/api/team/', {'role': role}).json()
                self.assertEqual([row['username'] for row in listed], [f'team.{role.lower()}'])
        refused = client.post('/api/team/', {
            'username': 'team.x', 'email': 'team.x@perm.test', 'full_name': 'X', 'role': 'STUDENT',
            'temporary_password': 'Temporary-Pass-2026!',
        }, format='json')
        self.assertEqual(refused.json()['message'], 'role must be Admin, Mentor, Tutor, BDE or Sales TL.')


class MigrationReversalTests(TransactionTestCase):
    """0012, 0011, 0010, 0009 and 0008 reverse cleanly to 0007 and apply again with the same seeds."""

    def groups(self):
        return {
            link.role: {f'{p.content_type.app_label}.{p.codename}' for p in link.group.permissions.select_related('content_type')}
            for link in RoleGroup.objects.select_related('group')
        }

    def test_reverse_and_reapply(self):
        # Starts from 0007 so it does not depend on what earlier
        # TransactionTestCases left in the (emptied) tables.
        executor = MigrationExecutor(connection)
        executor.migrate([('accounts', '0007_user_team_permissions')])
        with connection.cursor() as cursor:
            cursor.execute("SELECT to_regclass('public.role_groups')")
            self.assertIsNone(cursor.fetchone()[0])
        self.assertFalse(Group.objects.exists())
        self.assertFalse(Permission.objects.filter(content_type__model='hubpermission').exists())
        self.assertTrue(Permission.objects.filter(codename='view_team').exists())  # 0007's, untouched

        executor = MigrationExecutor(connection)
        executor.migrate([('accounts', '0008_role_groups')])
        self.assertEqual(self.groups(), EXPECTED_ROLE_PERMISSIONS)

        executor = MigrationExecutor(connection)
        executor.migrate([('accounts', '0009_hub_roles_bde_sales_tl')])
        self.assertEqual(self.groups(), {**EXPECTED_ROLE_PERMISSIONS, 'BDE': set(), 'SALES_TL': set()})

        executor = MigrationExecutor(connection)
        executor.migrate([('accounts', '0010_bde_booking_links_permission')])
        self.assertEqual(self.groups(), GROUP_PERMISSIONS_AT_0010)

        executor = MigrationExecutor(connection)
        executor.migrate([('accounts', '0011_booking_slots_permission')])
        self.assertEqual(self.groups(), GROUP_PERMISSIONS_AT_0011)

        executor = MigrationExecutor(connection)
        executor.migrate([('accounts', '0012_bde_enquiries_permissions')])
        self.assertEqual(self.groups(), EXPECTED_GROUP_PERMISSIONS)

        # 0012 alone reverses: BDE's group is back to its booking links and the enquiry rows gone.
        executor = MigrationExecutor(connection)
        executor.migrate([('accounts', '0011_booking_slots_permission')])
        self.assertEqual(self.groups(), GROUP_PERMISSIONS_AT_0011)
        self.assertFalse(Permission.objects.filter(codename__in=('view_own_enquiries', 'add_enquiry')).exists())

        # 0011 alone reverses: ADMIN's group is back to 0008's and its permission row gone.
        executor = MigrationExecutor(connection)
        executor.migrate([('accounts', '0010_bde_booking_links_permission')])
        self.assertEqual(self.groups(), GROUP_PERMISSIONS_AT_0010)
        self.assertFalse(Permission.objects.filter(codename='manage_booking_slots').exists())

        # 0010 alone reverses: BDE's group is empty again and its permission row gone.
        executor = MigrationExecutor(connection)
        executor.migrate([('accounts', '0009_hub_roles_bde_sales_tl')])
        self.assertEqual(self.groups(), {**EXPECTED_ROLE_PERMISSIONS, 'BDE': set(), 'SALES_TL': set()})
        self.assertFalse(Permission.objects.filter(codename='view_own_booking_links').exists())

        # 0009 alone reverses: the new roles' groups go, the others stay.
        executor = MigrationExecutor(connection)
        executor.migrate([('accounts', '0008_role_groups')])
        self.assertEqual(self.groups(), EXPECTED_ROLE_PERMISSIONS)
        self.assertFalse(Group.objects.filter(name__in=('Role: BDE', 'Role: Sales TL')).exists())

        executor = MigrationExecutor(connection)
        executor.migrate([('accounts', '0012_bde_enquiries_permissions')])  # back to the leaf
        self.assertEqual(self.groups(), EXPECTED_GROUP_PERMISSIONS)
