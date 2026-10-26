"""
    python manage.py role_permissions show
    python manage.py role_permissions check
    python manage.py role_permissions grant  ROLE app_label.codename [--apply]
    python manage.py role_permissions revoke ROLE app_label.codename [--apply]
    python manage.py role_permissions snapshot [--output FILE]
    python manage.py role_permissions compare FILE

The operator's handle on the role groups (accounts.RoleGroup) -- the same
configuration the Django admin's group pages edit, with the same rules: only
catalogue permissions, only within the role's ceiling
(accounts.permission_catalogue), every change audited (accounts.signals).

``check`` exits non-zero on anything the resolver would ignore or a deployment
should not carry: group memberships, grants beyond a role's ceiling, roles
without a group, unknown role values. ``snapshot`` and ``compare`` record and
compare what every account can do, for proving a change kept access unchanged.
"""
import json

from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.authz import acting_as, effective_permissions, has_app_permission
from accounts.models import ROLE_GROUP_ROLES, RoleChoices, RoleGroup, User
from accounts.permission_catalogue import CATALOGUE, VIEW_TEAM, allowed_for_role, grantable_permissions
from accounts.team import is_team_manager


def _name(permission):
    return f'{permission.content_type.app_label}.{permission.codename}'


def _group_permission_names(group):
    return sorted(_name(p) for p in group.permissions.select_related('content_type'))


def account_snapshot(user):
    """What one account can do, in the form ``snapshot`` records and ``compare`` checks."""
    if is_team_manager(user):
        team = 'manage'
    elif has_app_permission(user, VIEW_TEAM):
        team = 'view'
    else:
        team = 'none'
    return {
        'role': user.role,
        'is_superuser': user.is_superuser,
        'is_active': user.is_active,
        'permissions': sorted(effective_permissions(user)),
        'team_access': team,
        'can_grant': sorted(name for name in CATALOGUE if has_app_permission(user, name)),
    }


def snapshot():
    return {
        'catalogue': sorted(CATALOGUE),
        'users': {str(user.pk): account_snapshot(user) for user in User.objects.order_by('pk')},
    }


class Command(BaseCommand):
    help = 'Show, check and configure the role groups, and snapshot or compare what every account can do.'

    def add_arguments(self, parser):
        actions = parser.add_subparsers(dest='action', required=True)
        actions.add_parser('show', help='Each role group and its permissions.')
        actions.add_parser('check', help='Exit non-zero on any misconfiguration.')
        for name, verb in (('grant', 'Add'), ('revoke', 'Remove')):
            sub = actions.add_parser(name, help=f'{verb} a permission on a role group (a dry run without --apply).')
            sub.add_argument('role', help='ADMIN, MENTOR or TUTOR')
            sub.add_argument('permission', help='app_label.codename, from the catalogue')
            sub.add_argument('--apply', action='store_true', help='Make the change; without it nothing is written.')
        sub = actions.add_parser('snapshot', help="Every account's effective permissions as JSON.")
        sub.add_argument('--output', help='Write to this file instead of standard output.')
        sub = actions.add_parser('compare', help='Exit non-zero if any account can do more or less than in FILE.')
        sub.add_argument('file')

    def handle(self, *args, **options):
        # Not named after the actions: BaseCommand.check runs the system checks.
        action = options['action']
        if action in ('grant', 'revoke'):
            return self.change_group(action, options['role'].strip().upper(), options['permission'].strip(), options['apply'])
        return {
            'show': self.show_groups,
            'check': self.check_configuration,
            'snapshot': self.write_snapshot,
            'compare': self.compare_snapshot,
        }[action](**options)

    # ------------------------------------------------------------ reading

    def show_groups(self, **options):
        for link in RoleGroup.objects.select_related('group').order_by('role'):
            allowed = allowed_for_role(link.role)
            self.stdout.write(f'{link.get_role_display()} ({link.role}) -> group "{link.group.name}"')
            names = _group_permission_names(link.group)
            for name in names:
                note = '' if name in allowed else "   [beyond the role's ceiling: ignored]"
                label = CATALOGUE.get(name, {}).get('label', 'not in the catalogue')
                self.stdout.write(f'  {name}  ({label}){note}')
            if not names:
                self.stdout.write('  (no permissions)')
        grants = User.user_permissions.through.objects.count()
        self.stdout.write(f'Individual grants (Team page): {grants}')

    def check_configuration(self, **options):
        problems, warnings = [], []
        for name in CATALOGUE:
            app_label, codename = name.split('.', 1)
            if not Permission.objects.filter(content_type__app_label=app_label, codename=codename).exists():
                problems.append(f'Catalogue permission {name} has no permission row (is migration accounts 0008 applied?).')
        memberships = User.groups.through.objects.count()
        if memberships:
            problems.append(f'{memberships} group membership(s) exist; they grant nothing and should be removed.')
        linked = set(RoleGroup.objects.values_list('role', flat=True))
        for role in ROLE_GROUP_ROLES:
            if role not in linked:
                problems.append(f'Role {role} has no role group: its accounts hold only individual grants.')
        for link in RoleGroup.objects.select_related('group'):
            beyond = sorted(set(_group_permission_names(link.group)) - allowed_for_role(link.role))
            if beyond:
                problems.append(f'Group "{link.group.name}" carries {", ".join(beyond)}, which {link.role} may not hold (ignored).')
        for group in Group.objects.filter(role_link__isnull=True).order_by('name'):
            problems.append(f'Group "{group.name}" is not a role group and grants nothing.')
        unknown = User.objects.exclude(role__in=RoleChoices.values).count()
        if unknown:
            problems.append(f'{unknown} account(s) carry an unknown role value and hold nothing.')
        grantable = grantable_permissions()
        for user in User.objects.filter(user_permissions__isnull=False).distinct().prefetch_related('user_permissions__content_type'):
            usable = grantable & (set(CATALOGUE) if user.is_superuser else allowed_for_role(user.role))
            beyond = sorted({_name(p) for p in user.user_permissions.all()} - usable)
            if beyond:
                problems.append(f'Account {str(user.pk)[:8]} ({user.role}) holds individual grants it cannot use: {", ".join(beyond)}.')
        # Decision D1: a superuser holds every permission whatever the role, so
        # a non-Admin role on a superuser misleads anyone reading the account.
        for user in User.objects.filter(is_superuser=True).exclude(role=RoleChoices.ADMIN).order_by('pk'):
            warnings.append(f'Superuser {str(user.pk)[:8]} has the {user.role} role but holds every permission, as a superuser.')

        for warning in warnings:
            self.stdout.write(self.style.WARNING(f'Warning: {warning}'))
        for problem in problems:
            self.stdout.write(self.style.ERROR(problem))
        if problems:
            raise CommandError(f'{len(problems)} problem(s) found.')
        self.stdout.write(self.style.SUCCESS(f'No problems found ({len(warnings)} warning(s)).'))

    def write_snapshot(self, output=None, **options):
        text = json.dumps(snapshot(), indent=2, sort_keys=True)
        if output:
            with open(output, 'w', encoding='utf-8') as handle:
                handle.write(text + '\n')
            self.stdout.write(f'Wrote {output}')
        else:
            self.stdout.write(text)

    def compare_snapshot(self, file=None, **options):
        try:
            with open(file, encoding='utf-8') as handle:
                before = json.load(handle)['users']
        except (OSError, ValueError, KeyError) as exc:
            raise CommandError(f'Cannot read snapshot {file}: {exc}')
        now = snapshot()['users']
        differences = []
        for pk in sorted(set(before) | set(now)):
            if pk not in now:
                differences.append(f'{pk[:8]}: in the snapshot, no longer exists')
            elif pk not in before:
                differences.append(f'{pk[:8]}: new since the snapshot ({now[pk]["role"]})')
            else:
                for key in sorted(set(before[pk]) | set(now[pk])):
                    if before[pk].get(key) != now[pk].get(key):
                        differences.append(f'{pk[:8]}: {key} {before[pk].get(key)!r} -> {now[pk].get(key)!r}')
        for line in differences:
            self.stdout.write(self.style.WARNING(line))
        if differences:
            raise CommandError(f'{len(differences)} difference(s) from {file}.')
        self.stdout.write(self.style.SUCCESS(f'All {len(now)} account(s) match {file}.'))

    # ------------------------------------------------------------ writing

    def change_group(self, action, role, name, apply):
        link = RoleGroup.objects.select_related('group').filter(role=role).first()
        if link is None:
            raise CommandError(f'No role group for {role!r}. Roles with a group: {", ".join(ROLE_GROUP_ROLES)}.')
        if action == 'grant':
            if name not in CATALOGUE:
                raise CommandError(f'{name} is not in the catalogue (accounts.permission_catalogue).')
            if name not in allowed_for_role(role):
                raise CommandError(f'The {role} role may not hold {name}.')
        app_label, _, codename = name.partition('.')
        permission = Permission.objects.filter(content_type__app_label=app_label, codename=codename).first()
        if permission is None:
            raise CommandError(f'No permission {name} exists.')

        holds = link.group.permissions.filter(pk=permission.pk).exists()
        if holds == (action == 'grant'):
            self.stdout.write(f'Nothing to do: "{link.group.name}" {"already holds" if holds else "does not hold"} {name}.')
            return
        if not apply:
            self.stdout.write(f'Would {action} {name} {"to" if action == "grant" else "from"} "{link.group.name}". '
                              'Re-run with --apply to make the change.')
            return
        with transaction.atomic(), acting_as(None, 'manage.py role_permissions'):
            if action == 'grant':
                link.group.permissions.add(permission)
            else:
                link.group.permissions.remove(permission)
        self.stdout.write(self.style.SUCCESS(f'{action.capitalize()}ed {name}: "{link.group.name}" now carries '
                                             f'{", ".join(_group_permission_names(link.group)) or "nothing"}.'))
