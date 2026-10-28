"""
Booking slot management (DEVT-5973): one date's Demo or Diagnostic slots for
administrators, and closing or reopening them -- what the public booking pages
then offer, and that no booking is ever touched.

Dates are relative to the real clock: the API judges past and future by it.
"""
from datetime import time, timedelta
from unittest import mock

from django.db import OperationalError
from django.utils import timezone
from rest_framework.test import APITestCase

from activity.models import ActivityLog

from . import booking_service
from .booking_service import BookingBusy, SlotFull, create_booking, set_schedule, set_slots_closed
from .models import Booking, BookingSlot, BookingStatus, BookingType, SlotTime
from .scheduling import AVAILABLE, FILLING_FAST, FULLY_BOOKED, ONLY_A_FEW_LEFT, calendar, indian_today
from .tests_booking import account, request

DEMO, DIAGNOSTIC = BookingType.DEMO, BookingType.DIAGNOSTIC
MORNING, EVENING = time(10, 0), time(19, 30)


class SlotAdminTestCase(APITestCase):
    def setUp(self):
        for booking_type in (DEMO, DIAGNOSTIC):
            for at in (MORNING, EVENING):
                SlotTime.objects.create(booking_type=booking_type, start_time=at)
        self.admin = account('slot_admin', role='ADMIN')
        self.client.force_authenticate(self.admin)
        self.today = indian_today()
        self.day = self.today + timedelta(days=2)  # in the parents' window
        self.students = 0

    def url(self, day=None, kind='demo'):
        return f'/api/booking-slots/{kind}/{(day or self.day).isoformat()}/'

    def change(self, action, *times, day=None, kind='demo', reason=''):
        return self.client.post(self.url(day, kind), {'action': action, 'times': list(times), 'reason': reason}, format='json')

    def book(self, at=EVENING, booking_type=DEMO):
        self.students += 1
        booking, _created = create_booking(
            request(student=f'Child {self.students}', phone=f'05012345{self.students:02d}', booking_type=booking_type,
                    day=self.day, at=at),
            now=timezone.now(),
        )
        return booking

    def slot(self, response, at):
        return next(entry for entry in response.json()['slots'] if entry['time'] == at)

    def parents_see(self, at, booking_type=DEMO):
        day = next(entry for entry in calendar(booking_type) if entry['date'] == self.day.isoformat())
        return next(entry['status'] for entry in day['slots'] if entry['time'] == at)


class DayTests(SlotAdminTestCase):
    def test_every_time_with_its_bookings_and_the_status_parents_see(self):
        self.book(MORNING)
        self.book(EVENING)
        self.book(EVENING)
        res = self.client.get(self.url())
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(
            {key: body[key] for key in ('booking_type', 'date', 'timezone', 'slot_minutes', 'capacity', 'parent_state', 'editable')},
            {'booking_type': 'DEMO', 'date': self.day.isoformat(), 'timezone': 'Asia/Kolkata', 'slot_minutes': 60,
             'capacity': 3, 'parent_state': 'open', 'editable': True},
        )
        self.assertEqual(body['window']['first'], (self.today + timedelta(days=1)).isoformat())
        self.assertEqual(body['slots'], [
            {'time': '10:00', 'end_time': '11:00', 'scheduled': True, 'booked': 1, 'capacity': 3, 'status': FILLING_FAST,
             'open_status': FILLING_FAST, 'closed': False, 'closed_at': None, 'closed_by': None, 'close_reason': ''},
            {'time': '19:30', 'end_time': '20:30', 'scheduled': True, 'booked': 2, 'capacity': 3, 'status': ONLY_A_FEW_LEFT,
             'open_status': ONLY_A_FEW_LEFT, 'closed': False, 'closed_at': None, 'closed_by': None, 'close_reason': ''},
        ])
        # Each booking type keeps its own slots.
        diagnostic = self.client.get(self.url(kind='diagnostic')).json()
        self.assertEqual([(s['time'], s['booked'], s['status']) for s in diagnostic['slots']],
                         [('10:00', 0, AVAILABLE), ('19:30', 0, AVAILABLE)])

    def test_where_a_date_stands_for_parents(self):
        for offset, state, editable in ((-1, 'past', False), (0, 'today', True), (1, 'open', True),
                                        (7, 'open', True), (8, 'upcoming', True)):
            with self.subTest(offset=offset):
                body = self.client.get(self.url(self.today + timedelta(days=offset))).json()
                self.assertEqual((body['parent_state'], body['editable']), (state, editable))

    def test_a_retired_time_that_still_holds_bookings_is_shown(self):
        self.book(MORNING)
        set_schedule(DEMO, [EVENING])
        slots = self.client.get(self.url()).json()['slots']
        self.assertEqual([(s['time'], s['scheduled'], s['booked']) for s in slots], [('10:00', False, 1), ('19:30', True, 0)])
        # Only an offered time can be closed.
        self.assertEqual(self.change('close', '10:00').json()['code'], 'UNKNOWN_TIME')


class CloseAndReopenTests(SlotAdminTestCase):
    def test_closing_keeps_the_bookings_and_refuses_new_ones(self):
        held = [self.book(), self.book()]
        res = self.change('close', '19:30', reason='  Teacher training  ')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()['changed'], ['19:30'])
        slot = self.slot(res, '19:30')
        # Parents see Fully Booked; its bookings would make it Only a Few Left if reopened.
        self.assertEqual(
            {key: slot[key] for key in ('closed', 'status', 'open_status', 'booked', 'closed_by', 'close_reason')},
            {'closed': True, 'status': FULLY_BOOKED, 'open_status': ONLY_A_FEW_LEFT, 'booked': 2,
             'closed_by': self.admin.full_name, 'close_reason': 'Teacher training'},
        )
        self.assertTrue(slot['closed_at'])
        # The bookings stay as they were; the slot takes no new one.
        self.assertEqual(
            list(Booking.objects.filter(pk__in=[b.pk for b in held]).values_list('status', flat=True)),
            [BookingStatus.BOOKED, BookingStatus.BOOKED],
        )
        with self.assertRaises(SlotFull):
            self.book()
        self.assertEqual(self.parents_see('19:30'), FULLY_BOOKED)
        self.assertEqual(self.parents_see('10:00'), AVAILABLE)
        entry = ActivityLog.objects.get(action='booking_slot.close')
        self.assertEqual((entry.actor, entry.context['reason']), (self.admin, 'Teacher training'))

    def test_reopening_takes_bookings_only_while_seats_remain(self):
        self.book()
        self.book()
        self.change('close', '19:30')
        res = self.change('reopen', '19:30')
        self.assertEqual(res.json()['changed'], ['19:30'])
        self.assertEqual(self.slot(res, '19:30')['status'], ONLY_A_FEW_LEFT)
        self.assertEqual(self.parents_see('19:30'), ONLY_A_FEW_LEFT)
        self.book()
        with self.assertRaises(SlotFull):
            self.book()
        slot = self.slot(self.client.get(self.url()), '19:30')
        self.assertEqual((slot['booked'], slot['status'], slot['closed']), (3, FULLY_BOOKED, False))
        self.assertEqual(ActivityLog.objects.filter(action='booking_slot.reopen', actor=self.admin).count(), 1)

    def test_reopening_a_full_slot_never_makes_it_available(self):
        for _ in range(3):
            self.book()
        closed = self.slot(self.change('close', '19:30'), '19:30')
        self.assertEqual((closed['status'], closed['open_status']), (FULLY_BOOKED, FULLY_BOOKED))
        reopened = self.slot(self.change('reopen', '19:30'), '19:30')
        self.assertEqual((reopened['closed'], reopened['status'], reopened['open_status']), (False, FULLY_BOOKED, FULLY_BOOKED))
        self.assertEqual(self.parents_see('19:30'), FULLY_BOOKED)
        with self.assertRaises(SlotFull):
            self.book()

    def test_a_whole_date_at_once_and_repeats_change_nothing(self):
        res = self.change('close', '19:30', '10:00', '19:30')
        self.assertEqual(res.json()['changed'], ['10:00', '19:30'])
        day = next(entry for entry in calendar(DEMO) if entry['date'] == self.day.isoformat())
        self.assertEqual(day['status'], FULLY_BOOKED)
        self.assertEqual(self.change('close', '10:00', '19:30').json()['changed'], [])
        self.assertEqual(self.change('reopen', '10:00', '19:30').json()['changed'], ['10:00', '19:30'])
        self.assertEqual(self.change('reopen', '10:00').json()['changed'], [])
        self.assertEqual(ActivityLog.objects.filter(action__startswith='booking_slot.').count(), 4)
        self.assertEqual(Booking.objects.count(), 0)

    def test_dates_beyond_the_window_can_be_closed_ahead(self):
        later = self.today + timedelta(days=30)
        self.assertEqual(self.change('close', '19:30', day=later).json()['changed'], ['19:30'])
        self.assertTrue(BookingSlot.objects.get(local_date=later, local_time=EVENING).closed_at)

    def test_all_or_nothing_when_a_slot_stays_locked(self):
        real_close = booking_service.close_slot

        class Busy(Exception):
            sqlstate = '55P03'

        def close_then_time_out(booking_type, local_date, local_time, **kwargs):
            if local_time == EVENING:
                error = OperationalError('lock timeout')
                error.__cause__ = Busy()
                raise error
            return real_close(booking_type, local_date, local_time, **kwargs)

        with mock.patch.object(booking_service, 'close_slot', side_effect=close_then_time_out):
            with self.assertRaises(BookingBusy):
                set_slots_closed(DEMO, self.day, [MORNING, EVENING], True, actor=self.admin)
            res = self.change('close', '10:00', '19:30')
        self.assertEqual((res.status_code, res.json()['code']), (503, 'SLOTS_BUSY'))
        self.assertFalse(BookingSlot.objects.filter(closed_at__isnull=False).exists())
        self.assertFalse(ActivityLog.objects.filter(action='booking_slot.close').exists())


class RefusalTests(SlotAdminTestCase):
    def test_bad_requests(self):
        self.assertEqual(self.client.get('/api/booking-slots/trial/2026-11-02/').status_code, 404)
        for value in ('2026-13-01', '02-11-2026', 'tomorrow'):
            with self.subTest(date=value):
                res = self.client.get(f'/api/booking-slots/demo/{value}/')
                self.assertEqual((res.status_code, res.json()['code']), (400, 'INVALID_DATE'))
        for body in ({'action': 'delete', 'times': ['19:30']}, {'action': 'close', 'times': []},
                     {'action': 'close', 'times': ['7:30 pm']}, {'action': 'close'}):
            with self.subTest(body=body):
                res = self.client.post(self.url(), body, format='json')
                self.assertEqual((res.status_code, res.json()['code']), (400, 'VALIDATION_ERROR'))
        res = self.change('close', '19:30', '12:00')
        self.assertEqual(res.json(), {'error': 'Not a demo time: 12:00.', 'code': 'UNKNOWN_TIME'})
        self.assertFalse(BookingSlot.objects.exists())

    def test_past_dates_are_never_changed(self):
        yesterday = self.today - timedelta(days=1)
        res = self.change('close', '19:30', day=yesterday)
        self.assertEqual((res.status_code, res.json()['code']), (400, 'DATE_IN_PAST'))
        self.assertFalse(BookingSlot.objects.exists())

    def test_only_slot_managers_reach_it(self):
        # Session authentication sends no challenge, so "not signed in" is a 403 too.
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(self.url()).status_code, 403)
        for role in ('MENTOR', 'TUTOR', 'BDE', 'SALES_TL'):
            with self.subTest(role=role):
                self.client.force_authenticate(account(f'slot_{role.lower()}', role=role))
                self.assertEqual(self.client.get(self.url()).status_code, 403)
                self.assertEqual(self.change('close', '19:30').status_code, 403)
        # A superuser holds every permission (decision D1), whatever the role.
        self.client.force_authenticate(account('slot_su', role='MENTOR', is_superuser=True))
        self.assertEqual(self.change('close', '19:30').status_code, 200)
        self.assertEqual(BookingSlot.objects.filter(closed_at__isnull=False).count(), 1)
