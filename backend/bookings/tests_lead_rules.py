"""
The lead-level booking rules on the public pages (Q26, design B.7): one live
booking per child and type, and never two of a child's live bookings at
overlapping times -- including under concurrency.
"""
import threading
from datetime import datetime, time, timedelta
from unittest import skipUnless

from django.db import connection, transaction
from django.test import TransactionTestCase
from django.utils import timezone

from activity.models import ActivityLog

from .booking_service import (
    BookingBusy,
    LeadAlreadyBooked,
    LeadTimeConflict,
    cancel_booking,
    create_booking,
    reschedule_booking,
)
from .models import (
    BookingEvent,
    BookingSlot,
    BookingStatus,
    CancelReason,
    DemoBooking,
    DiagnosticBooking,
    Lead,
    RescheduleReason,
    SlotTime,
)
from .scheduling import BOOKING_TIMEZONE
from .tests_booking import (
    DAY,
    DEMO,
    DIAGNOSTIC,
    EVENING,
    MORNING,
    NOW,
    BookingTestCase,
    account,
    all_bookings,
    book,
    booking_count,
    request,
    schedule,
)
from .tests_public_api import PublicApiTestCase

# Diagnostic times around the Demo's 19:30-20:30: one ending as it starts,
# one overlapping it by half an hour, one starting as it ends.
HALF_SIX, SEVEN, HALF_EIGHT = time(18, 30), time(19, 0), time(20, 30)


def overlapping_live_pairs():
    """Every pair of one lead's booked bookings whose slots overlap: what the rules never allow."""
    live = all_bookings(status=BookingStatus.BOOKED)
    return [
        (a.id, b.id) for i, a in enumerate(live) for b in live[i + 1:]
        if a.lead_id == b.lead_id and a.slot.starts_at < b.slot.ends_at and b.slot.starts_at < a.slot.ends_at
    ]


# ------------------------------------------------------- one live per type

class OneLiveBookingPerTypeTests(BookingTestCase):
    def test_a_second_demo_or_diagnostic_for_one_child_is_refused(self):
        demo, _ = book()
        # The other type at another time is the child's to have.
        diagnostic, created = book(booking_type=DIAGNOSTIC, at=MORNING)
        self.assertTrue(created)
        for booking_type, held, label in ((DEMO, demo, 'Demo'), (DIAGNOSTIC, diagnostic, 'Diagnostic')):
            with self.subTest(booking_type=booking_type), self.assertRaises(LeadAlreadyBooked) as refused:
                book(booking_type=booking_type, day=DAY + timedelta(days=3), at=MORNING)
            self.assertEqual(refused.exception.booking, held)
            self.assertEqual((refused.exception.code, refused.exception.http_status), ('LEAD_ALREADY_BOOKED', 409))
            self.assertEqual(
                refused.exception.message,
                f'This child already has a {label} booked. Only one can be booked at a time.',
            )
        self.assertEqual(booking_count(), 2)

    def test_a_refusal_changes_nothing(self):
        book()
        with self.assertRaises(LeadAlreadyBooked):
            book(day=DAY + timedelta(days=1), school='Another School', parent_name='Someone Else')
        lead = Lead.objects.get()
        self.assertEqual((lead.school_name, lead.parent_name), ('Delhi Private School', 'Asha Nair'))
        self.assertEqual((booking_count(), BookingSlot.objects.count(), BookingEvent.objects.count()), (1, 1, 1))
        self.assertEqual(ActivityLog.objects.filter(action='booking.create').count(), 1)

    def test_the_same_submission_again_is_still_answered_with_its_booking(self):
        first, _ = book()
        again, created = book(phone='501234567')
        self.assertEqual((again.pk, created), (first.pk, False))

    def test_siblings_are_children_of_their_own(self):
        riya, _ = book(student='Riya')
        ali, _ = book(student='Ali')
        sara, _ = book(student='Sara', booking_type=DIAGNOSTIC)
        self.assertEqual(len({riya.lead_id, ali.lead_id, sara.lead_id}), 3)

    def test_a_cancelled_booking_holds_nothing(self):
        first, _ = book()
        cancel_booking(first, reason_code=CancelReason.PARENT_REQUEST)
        again, created = book(day=DAY + timedelta(days=2))
        self.assertTrue(created)
        # Nor its time: a Diagnostic may take it.
        self.assertTrue(book(booking_type=DIAGNOSTIC)[1])
        self.assertEqual(again.lead_id, first.lead_id)

    def test_a_rescheduled_booking_holds_nothing_but_its_replacement_does(self):
        first, _ = book()
        moved = reschedule_booking(first, DAY + timedelta(days=2), EVENING, reason_code=RescheduleReason.OTHER,
                                   actor=account('admin_one', role='ADMIN'), now=NOW).booking
        with self.assertRaises(LeadAlreadyBooked) as refused:
            book(day=DAY + timedelta(days=4))
        self.assertEqual(refused.exception.booking, moved)
        # The old time is free for the other type.
        self.assertTrue(book(booking_type=DIAGNOSTIC)[1])
        cancel_booking(moved, reason_code=CancelReason.PARENT_REQUEST)
        self.assertTrue(book(day=DAY + timedelta(days=4))[1])

    def test_a_completed_booking_holds_nothing(self):
        first, _ = book()
        tutor = account('tutor_one', role='TUTOR')
        DemoBooking.objects.filter(pk=first.pk).update(
            status=BookingStatus.COMPLETED, completed_at=timezone.now(), assigned_tutor=tutor,
            tutor_assigned_at=timezone.now(),
        )
        self.assertTrue(book(day=DAY + timedelta(days=2))[1])

    def test_a_booking_holds_its_type_until_its_slot_has_ended(self):
        # Booked for 28 Oct 19:30-20:30 IST.
        book()
        during = datetime(2026, 10, 28, 20, 0, tzinfo=BOOKING_TIMEZONE)
        with self.assertRaises(LeadAlreadyBooked):
            create_booking(request(day=DAY + timedelta(days=2)), now=during)
        # Ended, never marked completed: no longer live, so the child may book again.
        after = datetime(2026, 10, 28, 20, 30, tzinfo=BOOKING_TIMEZONE)
        self.assertTrue(create_booking(request(day=DAY + timedelta(days=2)), now=after)[1])

    def test_the_childs_own_booking_is_named_before_a_full_slot(self):
        book(at=MORNING)
        for name in ('A', 'B', 'C'):
            book(student=name)
        with self.assertRaises(LeadAlreadyBooked):
            book()


# ------------------------------------------------------------ no overlaps

class NoOverlapTests(BookingTestCase):
    def setUp(self):
        super().setUp()
        for at in (HALF_SIX, SEVEN, HALF_EIGHT):
            SlotTime.objects.create(booking_type=DIAGNOSTIC, start_time=at)

    def test_a_demo_and_a_diagnostic_at_one_time_are_refused_either_way(self):
        demo, _ = book(student='Riya')
        with self.assertRaises(LeadTimeConflict) as refused:
            book(student='Riya', booking_type=DIAGNOSTIC)
        self.assertEqual(refused.exception.booking, demo)
        self.assertEqual((refused.exception.code, refused.exception.http_status), ('LEAD_TIME_CONFLICT', 409))

        diagnostic, _ = book(student='Ali', booking_type=DIAGNOSTIC)
        with self.assertRaises(LeadTimeConflict) as refused:
            book(student='Ali')
        self.assertEqual(refused.exception.booking, diagnostic)
        self.assertEqual(booking_count(), 2)

    def test_a_partial_overlap_is_refused(self):
        book()
        with self.assertRaises(LeadTimeConflict):
            book(booking_type=DIAGNOSTIC, at=SEVEN)

    def test_touching_slots_do_not_overlap(self):
        book(student='Riya')
        self.assertTrue(book(student='Riya', booking_type=DIAGNOSTIC, at=HALF_SIX)[1])
        book(student='Ali')
        self.assertTrue(book(student='Ali', booking_type=DIAGNOSTIC, at=HALF_EIGHT)[1])

    def test_cancelled_rescheduled_and_ended_bookings_hold_no_time(self):
        cancelled, _ = book(student='Riya')
        cancel_booking(cancelled, reason_code=CancelReason.OTHER)
        self.assertTrue(book(student='Riya', booking_type=DIAGNOSTIC)[1])

        # Another parent's phone, clear of the first's daily limit.
        moved, _ = book(student='Ali', phone='0507770000')
        reschedule_booking(moved, DAY + timedelta(days=1), EVENING, reason_code=RescheduleReason.OTHER, now=NOW)
        self.assertTrue(book(student='Ali', phone='0507770000', booking_type=DIAGNOSTIC)[1])
        self.assertEqual(overlapping_live_pairs(), [])


# ---------------------------------------------------------- the public API

class PublicLeadRuleTests(PublicApiTestCase):
    def test_the_codes_and_messages_name_no_booking(self):
        first = self.post()
        self.assertEqual(first.status_code, 201)
        booking_id = first.json()['booking_id']
        repeated = self.post()
        self.assertEqual((repeated.status_code, repeated.json()['booking_id']), (200, booking_id))

        again = self.post(date=self.window[1].isoformat())
        self.assertEqual(again.status_code, 409)
        self.assertEqual(again.json(), {
            'error': 'LEAD_ALREADY_BOOKED',
            'message': 'This child already has a Demo booked. Only one can be booked at a time.',
        })

        clash = self.post('diagnostic')
        self.assertEqual(clash.status_code, 409)
        self.assertEqual(clash.json(), {
            'error': 'LEAD_TIME_CONFLICT',
            'message': 'This child already has another booking at that time. Choose another time.',
        })
        self.assertEqual(self.post('diagnostic', time='10:00').status_code, 201)
        self.assertEqual(booking_count(), 2)


# ------------------------------------------------------------ concurrency

@skipUnless(connection.vendor == 'postgresql', 'the lead lock needs PostgreSQL row locking')
class ConcurrentLeadRuleTests(TransactionTestCase):
    """Real threads, each with its own database connection, starting together."""

    def setUp(self):
        schedule()

    def race(self, calls):
        """Run ``calls`` at once; each outcome is what its call returned, or the rule that refused it."""
        barrier = threading.Barrier(len(calls))
        outcomes = [None] * len(calls)

        def run(index, call):
            try:
                barrier.wait(timeout=10)
                outcomes[index] = call()
            except LeadAlreadyBooked:
                outcomes[index] = 'already'
            except LeadTimeConflict:
                outcomes[index] = 'clash'
            except Exception as exc:  # reported in the assertion, not lost in the thread
                outcomes[index] = repr(exc)
            finally:
                connection.close()

        threads = [threading.Thread(target=run, args=(i, call)) for i, call in enumerate(calls)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        return outcomes

    @staticmethod
    def booking(**kwargs):
        return lambda: 'created' if create_booking(request(**kwargs), now=NOW)[1] else 'replay'

    def test_one_child_in_four_demo_slots_at_once(self):
        # A new child, whose requests also meet on the new lead's unique key,
        # then one who already has a lead (a cancelled booking): only the lead
        # lock stands between those.
        cancelled, _ = create_booking(request(student='Known', day=DAY + timedelta(days=3)), now=NOW)
        cancel_booking(cancelled, reason_code=CancelReason.OTHER)
        for student in ('New', 'Known'):
            with self.subTest(student=student):
                outcomes = self.race([self.booking(student=student, day=DAY + timedelta(days=d), at=at)
                                      for d in (0, 1) for at in (MORNING, EVENING)])
                self.assertEqual(sorted(outcomes), ['already'] * 3 + ['created'], outcomes)
        self.assertEqual((DemoBooking.objects.filter(status=BookingStatus.BOOKED).count(), Lead.objects.count()), (2, 2))

    def test_a_demo_and_a_diagnostic_at_one_time_at_once(self):
        # A new child, then one who already has a lead (a cancelled booking).
        cancelled, _ = create_booking(request(student='Known', day=DAY + timedelta(days=3)), now=NOW)
        cancel_booking(cancelled, reason_code=CancelReason.OTHER)
        for student in ('New', 'Known'):
            with self.subTest(student=student):
                outcomes = self.race([self.booking(student=student),
                                      self.booking(student=student, booking_type=DIAGNOSTIC)])
                self.assertEqual(sorted(outcomes), ['clash', 'created'], outcomes)
        self.assertEqual(booking_count(status=BookingStatus.BOOKED), 2)
        self.assertEqual(overlapping_live_pairs(), [])

    def test_a_reschedule_racing_a_public_booking_for_the_same_time(self):
        demo, _ = create_booking(request(at=MORNING), now=NOW)
        admin = account('admin_race', role='ADMIN')
        target = DAY + timedelta(days=1)

        def move():
            reschedule_booking(demo, target, EVENING, reason_code=RescheduleReason.OTHER, actor=admin, now=NOW)
            return 'moved'

        outcomes = self.race([move, self.booking(booking_type=DIAGNOSTIC, day=target)])
        self.assertIn(sorted(outcomes), (['clash', 'moved'], ['clash', 'created']), outcomes)
        self.assertEqual(overlapping_live_pairs(), [])
        if 'moved' in outcomes:
            self.assertFalse(DiagnosticBooking.objects.exists())
        else:
            self.assertEqual(DemoBooking.objects.get().status, BookingStatus.BOOKED)

    def test_a_lead_locked_too_long_answers_busy_and_holds_up_no_other_child(self):
        first, _ = create_booking(request(), now=NOW)
        locked, release = threading.Event(), threading.Event()

        def hold_the_lead():
            try:
                with transaction.atomic():
                    Lead.objects.select_for_update(no_key=True).get(pk=first.lead_id)
                    locked.set()
                    release.wait(timeout=15)
            finally:
                connection.close()

        holder = threading.Thread(target=hold_the_lead)
        holder.start()
        try:
            self.assertTrue(locked.wait(timeout=10))
            with self.assertRaises(BookingBusy):
                create_booking(request(booking_type=DIAGNOSTIC, at=MORNING), now=NOW)
            # A sibling is another lead: booked while the first child's lead is held.
            self.assertTrue(create_booking(request(student='Ali'), now=NOW)[1])
        finally:
            release.set()
            holder.join(timeout=15)
        self.assertEqual(booking_count(), 2)
