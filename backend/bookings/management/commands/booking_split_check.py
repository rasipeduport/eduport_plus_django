"""
manage.py booking_split_check [--after]

Read-only checks around bookings.0005, which replaces the combined
``bookings`` table with ``diagnostic_bookings`` and ``demo_bookings`` (and the
``booking_events`` history) and drops the old table with its rows -- test data
only, so nothing is copied.

Before the migration (no flag): what it will discard -- the old table's rows
counted by type and status, with the newest -- and whether anything else in
the database depends on that table, which would stop the drop. With --after
(once every bookings migration has run, 0005 and those after it): that the old
table is gone and the new tables carry every constraint and index the models
declare, with the triggers that keep the history append-only
and each booking on a slot of its own type.

Prints counts and the names of database objects only, never a person's
details, and changes nothing. Exits with an error when a check fails.
"""
import django
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.recorder import MigrationRecorder

from bookings.models import BookingEvent, BookingSlot, DemoBooking, DiagnosticBooking

LAST_BEFORE = ('bookings', '0004_booking_tutor_assignment')
SPLIT = ('bookings', '0005_booking_split')
OLD_TABLE = 'bookings'
NEW_MODELS = (DiagnosticBooking, DemoBooking, BookingEvent)
# The triggers 0005 adds, by table, and what each keeps.
TRIGGERS = {
    BookingEvent._meta.db_table: {'booking_events_no_mutate': 'append-only'},
    DiagnosticBooking._meta.db_table: {'diagnostic_bookings_slot_type': 'Diagnostic slots only'},
    DemoBooking._meta.db_table: {'demo_bookings_slot_type': 'Demo slots only'},
    BookingSlot._meta.db_table: {'booking_slots_type_fixed': 'type fixed once booked'},
}


class Command(BaseCommand):
    help = 'Read-only checks before (and, with --after, after) the Diagnostic/Demo booking split.'

    def add_arguments(self, parser):
        parser.add_argument('--after', action='store_true', help='Check the split has been applied correctly.')

    def handle(self, *args, after=False, **options):
        self._environment()
        failures = self._after() if after else self._before()
        if failures:
            for failure in failures:
                self.stdout.write(self.style.ERROR(f'FAIL  {failure}'))
            raise CommandError(f'{len(failures)} check(s) failed.')
        self.stdout.write(self.style.SUCCESS('All checks passed.'))

    # ------------------------------------------------------------- reports

    def _environment(self):
        settings = connection.settings_dict
        server = getattr(connection, 'pg_version', None)
        self.stdout.write(
            f"Database: {settings.get('NAME')} on {settings.get('HOST') or 'localhost'}:{settings.get('PORT') or '-'} "
            f"({connection.vendor}{f', server {server}' if server else ''}); Django {django.get_version()}"
        )

    def _before(self):
        failures = []
        applied = MigrationRecorder(connection).applied_migrations()
        if SPLIT in applied:
            return [f'{SPLIT[0]}.{SPLIT[1]} is already applied; run with --after to check the result.']
        if LAST_BEFORE not in applied:
            failures.append(f'{LAST_BEFORE[0]}.{LAST_BEFORE[1]} is not applied, so the split cannot run yet.')
        tables = set(connection.introspection.table_names())
        if OLD_TABLE not in tables:
            failures.append(f'The {OLD_TABLE} table does not exist.')
            return failures

        with connection.cursor() as cursor:
            cursor.execute(
                f'SELECT booking_type, status, COUNT(*), MAX(created_at) FROM {OLD_TABLE} '
                'GROUP BY booking_type, status ORDER BY booking_type, status'
            )
            rows = cursor.fetchall()
        total = sum(count for _type, _status, count, _newest in rows)
        self.stdout.write(f'Rows in {OLD_TABLE} that the split will discard: {total}')
        for booking_type, status, count, newest in rows:
            self.stdout.write(f'  {booking_type:<10} {status:<10} {count:>5}   newest {newest:%Y-%m-%d %H:%M %Z}')

        dependents = self._dependents()
        if dependents:
            failures.extend(f'{name} depends on {OLD_TABLE}; the drop would fail.' for name in dependents)
        else:
            self.stdout.write(f'Nothing else in the database depends on {OLD_TABLE}.')
        return failures

    def _after(self):
        failures = []
        applied = MigrationRecorder(connection).applied_migrations()
        if SPLIT not in applied:
            failures.append(f'{SPLIT[0]}.{SPLIT[1]} is not applied.')
        # The models declare what every bookings migration makes, so every one must have run.
        executor = MigrationExecutor(connection)
        pending = [migration.name for migration, _backwards in
                   executor.migration_plan(executor.loader.graph.leaf_nodes('bookings'))]
        if pending:
            failures.append(f"bookings migrations not applied yet: {', '.join(pending)}.")
        tables = set(connection.introspection.table_names())
        if OLD_TABLE in tables:
            failures.append(f'The old {OLD_TABLE} table still exists.')
        with connection.cursor() as cursor:
            for model in NEW_MODELS:
                table = model._meta.db_table
                if table not in tables:
                    failures.append(f'The {table} table is missing.')
                    continue
                expected = {item.name for item in (*model._meta.constraints, *model._meta.indexes)}
                present = set(connection.introspection.get_constraints(cursor, table))
                failures.extend(f'{table}: {name} is missing.' for name in sorted(expected - present))
                self.stdout.write(f'{table}: {len(expected & present)}/{len(expected)} declared constraints and indexes present')
        if connection.vendor == 'postgresql':
            for table, expected in TRIGGERS.items():
                if table not in tables:
                    continue
                with connection.cursor() as cursor:
                    cursor.execute(
                        'SELECT tgname FROM pg_trigger WHERE tgrelid = %s::regclass AND NOT tgisinternal', [table],
                    )
                    present = {name for (name,) in cursor.fetchall()}
                for name, keeps in expected.items():
                    if name in present:
                        self.stdout.write(f'{table}: {name} trigger present ({keeps})')
                    else:
                        failures.append(f'{table}: the {name} trigger is missing.')
        return failures

    @staticmethod
    def _dependents():
        """Foreign keys and views elsewhere in the database that reference the old table."""
        if connection.vendor != 'postgresql':
            return []
        with connection.cursor() as cursor:
            cursor.execute(
                'SELECT conrelid::regclass::text || %s || conname FROM pg_constraint '
                'WHERE confrelid = %s::regclass AND conrelid <> %s::regclass',
                ['.', OLD_TABLE, OLD_TABLE],
            )
            keys = [f'Foreign key {name}' for (name,) in cursor.fetchall()]
            cursor.execute(
                'SELECT DISTINCT view_name FROM information_schema.view_table_usage '
                'WHERE table_name = %s AND table_schema = current_schema()',
                [OLD_TABLE],
            )
            views = [f'View {name}' for (name,) in cursor.fetchall()]
        return keys + views
