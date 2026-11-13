"""Migrations 0016-0018 against legacy-shaped data: report, apply, reverse and re-apply.

Runs the real migrations in the disposable test database only.
"""
from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone

BEFORE = [('sales', '0015_durable_checkout_recovery')]
ACCOUNTS_ONLY = [('sales', '0016_student_accounts')]
AFTER = [('sales', '0018_student_account_required')]


class StudentAccountBackfillTests(TransactionTestCase):
    def migrate(self, targets):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(targets)
        return MigrationExecutor(connection).loader.project_state(targets).apps

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())

    def legacy_world(self, apps):
        User = apps.get_model('accounts', 'User')
        Lead = apps.get_model('bookings', 'Lead')
        Student = apps.get_model('students', 'Student')
        Sale = apps.get_model('sales', 'Sale')
        StripeCustomer = apps.get_model('sales', 'StripeCustomer')
        bde = User.objects.create(username='legacy_bde', email='legacy_bde@sales.test', role='BDE', full_name='Legacy BDE')
        learner = User.objects.create(username='edp00045', email='', role='STUDENT', full_name='Aarav Rahman')
        start = timezone.now() - timedelta(days=30)

        def lead(name, phone, email, offset):
            return Lead.objects.create(parent_name='Mohammed Rahman', phone_dial_code='+971', phone_number=phone,
                                       phone_key=f'+971{phone}', student_name=name, student_name_key=name.lower(),
                                       school_name='Legacy School', grade='Class 7', syllabus='CBSE', parent_email=email,
                                       owner_bde=bde, owner_assigned_at=start, created_at=start + timedelta(minutes=offset))
        aarav = lead('Aarav Rahman', '501110001', 'mohammed@family.test', 1)
        maya = lead('Maya Rahman', '501110001', 'mohammed@family.test', 2)
        other = lead('Zara Khan', '502220002', '', 3)
        lead('Enquiry Only', '503330003', '', 4)  # No sale, no Customer: no account.
        student = Student.objects.create(profile=learner, student_code='EDP00045', full_name='Aarav Rahman',
                                         quota_source='PAYMENTS', total_class_quota=6)
        Sale.objects.create(enquiry=aarav, original_bde=bde, created_by=bde, kind='NEW', student=student,
                            enrolled_at=start + timedelta(days=1), parent_email='mohammed@family.test', created_at=start + timedelta(hours=1))
        Sale.objects.create(enquiry=maya, original_bde=bde, created_by=bde, kind='NEW', parent_email='mohammed@family.test',
                            created_at=start + timedelta(hours=2))
        StripeCustomer.objects.create(enquiry=aarav, customer_id='cus_legacy_aarav', livemode=False, student_metadata_synced=True,
                                      creation_request={'name': 'Mohammed Rahman', 'metadata': {'enquiry_id': str(aarav.pk)}})
        StripeCustomer.objects.create(enquiry=other, customer_id=None, livemode=False,
                                      creation_request={'name': 'Parent', 'metadata': {'enquiry_id': str(other.pk)}})
        return aarav, maya, other, student

    def test_report_then_backfill_links_legacy_records_without_touching_stripe_ids(self):
        aarav, maya, other, student = self.legacy_world(self.migrate(BEFORE))
        report = StringIO()
        call_command('backfill_student_accounts', stdout=report)
        text = report.getvalue()
        self.assertIn('Database is before migration sales.0016. Read-only dry run', text)
        # Numbered by first financial activity: Zara's Customer mapping predates both sales.
        for reference, name in [('SA-000001', 'Zara Khan'), ('SA-000002', 'Aarav Rahman'), ('SA-000003', 'Maya Rahman')]:
            self.assertIn(f'{reference} (provisional)  {name}', text)
        self.assertIn('2 children share a parent phone', text)
        self.assertIn('Stripe Customer without a sale', text)
        self.assertIn('No ambiguous or duplicate mappings', text)
        self.assertNotIn('Enquiry Only', text)
        self.assertNotIn('mohammed@family.test', text)  # Contact details are masked.

        apps = self.migrate(AFTER)
        StudentAccount = apps.get_model('sales', 'StudentAccount')
        Sale = apps.get_model('sales', 'Sale')
        StripeCustomer = apps.get_model('sales', 'StripeCustomer')
        StudentGuardian = apps.get_model('sales', 'StudentGuardian')
        accounts = {row.origin_lead_id: row for row in StudentAccount.objects.all()}
        self.assertEqual({row.reference for row in accounts.values()}, {'SA-000001', 'SA-000002', 'SA-000003'})
        self.assertEqual((accounts[aarav.pk].reference, accounts[aarav.pk].student_id), ('SA-000002', student.pk))
        self.assertIsNone(accounts[maya.pk].student_id)
        self.assertEqual({sale.enquiry_id: sale.account_id for sale in Sale.objects.all()},
                         {aarav.pk: accounts[aarav.pk].pk, maya.pk: accounts[maya.pk].pk})
        legacy = StripeCustomer.objects.get(legacy_enquiry_id=aarav.pk)
        self.assertEqual((legacy.customer_id, legacy.account_id, legacy.label_format, legacy.stripe_account_id),
                         ('cus_legacy_aarav', accounts[aarav.pk].pk, 'LEGACY_PARENT', ''))
        self.assertIsNone(StripeCustomer.objects.get(legacy_enquiry_id=other.pk).customer_id)
        # Siblings sharing a phone and email are NOT linked to one guardian automatically.
        links = {link.account_id: link for link in StudentGuardian.objects.all()}
        self.assertNotEqual(links[accounts[aarav.pk].pk].guardian_id, links[accounts[maya.pk].pk].guardian_id)
        self.assertEqual({link.basis for link in links.values()}, {'BACKFILL'})

        # Reversible while nothing newer depends on it; re-applying is deterministic.
        apps = self.migrate(ACCOUNTS_ONLY)
        self.assertFalse(apps.get_model('sales', 'StudentAccount').objects.exists())
        self.assertFalse(apps.get_model('sales', 'Sale').objects.exclude(account=None).exists())
        apps = self.migrate(AFTER)
        again = {row.origin_lead_id: (row.pk, row.reference) for row in apps.get_model('sales', 'StudentAccount').objects.all()}
        self.assertEqual(again, {lead_id: (row.pk, row.reference) for lead_id, row in accounts.items()})
