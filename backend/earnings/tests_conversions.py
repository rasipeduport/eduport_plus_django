"""
Demo Conversion (earnings.conversions): a Demo that counted, whose student
then enrolled, tops its tutor's earning up to the conversion rate -- the
difference over the Demo's own earning, never the rate on top of it -- once
per enrollment and once per Demo, for the last Demo taught before the
enrollment, at the conversion rate in effect when the student enrolled.
"""
import json
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from unittest import mock

from django.db import DatabaseError, IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.db.models import Sum
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from bookings.booking_service import assign_tutor, cancel_booking, request_redemo, schedule_redemo
from bookings.models import CancelReason, DemoBooking, Lead
from bookings.tests_booking import DAY, DEMO, EVENING, MORNING, NOW, book, schedule, start
from bookings.tests_booking import account as person
from bookings.tests_redemos import AFTER, REASON, REDEMO_DAY, complete
from reports.services import submit_report
from reports.tests_services import report_input
from sales.account_models import StudentAccount
from sales.payment_models import Sale
from sales.student_accounts import next_reference
from students.models import Student

from . import conversions, corrections, ledger, payments, rates, summaries
from .models import (
    ClassType,
    EarningEntry,
    EarningsRate,
    EntryKind,
    RateSource,
    TutorEarningsActivation,
    TutorEarningsPricing,
    TutorPayment,
)
from .tests_bookings import ACTIVATED
from .values import INDIA, EarningsError, india_today, month_of

CONVERSION = ClassType.DEMO_CONVERSION
# Diagnostic ₹300, Demo ₹200, Normal Sessions ₹400 an hour, a converted Demo ₹350 in all.
GLOBAL = {'DIAGNOSTIC': '300', 'DEMO': '200', 'SESSION': '400', 'DEMO_CONVERSION': '350'}


def india(*parts):
    return datetime(*parts, tzinfo=INDIA)


def clock(moment):
    """The server's clock reading ``moment`` -- when a rate change is saved, and so takes effect."""
    return mock.patch('django.utils.timezone.now', return_value=moment)


class ConversionWorld(TestCase):
    def setUp(self):
        schedule()
        TutorEarningsActivation.objects.update_or_create(id=1, defaults={'activated_at': ACTIVATED})
        self.admin = person('admin_conversion', role='ADMIN')
        self.bde = person('bde_conversion', role='BDE')
        self.tutor = person('abhiram', role='TUTOR')
        self.other_tutor = person('tutor_after', role='TUTOR')
        self.students = 0

    def price(self, tutors=None, **global_rates):
        return rates.start_pricing(self.admin, {'global': {**GLOBAL, **global_rates}, 'tutors': tutors or [],
                                                'confirm': True})

    def demo(self, student='Riya', phone='0501234567', day=DAY, at=EVENING, tutor=None, report=True):
        """A Demo booked for ``day`` and ``at``, its tutor's own start and (``report``) report: read again."""
        tutor = tutor or self.tutor
        booking = book(booking_type=DEMO, student=student, phone=phone, day=day, at=at)[0]
        booking = start(assign_tutor(booking, tutor, now=NOW)[0])
        if report:
            submit_report(booking, tutor, report_input(booking), now=booking.slot.starts_at + timedelta(minutes=50))
        return DemoBooking.objects.select_related('slot', 'lead').get(pk=booking.pk)

    def enroll(self, lead, when, tutor=None):
        """``lead``'s initial sale, enrolled at ``when`` as sales.enrollment.enroll leaves it (the student's tutor: ``tutor``)."""
        self.students += 1
        student = Student.objects.create(
            profile=person(f'conversion_student_{self.students}', role='STUDENT'),
            student_code=f'EDP9{self.students:04d}', full_name=lead.student_name, tutor=tutor,
        )
        holder = StudentAccount.objects.create(reference=next_reference(), origin_lead=lead, student=student,
                                               student_name=lead.student_name)
        return Sale.objects.create(account=holder, enquiry=lead, original_bde=self.bde, created_by=self.bde,
                                   kind='NEW', student=student, enrolled_at=when)

    def converted(self, **filters):
        return EarningEntry.objects.filter(kind=EntryKind.EARNING, class_type=CONVERSION, **filters)

    def demo_earning(self, demo):
        return EarningEntry.objects.get(kind=EntryKind.EARNING, class_type=ClassType.DEMO, source_id=demo.pk)

    def earned(self, tutor):
        return EarningEntry.objects.filter(tutor=tutor).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

    def refusal(self, call):
        with self.assertRaises(EarningsError) as caught:
            call()
        return caught.exception


class ConversionTests(ConversionWorld):
    def test_a_demo_whose_student_never_enrolls_earns_the_demo_only(self):
        demo = self.demo()
        self.price()
        ledger.reconcile()
        self.assertEqual(self.demo_earning(demo).amount, Decimal('200.00'))
        self.assertFalse(self.converted().exists())
        self.assertEqual(conversions.pending(rates.RateBook.load()), [])
        self.assertEqual(summaries.tutor_earnings(self.tutor)['summary']['conversions'], 0)

    def test_enrolling_right_after_the_demo_tops_it_up_to_the_conversion_rate_never_on_top_of_it(self):
        demo = self.demo()
        self.price()
        sale = self.enroll(demo.lead, demo.slot.ends_at + timedelta(minutes=10))
        # One run earns the Demo, then its conversion.
        run = ledger.reconcile()
        self.assertEqual(run.earned_count, 2)
        earning, conversion = self.demo_earning(demo), self.converted().get()
        self.assertEqual((conversion.tutor, conversion.amount, conversion.rate, conversion.units, conversion.rate_source),
                         (self.tutor, Decimal('150.00'), Decimal('350.00'), Decimal('1.00'), RateSource.GLOBAL))
        self.assertEqual((conversion.source_id, conversion.converts_id, conversion.sync_run), (sale.pk, earning.pk, run))
        self.assertEqual((conversion.class_start, conversion.class_end), (demo.slot.starts_at, demo.slot.ends_at))
        self.assertEqual(conversion.month, month_of(sale.enrolled_at))
        details = conversion.details
        self.assertEqual(
            (details['demo_amount'], details['conversion_rate'], details['incentive'], details['final_amount']),
            ('200.00', '350.00', '150.00', '350.00'),
        )
        self.assertEqual(
            (details['sale_id'], details['demo_booking_id'], details['demo_entry_id'], details['student_code'],
             details['student_name'], details['converted_at'], details['is_redemo']),
            (str(sale.pk), str(demo.pk), str(earning.pk), sale.student.student_code, 'Riya',
             sale.enrolled_at.isoformat(), False),
        )
        # The Demo keeps its ₹200; with the ₹150 the converted Demo earned ₹350 -- never ₹200 + ₹350.
        self.assertEqual(earning.amount, Decimal('200.00'))
        self.assertEqual(self.earned(self.tutor), Decimal('350.00'))

    def test_enrolling_one_or_two_weeks_later_converts_in_the_enrollments_month(self):
        week = self.demo()
        fortnight = self.demo(student='Ali', phone='0507654321', at=MORNING)
        self.price()
        ledger.reconcile()
        later = self.enroll(week.lead, week.slot.ends_at + timedelta(weeks=1))
        latest = self.enroll(fortnight.lead, fortnight.slot.ends_at + timedelta(weeks=2))
        ledger.reconcile()
        by_sale = {entry.source_id: entry for entry in self.converted()}
        self.assertEqual(set(by_sale), {later.pk, latest.pk})
        self.assertEqual({entry.month for entry in by_sale.values()}, {date(2026, 11, 1)})
        self.assertEqual({entry.amount for entry in by_sale.values()}, {Decimal('150.00')})
        # The Demos count in October, their conversions in November; each month adds up to its entries.
        months = {row['month']: row for row in summaries.tutor_earnings(self.tutor)['months_breakdown']}
        self.assertEqual((months['2026-10']['earned'], months['2026-10']['demo'], months['2026-10']['conversions']),
                         ('400.00', 2, 0))
        self.assertEqual((months['2026-11']['earned'], months['2026-11']['demo'], months['2026-11']['conversions'],
                          months['2026-11']['conversion_earned'], months['2026-11']['classes']),
                         ('300.00', 0, 2, '300.00', 0))
        november = summaries.tutor_earnings(self.tutor, month=date(2026, 11, 1))['summary']
        self.assertEqual((november['earned'], november['conversions'], november['classes']), ('300.00', 2, 0))

    def test_the_demo_tutor_is_paid_whoever_teaches_the_student_after_the_enrollment(self):
        demo = self.demo()
        self.price()
        sale = self.enroll(demo.lead, demo.slot.ends_at + timedelta(days=3), tutor=self.other_tutor)
        Student.objects.filter(pk=sale.student_id).update(tutor=self.other_tutor)
        ledger.reconcile()
        self.assertEqual(self.converted().get().tutor, self.tutor)
        self.assertFalse(EarningEntry.objects.filter(tutor=self.other_tutor).exists())

    def test_a_lead_with_a_re_demo_converts_once_for_the_last_demo_taught_before_the_enrollment(self):
        original = self.demo()
        redemo = request_redemo(original, REASON, actor=self.admin, now=AFTER)
        again = complete(schedule_redemo(redemo, self.other_tutor, REDEMO_DAY, EVENING, actor=self.admin, now=AFTER),
                         self.other_tutor)
        self.price()
        ledger.reconcile()
        self.assertEqual(self.demo_earning(original).amount, self.demo_earning(again).amount)
        self.enroll(original.lead, again.slot.ends_at + timedelta(hours=2))
        for _ in range(3):
            ledger.reconcile()
        conversion = self.converted().get()
        self.assertEqual((conversion.tutor, conversion.converts.source_id), (self.other_tutor, again.pk))
        self.assertTrue(conversion.details['is_redemo'])
        self.assertEqual(self.earned(self.tutor), Decimal('200.00'))

    def test_an_enrollment_before_the_re_demo_was_taught_converts_the_original_demo(self):
        original = self.demo()
        redemo = request_redemo(original, REASON, actor=self.admin, now=AFTER)
        scheduled = schedule_redemo(redemo, self.other_tutor, REDEMO_DAY, EVENING, actor=self.admin, now=AFTER)
        self.price()
        self.enroll(original.lead, AFTER + timedelta(hours=1))
        # The Re-Demo is taught after the enrollment: it never converts.
        complete(scheduled, self.other_tutor)
        ledger.reconcile()
        self.assertEqual(self.converted().get().converts.source_id, original.pk)
        self.assertEqual(self.converted().get().tutor, self.tutor)

    def test_the_last_demo_waiting_for_its_report_holds_the_conversion_and_never_pays_an_earlier_one(self):
        original = self.demo()
        redemo = request_redemo(original, REASON, actor=self.admin, now=AFTER)
        again = start(schedule_redemo(redemo, self.other_tutor, REDEMO_DAY, EVENING, actor=self.admin, now=AFTER))
        self.price()
        # Enrolled while the Re-Demo was under way: its report is still to come.
        self.enroll(original.lead, again.slot.starts_at + timedelta(minutes=20))
        ledger.reconcile()
        self.assertFalse(self.converted().exists())
        waiting = [item for item in summaries.not_counted(self.other_tutor) if item['class_type'] == CONVERSION]
        self.assertEqual([(item['reason'], item['is_redemo']) for item in waiting], [('WAITING_FOR_DEMO', True)])
        self.assertFalse([item for item in summaries.not_counted(self.tutor) if item['class_type'] == CONVERSION])
        self.assertEqual(summaries.not_counted_counts()['WAITING_FOR_DEMO'], 1)
        submit_report(again, self.other_tutor, report_input(again), now=again.slot.starts_at + timedelta(minutes=50))
        ledger.reconcile()
        self.assertEqual(self.converted().get().tutor, self.other_tutor)
        self.assertEqual(summaries.not_counted_counts()['WAITING_FOR_DEMO'], 0)

    def test_a_last_demo_cancelled_as_a_no_show_leaves_the_conversion_to_the_demo_before_it(self):
        original = self.demo()
        redemo = request_redemo(original, REASON, actor=self.admin, now=AFTER)
        again = start(schedule_redemo(redemo, self.other_tutor, REDEMO_DAY, EVENING, actor=self.admin, now=AFTER))
        cancel_booking(again, reason_code=CancelReason.NO_SHOW, actor=self.admin,
                       now=again.slot.starts_at + timedelta(minutes=30))
        self.price()
        self.enroll(original.lead, again.slot.ends_at + timedelta(days=1))
        ledger.reconcile()
        self.assertEqual(self.converted().get().tutor, self.tutor)

    def test_a_demo_that_never_counted_never_converts_and_is_not_listed(self):
        before = self.demo()
        reversed_demo = self.demo(student='Ali', phone='0507654321', day=DAY + timedelta(days=1))
        # The first Demo's slot ended before Tutor Earnings was activated.
        TutorEarningsActivation.objects.update(activated_at=before.slot.ends_at + timedelta(seconds=1))
        self.price()
        ledger.reconcile()
        corrections.reverse_entry(self.admin, self.demo_earning(reversed_demo).pk, {'reason': 'Not taught as booked'})
        self.enroll(before.lead, before.slot.ends_at + timedelta(days=2))
        self.enroll(reversed_demo.lead, reversed_demo.slot.ends_at + timedelta(days=2))
        run = ledger.reconcile()
        self.assertFalse(self.converted().exists())
        self.assertEqual(run.skipped_count, 0)
        self.assertEqual({item.state for item in conversions.pending(rates.RateBook.load())}, {conversions.NOT_ELIGIBLE})
        self.assertFalse([item for item in summaries.not_counted(self.tutor) if item['class_type'] == CONVERSION])

    def test_an_enrollment_with_no_demo_started_before_it_is_not_a_conversion(self):
        later = self.demo(day=DAY + timedelta(days=2))
        self.price()
        # Enrolled before the Demo was taught; and a lead that never had a Demo.
        self.enroll(later.lead, later.slot.starts_at - timedelta(days=1))
        unrelated = Lead.objects.create(parent_name='P', phone_dial_code='+971', phone_number='509999999',
                                        phone_key='+971509999999', student_name='Zara', student_name_key='zara',
                                        school_name='S', grade='Class 7', syllabus='CBSE')
        self.enroll(unrelated, later.slot.ends_at + timedelta(days=1))
        ledger.reconcile()
        self.assertTrue(EarningEntry.objects.filter(class_type=ClassType.DEMO, source_id=later.pk).exists())
        self.assertFalse(self.converted().exists())
        self.assertEqual(conversions.pending(rates.RateBook.load()), [])


class ConversionOnceTests(ConversionWorld):
    def setUp(self):
        super().setUp()
        self.first = self.demo()
        self.second = self.demo(student='Ali', phone='0507654321', at=MORNING)
        self.price()
        self.sale = self.enroll(self.first.lead, self.first.slot.ends_at + timedelta(days=1))
        ledger.reconcile()
        self.conversion = self.converted().get()

    def copy(self, **changes):
        """The conversion as a new row, with ``changes``: what a second write would insert."""
        row = EarningEntry.objects.get(pk=self.conversion.pk)
        row.pk, row.sync_run = uuid.uuid4(), None
        for name, value in changes.items():
            setattr(row, name, value)
        return row

    def assert_refused(self, row, error=IntegrityError):
        with self.assertRaises(error), transaction.atomic():
            row.save(force_insert=True)

    def test_the_dry_run_reports_the_conversions_it_would_add(self):
        from io import StringIO

        from django.core.management import call_command
        demo = self.demo(student='Kabir', phone='0503333333', day=DAY + timedelta(days=2))
        ledger.reconcile()
        self.enroll(demo.lead, demo.slot.ends_at + timedelta(days=1))
        out = StringIO()
        call_command('reconcile_tutor_earnings', '--dry-run', stdout=out)
        self.assertIn('Would add 1 Demo conversion(s) for Demos already earned', out.getvalue())
        self.assertFalse(self.converted(source_id__in=Sale.objects.filter(enquiry=demo.lead).values('pk')).exists())

    def test_repeated_sync_runs_change_nothing(self):
        for _ in range(3):
            run = ledger.reconcile()
            self.assertEqual((run.earned_count, run.skipped_count), (0, 0))
        self.assertEqual(self.converted().count(), 1)
        self.assertEqual(self.earned(self.tutor), Decimal('550.00'))

    def test_the_database_refuses_a_second_conversion_of_an_enrollment_or_of_a_demo(self):
        second_earning = self.demo_earning(self.second)
        # The same enrollment again, through another Demo earning.
        self.assert_refused(self.copy(converts=second_earning))
        # The same Demo again, for another enrollment.
        self.assert_refused(self.copy(source_id=uuid.uuid4()))
        self.assertEqual(self.converted().count(), 1)

    def test_the_database_refuses_a_conversion_that_is_not_the_difference(self):
        second_earning = self.demo_earning(self.second)
        other = {'source_id': uuid.uuid4(), 'converts': second_earning}
        # The conversion rate on top of the Demo's ₹200 -- ₹350 more -- is refused.
        self.assert_refused(self.copy(amount=Decimal('350.00'), **other), DatabaseError)
        # So is topping up another tutor's Demo, or anything but a Demo earning.
        self.assert_refused(self.copy(tutor=self.other_tutor, **other), DatabaseError)
        self.assert_refused(self.copy(source_id=uuid.uuid4(), converts=self.conversion), DatabaseError)
        # A conversion with no Demo earning, or one unit too many, breaks its shape.
        self.assert_refused(self.copy(source_id=uuid.uuid4(), converts=None))
        self.assert_refused(self.copy(units=Decimal('2.00'), **other))
        # The difference itself is accepted.
        self.copy(**other).save(force_insert=True)

    def test_a_reversed_demo_earning_puts_its_conversion_up_for_review_and_it_is_never_written_again(self):
        demo_earning = self.demo_earning(self.first)
        corrections.reverse_entry(self.admin, demo_earning.pk, {'reason': 'Taught by someone else'})
        [item] = summaries.review_items()
        self.assertEqual((item['problem'], item['entry']['id'], item['entry']['class_type']),
                         ('DEMO_EARNING_REVERSED', str(self.conversion.pk), CONVERSION))
        # Keeping it as earned settles it; reversing it would too.
        corrections.keep_entry(self.admin, self.conversion.pk, {'reason': 'The student enrolled on this Demo',
                                                                 'seen': summaries.seen(item)})
        self.assertEqual(summaries.review_items(), [])
        corrections.reverse_entry(self.admin, self.conversion.pk, {'reason': 'Its Demo did not count after all'})
        for _ in range(2):
            ledger.reconcile()
        self.assertEqual(self.converted().count(), 1)
        self.assertEqual(self.earned(self.tutor), Decimal('200.00'))  # the second Demo only

    def test_a_demo_earning_shows_its_conversion_in_the_ledger(self):
        rows = {row['id']: row for row in (summaries.entry_row(entry, admin=False)
                                           for entry in summaries.entries_page(self.tutor))}
        demo_row = rows[str(self.demo_earning(self.first).pk)]
        self.assertEqual((demo_row['conversion']['id'], demo_row['conversion']['amount'], demo_row['conversion']['reversed']),
                         (str(self.conversion.pk), '150.00', False))
        conversion_row = rows[str(self.conversion.pk)]
        self.assertEqual((conversion_row['class_type'], conversion_row['unit'], conversion_row['rate'],
                          conversion_row['amount'], conversion_row['converts_id']),
                         (CONVERSION, 'CONVERSION', '350.00', '150.00', str(self.conversion.converts_id)))
        self.assertIsNone(rows[str(self.demo_earning(self.second).pk)]['conversion'])


class ConversionRateTests(ConversionWorld):
    def test_initial_pricing_needs_a_conversion_rate_at_least_the_demo_rate(self):
        missing = {key: value for key, value in GLOBAL.items() if key != 'DEMO_CONVERSION'}
        exc = self.refusal(lambda: rates.start_pricing(self.admin, {'global': missing, 'confirm': True}))
        self.assertEqual(exc.code, rates.INVALID_RATE)
        exc = self.refusal(lambda: self.price(DEMO_CONVERSION='150'))
        self.assertEqual((exc.code, exc.extra['field']), (rates.INVALID_RATE, 'rates.DEMO_CONVERSION'))
        self.assertIn('at least the Demo rate', exc.message)
        exc = self.refusal(lambda: self.price(tutors=[{'tutor': str(self.tutor.pk), 'rates': {'DEMO': '400'}}]))
        self.assertIn('Abhiram', exc.message)
        self.assertFalse(EarningsRate.objects.exists())
        # Equal pays no incentive, but is allowed.
        self.price(DEMO_CONVERSION='200')
        self.assertEqual(EarningsRate.objects.filter(class_type=CONVERSION).get().amount, Decimal('200.00'))

    def test_a_change_leaving_a_conversion_rate_below_its_demo_rate_is_refused(self):
        self.price(tutors=[{'tutor': str(self.other_tutor.pk), 'rates': {'DEMO': '300'}}])
        for change in ({'DEMO_CONVERSION': '150'}, {'DEMO': '400'}):
            with self.subTest(change=change):
                exc = self.refusal(lambda: rates.set_global_rates(self.admin, {'rates': change, 'reason': 'Revision'}))
                self.assertEqual(exc.code, rates.INVALID_RATE)
        # Above the global Demo rate, but below the other tutor's own Demo rate.
        exc = self.refusal(lambda: rates.set_global_rates(self.admin, {'rates': {'DEMO_CONVERSION': '250'},
                                                                       'reason': 'Revision'}))
        self.assertIn('Tutor After', exc.message)
        exc = self.refusal(lambda: rates.set_tutor_rates(self.admin, self.tutor, {'rates': {'DEMO': '400'},
                                                                                   'reason': 'Senior'}))
        self.assertIn('Abhiram', exc.message)
        exc = self.refusal(lambda: rates.set_tutor_rates(self.admin, self.tutor, {'rates': {'DEMO_CONVERSION': '150'},
                                                                                   'reason': 'Senior'}))
        self.assertEqual(exc.code, rates.INVALID_RATE)
        # Both together, equal or above: accepted.
        rates.set_tutor_rates(self.admin, self.tutor, {'rates': {'DEMO': '400', 'DEMO_CONVERSION': '400'},
                                                       'reason': 'Senior'})
        # A change that touches neither rate is not compared.
        rates.set_global_rates(self.admin, {'rates': {'SESSION': '450'}, 'reason': 'Revision'})
        self.assertEqual(EarningsRate.objects.filter(class_type=CONVERSION).count(), 2)

    def test_a_former_tutors_own_demo_rate_never_blocks_a_global_conversion_rate(self):
        # Their rates can no longer be edited (they are not a tutor now), so they must not block the global one.
        self.price(tutors=[{'tutor': str(self.other_tutor.pk), 'rates': {'DEMO': '300'}}])
        type(self.other_tutor).objects.filter(pk=self.other_tutor.pk).update(role='MENTOR')
        rates.set_global_rates(self.admin, {'rates': {'DEMO_CONVERSION': '250'}, 'reason': 'Revision'})
        self.assertEqual(rates.RateBook.load().resolve(None, CONVERSION, timezone.now())[0].amount, Decimal('250.00'))

    def test_a_tutors_own_conversion_rate_takes_the_global_ones_place(self):
        # Abhiram: Demo ₹200 (his own), Demo Conversion ₹400 (his own): converted, he earns ₹200 more.
        mine = self.demo()
        theirs = self.demo(student='Ali', phone='0507654321', at=MORNING, tutor=self.other_tutor)
        self.price(tutors=[{'tutor': str(self.tutor.pk), 'rates': {'DEMO': '200', 'DEMO_CONVERSION': '400'}}])
        self.enroll(mine.lead, mine.slot.ends_at + timedelta(days=1))
        self.enroll(theirs.lead, theirs.slot.ends_at + timedelta(days=1))
        ledger.reconcile()
        by_tutor = {entry.tutor_id: entry for entry in self.converted()}
        self.assertEqual((by_tutor[self.tutor.pk].rate, by_tutor[self.tutor.pk].amount, by_tutor[self.tutor.pk].rate_source),
                         (Decimal('400.00'), Decimal('200.00'), RateSource.TUTOR))
        other = by_tutor[self.other_tutor.pk]
        self.assertEqual((other.rate, other.amount, other.rate_source), (Decimal('350.00'), Decimal('150.00'), RateSource.GLOBAL))
        self.assertEqual(self.earned(self.tutor), Decimal('400.00'))

    def test_the_rate_in_effect_when_the_student_enrolls_prices_it_and_later_changes_never_reprice_it(self):
        demo = self.demo()
        self.price()
        ledger.reconcile()  # The Demo earns ₹200, the Demo rate at its end.
        # Between the Demo and the enrollment both global rates change.
        with clock(india(2026, 11, 2, 12)):
            rates.set_global_rates(self.admin, {'rates': {'DEMO': '250', 'DEMO_CONVERSION': '400'}, 'reason': 'Revision'})
        self.enroll(demo.lead, india(2026, 11, 5, 12))
        ledger.reconcile()
        conversion = self.converted().get()
        # ₹400 in all, the Demo keeping the ₹200 it earned: ₹200 more.
        self.assertEqual((conversion.rate, conversion.amount), (Decimal('400.00'), Decimal('200.00')))
        self.assertEqual(self.demo_earning(demo).amount, Decimal('200.00'))
        # A later change never reprices it; a later enrollment takes the new rate.
        with clock(india(2026, 11, 8, 12)):
            rates.set_global_rates(self.admin, {'rates': {'DEMO_CONVERSION': '500'}, 'reason': 'Revision'})
        later = self.demo(student='Ali', phone='0507654321', at=MORNING)
        ledger.reconcile()
        self.enroll(later.lead, india(2026, 11, 9, 12))
        ledger.reconcile()
        self.assertEqual(EarningEntry.objects.get(pk=conversion.pk).amount, Decimal('200.00'))
        newer = self.converted(converts__source_id=later.pk).get()
        self.assertEqual((newer.rate, newer.amount, newer.rate_version.effective_from),
                         (Decimal('500.00'), Decimal('300.00'), india(2026, 11, 8, 12)))

    def test_a_tutors_own_conversion_rate_applies_from_when_it_is_saved_until_it_goes_back_to_the_global_one(self):
        demos = [self.demo(student=name, phone=phone, day=DAY + timedelta(days=offset))
                 for offset, (name, phone) in enumerate((('Riya', '0501234567'), ('Ali', '0507654321'),
                                                         ('Sara', '0505555555')))]
        self.price()
        ledger.reconcile()
        with clock(india(2026, 11, 2, 12)):
            rates.set_tutor_rates(self.admin, self.tutor, {'rates': {'DEMO_CONVERSION': '500'}, 'reason': 'Senior'})
        with clock(india(2026, 11, 6, 12)):
            rates.set_tutor_rates(self.admin, self.tutor, {'rates': {'DEMO_CONVERSION': None}, 'reason': 'Back'})
        for demo, when in zip(demos, (india(2026, 11, 1, 12), india(2026, 11, 3, 12), india(2026, 11, 7, 12))):
            self.enroll(demo.lead, when)
        ledger.reconcile()
        found = [(entry.rate, entry.amount, entry.rate_source)
                 for entry in sorted(self.converted(), key=lambda entry: entry.details['converted_at'])]
        self.assertEqual(found, [(Decimal('350.00'), Decimal('150.00'), RateSource.GLOBAL),
                                 (Decimal('500.00'), Decimal('300.00'), RateSource.TUTOR),
                                 (Decimal('350.00'), Decimal('150.00'), RateSource.GLOBAL)])

    def test_an_enrollment_before_any_conversion_rate_was_in_effect_is_never_paid(self):
        # Pricing started before Demo Conversion existed: the three class rates only.
        EarningsRate.objects.bulk_create([
            EarningsRate(class_type=class_type, amount=Decimal(amount), effective_from=ACTIVATED, initial=True,
                         reason='Initial rates', created_by=self.admin)
            for class_type, amount in (('DIAGNOSTIC', '300'), ('DEMO', '200'), ('SESSION', '400'))
        ])
        TutorEarningsPricing.objects.create(started_at=ACTIVATED, started_by=self.admin)
        early, late = self.demo(), self.demo(student='Ali', phone='0507654321', at=MORNING)
        self.enroll(early.lead, india(2026, 10, 30, 12))
        run = ledger.reconcile()
        self.assertEqual((run.earned_count, run.skipped_count), (2, 0))
        self.assertFalse(self.converted().exists())
        with clock(india(2026, 11, 1, 12)):
            rates.set_global_rates(self.admin, {'rates': {'DEMO_CONVERSION': '350'}, 'reason': 'Conversion incentive'})
        self.enroll(late.lead, india(2026, 11, 2, 12))
        ledger.reconcile()
        self.assertEqual([entry.converts.source_id for entry in self.converted()], [late.pk])

    def test_a_conversion_rate_not_above_what_the_demo_earned_pays_nothing(self):
        demo = self.demo()
        self.price(tutors=[{'tutor': str(self.tutor.pk), 'rates': {'DEMO': '400', 'DEMO_CONVERSION': '400'}}])
        ledger.reconcile()  # His own Demo rate: ₹400.
        # By the enrollment he is back on the global rates: a ₹350 conversion, below the ₹400 the Demo earned.
        with clock(india(2026, 11, 2, 12)):
            rates.set_tutor_rates(self.admin, self.tutor, {'rates': {'DEMO': None, 'DEMO_CONVERSION': None},
                                                           'reason': 'Back to global'})
        self.enroll(demo.lead, india(2026, 11, 3, 12))
        run = ledger.reconcile()
        self.assertFalse(self.converted().exists())
        self.assertEqual(run.skipped_count, 1)
        self.assertEqual(self.demo_earning(demo).amount, Decimal('400.00'))


class ConversionSummaryTests(ConversionWorld):
    def setUp(self):
        super().setUp()
        self.first = self.demo()
        self.second = self.demo(student='Ali', phone='0507654321', at=MORNING)
        self.price()
        ledger.reconcile()
        # Paid ₹100 before the student converted.
        self.payment, _created = payments.record_payment(self.admin, self.tutor, {
            'request_id': str(uuid.uuid4()), 'amount': '100', 'paid_on': india_today().isoformat(),
            'method': 'UPI', 'reference': 'UPI CONV 1'})
        self.sale = self.enroll(self.first.lead, india(2026, 11, 4, 12))
        ledger.reconcile()

    def test_conversions_count_in_every_total_without_counting_the_demo_twice(self):
        data = summaries.tutor_earnings(self.tutor)
        summary = data['summary']
        self.assertEqual(
            (summary['earned'], summary['paid'], summary['outstanding'], summary['balance_state'], summary['classes'],
             summary['demo'], summary['conversions'], summary['demo_earned'], summary['conversion_earned']),
            ('550.00', '100.00', '450.00', 'pending', 2, 2, 1, '400.00', '150.00'),
        )
        row = next(row for row in data['breakdown'] if row['class_type'] == CONVERSION)
        self.assertEqual((row['unit'], row['classes'], row['units'], row['amount']), ('CONVERSION', 1, '1.00', '150.00'))
        self.assertEqual(row['lines'], [{'rate': '350.00', 'classes': 1, 'units': '1.00', 'amount': '150.00',
                                         'rate_source': 'GLOBAL'}])
        self.assertEqual(sum(row['classes'] for row in data['breakdown'] if row['class_type'] != CONVERSION), 2)
        rates_now = {row['class_type']: row for row in data['rates']}
        self.assertEqual((rates_now[CONVERSION]['amount'], rates_now[CONVERSION]['unit']), ('350.00', 'CONVERSION'))
        overview = summaries.overview()
        totals = overview['totals']
        self.assertEqual((totals['earned'], totals['pending'], totals['classes'], totals['demo'], totals['conversions'],
                          totals['demo_earned'], totals['conversion_earned']),
                         ('550.00', '450.00', 2, 2, 1, '400.00', '150.00'))
        row = next(row for row in overview['tutors'] if row['id'] == str(self.tutor.pk))
        self.assertEqual((row['conversions'], row['outstanding']), (1, '450.00'))
        # The payment is as it was recorded.
        self.assertEqual(TutorPayment.objects.get(pk=self.payment.pk).amount, Decimal('100.00'))
        self.assertEqual(payments.outstanding(self.tutor.pk), Decimal('450.00'))

    def test_the_months_add_up_to_the_ledger(self):
        october = summaries.tutor_earnings(self.tutor, month=date(2026, 10, 1))['summary']
        november = summaries.tutor_earnings(self.tutor, month=date(2026, 11, 1))['summary']
        self.assertEqual((october['earned'], october['conversions'], november['earned'], november['conversions']),
                         ('400.00', 0, '150.00', 1))
        months = summaries.tutor_earnings(self.tutor)['months_breakdown']
        self.assertEqual(sum(Decimal(row['earned']) for row in months), self.earned(self.tutor))

    def test_a_tutor_reads_their_conversion_and_an_administrator_its_rate_source(self):
        client = APIClient()
        client.force_authenticate(self.tutor)
        mine = client.get('/api/earnings/me/')
        self.assertEqual(mine.status_code, 200, mine.data)
        self.assertEqual((mine.data['summary']['conversions'], mine.data['summary']['conversion_earned']), (1, '150.00'))
        ledger_page = client.get('/api/earnings/me/entries/', {'class_type': CONVERSION})
        [row] = ledger_page.data['results']
        self.assertEqual((row['amount'], row['details']['final_amount']), ('150.00', '350.00'))
        self.assertNotIn('rate_source', row)
        client.force_authenticate(self.admin)
        detail = client.get(f'/api/earnings/tutors/{self.tutor.pk}/entries/', {'class_type': CONVERSION})
        self.assertEqual(detail.data['results'][0]['rate_source'], 'GLOBAL')
        rates_page = client.get('/api/earnings/rates/')
        self.assertIn(CONVERSION, [row['class_type'] for row in rates_page.data['rates']])


class RealEnrollmentTests(ConversionWorld):
    """The enrollment as sales makes it: a verified payment enrolls once, however often it is repeated."""

    def test_a_verified_payment_that_enrolls_converts_once_however_often_it_is_replayed(self):
        from sales import enrollment, payments as sales_payments
        from sales.payment_models import Payment, Purchase
        from sales.tests_payments import InitialPaymentTests

        demo = self.demo()
        self.price()
        # The sales tests' own world: a published Bridge Course, its pricing, a BDE and a receipt upload.
        world = InitialPaymentTests(methodName='run')
        world.client = world.client_class()
        world.setUp()
        self.addCleanup(world.tmp.cleanup)
        self.addCleanup(world.storage.disable)
        lead = demo.lead
        Lead.objects.filter(pk=lead.pk).update(owner_bde=world.bde, owner_assigned_at=timezone.now())
        from sales import quotes
        quotes.create_quote(world.bde, {'collection_mode': 'PARTIAL', 'syllabus': world.bridge.pk, 'revision': 1,
                                        'plan_type': 'BRIDGE_COURSE', 'lead': lead.pk})
        world.lead = lead
        self.assertEqual(world.start().status_code, 201)
        response = world.collect()
        self.assertEqual(response.status_code, 201, response.content)
        sale = Sale.objects.get(enquiry=lead)
        self.assertIsNotNone(sale.enrolled_at)
        ledger.reconcile()
        # The payment's success and the enrollment again, as a replayed webhook or a retried job would ask.
        payment = Payment.objects.get(sale=sale)
        sales_payments.succeed(payment)
        enrollment.enroll(sale, Purchase.objects.get(sale=sale), world.bde)
        for _ in range(2):
            ledger.reconcile()
        conversion = self.converted().get()
        self.assertEqual((conversion.source_id, conversion.tutor, conversion.amount), (sale.pk, self.tutor, Decimal('150.00')))
        self.assertEqual(conversion.month, month_of(sale.enrolled_at))


class ConversionMigrationTests(TransactionTestCase):
    """
    earnings.0003 adds Demo Conversion without touching a row, and reverses
    cleanly while no Demo Conversion rate or earning exists -- and refuses to
    while one does, rather than drop them.
    """

    LATEST = [('earnings', '0003_demo_conversion')]
    BEFORE = [('earnings', '0002_rates_ledger_payments')]

    def rate(self, class_type):
        admin = person(f'migration_admin_{class_type.lower()}', role='ADMIN')
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO tutor_earnings_rates (id, class_type, tutor_id, amount, currency, effective_from, initial, "
                "reason, created_by_id, created_at) VALUES (%s, %s, NULL, 350, 'INR', now(), false, 'x', %s, now())",
                [uuid.uuid4(), class_type, admin.pk],
            )

    def test_it_reverses_and_reapplies_while_nothing_uses_it(self):
        try:
            MigrationExecutor(connection).migrate(self.BEFORE)
            # Before it, the database knows no Demo Conversion.
            with self.assertRaises(IntegrityError), transaction.atomic():
                self.rate('DEMO_CONVERSION')
        finally:
            MigrationExecutor(connection).migrate(self.LATEST)
        self.rate('DEMO_CONVERSION')
        self.assertTrue(EarningsRate.objects.filter(class_type=CONVERSION).exists())

    def test_it_refuses_to_reverse_while_a_conversion_rate_exists(self):
        self.rate('DEMO_CONVERSION')
        try:
            with self.assertRaises(DatabaseError):
                MigrationExecutor(connection).migrate(self.BEFORE)
        finally:
            MigrationExecutor(connection).migrate(self.LATEST)
        self.assertTrue(EarningsRate.objects.filter(class_type=CONVERSION).exists())


class ConversionVisibilityTests(ConversionWorld):
    """
    The authorization matrix for Demo conversions, on real earnings data (the
    core matrix world has none): every caller on every earnings read, which of
    them reaches a conversion at all, and which nested fields each one sees --
    an administrator the provenance (rate source, who wrote it), a tutor their
    own conversions only and without it, anyone else nothing.
    """

    # What a Demo Conversion earning records about itself, as an administrator reads it ...
    CONVERSION_DETAILS = {
        'sale_id', 'lead_id', 'student_id', 'student_code', 'student_name', 'converted_at', 'demo_booking_id',
        'demo_entry_id', 'demo_started_at', 'is_redemo', 'demo_amount', 'demo_rate', 'conversion_rate', 'incentive',
        'final_amount', 'activated_at',
    }
    # ... and as its tutor does: everything but the enrollment's sale.
    TUTOR_CONVERSION_DETAILS = CONVERSION_DETAILS - {'sale_id'}
    # A Demo earning's link to its conversion.
    CONVERSION_LINK = {'id', 'amount', 'month', 'converted_at', 'reversed'}
    # Fields of one tutor's earnings that only an administrator reads (earnings.summaries.tutor_earnings).
    ADMIN_ONLY = ('own_rates', 'rate_history', 'review', 'pricing.started_by', 'last_sync.status',
                  'last_sync.earned_count', 'last_sync.waiting_count', 'breakdown[].lines[].rate_source',
                  'rates[].source', 'rates[].global_amount', 'rates[].effective_from')
    # ... and of a ledger row (earnings.summaries.entry_row).
    ADMIN_ONLY_ROWS = ('results[].rate_source', 'results[].created_by', 'results[].reversal.created_by',
                       'results[].details.sale_id')

    def setUp(self):
        super().setUp()
        self.mentor = person('mentor_visibility', role='MENTOR')
        self.student_user = person('student_visibility', role='STUDENT')
        self.superuser = person('superuser_visibility', role='ADMIN', is_superuser=True, is_staff=True)
        self.price()
        converted = self.demo()
        reversed_demo = self.demo(student='Ali', phone='0507654321', at=MORNING)
        theirs = self.demo(student='Zoya', phone='0508888888', day=DAY + timedelta(days=1), at=MORNING,
                           tutor=self.other_tutor)
        self.sales = [self.enroll(converted.lead, converted.slot.ends_at + timedelta(days=1)),
                      self.enroll(reversed_demo.lead, reversed_demo.slot.ends_at + timedelta(days=1))]
        ledger.reconcile()
        # One conversion stands; the other's Demo earning is reversed afterwards, so it is up for review.
        corrections.reverse_entry(self.admin, self.demo_earning(reversed_demo).pk, {'reason': 'Not taught as booked'})
        # A third enrolled while its Demo's report is still due: waiting for its Demo.
        waiting = self.demo(student='Sara', phone='0505555555', day=DAY + timedelta(days=1), report=False)
        self.sales.append(self.enroll(waiting.lead, waiting.slot.starts_at + timedelta(minutes=20)))
        ledger.reconcile()
        self.assertEqual(self.converted(tutor=self.tutor).count(), 2)
        self.assertTrue(self.demo_earning(theirs))

    def get(self, user, name, *args):
        client = APIClient()
        if user is not None:
            client.force_authenticate(user)
        return client.get(reverse(f'earnings:{name}', args=args))

    def paths(self, data):
        from core.authz_matrix import _field_paths
        return _field_paths(data)

    def without(self, paths, prefixes):
        return {path for path in paths if not any(path == p or path.startswith(f'{p}.') or path.startswith(f'{p}[')
                                                  for p in prefixes)}

    def test_who_reaches_the_earnings_that_hold_conversions(self):
        tutor = str(self.tutor.pk)
        admin_reads = [('overview',), ('review',), ('tutor', tutor), ('tutor-entries', tutor)]
        own_reads = [('me',), ('me-entries',)]
        expected = {
            'admin': (200, 403), 'superuser': (200, 200), 'tutor': (403, 200), 'other_tutor': (403, 200),
            'mentor': (403, 403), 'bde': (403, 403), 'student': (403, 403), 'anonymous': (403, 403),
        }
        callers = {'admin': self.admin, 'superuser': self.superuser, 'tutor': self.tutor,
                   'other_tutor': self.other_tutor, 'mentor': self.mentor, 'bde': self.bde,
                   'student': self.student_user, 'anonymous': None}
        for caller, user in callers.items():
            for reads, status in zip((admin_reads, own_reads), expected[caller]):
                for read in reads:
                    with self.subTest(caller=caller, read=read[0]):
                        self.assertEqual(self.get(user, *read).status_code, status)

    def test_an_administrator_reads_every_conversion_field_with_its_provenance(self):
        rows = self.get(self.admin, 'tutor-entries', str(self.tutor.pk)).data['results']
        conversions = [row for row in rows if row['class_type'] == CONVERSION]
        self.assertEqual(len(conversions), 2)
        sale_ids = {str(sale.pk) for sale in self.sales}
        for row in conversions:
            self.assertEqual(set(row['details']), self.CONVERSION_DETAILS)
            # An administrator reads the enrollment's sale: the row's source and in its details.
            self.assertIn(row['source_id'], sale_ids)
            self.assertEqual(row['details']['sale_id'], row['source_id'])
            self.assertIn(row['rate_source'], ('GLOBAL', 'TUTOR'))
            self.assertIn('created_by', row)
            self.assertIsNotNone(row['converts_id'])
        demos = [row for row in rows if row['class_type'] == ClassType.DEMO and row['kind'] == 'EARNING']
        self.assertEqual([set(row['conversion']) for row in demos], [self.CONVERSION_LINK] * 2)
        [item] = self.get(self.admin, 'review').data['items']
        self.assertEqual((item['problem'], set(item['current']), item['entry']['class_type']),
                         ('DEMO_EARNING_REVERSED', {'demo_entry_id', 'demo_reversed'}, CONVERSION))
        page = self.get(self.admin, 'tutor', str(self.tutor.pk)).data
        line = next(row for row in page['breakdown'] if row['class_type'] == CONVERSION)['lines'][0]
        self.assertIn('rate_source', line)
        self.assertEqual([entry['problem'] for entry in page['review']], ['DEMO_EARNING_REVERSED'])
        waiting = [entry for entry in page['not_counted'] if entry['class_type'] == CONVERSION]
        self.assertEqual([(entry['reason'], entry['source_id']) for entry in waiting],
                         [('WAITING_FOR_DEMO', str(self.sales[2].pk))])

    def test_a_tutor_reads_their_own_conversions_as_an_administrator_does_less_the_provenance(self):
        tutor = str(self.tutor.pk)
        mine, theirs = self.get(self.tutor, 'me').data, self.get(self.admin, 'tutor', tutor).data
        self.assertEqual(self.paths(mine), self.without(self.paths(theirs), self.ADMIN_ONLY))
        for field in ('own_rates', 'rate_history', 'review'):
            self.assertNotIn(field, mine)
        self.assertEqual((mine['summary']['conversions'], mine['summary']['conversion_earned']),
                         (theirs['summary']['conversions'], theirs['summary']['conversion_earned']))
        rows, admin_rows = self.get(self.tutor, 'me-entries').data, self.get(self.admin, 'tutor-entries', tutor).data
        self.assertEqual(self.paths(rows), self.without(self.paths(admin_rows), self.ADMIN_ONLY_ROWS))
        self.assertEqual([row['id'] for row in rows['results']], [row['id'] for row in admin_rows['results']])
        for row in rows['results']:
            self.assertNotIn('rate_source', row)
            self.assertNotIn('created_by', row)
            if row['class_type'] == CONVERSION:
                self.assertEqual(set(row['details']), self.TUTOR_CONVERSION_DETAILS)
                self.assertIsNone(row['source_id'])
        self.assertEqual([(entry['reason'], entry['source_id']) for entry in mine['not_counted']
                          if entry['class_type'] == CONVERSION], [('WAITING_FOR_DEMO', None)])

    def test_no_other_caller_ever_reads_a_tutors_conversion(self):
        marks = [str(sale.pk) for sale in self.sales] + [sale.student.student_code for sale in self.sales]
        for user in (self.other_tutor, self.superuser):
            for name in ('me', 'me-entries'):
                with self.subTest(user=user.username, read=name):
                    response = self.get(user, name)
                    self.assertEqual(response.status_code, 200)
                    shown = json.dumps(response.data, default=str)
                    self.assertFalse([mark for mark in marks if mark in shown])
        mine = self.get(self.other_tutor, 'me').data
        self.assertEqual((mine['summary']['conversions'], mine['summary']['demo']), (0, 1))
        self.assertFalse([item for item in mine['not_counted'] if item['class_type'] == CONVERSION])

    def test_a_tutor_never_reads_a_sale_id_on_any_conversion_line(self):
        # Every line about a conversion: the conversion, its reversal, and an adjustment about it.
        # Ali's morning Demo, whose earning was reversed, converted first in the day; Riya's evening one stands.
        reviewed, standing = sorted(self.converted(tutor=self.tutor), key=lambda entry: entry.converts.class_start)
        self.assertEqual((reviewed.details['student_name'], standing.details['student_name']), ('Ali', 'Riya'))
        corrections.reverse_entry(self.admin, reviewed.pk, {'reason': 'Its Demo was reversed'})
        corrections.add_adjustment(self.admin, self.tutor, {'amount': '25', 'reason': 'Conversion bonus',
                                                            'entry': str(standing.pk)})
        sale_ids = [str(sale.pk) for sale in self.sales]
        lines = self.get(self.tutor, 'me-entries').data['results']
        kinds = sorted(row['kind'] for row in lines if row['class_type'] == CONVERSION)
        self.assertEqual(kinds, ['ADJUSTMENT', 'EARNING', 'EARNING', 'REVERSAL'])
        for row in lines:
            if row['class_type'] == CONVERSION:
                self.assertIsNone(row['source_id'])
                self.assertNotIn('sale_id', row['details'])
        for name in ('me', 'me-entries'):
            shown = json.dumps(self.get(self.tutor, name).data, default=str)
            self.assertFalse([sale_id for sale_id in sale_ids if sale_id in shown], name)
        # The students are still named for the tutor, by name and code.
        self.assertEqual({row['details']['student_code'] for row in lines
                          if row['kind'] == 'EARNING' and row['class_type'] == CONVERSION},
                         {self.sales[0].student.student_code, self.sales[1].student.student_code})
        # An administrator reads the sale on every one of those lines.
        admin_lines = self.get(self.admin, 'tutor-entries', str(self.tutor.pk)).data['results']
        self.assertTrue(all(row['source_id'] in sale_ids and row['details']['sale_id'] == row['source_id']
                            for row in admin_lines if row['class_type'] == CONVERSION))
