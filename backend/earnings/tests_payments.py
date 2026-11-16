"""
Payments to tutors (earnings.payments): recorded by an administrator, in
rupees, by account transfer or UPI; at most what the tutor is owed, even when
two are recorded at once; once per request; never with a reference another
payment still counting has; never edited or deleted -- only voided, with a
reason, after which it no longer counts as paid.
"""
import threading
import uuid
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import DatabaseError, IntegrityError, connection, transaction
from django.test import TransactionTestCase
from django.utils import timezone

from activity.models import ActivityLog
from sessions.models import Session, SessionStatusChoices
from students.models import StatusChoices, Student

from . import corrections, ledger, payments, rates, summaries
from .models import EarningEntry, EntryKind, TutorEarningsActivation, TutorPayment
from .tests_ledger import LedgerWorld
from .values import EarningsError, india_today

User = get_user_model()


def payment(**changes):
    data = {'request_id': str(uuid.uuid4()), 'amount': '250.00', 'paid_on': india_today().isoformat(),
            'method': 'ACCOUNT_TRANSFER', 'reference': 'NEFT N0362-7004 5812', 'notes': 'Part of November'}
    data.update(changes)
    return data


class PaymentWorld(LedgerWorld):
    def setUp(self):
        super().setUp()
        self.price()
        self.completed(timedelta(days=2), hours=1.5)  # ₹600 owed
        ledger.reconcile()

    def pay(self, tutor=None, **changes):
        return payments.record_payment(self.admin, tutor or self.tutor, payment(**changes))

    def refused(self, **changes):
        with self.assertRaises(EarningsError) as raised:
            self.pay(**changes)
        return raised.exception


class RecordPaymentTests(PaymentWorld):
    def test_a_part_payment_is_recorded_and_counts_as_paid(self):
        paid, created = self.pay(amount='250.50')
        self.assertTrue(created)
        self.assertEqual((paid.amount, paid.currency, paid.method, paid.recorded_by), (Decimal('250.50'), 'INR', 'ACCOUNT_TRANSFER', self.admin))
        self.assertEqual(paid.reference_key, 'NEFTN036270045812')
        self.assertEqual(payments.outstanding(self.tutor.pk), Decimal('349.50'))
        log = ActivityLog.objects.get(action='earnings.record_payment', entity_id=str(paid.pk))
        self.assertEqual((log.actor, log.context['outstanding_before']), (self.admin, '600.00'))

    def test_a_repeated_request_records_it_once(self):
        data = payment()
        first, created = payments.record_payment(self.admin, self.tutor, data)
        again, created_again = payments.record_payment(self.admin, self.tutor, dict(data))
        self.assertEqual((first.pk, created, created_again), (again.pk, True, False))
        self.assertEqual(TutorPayment.objects.count(), 1)
        with self.assertRaises(EarningsError) as raised:
            payments.record_payment(self.admin, self.tutor, {**data, 'amount': '300'})
        self.assertEqual(raised.exception.code, payments.IDEMPOTENCY_CONFLICT)

    def test_never_more_than_is_owed(self):
        exc = self.refused(amount='600.01')
        self.assertEqual((exc.code, exc.extra['outstanding']), (payments.EXCEEDS_OUTSTANDING, '600.00'))
        self.pay(amount='600')
        exc = self.refused(amount='1', reference='UTR 2')
        self.assertEqual(exc.code, payments.NOTHING_OUTSTANDING)
        self.assertEqual(TutorPayment.objects.count(), 1)

    def test_only_by_account_transfer_or_upi_and_in_rupees_to_the_paisa(self):
        for changes, field in (({'method': 'CASH'}, 'method'), ({'method': 'CHEQUE'}, 'method'), ({'amount': '10.005'}, 'amount'),
                               ({'amount': '0'}, 'amount'), ({'amount': '-5'}, 'amount'), ({'amount': 'ten'}, 'amount'),
                               ({'amount': '1e30'}, 'amount'), ({'amount': '1' * 27}, 'amount'),
                               ({'amount': '1e1000000'}, 'amount'), ({'amount': '-1e1000000'}, 'amount'),
                               ({'reference': '  '}, 'reference'), ({'reference': '--/--'}, 'reference'),
                               ({'reference': 'x' * 101}, 'reference'), ({'notes': 'x' * 1001}, 'notes'),
                               ({'paid_on': (india_today() + timedelta(days=1)).isoformat()}, 'paid_on'),
                               ({'paid_on': '2020-01-01'}, 'paid_on'), ({'paid_on': 'yesterday'}, 'paid_on'),
                               ({'request_id': 'nope'}, 'request_id')):
            with self.subTest(changes=changes):
                exc = self.refused(**changes)
                self.assertEqual((exc.code, exc.extra.get('field')), ('INVALID_INPUT', field))
        self.pay(method='UPI', reference='UPI 4029 1827 3645')
        self.assertEqual(TutorPayment.objects.get().method, 'UPI')

    def test_a_reference_counts_once_whatever_its_case_or_punctuation_and_for_any_tutor(self):
        self.pay(reference='NEFT N0362-7004')
        exc = self.refused(reference='neft n03627004', amount='10')
        self.assertEqual(exc.code, payments.DUPLICATE_REFERENCE)
        # Another tutor, owed money too, cannot reuse it either.
        self.completed(timedelta(days=1), tutor=self.other_tutor)
        ledger.reconcile()
        with self.assertRaises(EarningsError) as raised:
            self.pay(tutor=self.other_tutor, reference='Neft-N0362 7004')
        self.assertEqual(raised.exception.code, payments.DUPLICATE_REFERENCE)

    def test_the_same_amount_on_the_same_day_must_be_confirmed(self):
        self.pay(amount='100', reference='UTR 1')
        exc = self.refused(amount='100', reference='UTR 2')
        self.assertEqual(exc.code, payments.POSSIBLE_DUPLICATE)
        _second, created = self.pay(amount='100', reference='UTR 2', confirm_duplicate=True)
        self.assertTrue(created)

    def test_a_tutor_owed_nothing_is_not_paid(self):
        with self.assertRaises(EarningsError) as raised:
            payments.record_payment(self.admin, self.other_tutor, payment())
        self.assertEqual(raised.exception.code, payments.NOTHING_OUTSTANDING)


class BeforePricingTests(LedgerWorld):
    def test_nothing_is_paid_before_pricing(self):
        self.completed(timedelta(days=1))
        with self.assertRaises(EarningsError) as raised:
            payments.record_payment(self.admin, self.tutor, payment())
        self.assertEqual(raised.exception.code, payments.PRICING_NOT_STARTED)
        self.assertFalse(TutorPayment.objects.exists())


class VoidTests(PaymentWorld):
    def test_a_voided_payment_stays_but_no_longer_counts_and_frees_its_reference(self):
        paid, _created = self.pay(amount='600', reference='NEFT 1')
        self.assertEqual(payments.outstanding(self.tutor.pk), Decimal('0.00'))
        with self.assertRaises(EarningsError) as raised:
            payments.void_payment(self.admin, paid.pk, {'reason': ' '})
        self.assertEqual(raised.exception.code, 'INVALID_INPUT')
        voided = payments.void_payment(self.admin, paid.pk, {'reason': 'Amount typed wrongly'})
        self.assertEqual((voided.voided_by, voided.void_reason), (self.admin, 'Amount typed wrongly'))
        self.assertEqual(payments.outstanding(self.tutor.pk), Decimal('600.00'))
        with self.assertRaises(EarningsError) as raised:
            payments.void_payment(self.admin, paid.pk, {'reason': 'Again'})
        self.assertEqual(raised.exception.code, payments.ALREADY_VOIDED)
        # The reference is free again.
        self.pay(amount='600', reference='neft-1')
        self.assertEqual(TutorPayment.objects.count(), 2)
        self.assertTrue(ActivityLog.objects.filter(action='earnings.void_payment', entity_id=str(paid.pk)).exists())

    def test_an_unknown_payment_is_404(self):
        with self.assertRaises(EarningsError) as raised:
            payments.void_payment(self.admin, uuid.uuid4(), {'reason': 'x'})
        self.assertEqual(raised.exception.status, 404)

    def test_the_database_never_edits_or_deletes_a_payment_and_voids_it_once(self):
        paid, _created = self.pay()
        for change in (lambda: TutorPayment.objects.filter(pk=paid.pk).update(amount=Decimal('1')),
                       lambda: TutorPayment.objects.filter(pk=paid.pk).update(reference='Changed', reference_key='CHANGED'),
                       lambda: TutorPayment.objects.filter(pk=paid.pk).delete()):
            with self.assertRaises(DatabaseError), transaction.atomic():
                change()
        TutorPayment.objects.filter(pk=paid.pk).update(voided_at=timezone.now(), voided_by=self.admin, void_reason='Mistake')
        with self.assertRaises(DatabaseError), transaction.atomic():
            TutorPayment.objects.filter(pk=paid.pk).update(void_reason='Changed my mind')
        # Two live payments never share a reference key, and no payment is in another currency.
        live = dict(tutor=self.tutor, amount=Decimal('5'), paid_on=india_today(), method='UPI', reference='R1',
                    reference_key='R1', recorded_by=self.admin)
        TutorPayment.objects.create(request_id=uuid.uuid4(), **live)
        for values in ({**live}, {**live, 'reference_key': 'R2', 'currency': 'AED'}):
            with self.subTest(values=values), self.assertRaises(IntegrityError), transaction.atomic():
                TutorPayment.objects.create(request_id=uuid.uuid4(), **values)


class OverpaidTests(PaymentWorld):
    def test_a_reversal_after_payment_leaves_the_tutor_overpaid_and_blocks_payments(self):
        self.pay(amount='600')
        earning = EarningEntry.objects.get(kind=EntryKind.EARNING)
        corrections.reverse_entry(self.admin, earning.pk, {'reason': 'Not taught'})
        self.assertEqual(payments.outstanding(self.tutor.pk), Decimal('-600.00'))
        exc = self.refused(amount='1', reference='UTR 9')
        self.assertEqual(exc.code, payments.NOTHING_OUTSTANDING)
        self.assertIn('overpaid by ₹600.00', exc.message)
        data = summaries.tutor_earnings(self.tutor)
        self.assertEqual((data['summary']['outstanding'], data['summary']['balance_state']), ('-600.00', 'overpaid'))


class ConcurrentPaymentTests(TransactionTestCase):
    """Two administrators paying the same tutor at once never pay more than is owed together."""

    def setUp(self):
        self.admin = User.objects.create_user(email='cp_admin@eduport.com', password='x', full_name='Cp Admin', role='ADMIN')
        self.tutor = User.objects.create_user(email='cp_tutor@eduport.com', password='x', full_name='Cp Tutor', role='TUTOR')
        student_user = User.objects.create_user(email='cp_stu@eduport.com', password='x', full_name='Cp Stu', role='STUDENT')
        student = Student.objects.create(profile=student_user, student_code='EDPCP1', full_name='Cp Stu', tutor=self.tutor,
                                         total_class_quota=10, status=StatusChoices.ACTIVE)
        now = timezone.now().replace(microsecond=0)
        TutorEarningsActivation.objects.update_or_create(id=1, defaults={'activated_at': now - timedelta(days=10)})
        start = now - timedelta(days=1)
        Session.objects.create(student=student, tutor=self.tutor, title='Algebra', start_time=start,
                               end_time=start + timedelta(hours=2.5), status=SessionStatusChoices.ATTENDED, started_at=start,
                               started_by=self.tutor, completed_at=start + timedelta(hours=3), completed_by=self.tutor)
        rates.start_pricing(self.admin, {'global': {'DIAGNOSTIC': '300', 'DEMO': '300', 'SESSION': '400'}, 'confirm': True})
        ledger.reconcile()  # ₹1,000 owed

    def test_two_payments_at_once_never_pay_more_than_is_owed(self):
        barrier = threading.Barrier(2)
        outcomes = [None, None]

        def run(index):
            try:
                barrier.wait(timeout=10)
                outcomes[index] = payments.record_payment(
                    self.admin, self.tutor, payment(amount='600', reference=f'UTR {index}'))[1]
            except EarningsError as exc:
                outcomes[index] = exc.code
            finally:
                connection.close()

        threads = [threading.Thread(target=run, args=(index,)) for index in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(sorted(outcomes, key=str), sorted([True, payments.EXCEEDS_OUTSTANDING], key=str))
        self.assertEqual(TutorPayment.objects.count(), 1)
        self.assertEqual(payments.outstanding(self.tutor.pk), Decimal('400.00'))
