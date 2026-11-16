"""
The reports schema (Phase 5.2, P6, design A.3): every rule the database holds
on reports, their revisions and their shares; the append-only triggers; the
read-only Django admin; and the two migrations reversing and applying cleanly.
"""
from datetime import timedelta
from unittest import skipUnless

from django.contrib import admin
from django.db import DatabaseError, DataError, IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.db.models import ProtectedError
from django.test import RequestFactory, TransactionTestCase, override_settings
from django.utils import timezone

from bookings.models import DiagnosticBooking
from bookings.tests_booking import DIAGNOSTIC, MORNING, BookingTestCase, account, book

from .models import (
    REPORT_MODELS,
    DemoReport,
    DemoReportRevision,
    DiagnosticReport,
    DiagnosticReportRevision,
    PerformanceLevel,
    ReportShare,
    ShareChannel,
    report_model,
)

TUTOR_NAME = 'Tutor Anu'
DEMO_FIELDS = ('assessment_review', 'class_observation_review', 'suggested_strategy')
HISTORY_TABLES = ('diagnostic_report_revisions', 'demo_report_revisions', 'report_shares')


def diagnostic_fields():
    return dict(
        score=18, max_score=25, performance_level=PerformanceLevel.GOOD,
        strength_areas=['Fractions', 'Place value'], skills_to_strengthen=['Word problems'],
        teacher_remarks='Works carefully and checks each step.', suggested_plan='Two sessions a week on word problems.',
    )


def demo_fields():
    return {field: f'The {field.replace("_", " ")}.' for field in DEMO_FIELDS}


class ReportTestCase(BookingTestCase):
    def setUp(self):
        super().setUp()
        self.tutor = account('tutor_anu', role='TUTOR')
        # One child: a Diagnostic in the morning and a Demo in the evening.
        self.diagnostic_booking = book(booking_type=DIAGNOSTIC, at=MORNING)[0]
        self.demo_booking = book()[0]

    def system(self):
        return dict(
            student_name_snapshot='Riya', grade_snapshot='8', tutor_name_snapshot=TUTOR_NAME,
            submitted_by=self.tutor, updated_by=self.tutor,
        )

    def diagnostic(self, **fields):
        values = {**self.system(), **diagnostic_fields(), **fields}
        return DiagnosticReport.objects.create(booking=self.diagnostic_booking, **values)

    def demo(self, **fields):
        values = {**self.system(), **demo_fields(), **fields}
        return DemoReport.objects.create(booking=self.demo_booking, **values)

    def assertRefused(self, create):
        # A check or unique constraint raises IntegrityError; text past a varchar's length, DataError.
        with self.assertRaises((IntegrityError, DataError)), transaction.atomic():
            create()

    def assertAccepted(self, create):
        """``create`` succeeds; it is rolled back, so the next case finds the booking free."""
        savepoint = transaction.savepoint()
        create()
        transaction.savepoint_rollback(savepoint)


class ReportConstraintTests(ReportTestCase):
    def test_a_report_of_each_type_belongs_to_its_booking(self):
        diagnostic, demo = self.diagnostic(), self.demo()
        self.assertEqual(DiagnosticBooking.objects.get(pk=self.diagnostic_booking.pk).report, diagnostic)
        self.assertEqual((diagnostic.version, diagnostic.booking_type, demo.booking_type), (1, 'DIAGNOSTIC', 'DEMO'))
        self.assertEqual([report_model(model.BOOKING_TYPE) for model in REPORT_MODELS], list(REPORT_MODELS))
        # Named by id and version, never by the student or the tutor.
        for report in (diagnostic, demo):
            self.assertEqual(str(report), f'{report._meta.verbose_name.capitalize()} {report.id} (v1)')

    def test_one_report_per_booking(self):
        self.diagnostic()
        self.assertRefused(self.diagnostic)
        self.demo()
        self.assertRefused(self.demo)

    def test_the_score_is_out_of_a_maximum_of_1_to_1000(self):
        for fields in ({'score': 26}, {'score': -1}, {'score': 0, 'max_score': 0}, {'max_score': 1001}):
            with self.subTest(fields=fields):
                self.assertRefused(lambda: self.diagnostic(**fields))
        for fields in ({'score': 25}, {'score': 0}, {'score': 1000, 'max_score': 1000}, {'score': 1, 'max_score': 1}):
            with self.subTest(fields=fields):
                self.assertAccepted(lambda: self.diagnostic(**fields))

    def test_the_performance_level_is_one_of_four(self):
        self.assertRefused(lambda: self.diagnostic(performance_level='OUTSTANDING'))
        for level in PerformanceLevel.values:
            self.assertAccepted(lambda: self.diagnostic(performance_level=level))

    def test_each_list_holds_1_to_15_items_of_1_to_120_characters(self):
        for field in ('strength_areas', 'skills_to_strengthen'):
            for items in ([], ['Topic'] * 16, ['Fractions', ''], ['Fractions', ' \t '], ['Fractions', None], ['x' * 121]):
                with self.subTest(field=field, items=[(item or '')[:5] for item in items]):
                    self.assertRefused(lambda: self.diagnostic(**{field: items}))
            self.assertAccepted(lambda: self.diagnostic(**{field: ['x' * 120] * 15}))

    def test_the_text_fields_are_required_and_capped(self):
        caps = [(self.diagnostic, 'teacher_remarks', 2000), (self.diagnostic, 'suggested_plan', 1000)]
        caps += [(self.demo, field, 1200) for field in DEMO_FIELDS]
        for create, field, cap in caps:
            with self.subTest(field=field):
                for blank in ('', '   ', '\n\t'):
                    self.assertRefused(lambda: create(**{field: blank}))
                self.assertRefused(lambda: create(**{field: 'x' * (cap + 1)}))
                self.assertAccepted(lambda: create(**{field: 'x' * cap}))
                # Characters, not bytes: a cap of Malayalam text is as long as one of English.
                self.assertAccepted(lambda: create(**{field: 'ക' * cap}))

    def test_versions_count_from_one_and_the_snapshots_are_present(self):
        self.assertRefused(lambda: self.diagnostic(version=0))
        now = timezone.now()
        self.assertRefused(lambda: self.demo(submitted_at=now, updated_at=now - timedelta(seconds=1)))
        for field in ('student_name_snapshot', 'grade_snapshot', 'tutor_name_snapshot'):
            with self.subTest(field=field):
                self.assertRefused(lambda: self.diagnostic(**{field: ''}))


class RevisionTests(ReportTestCase):
    def setUp(self):
        super().setUp()
        self.report = self.diagnostic()
        self.revision = DiagnosticReportRevision.objects.create(
            report=self.report, version=1, content={'score': 18}, changed_fields=[], edited_by=self.tutor,
        )

    def assertAppendOnly(self, table, changes):
        for change in changes:
            with self.subTest(table=table, change=change.__name__):
                with self.assertRaisesMessage(DatabaseError, f'{table} is append-only'), transaction.atomic():
                    change()

    def test_one_row_per_version(self):
        self.assertRefused(lambda: DiagnosticReportRevision.objects.create(
            report=self.report, version=1, content={}, edited_by=self.tutor,
        ))
        self.assertRefused(lambda: DiagnosticReportRevision.objects.create(
            report=self.report, version=0, content={}, edited_by=self.tutor,
        ))
        second = DiagnosticReportRevision.objects.create(
            report=self.report, version=2, content={'score': 19}, changed_fields=['score'], edited_by=self.tutor,
        )
        self.assertEqual(list(self.report.revisions.values_list('version', flat=True)), [1, 2])
        self.assertEqual(str(second), f'Diagnostic report revision v2 of {self.report.id}')

    def test_revisions_are_never_updated_or_deleted(self):
        demo_revision = DemoReportRevision.objects.create(
            report=self.demo(), version=1, content={}, edited_by=self.tutor,
        )
        for table, revision, model in (('diagnostic_report_revisions', self.revision, DiagnosticReportRevision),
                                       ('demo_report_revisions', demo_revision, DemoReportRevision)):
            def save():
                revision.changed_fields = ['score']
                revision.save()

            def update():
                model.objects.update(version=9)

            def delete():
                revision.delete()

            def raw_update():
                with connection.cursor() as cursor:
                    cursor.execute(f'UPDATE {table} SET content = %s', ['{}'])

            def raw_delete():
                with connection.cursor() as cursor:
                    cursor.execute(f'DELETE FROM {table}')

            self.assertAppendOnly(table, (save, update, delete, raw_update, raw_delete))
        self.assertEqual(DiagnosticReportRevision.objects.get().content, {'score': 18})

    def test_a_report_with_history_is_never_deleted_nor_its_booking(self):
        with self.assertRaises(ProtectedError):
            self.report.delete()
        with self.assertRaises(ProtectedError) as refused:
            self.diagnostic_booking.delete()
        self.assertIn(self.report, refused.exception.protected_objects)
        # Below the ORM too: the foreign key refuses it.
        with self.assertRaises(IntegrityError), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute('SET CONSTRAINTS ALL IMMEDIATE')
                cursor.execute('DELETE FROM diagnostic_reports')


class ShareTests(ReportTestCase):
    def setUp(self):
        super().setUp()
        self.report = self.diagnostic()
        self.bde = account('bde_one')

    def share(self, **fields):
        values = dict(diagnostic_report=self.report, report_version=1, shared_by=self.bde)
        values.update(fields)
        return ReportShare.objects.create(**values)

    def test_one_report_a_known_channel_and_a_version(self):
        self.assertRefused(lambda: self.share(diagnostic_report=None))
        self.assertRefused(lambda: self.share(demo_report=self.demo()))
        self.assertRefused(lambda: self.share(report_version=0))
        self.assertRefused(lambda: self.share(channel='EMAIL'))
        share = self.share()
        self.assertEqual((share.channel, share.report), (ShareChannel.WHATSAPP_MANUAL, self.report))
        # The parent's number is read from the lead when it is needed, never kept here.
        self.assertFalse(any('phone' in field.name for field in ReportShare._meta.get_fields()))

    def test_shares_are_never_updated_or_deleted(self):
        share = self.share()

        def save():
            share.report_version = 2
            share.save()

        def update():
            ReportShare.objects.update(report_version=2)

        def delete():
            share.delete()

        with self.assertRaisesMessage(DatabaseError, 'report_shares is append-only'), transaction.atomic():
            save()
        for change in (update, delete):
            with self.subTest(change=change.__name__):
                with self.assertRaisesMessage(DatabaseError, 'report_shares is append-only'), transaction.atomic():
                    change()
        self.assertEqual(ReportShare.objects.get().report_version, 1)


# The admin's pages need static files; the test container has no collected manifest.
@override_settings(STORAGES={
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
})
class AdminTests(ReportTestCase):
    MODELS = (DiagnosticReport, DemoReport, DiagnosticReportRevision, DemoReportRevision, ReportShare)

    def setUp(self):
        super().setUp()
        self.superuser = account('admin_root', role='ADMIN', is_staff=True, is_superuser=True)

    def test_every_report_table_is_read_only(self):
        request = RequestFactory().get('/admin/')
        request.user = self.superuser
        for model in self.MODELS:
            with self.subTest(model=model.__name__):
                model_admin = admin.site._registry[model]
                self.assertFalse(model_admin.has_add_permission(request))
                self.assertFalse(model_admin.has_change_permission(request))
                self.assertFalse(model_admin.has_delete_permission(request))

    def test_the_reports_group_lists_them(self):
        report = self.diagnostic()
        DiagnosticReportRevision.objects.create(report=report, version=1, content={}, edited_by=self.tutor)
        ReportShare.objects.create(diagnostic_report=report, report_version=1, shared_by=self.superuser)
        self.demo()
        self.client.force_login(self.superuser)
        self.assertContains(self.client.get('/admin/'), 'Reports')
        for model in self.MODELS:
            with self.subTest(model=model.__name__):
                response = self.client.get(f'/admin/reports/{model._meta.model_name}/')
                self.assertEqual(response.status_code, 200)
                # No add link for it (the sidebar offers other apps' own).
                self.assertNotContains(response, f'/admin/reports/{model._meta.model_name}/add/')


@skipUnless(connection.vendor == 'postgresql', 'the triggers need PostgreSQL')
class MigrationTests(TransactionTestCase):
    """reports.0002 and 0001 reverse to nothing and apply again, leaving the tables, checks and triggers as declared."""

    TABLES = ('diagnostic_reports', 'demo_reports', *HISTORY_TABLES)

    def migrate(self, target):
        MigrationExecutor(connection).migrate([('reports', target)])

    def tables(self):
        return set(connection.introspection.table_names()) & set(self.TABLES)

    def triggers(self):
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT tgname FROM pg_trigger WHERE NOT tgisinternal AND tgname LIKE %s", ['%_no_mutate'],
            )
            return {name for (name,) in cursor.fetchall()} & {f'{table}_no_mutate' for table in HISTORY_TABLES}

    def functions(self):
        with connection.cursor() as cursor:
            cursor.execute(
                'SELECT proname FROM pg_proc WHERE proname IN (%s, %s)', ['report_items_valid', 'report_history_immutable'],
            )
            return {name for (name,) in cursor.fetchall()}

    def test_reverse_and_reapply(self):
        try:
            self.migrate(None)
            self.assertEqual((self.tables(), self.triggers(), self.functions()), (set(), set(), set()))

            self.migrate('0001_reports_and_revisions')
            self.assertEqual((self.tables(), self.triggers()), (set(self.TABLES), set()))
            self.assertEqual(self.functions(), {'report_items_valid'})

            self.migrate('0002_append_only')
            self.assertEqual(self.triggers(), {f'{table}_no_mutate' for table in HISTORY_TABLES})
            self.assertEqual(self.functions(), {'report_items_valid', 'report_history_immutable'})
            with connection.cursor() as cursor:
                for model in (*REPORT_MODELS, DiagnosticReportRevision, DemoReportRevision, ReportShare):
                    declared = {item.name for item in (*model._meta.constraints, *model._meta.indexes)}
                    present = set(connection.introspection.get_constraints(cursor, model._meta.db_table))
                    self.assertLessEqual(declared, present, model.__name__)
        finally:
            MigrationExecutor(connection).migrate(MigrationExecutor(connection).loader.graph.leaf_nodes('reports'))
