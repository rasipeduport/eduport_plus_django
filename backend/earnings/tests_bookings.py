"""
Which Diagnostic and Demo bookings count towards Tutor Earnings
(earnings.eligibility.eligible_bookings), and what the sync earns for them:
only a booking its assigned tutor started and reported on themselves, once its
slot has ended (a report in before the slot's end waits for it), and only for
a slot ending at or after the activation. A Re-Demo is a Demo booking of its
own and counts for its own tutor; a status -- Re-Demo required included -- is
never enough on its own.
"""
from datetime import datetime, timedelta
from decimal import Decimal

from django.test import TestCase

from bookings.booking_service import assign_tutor, cancel_booking, request_redemo, schedule_redemo
from bookings.models import BookingSlot, BookingStatus, CancelReason, DemoBooking, DiagnosticBooking
from bookings.scheduling import BOOKING_TIMEZONE
from bookings.tests_booking import DEMO, DIAGNOSTIC, EVENING, MORNING, NOW, account, book, schedule, start
from bookings.tests_redemos import AFTER, REASON, REDEMO_DAY, complete
from reports.services import submit_report
from reports.tests_services import report_input

from . import corrections, eligibility, ledger, rates, summaries
from .models import ClassType, EarningEntry, EntryKind, RateSource, TutorEarningsActivation

ACTIVATED = datetime(2026, 10, 1, tzinfo=BOOKING_TIMEZONE)


class BookingEarningsTests(TestCase):
    def setUp(self):
        schedule()
        TutorEarningsActivation.objects.update_or_create(id=1, defaults={'activated_at': ACTIVATED})
        self.admin = account('admin_earn', role='ADMIN')
        self.tutor = account('tutor_earn', role='TUTOR')
        self.other_tutor = account('tutor_redemo', role='TUTOR')

    def assigned(self, booking_type=DEMO, at=EVENING, student='Riya', phone='0501234567', tutor=None):
        booking = book(booking_type=booking_type, at=at, student=student, phone=phone)[0]
        return assign_tutor(booking, tutor or self.tutor, now=NOW)[0]

    def reported(self, booking, tutor=None):
        booking = start(booking)
        submit_report(booking, tutor or self.tutor, report_input(booking), now=booking.slot.starts_at + timedelta(minutes=50))
        return type(booking).objects.select_related('slot', 'report').get(pk=booking.pk)

    def eligible(self, model, now=None):
        return set(eligibility.eligible_bookings(model, now=now).values_list('pk', flat=True))

    def test_a_booking_its_tutor_started_and_reported_counts_once_its_slot_has_ended(self):
        diagnostic = self.reported(self.assigned(DIAGNOSTIC, at=MORNING))
        demo = self.reported(self.assigned(DEMO, student='Ali', phone='0507654321'))
        for booking, model in ((diagnostic, DiagnosticBooking), (demo, DemoBooking)):
            with self.subTest(booking_type=booking.booking_type):
                ends = booking.slot.ends_at
                # Reported 50 minutes into the slot: until the slot ends it does not count.
                self.assertEqual(self.eligible(model, now=ends - timedelta(minutes=10)), set())
                self.assertEqual(self.eligible(model, now=ends - timedelta(microseconds=1)), set())
                self.assertEqual(self.eligible(model, now=ends), {booking.pk})

    def test_a_booking_not_started_or_not_reported_never_counts(self):
        assigned = self.assigned()
        started_only = start(self.assigned(DEMO, at=MORNING, student='Ali', phone='0507654321'))
        self.assertEqual(self.eligible(DemoBooking), set())
        self.assertEqual(started_only.status, BookingStatus.BOOKED)
        self.assertIsNone(DemoBooking.objects.get(pk=assigned.pk).started_at)

    def test_a_no_show_or_cancelled_booking_never_counts(self):
        started = start(self.assigned())
        cancel_booking(started, reason_code=CancelReason.NO_SHOW, actor=self.admin,
                       now=started.slot.starts_at + timedelta(minutes=30))
        self.assertEqual(DemoBooking.objects.get(pk=started.pk).status, BookingStatus.CANCELLED)
        self.assertEqual(self.eligible(DemoBooking), set())

    def test_only_the_assigned_tutors_own_start_and_report_count(self):
        booking = self.reported(self.assigned())
        self.assertEqual(self.eligible(DemoBooking), {booking.pk})
        DemoBooking.objects.filter(pk=booking.pk).update(completed_by=self.other_tutor)
        self.assertEqual(self.eligible(DemoBooking), set())
        DemoBooking.objects.filter(pk=booking.pk).update(completed_by=self.tutor, started_by=self.other_tutor)
        self.assertEqual(self.eligible(DemoBooking), set())

    def test_a_slot_ending_before_the_activation_never_counts(self):
        booking = self.reported(self.assigned())
        TutorEarningsActivation.objects.update(activated_at=booking.slot.ends_at)
        self.assertEqual(self.eligible(DemoBooking), {booking.pk})
        TutorEarningsActivation.objects.update(activated_at=booking.slot.ends_at + timedelta(seconds=1))
        self.assertEqual(self.eligible(DemoBooking), set())

    def test_re_demo_required_alone_never_counts(self):
        # A Demo marked Re-Demo required with no start and no report (as a row from before Start could be).
        booking = self.assigned()
        DemoBooking.objects.filter(pk=booking.pk).update(
            status=BookingStatus.REDEMO_REQUIRED, completed_at=booking.slot.ends_at, completed_by=self.tutor,
        )
        self.assertEqual(self.eligible(DemoBooking), set())

    def test_a_demo_sent_for_a_re_demo_still_counts_and_its_re_demo_counts_for_its_own_tutor(self):
        original = self.reported(self.assigned())
        redemo = request_redemo(original, REASON, actor=self.admin, now=AFTER)
        self.assertEqual(DemoBooking.objects.get(pk=original.pk).status, BookingStatus.REDEMO_REQUIRED)
        again = schedule_redemo(redemo, self.other_tutor, REDEMO_DAY, EVENING, actor=self.admin, now=AFTER)
        # Scheduled but not taught yet: only the original counts.
        self.assertEqual(self.eligible(DemoBooking), {original.pk})
        again = complete(again, self.other_tutor)
        self.assertEqual(self.eligible(DemoBooking), {original.pk, again.pk})

        rates.start_pricing(self.admin, {'global': {'DIAGNOSTIC': '300', 'DEMO': '300', 'SESSION': '400'},
                                         'tutors': [{'tutor': str(self.other_tutor.pk), 'rates': {'DEMO': '350'}}],
                                         'confirm': True})
        ledger.reconcile()
        earnings = {entry.source_id: entry for entry in EarningEntry.objects.filter(kind=EntryKind.EARNING)}
        self.assertEqual(set(earnings), {original.pk, again.pk})
        first, second = earnings[original.pk], earnings[again.pk]
        self.assertEqual((first.tutor, first.amount, first.rate_source), (self.tutor, Decimal('300.00'), RateSource.GLOBAL))
        self.assertEqual((second.tutor, second.amount, second.rate_source), (self.other_tutor, Decimal('350.00'), RateSource.TUTOR))
        self.assertEqual((first.class_type, first.units), (ClassType.DEMO, Decimal('1.00')))
        self.assertTrue(second.details['is_redemo'])
        self.assertEqual(second.details['redemo_request_id'], str(redemo.pk))
        self.assertEqual((second.class_start, second.class_end), (again.slot.starts_at, again.slot.ends_at))

    def test_the_sync_earns_a_reported_booking_only_once_its_slot_has_ended(self):
        booking = self.reported(self.assigned(DIAGNOSTIC, at=MORNING))
        rates.start_pricing(self.admin, {'global': {'DIAGNOSTIC': '300', 'DEMO': '300', 'SESSION': '400'}, 'confirm': True})
        run = ledger.reconcile(now=booking.slot.ends_at - timedelta(minutes=5))
        self.assertEqual(run.earned_count, 0)
        run = ledger.reconcile(now=booking.slot.ends_at)
        self.assertEqual(run.earned_count, 1)
        earning = EarningEntry.objects.get(kind=EntryKind.EARNING)
        self.assertEqual((earning.class_type, earning.source_id, earning.amount), (ClassType.DIAGNOSTIC, booking.pk, Decimal('300.00')))
        self.assertEqual(earning.details['report_id'], str(booking.report.pk))
        self.assertEqual(ledger.reconcile(now=booking.slot.ends_at + timedelta(days=1)).earned_count, 0)

    def test_a_changed_booking_earning_is_reviewed_kept_and_a_re_demo_request_leaves_it_kept(self):
        original = self.reported(self.assigned())
        rates.start_pricing(self.admin, {'global': {'DIAGNOSTIC': '300', 'DEMO': '300', 'SESSION': '400'}, 'confirm': True})
        ledger.reconcile()
        earning = EarningEntry.objects.get(kind=EntryKind.EARNING, source_id=original.pk)
        self.assertEqual(summaries.review_items(), [])
        # Its slot moved outside the Hub: still taught and reported by its tutor, so it still counts as it reads.
        slot = BookingSlot.objects.get(pk=original.slot_id)
        BookingSlot.objects.filter(pk=slot.pk).update(starts_at=slot.starts_at + timedelta(minutes=7),
                                                      ends_at=slot.ends_at + timedelta(minutes=7))
        [item] = summaries.review_items()
        self.assertEqual((item['problem'], item['current']['eligible'], item['current_tutor']['id']),
                         ('TIMES_CHANGED', True, str(self.tutor.pk)))
        corrections.keep_entry(self.admin, earning.pk, {'reason': 'Started 7 minutes late, as taught',
                                                        'seen': summaries.seen(item)})
        self.assertEqual(summaries.review_items(), [])
        # A Re-Demo request leaves it counting (Re-Demo required is conducted): still kept.
        request_redemo(original, REASON, actor=self.admin, now=AFTER)
        self.assertEqual(DemoBooking.objects.get(pk=original.pk).status, BookingStatus.REDEMO_REQUIRED)
        self.assertEqual(summaries.review_items(), [])
        # Reassigned to another tutor: back for review.
        DemoBooking.objects.filter(pk=original.pk).update(assigned_tutor=self.other_tutor)
        [item] = summaries.review_items()
        self.assertEqual((item['problem'], item['current']['eligible'], item['current_tutor']['id']),
                         ('TUTOR_CHANGED', False, str(self.other_tutor.pk)))
