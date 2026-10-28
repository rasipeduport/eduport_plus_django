"""
Bookings (DEVT-5935): the schedule and calendar, lead matching, BDE
attribution and the booking transaction -- capacity, repeated submissions,
cancellation and first-touch ownership -- including under concurrency.
"""
import json
import threading
from datetime import date, datetime, time, timedelta, timezone as dt_timezone
from io import StringIO
from unittest import skipUnless

from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command
from django.db import IntegrityError, connection, transaction
from django.db.models import ProtectedError
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from activity.models import ActivityLog

from .attribution import resolve_referral
from .booking_service import (
    BookingBusy,
    BookingRequest,
    DateOutOfWindow,
    SlotFull,
    SlotUnavailable,
    TooManyBookings,
    cancel_booking,
    close_slot,
    create_booking,
    reopen_slot,
    set_schedule,
)
from .leads import InvalidLeadDetails, name_key, normalize_phone
from .models import Booking, BookingLink, BookingSlot, BookingStatus, BookingType, Lead, ReferralStatus, SlotTime
from .scheduling import (
    AVAILABLE,
    BOOKING_TIMEZONE,
    FILLING_FAST,
    FULLY_BOOKED,
    ONLY_A_FEW_LEFT,
    booking_window,
    calendar,
    day_status,
    slot_instants,
    status_for_count,
)

User = get_user_model()

DEMO, DIAGNOSTIC = BookingType.DEMO, BookingType.DIAGNOSTIC
BOOKED, CANCELLED = BookingStatus.BOOKED, BookingStatus.CANCELLED
# Noon in India on 27 Oct 2026: the window is 28 Oct - 3 Nov.
NOW = datetime(2026, 10, 27, 12, 0, tzinfo=BOOKING_TIMEZONE)
DAY = date(2026, 10, 28)
MORNING, EVENING = time(10, 0), time(19, 30)


def account(username, role='BDE', **extra):
    return User.objects.create_user(
        email=f'{username}@bookings.test', username=username, password=None,
        full_name=username.replace('_', ' ').title(), role=role, **extra,
    )


def link(bde, booking_type=DEMO, **fields):
    return BookingLink.objects.create(bde=bde, booking_type=booking_type, **fields)


def request(student='Riya', phone='0501234567', booking_type=DEMO, day=DAY, at=EVENING, ref=None, **overrides):
    values = dict(
        booking_type=booking_type, date=day, time=at, parent_name='Asha Nair', phone_dial_code='+971',
        phone_number=phone, student_name=student, school='Delhi Private School', student_class='Class 8',
        syllabus='CBSE', country='United Arab Emirates', display_time='06:00 pm - 07:00 pm', ref=ref,
    )
    values.update(overrides)
    return BookingRequest(**values)


def book(**kwargs):
    return create_booking(request(**kwargs), now=NOW)


def schedule():
    for booking_type in (DEMO, DIAGNOSTIC):
        for at in (MORNING, EVENING):
            SlotTime.objects.create(booking_type=booking_type, start_time=at)


class BookingTestCase(TestCase):
    def setUp(self):
        schedule()


# ------------------------------------------------------------- constraints

class ConstraintTests(BookingTestCase):
    def slot(self, **fields):
        starts_at, ends_at = slot_instants(DAY, EVENING)
        values = dict(booking_type=DEMO, local_date=DAY, local_time=EVENING, starts_at=starts_at, ends_at=ends_at)
        values.update(fields)
        return BookingSlot.objects.create(**values)

    def lead(self, student='Riya', **fields):
        values = dict(parent_name='Asha', phone_dial_code='+971', phone_number='501234567', phone_key='+971501234567',
                      student_name=student, student_name_key=name_key(student), school_name='DPS', grade='Class 8',
                      syllabus='CBSE')
        values.update(fields)
        return Lead.objects.create(**values)

    def booking(self, slot, lead, seat=1, **fields):
        values = dict(booking_type=DEMO, lead=lead, slot=slot, seat=seat, referral_status=ReferralStatus.NO_REF)
        values.update(fields)
        return Booking.objects.create(**values)

    def assertRefused(self, create):
        with self.assertRaises(IntegrityError), transaction.atomic():
            create()

    def test_one_time_and_one_slot_row_per_occurrence(self):
        self.assertRefused(lambda: SlotTime.objects.create(booking_type=DEMO, start_time=EVENING))
        self.slot()
        self.assertRefused(self.slot)
        self.assertRefused(lambda: self.slot(local_date=DAY + timedelta(days=1), capacity=4))

    def test_a_slot_holds_three_booked_seats_and_one_per_lead(self):
        slot, riya, ali = self.slot(), self.lead('Riya'), self.lead('Ali')
        first = self.booking(slot, riya, seat=1)
        self.assertRefused(lambda: self.booking(slot, ali, seat=1))
        self.assertRefused(lambda: self.booking(slot, riya, seat=2))
        self.assertRefused(lambda: self.booking(slot, ali, seat=4))
        # A cancelled booking frees both its seat and its lead's place.
        Booking.objects.filter(pk=first.pk).update(status=CANCELLED, cancelled_at=timezone.now())
        self.booking(slot, riya, seat=1)

    def test_cancellation_and_referral_fields_agree_with_the_status(self):
        slot, lead = self.slot(), self.lead()
        bde = account('bde_one')
        demo = link(bde)
        self.assertRefused(lambda: self.booking(slot, lead, status=CANCELLED))
        self.assertRefused(lambda: self.booking(slot, lead, referral_status=ReferralStatus.ATTRIBUTED))
        self.assertRefused(lambda: self.booking(slot, lead, referral_link=demo))
        self.assertRefused(lambda: self.booking(
            slot, lead, referral_status=ReferralStatus.WRONG_TYPE, referral_link=demo, attributed_bde=bde,
        ))
        self.booking(slot, lead, referral_status=ReferralStatus.ATTRIBUTED, referral_link=demo, attributed_bde=bde)

    def test_one_lead_per_phone_and_student_with_complete_ownership(self):
        self.lead('Riya')
        self.assertRefused(lambda: self.lead('Riya'))
        self.assertRefused(lambda: self.lead('Ali', owner_bde=account('bde_one')))

    def test_booking_history_cannot_be_deleted(self):
        booking, _ = book()
        with self.assertRaises(ProtectedError):
            booking.lead.delete()
        with self.assertRaises(ProtectedError):
            booking.slot.delete()


# ---------------------------------------------------------------- schedule

class ScheduleTests(BookingTestCase):
    def test_the_window_is_tomorrow_and_six_more_days_in_indian_time(self):
        before_midnight = datetime(2026, 10, 27, 23, 59, tzinfo=BOOKING_TIMEZONE)
        self.assertEqual(booking_window(DEMO, before_midnight), [DAY + timedelta(days=i) for i in range(7)])
        self.assertEqual(booking_window(DIAGNOSTIC, before_midnight + timedelta(minutes=2))[0], DAY + timedelta(days=1))
        # 23:59 in India is 18:29 UTC: the date is India's, whatever the clock's zone.
        self.assertEqual(booking_window(DEMO, before_midnight.astimezone(dt_timezone.utc))[0], DAY)

    def test_status_thresholds(self):
        self.assertEqual(
            [status_for_count(count) for count in range(5)],
            [AVAILABLE, FILLING_FAST, ONLY_A_FEW_LEFT, FULLY_BOOKED, FULLY_BOOKED],
        )

    def test_a_date_is_full_only_when_every_slot_is(self):
        self.assertEqual(day_status([FULLY_BOOKED, FULLY_BOOKED]), FULLY_BOOKED)
        self.assertEqual(day_status([FULLY_BOOKED, FILLING_FAST, AVAILABLE]), FILLING_FAST)
        self.assertEqual(day_status([AVAILABLE, ONLY_A_FEW_LEFT]), ONLY_A_FEW_LEFT)
        self.assertEqual(day_status([]), FULLY_BOOKED)

    def test_the_calendar_counts_bookings_and_closures_per_type(self):
        book(student='A')
        book(student='B')
        close_slot(DEMO, DAY, MORNING, reason='Holiday')
        days = calendar(DEMO, now=NOW)
        self.assertEqual([entry['date'] for entry in days], [(DAY + timedelta(days=i)).isoformat() for i in range(7)])
        self.assertEqual(days[0]['slots'], [{'time': '10:00', 'status': FULLY_BOOKED}, {'time': '19:30', 'status': ONLY_A_FEW_LEFT}])
        self.assertEqual(days[0]['status'], ONLY_A_FEW_LEFT)
        self.assertEqual(days[1]['status'], AVAILABLE)
        self.assertEqual(calendar(DIAGNOSTIC, now=NOW)[0]['status'], AVAILABLE)

    def test_inactive_times_are_not_offered_and_an_empty_schedule_is_full(self):
        set_schedule(DEMO, [EVENING])
        self.assertEqual([slot['time'] for slot in calendar(DEMO, now=NOW)[0]['slots']], ['19:30'])
        with self.assertRaises(SlotUnavailable):
            book(at=MORNING)
        set_schedule(DEMO, [])
        self.assertEqual({(day['status'], len(day['slots'])) for day in calendar(DEMO, now=NOW)}, {(FULLY_BOOKED, 0)})

    def test_slots_last_an_hour_and_are_stored_as_utc(self):
        starts_at, ends_at = slot_instants(DAY, EVENING)
        self.assertEqual(starts_at, datetime(2026, 10, 28, 14, 0, tzinfo=dt_timezone.utc))
        self.assertEqual(ends_at - starts_at, timedelta(hours=1))

    def test_setting_the_schedule_is_idempotent_and_audited(self):
        self.assertEqual(set_schedule(DEMO, [MORNING, EVENING]), ([], []))
        self.assertEqual(set_schedule(DEMO, [time(18, 0), EVENING]), ([time(18, 0)], [MORNING]))
        self.assertEqual(
            list(SlotTime.objects.filter(booking_type=DEMO, is_active=True).values_list('start_time', flat=True)),
            [time(18, 0), EVENING],
        )
        row = ActivityLog.objects.get(action='booking_schedule.update')
        self.assertEqual((row.context['added'], row.context['removed']), (['18:00'], ['10:00']))


# ------------------------------------------------------- leads, attribution

class LeadTests(BookingTestCase):
    def test_phone_numbers_normalise(self):
        self.assertEqual(normalize_phone('+971', '050 123-4567'), ('+971', '501234567', '+971501234567'))
        self.assertEqual(normalize_phone('+971', '501234567')[2], '+971501234567')
        self.assertEqual(normalize_phone('+1', '1 415 555 0100')[2], '+14155550100')
        self.assertEqual(normalize_phone('+91', '09876543210')[2], '+919876543210')
        # Arabic-Indic digits: the pages send ASCII digits only.
        for dial, number in (('971', '501234567'), ('+0', '501234567'), ('+971', '0012345'), ('+971', '1234567890123456'),
                             ('+971', '٠٥٠١٢٣٤٥٦٧'), ('+9٧١', '501234567')):
            with self.subTest(dial=dial, number=number), self.assertRaises(InvalidLeadDetails):
                normalize_phone(dial, number)

    def test_names_compare_without_case_spacing_or_punctuation(self):
        self.assertEqual(name_key('  Riya  S. '), name_key('riya s'))
        self.assertNotEqual(name_key('Riya'), name_key('Ria'))

    def test_vowel_signs_and_accents_are_part_of_a_name(self):
        self.assertNotEqual(name_key('रानी'), name_key('रेनु'))
        self.assertNotEqual(name_key('രാഹുൽ'), name_key('രിഹൊൽ'))
        self.assertEqual(name_key('José'), name_key('JOSÉ'))

    def test_siblings_are_separate_and_a_child_keeps_their_lead(self):
        riya, _ = book(student='Riya')
        ali, _ = book(student='Ali')
        self.assertNotEqual(riya.lead_id, ali.lead_id)
        again, _ = book(student='riya', phone='501234567', at=MORNING, school='New School')
        self.assertEqual(again.lead_id, riya.lead_id)
        self.assertEqual(Lead.objects.get(pk=riya.lead_id).school_name, 'New School')
        self.assertEqual(Lead.objects.count(), 2)


class AttributionTests(BookingTestCase):
    def test_every_outcome(self):
        bde = account('bde_one')
        demo, diagnostic = link(bde), link(bde, DIAGNOSTIC)
        revoked = link(account('bde_two'), revoked_at=timezone.now())
        deactivated = link(account('bde_three', is_active=False, deactivated_at=timezone.now()))
        former = link(account('bde_four', role='MENTOR'))
        cases = [
            (None, ReferralStatus.NO_REF), ('', ReferralStatus.NO_REF),
            (42, ReferralStatus.INVALID_REF), ('not a token!', ReferralStatus.INVALID_REF),
            ('x' * 65, ReferralStatus.INVALID_REF), ('A' * 22, ReferralStatus.UNKNOWN_REF),
            (revoked.token, ReferralStatus.REVOKED_LINK), (deactivated.token, ReferralStatus.INACTIVE_BDE),
            (former.token, ReferralStatus.INACTIVE_BDE), (diagnostic.token, ReferralStatus.WRONG_TYPE),
            (demo.token, ReferralStatus.ATTRIBUTED),
        ]
        for ref, expected in cases:
            with self.subTest(expected=expected, ref=str(ref)[:8]):
                referral = resolve_referral(ref, DEMO)
                self.assertEqual(referral.status, expected)
                self.assertEqual(referral.bde, bde if expected == ReferralStatus.ATTRIBUTED else None)


# ----------------------------------------------------------------- service

class BookingServiceTests(BookingTestCase):
    def setUp(self):
        super().setUp()
        self.bde = account('bde_one')
        self.demo = link(self.bde)

    def test_a_booking_takes_a_seat_and_keeps_what_was_submitted(self):
        booking, created = book(ref=self.demo.token)
        self.assertTrue(created)
        self.assertEqual((booking.status, booking.seat, booking.booking_type), (BOOKED, 1, DEMO))
        self.assertEqual(
            (booking.referral_status, booking.referral_link, booking.attributed_bde),
            (ReferralStatus.ATTRIBUTED, self.demo, self.bde),
        )
        self.assertEqual(booking.slot.starts_at, datetime(2026, 10, 28, 14, 0, tzinfo=dt_timezone.utc))
        self.assertEqual((booking.details['phone'], booking.details['display_time']), ('+971 0501234567', '06:00 pm - 07:00 pm'))
        lead = Lead.objects.get(pk=booking.lead_id)
        self.assertEqual((lead.owner_bde, lead.owner_link, lead.phone_key), (self.bde, self.demo, '+971501234567'))

    def test_a_repeated_submission_returns_the_booking_it_made(self):
        first, _ = book()
        again, created = book(phone='501234567')
        self.assertFalse(created)
        self.assertEqual(again.pk, first.pk)
        self.assertEqual(Booking.objects.count(), 1)

    def test_three_bookings_fill_a_slot_and_a_fourth_is_refused(self):
        self.assertEqual([book(student=name)[0].seat for name in ('A', 'B', 'C')], [1, 2, 3])
        with self.assertRaises(SlotFull):
            book(student='D')
        self.assertEqual(Booking.objects.filter(status=BOOKED).count(), 3)
        # The refused booking left no lead behind.
        self.assertFalse(Lead.objects.filter(student_name='D').exists())

    def test_a_cancellation_is_kept_and_frees_its_seat(self):
        first, _ = book(student='A')
        book(student='B')
        book(student='C')
        cancelled, changed = cancel_booking(first, reason='Parent asked')
        self.assertTrue(changed)
        self.assertEqual((cancelled.status, cancelled.cancel_reason), (CANCELLED, 'Parent asked'))
        self.assertFalse(cancel_booking(first)[1])
        self.assertEqual(book(student='D')[0].seat, 1)
        self.assertEqual(Booking.objects.count(), 4)
        self.assertEqual(Booking.objects.filter(status=BOOKED).count(), 3)

    def test_a_cancelled_child_may_book_the_same_slot_again(self):
        first, _ = book(at=MORNING)
        cancel_booking(first)
        again, created = book(at=MORNING)
        self.assertTrue(created)
        self.assertNotEqual(again.pk, first.pk)

    def test_a_closed_slot_takes_no_booking_until_reopened(self):
        close_slot(DEMO, DAY, EVENING, reason='Holiday')
        with self.assertRaises(SlotFull):
            book()
        reopen_slot(DEMO, DAY, EVENING)
        self.assertTrue(book()[1])

    def test_dates_outside_the_window_and_times_not_offered_are_refused(self):
        for day in (NOW.date(), DAY + timedelta(days=7)):
            with self.subTest(day=day), self.assertRaises(DateOutOfWindow):
                book(day=day)
        with self.assertRaises(SlotUnavailable):
            book(at=time(11, 0))

    def test_the_first_valid_attribution_owns_the_lead(self):
        other = account('bde_two')
        other_demo = link(other)
        unowned, _ = book(at=MORNING)
        self.assertIsNone(Lead.objects.get(pk=unowned.lead_id).owner_bde)
        second, _ = book(ref=self.demo.token)
        third, _ = book(day=DAY + timedelta(days=1), ref=other_demo.token)
        lead = Lead.objects.get(pk=unowned.lead_id)
        self.assertEqual((lead.owner_bde, lead.owner_link), (self.bde, self.demo))
        # Each booking is still credited to the link it came through.
        self.assertEqual((second.attributed_bde, third.attributed_bde), (self.bde, other))

    def test_a_token_that_cannot_attribute_never_blocks_the_booking(self):
        wrong_type = link(self.bde, DIAGNOSTIC)
        cases = [(None, ReferralStatus.NO_REF), ('??', ReferralStatus.INVALID_REF),
                 ('B' * 22, ReferralStatus.UNKNOWN_REF), (wrong_type.token, ReferralStatus.WRONG_TYPE)]
        for offset, (ref, expected) in enumerate(cases):
            with self.subTest(expected=expected):
                booking, created = book(student=f'Child {offset}', day=DAY + timedelta(days=offset), ref=ref)
                self.assertTrue(created)
                self.assertEqual((booking.referral_status, booking.attributed_bde), (expected, None))
                self.assertIsNone(Lead.objects.get(pk=booking.lead_id).owner_bde)

    @override_settings(BOOKING_PHONE_DAILY_LIMIT=2)
    def test_one_phone_number_has_a_daily_limit(self):
        book(student='A')
        book(student='B', at=MORNING)
        with self.assertRaises(TooManyBookings):
            book(student='C', day=DAY + timedelta(days=1))
        self.assertFalse(book(student='A')[1])

    def test_the_activity_log_names_no_one(self):
        booking, _ = book(ref=self.demo.token)
        cancel_booking(booking, actor=account('admin_one', role='ADMIN'), reason='Duplicate')
        created = ActivityLog.objects.get(action='booking.create')
        self.assertEqual((created.entity_type, created.entity_id), ('booking', str(booking.id)))
        self.assertEqual(created.entity_label, 'Demo · 28 Oct 2026, 19:30 IST')
        self.assertEqual(
            (created.context['referral_status'], created.context['attributed_bde_id'], created.context['lead_owner_id']),
            (ReferralStatus.ATTRIBUTED, str(self.bde.pk), str(self.bde.pk)),
        )
        recorded = json.dumps([created.entity_label, created.changes, created.context])
        for private in ('Riya', 'Asha', '501234567', self.demo.token, 'Delhi'):
            self.assertNotIn(private, recorded)
        self.assertTrue(ActivityLog.objects.filter(action='booking.cancel', entity_id=str(booking.id)).exists())


class ScheduleCommandTests(BookingTestCase):
    def run_command(self, *args):
        out = StringIO()
        call_command('booking_schedule', *args, stdout=out)
        return out.getvalue()

    def active(self, booking_type=DEMO):
        return [t.strftime('%H:%M') for t in SlotTime.objects.filter(booking_type=booking_type, is_active=True)
                .order_by('start_time').values_list('start_time', flat=True)]

    def test_set_is_a_dry_run_until_applied(self):
        self.assertIn('Re-run with --apply', self.run_command('set', 'demo', '18:00', '19:30'))
        self.assertEqual(self.active(), ['10:00', '19:30'])
        self.run_command('set', 'demo', '19:30', '18:00', '--apply')
        self.assertEqual(self.active(), ['18:00', '19:30'])
        self.assertEqual(self.active(DIAGNOSTIC), ['10:00', '19:30'])
        self.assertIn('demo: 18:00, 19:30', self.run_command('show'))
        self.assertIn('Nothing to do', self.run_command('set', 'demo', '18:00', '19:30', '--apply'))

    def test_close_and_reopen_one_slot(self):
        self.run_command('close', 'demo', '2026-10-28', '19:30', '--reason', 'Holiday', '--apply')
        slot = BookingSlot.objects.get()
        self.assertEqual((slot.close_reason, slot.closed_at is not None), ('Holiday', True))
        self.run_command('reopen', 'demo', '2026-10-28', '19:30', '--apply')
        slot.refresh_from_db()
        self.assertIsNone(slot.closed_at)

    def test_bad_input_is_refused(self):
        for args in (('set', 'webinar', '10:00'), ('set', 'demo', '7pm'), ('close', 'demo', '2026-02-30', '19:30'),
                     ('close', 'demo', '2026-10-28', '11:00', '--apply')):
            with self.subTest(args=args), self.assertRaises(CommandError):
                self.run_command(*args)


# -------------------------------------------------------------- concurrency

@skipUnless(connection.vendor == 'postgresql', 'the slot lock needs PostgreSQL row locking')
class ConcurrentBookingTests(TransactionTestCase):
    """Real threads, each with its own database connection, starting together."""

    def setUp(self):
        SlotTime.objects.create(booking_type=DEMO, start_time=MORNING)
        SlotTime.objects.create(booking_type=DEMO, start_time=EVENING)

    def race(self, requests):
        barrier = threading.Barrier(len(requests))
        outcomes = [None] * len(requests)

        def run(index, booking_request):
            try:
                barrier.wait(timeout=10)
                booking, created = create_booking(booking_request, now=NOW)
                outcomes[index] = ('created' if created else 'replay', booking.pk)
            except SlotFull:
                outcomes[index] = ('full', None)
            except Exception as exc:  # reported in the assertion, not lost in the thread
                outcomes[index] = ('error', repr(exc))
            finally:
                connection.close()

        threads = [threading.Thread(target=run, args=(i, r)) for i, r in enumerate(requests)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        return outcomes

    def kinds(self, outcomes):
        return sorted(kind for kind, _ in outcomes)

    def test_six_requests_for_a_slot_nobody_has_booked(self):
        outcomes = self.race([request(student=f'Child {i}') for i in range(6)])
        self.assertEqual(self.kinds(outcomes), ['created'] * 3 + ['full'] * 3, outcomes)
        self.assertEqual(BookingSlot.objects.count(), 1)
        self.assertEqual(sorted(Booking.objects.values_list('seat', flat=True)), [1, 2, 3])

    def test_four_requests_for_the_last_seat(self):
        create_booking(request(student='A'), now=NOW)
        create_booking(request(student='B'), now=NOW)
        outcomes = self.race([request(student=f'Late {i}') for i in range(4)])
        self.assertEqual(self.kinds(outcomes), ['created'] + ['full'] * 3, outcomes)
        self.assertEqual(Booking.objects.filter(status=BOOKED).count(), 3)

    def test_identical_submissions_make_one_booking(self):
        outcomes = self.race([request() for _ in range(4)])
        self.assertEqual(self.kinds(outcomes), ['created'] + ['replay'] * 3, outcomes)
        self.assertEqual(len({pk for _, pk in outcomes}), 1)
        self.assertEqual((Booking.objects.count(), Lead.objects.count()), (1, 1))

    def test_a_slot_locked_too_long_answers_busy(self):
        create_booking(request(student='A'), now=NOW)
        slot = BookingSlot.objects.get()
        locked, release = threading.Event(), threading.Event()

        def hold_the_lock():
            try:
                with transaction.atomic():
                    BookingSlot.objects.select_for_update().get(pk=slot.pk)
                    locked.set()
                    release.wait(timeout=15)
            finally:
                connection.close()

        holder = threading.Thread(target=hold_the_lock)
        holder.start()
        try:
            self.assertTrue(locked.wait(timeout=10))
            with self.assertRaises(BookingBusy):
                create_booking(request(student='B'), now=NOW)
        finally:
            release.set()
            holder.join(timeout=15)
        self.assertEqual(Booking.objects.count(), 1)

    def test_two_bdes_racing_for_a_new_lead(self):
        first, second = account('bde_one'), account('bde_two')
        outcomes = self.race([request(at=EVENING, ref=link(first).token), request(at=MORNING, ref=link(second).token)])
        self.assertEqual(self.kinds(outcomes), ['created', 'created'], outcomes)
        lead = Lead.objects.get()
        self.assertIn(lead.owner_bde, (first, second))
        self.assertEqual(lead.owner_link.bde, lead.owner_bde)
        self.assertEqual({booking.attributed_bde for booking in Booking.objects.all()}, {first, second})
