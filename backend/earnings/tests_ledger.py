"""
The earnings ledger: pricing (earnings.rates), the sync that writes each
counted class's earning once (earnings.ledger), an administrator's reversals
and adjustments (earnings.corrections), what the database refuses, and the
earnings an administrator is asked to review (earnings.summaries).
"""
import threading
import uuid
from datetime import date, datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from io import StringIO
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import DatabaseError, IntegrityError, connection, transaction
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from activity.models import ActivityLog
from sessions.models import Session, SessionStatusChoices
from students.models import StatusChoices, Student

from . import corrections, ledger, rates, summaries
from .models import (
    ClassType,
    EarningEntry,
    EarningReview,
    EarningsRate,
    EarningsSyncRun,
    EntryKind,
    RateSource,
    SyncStatus,
    TutorEarningsActivation,
    TutorEarningsPricing,
)
from .tests import EarningsWorld
from .values import INDIA, EarningsError, month_of

User = get_user_model()
SESSION, DEMO, DIAGNOSTIC = ClassType.SESSION, ClassType.DEMO, ClassType.DIAGNOSTIC


class LedgerWorld(EarningsWorld):
    def setUp(self):
        super().setUp()
        self.activate(self.now - timedelta(days=30))

    def price(self, session='400', tutors=None, **overrides):
        data = {'global': {'DIAGNOSTIC': '300', 'DEMO': '300', 'SESSION': session, 'DEMO_CONVERSION': '450'}, 'tutors': tutors or [],
                'confirm': True, **overrides}
        return rates.start_pricing(self.admin, data)

    def completed(self, ago, hours=1, tutor=None):
        """A class that started ``ago`` (and was started then) and lasted ``hours``, completed now by its tutor's notes."""
        tutor = tutor or self.tutor
        session = self.make(-ago, hours=hours, started=True, tutor=tutor)
        res = self.notes(tutor, session)
        self.assertTrue(res.data['completed'], res.data)
        session.refresh_from_db()
        return session

    def earnings(self, **filters):
        return EarningEntry.objects.filter(kind=EntryKind.EARNING, **filters)

    def refusal(self, call):
        with self.assertRaises(EarningsError) as raised:
            call()
        return raised.exception


class PricingTests(LedgerWorld):
    def test_nothing_is_earned_before_pricing_starts(self):
        self.completed(timedelta(days=3))
        run = ledger.reconcile()
        self.assertEqual((run.status, run.waiting_count, run.earned_count), (SyncStatus.WAITING_FOR_PRICING, 1, 0))
        self.assertFalse(EarningEntry.objects.exists())

    def test_the_initial_rates_price_every_eligible_class_since_the_activation(self):
        session = self.completed(timedelta(days=20), hours=1.5)
        before_activation = self.completed(timedelta(days=40))
        self.price()
        run = ledger.reconcile()
        self.assertEqual((run.status, run.earned_count), (SyncStatus.SUCCEEDED, 1))
        earning = self.earnings().get()
        self.assertEqual((earning.class_type, earning.source_id, earning.tutor), (SESSION, session.pk, self.tutor))
        self.assertEqual((earning.units, earning.rate, earning.amount), (Decimal('1.50'), Decimal('400.00'), Decimal('600.00')))
        self.assertEqual((earning.rate_source, earning.currency), (RateSource.GLOBAL, 'INR'))
        self.assertEqual(earning.month, month_of(session.end_time))
        self.assertEqual((earning.class_start, earning.class_end), (session.start_time, session.end_time))
        self.assertTrue(earning.rate_version.initial)
        self.assertEqual(earning.rate_version.effective_from, TutorEarningsActivation.objects.get().activated_at)
        self.assertEqual(earning.details['completed_at'], session.completed_at.isoformat())
        self.assertEqual(earning.details['student_code'], 'EDPLC1')
        self.assertEqual((earning.created_by, earning.sync_run), (None, run))
        self.assertFalse(self.earnings(source_id=before_activation.pk).exists())

    def test_a_tutors_own_rate_takes_the_global_ones_place_for_its_class_type(self):
        session = self.completed(timedelta(days=2), hours=1.5)
        self.price(tutors=[{'tutor': str(self.tutor.pk), 'rates': {'SESSION': '450', 'DEMO': '350'}}])
        ledger.reconcile()
        earning = self.earnings().get(source_id=session.pk)
        self.assertEqual((earning.rate, earning.amount, earning.rate_source), (Decimal('450.00'), Decimal('675.00'), RateSource.TUTOR))
        self.assertEqual(earning.rate_version.tutor, self.tutor)

    def test_pricing_starts_once_with_every_global_rate_and_its_confirmation(self):
        for data, code in (
            ({'global': {'DIAGNOSTIC': '300', 'DEMO': '300'}, 'confirm': True}, rates.INVALID_RATE),
            ({'global': {'DIAGNOSTIC': '300', 'DEMO': '300', 'SESSION': '400', 'DEMO_CONVERSION': '450'}}, rates.NOT_CONFIRMED),
            ({'global': {'DIAGNOSTIC': '300', 'DEMO': '300', 'SESSION': '400', 'DEMO_CONVERSION': '450', 'EXAM': '5'}, 'confirm': True}, rates.INVALID_RATE),
            ({'global': {'DIAGNOSTIC': '300', 'DEMO': '300', 'SESSION': '400', 'DEMO_CONVERSION': '450'}, 'confirm': True,
              'tutors': [{'tutor': str(self.mentor.pk), 'rates': {'DEMO': '350'}}]}, rates.UNKNOWN_TUTOR),
            ({'global': {'DIAGNOSTIC': '300', 'DEMO': '300', 'SESSION': '400', 'DEMO_CONVERSION': '450'}, 'confirm': True,
              'tutors': [{'tutor': 'not-an-id', 'rates': {'DEMO': '350'}}]}, rates.UNKNOWN_TUTOR),
            ({'global': {'DIAGNOSTIC': '300', 'DEMO': '300', 'SESSION': '400', 'DEMO_CONVERSION': '450'}, 'confirm': True, 'reason': 12}, 'INVALID_INPUT'),
            ({'global': {'DIAGNOSTIC': '300', 'DEMO': '300', 'SESSION': '400', 'DEMO_CONVERSION': '450'}, 'confirm': True, 'reason': 'x' * 501},
             'INVALID_INPUT'),
        ):
            with self.subTest(data=data):
                self.assertEqual(self.refusal(lambda: rates.start_pricing(self.admin, data)).code, code)
        for bad in ('0', '-1', '12.345', 'abc', True, None, '100000000'):
            with self.subTest(rate=bad):
                exc = self.refusal(lambda: self.price(session=bad))
                self.assertEqual(exc.code, rates.INVALID_RATE)
        self.assertFalse(EarningsRate.objects.exists())
        self.price()
        self.assertEqual(self.refusal(self.price).code, rates.PRICING_STARTED)
        self.assertEqual(EarningsRate.objects.count(), 4)
        log = ActivityLog.objects.get(action='earnings.start_pricing')
        self.assertEqual(log.context['global'], {'DIAGNOSTIC': '300.00', 'DEMO': '300.00', 'SESSION': '400.00',
                                                  'DEMO_CONVERSION': '450.00'})

    def test_pricing_needs_the_activation(self):
        TutorEarningsActivation.objects.all().delete()
        self.assertEqual(self.refusal(self.price).code, rates.NOT_ACTIVATED)
        self.assertFalse(TutorEarningsPricing.objects.exists())


class RateChangeTests(LedgerWorld):
    def test_a_rate_change_applies_from_when_it_is_saved_and_never_reprices_an_earning(self):
        first = self.completed(timedelta(days=2))
        self.price()
        ledger.reconcile()
        self.assertEqual(self.refusal(lambda: rates.set_global_rates(self.admin, {'rates': {'SESSION': '500'}})).code,
                         'INVALID_INPUT')  # a reason is required
        changed = rates.set_global_rates(self.admin, {'rates': {'SESSION': '500', 'DEMO': '300'}, 'reason': 'Revision'})
        # Only the rate that differs gets a new version, in effect from now.
        self.assertEqual([(v.class_type, v.amount, v.initial) for v in changed], [(SESSION, Decimal('500.00'), False)])
        self.assertGreater(changed[0].effective_from, first.end_time)
        self.assertEqual(self.earnings().get(source_id=first.pk).amount, Decimal('400.00'))
        ledger.reconcile()
        self.assertEqual(self.earnings().count(), 1)
        self.assertEqual(self.refusal(lambda: rates.set_global_rates(
            self.admin, {'rates': {'SESSION': '500'}, 'reason': 'Again'})).code, rates.NO_CHANGE)

    def test_a_class_is_paid_at_the_rate_in_effect_at_its_scheduled_end(self):
        self.price()
        before = self.completed(timedelta(hours=5))
        after = self.completed(timedelta(hours=3))
        # A change saved between the two classes' ends (written as rates.set_global_rates writes it).
        EarningsRate.objects.create(class_type=SESSION, amount=Decimal('550'), effective_from=before.end_time + timedelta(minutes=30),
                                    reason='Revision', created_by=self.admin)
        ledger.reconcile()
        self.assertEqual(self.earnings().get(source_id=before.pk).amount, Decimal('400.00'))
        self.assertEqual(self.earnings().get(source_id=after.pk).amount, Decimal('550.00'))

    def test_a_tutors_rate_and_back_to_the_global_one(self):
        self.price()
        self.assertEqual(self.refusal(lambda: rates.set_tutor_rates(self.admin, self.tutor, {'rates': {'SESSION': None},
                                                                                             'reason': 'x'})).code,
                         rates.NO_CHANGE)
        rates.set_tutor_rates(self.admin, self.tutor, {'rates': {'SESSION': '450'}, 'reason': 'Senior'})
        book = rates.RateBook.load()
        later = timezone.now() + timedelta(seconds=1)
        self.assertEqual(book.resolve(self.tutor.pk, SESSION, later)[1], RateSource.TUTOR)
        self.assertEqual(book.resolve(self.other_tutor.pk, SESSION, later)[1], RateSource.GLOBAL)
        self.assertEqual(book.tutors_with_own_rates(later), {self.tutor.pk})
        rates.set_tutor_rates(self.admin, self.tutor, {'rates': {'SESSION': None}, 'reason': 'Back to global'})
        book = rates.RateBook.load()
        version, source = book.resolve(self.tutor.pk, SESSION, timezone.now() + timedelta(seconds=1))
        self.assertEqual((version.amount, source), (Decimal('400.00'), RateSource.GLOBAL))
        self.assertEqual(len(book.history(self.tutor.pk)), 2)

    def test_rates_change_only_once_pricing_has_started(self):
        for call in (lambda: rates.set_global_rates(self.admin, {'rates': {'SESSION': '500'}, 'reason': 'x'}),
                     lambda: rates.set_tutor_rates(self.admin, self.tutor, {'rates': {'SESSION': '500'}, 'reason': 'x'})):
            self.assertEqual(self.refusal(call).code, rates.PRICING_NOT_STARTED)


class SyncTests(LedgerWorld):
    def test_a_class_is_earned_once_however_often_the_sync_runs(self):
        self.price()
        session = self.completed(timedelta(days=1))
        self.assertEqual(ledger.reconcile().earned_count, 1)
        self.assertEqual(ledger.reconcile().earned_count, 0)
        self.assertEqual(self.earnings(source_id=session.pk).count(), 1)
        # The database refuses a second earning for the class, whoever writes it.
        earning = self.earnings().get()
        with self.assertRaises(IntegrityError), transaction.atomic():
            EarningEntry.objects.create(
                kind=EntryKind.EARNING, tutor=self.tutor, amount=earning.amount, class_type=SESSION,
                source_id=session.pk, class_start=session.start_time, class_end=session.end_time, month=earning.month,
                units=earning.units, rate=earning.rate, rate_source=earning.rate_source, rate_version=earning.rate_version,
            )

    def test_only_classes_that_count_are_earned(self):
        self.price()
        counted = self.completed(timedelta(days=1))
        staff_attended = self.make(-timedelta(days=2), started=True)
        self.put(self.mentor, {'id': str(staff_attended.id), 'status': 'ATTENDED'})
        notes_due = self.make(-timedelta(days=3), started=True)
        not_started = self.make(-timedelta(days=4))
        ledger.reconcile()
        self.assertEqual(set(self.earnings().values_list('source_id', flat=True)), {counted.pk})
        # Notes days later still count: the next run earns the class.
        self.notes(self.tutor, notes_due)
        ledger.reconcile()
        self.assertEqual(set(self.earnings().values_list('source_id', flat=True)), {counted.pk, notes_due.pk})
        self.assertFalse(self.earnings(source_id=not_started.pk).exists())

    @override_settings(TUTOR_EARNINGS_SYNC_ENABLED=False)
    def test_a_sync_switched_off_writes_nothing(self):
        self.price()
        self.completed(timedelta(days=1))
        self.assertIsNone(ledger.reconcile())
        self.assertFalse(EarningsSyncRun.objects.exists())
        self.assertFalse(EarningEntry.objects.exists())

    def test_the_command_reports_and_runs_the_same_sync(self):
        self.completed(timedelta(days=1))
        out = StringIO()
        call_command('reconcile_tutor_earnings', '--dry-run', stdout=out)
        self.assertIn('1 eligible class(es) waiting for rates', out.getvalue())
        self.price()
        out = StringIO()
        call_command('reconcile_tutor_earnings', '--dry-run', stdout=out)
        self.assertIn('Would add 1 earning(s): 1 SESSION', out.getvalue())
        self.assertFalse(EarningEntry.objects.exists())
        out = StringIO()
        call_command('reconcile_tutor_earnings', stdout=out)
        self.assertIn('SUCCEEDED: 1 earned', out.getvalue())
        self.assertEqual(EarningsSyncRun.objects.first().trigger, 'COMMAND')


class CorrectionTests(LedgerWorld):
    def setUp(self):
        super().setUp()
        self.price()
        self.session = self.completed(timedelta(days=1), hours=1.5)
        ledger.reconcile()
        self.earning = self.earnings().get()

    def test_a_reversal_takes_an_earning_back_whole_and_its_class_is_never_earned_again(self):
        self.assertEqual(self.refusal(lambda: corrections.reverse_entry(self.admin, self.earning.pk, {})).code, 'INVALID_INPUT')
        reversal = corrections.reverse_entry(self.admin, self.earning.pk, {'reason': 'Taught by someone else'})
        self.assertEqual((reversal.kind, reversal.amount, reversal.month), (EntryKind.REVERSAL, Decimal('-600.00'), self.earning.month))
        self.assertEqual((reversal.reverses, reversal.created_by, reversal.class_type), (self.earning, self.admin, SESSION))
        self.assertEqual(self.refusal(lambda: corrections.reverse_entry(self.admin, self.earning.pk, {'reason': 'Again'})).code,
                         corrections.ALREADY_REVERSED)
        self.assertEqual(self.refusal(lambda: corrections.reverse_entry(self.admin, reversal.pk, {'reason': 'x'})).code,
                         corrections.NOT_REVERSIBLE)
        self.assertEqual(ledger.reconcile().earned_count, 0)
        self.assertEqual(self.earnings().count(), 1)
        self.assertEqual(sum(EarningEntry.objects.values_list('amount', flat=True)), 0)
        self.assertTrue(ActivityLog.objects.filter(action='earnings.reverse_entry', entity_id=str(self.earning.pk)).exists())

    def test_an_adjustment_adds_or_deducts_with_its_reason_in_a_month_since_the_activation(self):
        month = timezone.localdate().strftime('%Y-%m')
        deduction = corrections.add_adjustment(
            self.admin, self.tutor, {'amount': '-150.50', 'month': month, 'reason': 'Shortened class', 'entry': str(self.earning.pk)},
        )
        self.assertEqual((deduction.kind, deduction.amount, deduction.source_id), (EntryKind.ADJUSTMENT, Decimal('-150.50'), self.session.pk))
        bonus = corrections.add_adjustment(self.admin, self.tutor, {'amount': '200', 'reason': 'Extra prep'})
        self.assertIsNone(bonus.class_type)
        for data in ({'amount': '0', 'reason': 'x'}, {'amount': '10', 'reason': ' '}, {'amount': '1.001', 'reason': 'x'},
                     {'amount': '10', 'reason': 'x', 'month': '2020-01'}, {'amount': '10', 'reason': 'x', 'month': '2999-01'},
                     {'amount': '10', 'reason': 'x', 'month': 'soon'}, {'amount': '10', 'reason': 'x', 'entry': 'not-an-id'}):
            with self.subTest(data=data):
                self.refusal(lambda: corrections.add_adjustment(self.admin, self.tutor, data))
        # An adjustment made by mistake is reversed with its own reason; a deduction's reversal gives it back.
        reversal = corrections.reverse_entry(self.admin, bonus.pk, {'reason': 'Entered twice'})
        self.assertEqual(reversal.amount, Decimal('-200.00'))
        given_back = corrections.reverse_entry(self.admin, deduction.pk, {'reason': 'The class ran its full length'})
        self.assertEqual((given_back.amount, given_back.month), (Decimal('150.50'), deduction.month))
        self.assertEqual(self.refusal(lambda: corrections.reverse_entry(self.admin, deduction.pk, {'reason': 'Again'})).code,
                         corrections.ALREADY_REVERSED)

    def test_only_a_reversal_written_meanwhile_is_already_reversed(self):
        with mock.patch.object(EarningEntry.objects, 'create', side_effect=IntegrityError('check violated')):
            with self.assertRaises(IntegrityError):
                corrections.reverse_entry(self.admin, self.earning.pk, {'reason': 'Mistake'})

    def test_the_database_keeps_the_ledger_rates_and_pricing_as_written(self):
        for change in (
            lambda: EarningEntry.objects.filter(pk=self.earning.pk).update(amount=Decimal('1')),
            lambda: EarningEntry.objects.filter(pk=self.earning.pk).delete(),
            lambda: EarningsRate.objects.update(reason='Edited'),
            lambda: EarningsRate.objects.all().delete(),
            lambda: TutorEarningsPricing.objects.update(started_at=timezone.now()),
        ):
            with self.assertRaises(DatabaseError), transaction.atomic():
                change()
        # A reversal is whole, the same tutor's, in the same month.
        for wrong in ({'amount': Decimal('-1.00')}, {'tutor': self.other_tutor}, {'month': self.earning.month.replace(year=2030)}):
            values = {'kind': EntryKind.REVERSAL, 'tutor': self.tutor, 'amount': -self.earning.amount, 'month': self.earning.month,
                      'reverses': self.earning, 'reason': 'Forged', 'created_by': self.admin, **wrong}
            with self.subTest(wrong=wrong), self.assertRaises(DatabaseError), transaction.atomic():
                EarningEntry.objects.create(**values)

    def test_the_database_holds_each_kind_of_line_to_its_shape(self):
        month = self.earning.month
        for values in (
            {'kind': EntryKind.EARNING, 'amount': Decimal('5'), 'class_type': SESSION, 'source_id': self.session.pk},
            {'kind': EntryKind.ADJUSTMENT, 'amount': Decimal('0'), 'reason': 'x', 'created_by': self.admin},
            {'kind': EntryKind.ADJUSTMENT, 'amount': Decimal('5'), 'reason': '', 'created_by': self.admin},
            {'kind': EntryKind.ADJUSTMENT, 'amount': Decimal('5'), 'reason': 'x', 'created_by': self.admin, 'currency': 'AED'},
            {'kind': EntryKind.ADJUSTMENT, 'amount': Decimal('5'), 'reason': 'x', 'created_by': self.admin,
             'month': month.replace(day=2)},
            {'kind': EntryKind.ADJUSTMENT, 'amount': Decimal('5'), 'reason': 'x', 'created_by': self.admin, 'class_type': SESSION},
        ):
            with self.subTest(values=values), self.assertRaises(IntegrityError), transaction.atomic():
                EarningEntry.objects.create(**{'tutor': self.tutor, 'month': month, **values})


class ReviewTests(LedgerWorld):
    def setUp(self):
        super().setUp()
        self.price()
        self.session = self.completed(timedelta(days=1))
        ledger.reconcile()

    def problems(self):
        return [(item['problem'], item['entry']['source_id']) for item in summaries.review_items()]

    def test_an_earned_class_changed_outside_the_hub_is_listed_never_touched(self):
        self.assertEqual(self.problems(), [])
        Session.objects.filter(pk=self.session.pk).update(end_time=self.session.end_time + timedelta(minutes=30))
        self.assertEqual(self.problems(), [('TIMES_CHANGED', str(self.session.pk))])
        Session.objects.filter(pk=self.session.pk).update(tutor=self.other_tutor)
        self.assertEqual(self.problems(), [('TUTOR_CHANGED', str(self.session.pk))])
        # The completion no longer the tutor's own.
        Session.objects.filter(pk=self.session.pk).update(tutor=self.tutor, end_time=self.session.end_time,
                                                          completed_by=None)
        self.assertEqual(self.problems(), [('NO_LONGER_ELIGIBLE', str(self.session.pk))])
        # The earning stays as it was; reversing it settles the review.
        self.assertEqual(self.earnings().get().amount, Decimal('400.00'))
        corrections.reverse_entry(self.admin, self.earnings().get().pk, {'reason': 'Class cancelled'})
        self.assertEqual(self.problems(), [])

    def keep(self, reason='The class ran as paid', seen=None):
        """Keep the earning as earned, as reviewed now (``seen``: as reviewed earlier)."""
        earning = self.earnings().get()
        if seen is None:
            item = summaries.review_item(earning)
            seen = summaries.seen(item) if item else {}
        return corrections.keep_entry(self.admin, earning.pk, {'reason': reason, 'seen': seen})

    def test_an_adjustment_alone_leaves_an_earning_in_review(self):
        Session.objects.filter(pk=self.session.pk).update(end_time=self.session.end_time + timedelta(minutes=30))
        corrections.add_adjustment(self.admin, self.tutor, {'amount': '200', 'reason': 'The extra half hour',
                                                            'entry': str(self.earnings().get().pk)})
        self.assertEqual(self.problems(), [('TIMES_CHANGED', str(self.session.pk))])

    def test_kept_as_earned_while_the_class_reads_as_it_did_when_kept(self):
        earning = self.earnings().get()
        self.assertEqual(self.refusal(self.keep).code, corrections.NOT_IN_REVIEW)  # unchanged: nothing to keep
        later = self.session.end_time + timedelta(minutes=30)
        Session.objects.filter(pk=self.session.pk).update(end_time=later)
        self.assertEqual(self.refusal(lambda: self.keep(' ')).code, 'INVALID_INPUT')
        review = self.keep()
        self.assertEqual((review.entry, review.created_by, review.seen['problem']), (earning, self.admin, 'TIMES_CHANGED'))
        self.assertEqual(self.problems(), [])
        self.assertEqual(self.refusal(self.keep).code, corrections.NOT_IN_REVIEW)  # kept once
        self.assertEqual(self.earnings().get().amount, Decimal('400.00'))
        log = ActivityLog.objects.get(action='earnings.keep_entry', entity_id=str(earning.pk))
        self.assertEqual((log.context['problem'], log.context['reason']), ('TIMES_CHANGED', 'The class ran as paid'))
        # Changed again, it is back for review; as it read when kept, it is kept still.
        Session.objects.filter(pk=self.session.pk).update(end_time=later + timedelta(minutes=15))
        self.assertEqual(self.problems(), [('TIMES_CHANGED', str(self.session.pk))])
        Session.objects.filter(pk=self.session.pk).update(end_time=later)
        self.assertEqual(self.problems(), [])
        # Reversing still takes it back, and a reversed earning has nothing to keep.
        corrections.reverse_entry(self.admin, earning.pk, {'reason': 'Taught by someone else'})
        Session.objects.filter(pk=self.session.pk).update(end_time=later + timedelta(minutes=15))
        self.assertEqual(self.problems(), [])
        self.assertEqual(self.refusal(self.keep).code, corrections.NOT_IN_REVIEW)

    def test_only_the_change_reviewed_is_kept(self):
        later = self.session.end_time + timedelta(minutes=30)
        Session.objects.filter(pk=self.session.pk).update(end_time=later)
        shown = summaries.seen(summaries.review_item(self.earnings().get()))
        # Changed again while the administrator was deciding: nothing is kept.
        Session.objects.filter(pk=self.session.pk).update(end_time=later + timedelta(minutes=15))
        self.assertEqual(self.refusal(lambda: self.keep(seen=shown)).code, corrections.REVIEW_CHANGED)
        exc = self.refusal(lambda: corrections.keep_entry(self.admin, self.earnings().get().pk, {'reason': 'Ran as paid'}))
        self.assertEqual((exc.code, exc.extra['field']), ('INVALID_INPUT', 'seen'))
        self.assertFalse(EarningReview.objects.exists())
        self.assertEqual(self.problems(), [('TIMES_CHANGED', str(self.session.pk))])

    def test_a_kept_earning_comes_back_when_its_class_stops_counting(self):
        Session.objects.filter(pk=self.session.pk).update(end_time=self.session.end_time + timedelta(minutes=30))
        self.assertTrue(summaries.review_item(self.earnings().get())['current']['eligible'])
        self.keep()
        self.assertEqual(self.problems(), [])
        Session.objects.filter(pk=self.session.pk).update(status=SessionStatusChoices.CANCELLED, completed_at=None,
                                                          completed_by=None)
        [item] = summaries.review_items()
        self.assertEqual((item['problem'], item['current']['eligible']), ('TIMES_CHANGED', False))

    def test_only_an_earning_is_kept_and_a_keep_is_never_changed(self):
        adjustment = corrections.add_adjustment(self.admin, self.tutor, {'amount': '50', 'reason': 'Prep'})
        for entry_id, code in ((adjustment.pk, corrections.NOT_IN_REVIEW), (uuid.uuid4(), corrections.NOT_FOUND)):
            with self.subTest(code=code):
                exc = self.refusal(lambda: corrections.keep_entry(self.admin, entry_id, {'reason': 'x', 'seen': {}}))
                self.assertEqual(exc.code, code)
        Session.objects.filter(pk=self.session.pk).update(tutor=self.other_tutor)
        item = summaries.review_item(self.earnings().get())
        self.assertEqual((item['current_tutor']['id'], item['current']['eligible']), (str(self.other_tutor.pk), False))
        review = self.keep()
        self.assertEqual(review.seen['current']['tutor_id'], str(self.other_tutor.pk))
        for change in (lambda: EarningReview.objects.filter(pk=review.pk).update(reason='Edited'),
                       lambda: EarningReview.objects.filter(pk=review.pk).delete()):
            with self.assertRaises(DatabaseError), transaction.atomic():
                change()


class IndiaMonthTests(LedgerWorld):
    def test_a_month_is_an_india_month(self):
        self.assertEqual(month_of(datetime(2026, 10, 31, 18, 29, tzinfo=dt_timezone.utc)), date(2026, 10, 1))
        self.assertEqual(month_of(datetime(2026, 10, 31, 18, 30, tzinfo=dt_timezone.utc)), date(2026, 11, 1))

    def test_a_class_counts_in_the_india_month_of_its_scheduled_end(self):
        # Two classes ending half an hour either side of the start of an India month: one UTC day, two months.
        boundary = timezone.localtime(self.now - timedelta(hours=2), INDIA).replace(day=1, hour=0, minute=0, second=0,
                                                                                    microsecond=0)
        self.activate(boundary - timedelta(days=3))
        self.price()
        before = self.completed(self.now - (boundary - timedelta(minutes=90)))
        after = self.completed(self.now - (boundary - timedelta(minutes=30)))
        self.assertEqual(before.end_time.astimezone(dt_timezone.utc).date(), after.end_time.astimezone(dt_timezone.utc).date())
        ledger.reconcile()
        months = {entry.source_id: entry.month for entry in self.earnings()}
        previous = (boundary - timedelta(days=1)).date().replace(day=1)
        self.assertEqual((months[before.pk], months[after.pk]), (previous, boundary.date()))


class ConcurrentSyncTests(TransactionTestCase):
    """Two syncs at once -- the schedule and the command -- still earn each class once."""

    def setUp(self):
        self.admin = User.objects.create_user(email='cs_admin@eduport.com', password='x', full_name='Cs Admin', role='ADMIN')
        self.tutor = User.objects.create_user(email='cs_tutor@eduport.com', password='x', full_name='Cs Tutor', role='TUTOR')
        student_user = User.objects.create_user(email='cs_stu@eduport.com', password='x', full_name='Cs Stu', role='STUDENT')
        student = Student.objects.create(profile=student_user, student_code='EDPCS1', full_name='Cs Stu', tutor=self.tutor,
                                         total_class_quota=10, status=StatusChoices.ACTIVE)
        now = timezone.now().replace(microsecond=0)
        TutorEarningsActivation.objects.update_or_create(id=1, defaults={'activated_at': now - timedelta(days=10)})
        for days in (1, 2, 3):
            start = now - timedelta(days=days)
            Session.objects.create(student=student, tutor=self.tutor, title='Algebra', start_time=start,
                                   end_time=start + timedelta(hours=1), status=SessionStatusChoices.ATTENDED,
                                   started_at=start, started_by=self.tutor, completed_at=start + timedelta(hours=2),
                                   completed_by=self.tutor)
        rates.start_pricing(self.admin, {'global': {'DIAGNOSTIC': '300', 'DEMO': '300', 'SESSION': '400', 'DEMO_CONVERSION': '450'}, 'confirm': True})

    def test_two_syncs_at_once_earn_each_class_once(self):
        barrier = threading.Barrier(2)
        results = [None, None]

        def run(index):
            try:
                barrier.wait(timeout=10)
                results[index] = ledger.reconcile()
            finally:
                connection.close()

        threads = [threading.Thread(target=run, args=(index,)) for index in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(EarningEntry.objects.filter(kind=EntryKind.EARNING).count(), 3)
        self.assertEqual(sum(run.earned_count for run in results if run is not None), 3)
