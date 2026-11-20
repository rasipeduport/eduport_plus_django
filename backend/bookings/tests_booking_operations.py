"""
Booking operations for the Admin (Phase 5.2, P3): cancelling with a reason
code and No-show (Q9, D12), rescheduling into an open slot until the slot
starts (Q23) with the tutor carried over only when free (Q24) and no
lead-level time conflict (Q26), the reschedule options, the history timeline,
and who may do any of it (Q22, Q23).
"""
import json
import threading
from datetime import datetime, time, timedelta
from unittest import mock, skipUnless

from django.contrib import admin as django_admin
from django.contrib.auth.models import Permission
from django.db import connection
from django.test import RequestFactory, TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import RoleGroup
from activity.models import ActivityLog
from communications.models import CommunicationEvent, CommunicationTask, EventKind, Step, TaskStatus

from . import coordination
from .admin import DemoBookingAdmin
from .booking_service import (
    DateOutOfWindow,
    SlotFull,
    SlotTooSoon,
    _check_offered,
    assign_tutor,
    cancel_booking,
    close_slot,
    create_booking,
    reschedule_booking,
)
from .models import (
    BookingEventKind,
    BookingSlot,
    BookingStatus,
    CancelReason,
    DemoBooking,
    DiagnosticBooking,
    RescheduleReason,
)
from .scheduling import BOOKING_TIMEZONE, RESCHEDULE_DAYS, booking_window, calendar, indian_today
from .tests_booking import EVENING, MORNING, account, request, schedule, start
from .tests_booking_admin import DEMO, DIAGNOSTIC, PRIVATE, BookingAdminTestCase, detail_url

ELEVEN = time(11, 0)


def ops_url(booking, action):
    return f'{detail_url(booking)}{action}/'


class OperationsTestCase(BookingAdminTestCase):
    def cancel(self, booking, reason='PARENT_REQUEST', client=None):
        return (client or self.client).post(ops_url(booking, 'cancel'), {'reason': reason}, format='json')

    def move(self, booking, day, at=EVENING, reason='PARENT_REQUEST', client=None):
        body = {'date': day.isoformat(), 'time': at.strftime('%H:%M'), 'reason': reason}
        return (client or self.client).post(ops_url(booking, 'reschedule'), body, format='json')

    def kinds(self, booking):
        return [event.kind for event in booking.events.all()]

    def same_lead(self, booking, booking_type=DIAGNOSTIC, day=None, at=EVENING):
        """Another booking of ``booking``'s lead (same phone and child), of ``booking_type``."""
        lead = booking.lead
        made, _ = create_booking(request(student=lead.student_name, phone=lead.phone_number, booking_type=booking_type,
                                         day=day or self.day, at=at))
        return made

    def last_week(self, student):
        then = timezone.now() - timedelta(days=7)
        return self.book(student, day=indian_today(then) + timedelta(days=1), now=then)


# ------------------------------------------------------------------ cancel

class CancelTests(OperationsTestCase):
    def test_a_cancellation_records_its_code_and_frees_the_seat(self):
        booking = self.book('Riya')
        res = self.cancel(booking)
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
        self.assertEqual((res.data['status'], res.data['cancel_reason'], res.data['cancel_reason_code'], res.data['changed']),
                         ('CANCELLED', 'Parent asked to cancel', 'PARENT_REQUEST', True))
        self.assertEqual(res.data['actions'], {'cancel': False, 'no_show': False, 'reschedule': False, 'demo_invite': False,
                                               'request_redemo': False})
        booking.refresh_from_db()
        self.assertEqual((booking.cancel_reason_code, booking.cancel_reason, booking.cancelled_by), ('PARENT_REQUEST', '', self.admin))
        self.assertEqual(booking.events.last().data, {'from_status': 'BOOKED', 'to_status': 'CANCELLED', 'reason_code': 'PARENT_REQUEST'})
        entry = ActivityLog.objects.get(action='booking.cancel')
        self.assertEqual(entry.context, {'booking_type': 'DEMO', 'reason_code': 'PARENT_REQUEST', 'lead_id': str(booking.lead_id)})
        # The seat is free again, and cancelling again changes nothing.
        self.assertEqual(self.book('Ali').seat, 1)
        again = self.cancel(booking, reason='DUPLICATE')
        self.assertEqual((again.status_code, again.data['changed'], again.data['cancel_reason_code']), (200, False, 'PARENT_REQUEST'))

    def test_a_reason_is_a_code_from_the_list(self):
        booking = self.book('Riya')
        for body in ({}, {'reason': ''}, {'reason': 'Parent asked'}, {'reason': 'TUTOR_UNAVAILABLE'}):
            with self.subTest(body=body):
                res = self.client.post(ops_url(booking, 'cancel'), body, format='json')
                self.assertEqual((res.status_code, res.data['error']), (400, 'VALIDATION_ERROR'))
                self.assertIn('reason', res.data['fields'])
        booking.refresh_from_db()
        self.assertEqual((booking.status, self.kinds(booking)), (BookingStatus.BOOKED, [BookingEventKind.CREATED]))

    def test_no_show_only_once_the_slot_has_started(self):
        ahead = self.book('Riya')
        res = self.cancel(ahead, reason='NO_SHOW')
        self.assertEqual((res.status_code, res.data['error']), (409, 'NO_SHOW_BEFORE_START'))
        detail = self.client.get(detail_url(ahead)).data
        self.assertEqual(detail['actions'], {'cancel': True, 'no_show': False, 'reschedule': True, 'demo_invite': False,
                                             'request_redemo': False})

        # Last week's, never started: a No-show, and still movable (D3).
        past = self.last_week('Old Kid')
        self.assertEqual(self.client.get(detail_url(past)).data['actions'],
                         {'cancel': True, 'no_show': True, 'reschedule': True, 'demo_invite': False, 'request_redemo': False})
        res = self.cancel(past, reason='NO_SHOW')
        self.assertEqual((res.status_code, res.data['cancel_reason']), (200, 'No-show'))

    def test_completed_and_moved_bookings_cannot_be_cancelled(self):
        booking = self.book('Riya')
        assign_tutor(booking, self.tutor_a, actor=self.admin)
        DemoBooking.objects.filter(pk=booking.pk).update(status=BookingStatus.COMPLETED, completed_at=timezone.now())
        self.assertEqual(self.cancel(booking).data['error'], 'BOOKING_COMPLETED')
        moved = self.book('Ali')
        self.move(moved, self.day + timedelta(days=1))
        self.assertEqual(self.cancel(moved).data['error'], 'BOOKING_RESCHEDULED')

    def test_a_booking_is_cancelled_through_its_own_type(self):
        diagnostic = self.book('Ali', booking_type=DIAGNOSTIC)
        wrong = self.client.post(f'/api/bookings/demo/{diagnostic.id}/cancel/', {'reason': 'OTHER'}, format='json')
        self.assertEqual((wrong.status_code, wrong.data['error']), (404, 'NOT_FOUND'))
        self.assertEqual(self.cancel(diagnostic, reason='OTHER').data['status'], 'CANCELLED')


# --------------------------------------------------------------- reschedule

class RescheduleTests(OperationsTestCase):
    def test_a_move_replaces_the_booking_in_the_new_slot(self):
        old = self.book('Riya', ref=None)
        tomorrow = self.day + timedelta(days=1)
        res = self.move(old, tomorrow)
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.data)
        new_data = res.data['booking']
        self.assertNotEqual(new_data['id'], str(old.id))
        self.assertEqual((new_data['status'], new_data['slot']['date'], new_data['slot']['time']), ('BOOKED', tomorrow.isoformat(), '19:30'))
        self.assertEqual(new_data['rescheduled_from']['id'], str(old.id))
        self.assertEqual(res.data['previous'], {'id': str(old.id), 'status': 'RESCHEDULED'})
        self.assertEqual(res.data['tutor'], {'carried_over': False, 'tutor': None, 'reason': None})

        old.refresh_from_db()
        new = DemoBooking.objects.get(pk=new_data['id'])
        self.assertEqual((old.status, old.reschedule_reason_code, old.rescheduled_by), (BookingStatus.RESCHEDULED, 'PARENT_REQUEST', self.admin))
        self.assertEqual((new.lead_id, new.details, new.referral_status, new.channel, new.seat),
                         (old.lead_id, old.details, old.referral_status, old.channel, 1))
        # The old booking points at its replacement, and its seat is free again.
        old_detail = self.client.get(detail_url(old)).data
        self.assertEqual((old_detail['rescheduled_to']['id'], old_detail['reschedule_reason']), (str(new.id), 'Parent asked to move'))
        self.assertEqual(self.book('Ali').seat, 1)

        self.assertEqual(self.kinds(old), [BookingEventKind.CREATED, BookingEventKind.RESCHEDULED])
        self.assertEqual(old.events.last().data, {
            'from_status': 'BOOKED', 'to_status': 'RESCHEDULED', 'reason_code': 'PARENT_REQUEST',
            'old_slot_id': str(old.slot_id), 'new_slot_id': str(new.slot_id), 'replacement_id': str(new.id),
        })
        self.assertEqual(new.events.get().data, {
            'slot_id': str(new.slot_id), 'seat': 1, 'referral_status': 'NO_REF', 'via': 'reschedule',
            'rescheduled_from_id': str(old.id),
        })
        entry = ActivityLog.objects.get(action='booking.reschedule')
        self.assertEqual(set(entry.context), {'booking_type', 'rescheduled_from_id', 'old_slot_starts_at', 'new_slot_starts_at',
                                              'reason_code', 'lead_id', 'tutor_id', 'tutor_carried_over'})
        recorded = json.dumps([entry.entity_label, entry.changes, entry.context])
        for private in (*PRIVATE, 'Riya'):
            self.assertNotIn(private, recorded)

    def test_repeated_moves_extend_one_chain(self):
        first = self.book('Riya')
        second = DemoBooking.objects.get(pk=self.move(first, self.day + timedelta(days=1)).data['booking']['id'])
        third_id = self.move(second, self.day + timedelta(days=2), at=MORNING, reason='OTHER').data['booking']['id']
        chain = self.client.get(ops_url(DemoBooking.objects.get(pk=third_id), 'history')).data['chain']
        self.assertEqual([(link['id'], link['status'], link['current']) for link in chain], [
            (str(first.id), 'RESCHEDULED', False), (str(second.id), 'RESCHEDULED', False), (third_id, 'BOOKED', True),
        ])
        # A booking already moved is moved no further: its replacement is.
        res = self.move(first, self.day + timedelta(days=3))
        self.assertEqual((res.status_code, res.data['error']), (409, 'BOOKING_RESCHEDULED'))

    def test_the_tutor_carries_over_when_free(self):
        old = self.book('Riya')
        assign_tutor(old, self.tutor_a, actor=self.admin)
        res = self.move(old, self.day + timedelta(days=1))
        self.assertEqual(res.data['tutor'], {'carried_over': True, 'tutor': {'id': str(self.tutor_a.id), 'full_name': 'Tutor Anu'},
                                             'reason': None})
        new = DemoBooking.objects.get(pk=res.data['booking']['id'])
        old.refresh_from_db()
        self.assertEqual((new.assigned_tutor, new.tutor_assigned_by, old.assigned_tutor), (self.tutor_a, self.admin, self.tutor_a))
        self.assertEqual(self.kinds(new), [BookingEventKind.CREATED, BookingEventKind.TUTOR_ASSIGNED])
        self.assertEqual(new.events.last().data, {'old_tutor_id': None, 'new_tutor_id': str(self.tutor_a.id), 'via': 'reschedule'})

    def test_a_busy_or_inactive_tutor_stays_behind(self):
        busy = self.book('Riya')
        assign_tutor(busy, self.tutor_a, actor=self.admin)
        lesson = self.class_for(self.tutor_a, self.ist(EVENING, days=1), 'EDP91')
        res = self.move(busy, self.day + timedelta(days=1))
        self.assertEqual((res.status_code, res.data['tutor']['carried_over'], res.data['tutor']['reason']['code']),
                         (201, False, 'CLASS_CONFLICT'))
        self.assertEqual(res.data['tutor']['reason']['session_id'], str(lesson.id))
        self.assertIsNone(DemoBooking.objects.get(pk=res.data['booking']['id']).assigned_tutor)

        gone = self.book('Ali')
        assign_tutor(gone, self.tutor_b, actor=self.admin)
        type(self.tutor_b).objects.filter(pk=self.tutor_b.pk).update(is_active=False, deactivated_at=timezone.now())
        res = self.move(gone, self.day + timedelta(days=2))
        self.assertEqual((res.data['tutor']['carried_over'], res.data['tutor']['reason']['code']), (False, 'TUTOR_NOT_ASSIGNABLE'))
        gone.refresh_from_db()
        self.assertEqual(gone.assigned_tutor, self.tutor_b)  # kept as history

    def test_only_a_slot_of_the_reschedule_window(self):
        booking = self.book('Riya')
        tomorrow = self.day + timedelta(days=1)
        for _ in range(3):
            self.book('Filler', day=tomorrow, at=MORNING)
        close_slot(DEMO, self.day + timedelta(days=2), EVENING, actor=self.admin)
        cases = [
            # Today through RESCHEDULE_DAYS days on (RescheduleWindowTests): never the past, never beyond.
            ({'day': indian_today() - timedelta(days=1)}, 400, 'DATE_OUT_OF_WINDOW'),
            ({'day': indian_today() + timedelta(days=RESCHEDULE_DAYS + 1)}, 400, 'DATE_OUT_OF_WINDOW'),
            ({'day': tomorrow, 'at': ELEVEN}, 409, 'SLOT_UNAVAILABLE'),
            ({'day': tomorrow, 'at': MORNING}, 409, 'SLOT_FULL'),
            ({'day': self.day + timedelta(days=2)}, 409, 'SLOT_FULL'),
            ({'day': self.day}, 409, 'SAME_SLOT'),
        ]
        for kwargs, code, error in cases:
            with self.subTest(error=error, **{k: str(v) for k, v in kwargs.items()}):
                res = self.move(booking, **kwargs)
                self.assertEqual((res.status_code, res.data['error']), (code, error))
        booking.refresh_from_db()
        self.assertEqual((booking.status, self.kinds(booking)), (BookingStatus.BOOKED, [BookingEventKind.CREATED]))

    def test_not_once_its_tutor_has_started_it_or_it_is_cancelled(self):
        started = self.book('Sara', at=MORNING)
        assign_tutor(started, self.tutor_a, actor=self.admin)
        start(started, minutes=-5)
        res = self.move(started, self.day + timedelta(days=1))
        self.assertEqual((res.status_code, res.data['error'], res.data['message']),
                         (409, 'BOOKING_STARTED', 'This booking has already started, so it can no longer be moved.'))
        self.assertFalse(self.client.get(detail_url(started)).data['actions']['reschedule'])
        cancelled = self.book('Riya')
        cancel_booking(cancelled, reason_code=CancelReason.OTHER, actor=self.admin)
        res = self.move(cancelled, self.day + timedelta(days=1))
        self.assertEqual((res.data['error'], res.data['message']),
                         ('BOOKING_CANCELLED', 'This booking is cancelled, so it can no longer be moved.'))

    def test_never_onto_another_live_booking_of_the_same_child(self):
        demo = self.book('Riya')
        tomorrow = self.day + timedelta(days=1)
        diagnostic = self.same_lead(demo, DIAGNOSTIC, day=tomorrow, at=EVENING)
        self.assertEqual(diagnostic.lead_id, demo.lead_id)
        res = self.move(demo, tomorrow)
        self.assertEqual((res.status_code, res.data['error']), (409, 'LEAD_TIME_CONFLICT'))
        self.assertEqual((res.data['conflict']['booking_type'], res.data['conflict']['booking_id']), ('DIAGNOSTIC', str(diagnostic.id)))
        self.assertEqual(res.data['conflict']['message'], f'Already has a Diagnostic booking from 7:30 PM to 8:30 PM IST on '
                                                          f'{tomorrow:%a} {tomorrow.day} {tomorrow:%b} {tomorrow.year}.')
        self.assertNotIn('Riya', json.dumps(res.data))
        # Cancelled, it no longer holds the time.
        cancel_booking(diagnostic, reason_code=CancelReason.OTHER, actor=self.admin)
        self.assertEqual(self.move(demo, tomorrow).status_code, 201)

    def test_reasons_are_codes_and_the_body_is_checked(self):
        booking = self.book('Riya')
        tomorrow = (self.day + timedelta(days=1)).isoformat()
        for body, field in (({'date': tomorrow, 'time': '19:30'}, 'reason'),
                            ({'date': tomorrow, 'time': '19:30', 'reason': 'NO_SHOW'}, 'reason'),
                            ({'date': '01/11/2026', 'time': '19:30', 'reason': 'OTHER'}, 'date'),
                            ({'date': tomorrow, 'time': '7:30 pm', 'reason': 'OTHER'}, 'time')):
            with self.subTest(field=field, body=body):
                res = self.client.post(ops_url(booking, 'reschedule'), body, format='json')
                self.assertEqual((res.status_code, res.data['error']), (400, 'VALIDATION_ERROR'))
                self.assertIn(field, res.data['fields'])


# ------------------------------------------------------ options and history

class NeverStartedRescheduleTests(OperationsTestCase):
    """D3: a booking whose scheduled time passed with no start never happened, so the Admin may still move it."""

    def test_after_its_scheduled_time_and_after_its_slot_ended(self):
        past = self.last_week('Old Kid')
        detail = self.client.get(detail_url(past)).data
        self.assertEqual((detail['activity_state'], detail['actions']['reschedule']), ('NOT_STARTED', True))
        res = self.move(past, self.day + timedelta(days=1))
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.data)
        past.refresh_from_db()
        self.assertEqual(past.status, BookingStatus.RESCHEDULED)
        self.assertEqual(res.data['booking']['activity_state'], 'UPCOMING')

    def test_never_beside_a_live_booking_of_the_same_type(self):
        stale = self.last_week('Zoya')
        # The parent booked a Demo again once the old slot was over: that one is the child's live Demo (Q26).
        again, created = create_booking(
            request(student='Zoya', phone='0' + stale.lead.phone_number, day=self.day, at=EVENING),
        )
        self.assertTrue(created)
        self.assertEqual(again.lead_id, stale.lead_id)
        detail = self.client.get(detail_url(stale)).data
        self.assertFalse(detail['actions']['reschedule'])
        options = self.client.get(ops_url(stale, 'reschedule-options')).data
        self.assertEqual((options['reschedulable'], options['refusal']['code']), (False, 'LEAD_ALREADY_BOOKED'))
        res = self.move(stale, self.day + timedelta(days=1))
        self.assertEqual((res.status_code, res.data['error']), (409, 'LEAD_ALREADY_BOOKED'))
        stale.refresh_from_db()
        self.assertEqual((stale.status, self.kinds(stale)), (BookingStatus.BOOKED, [BookingEventKind.CREATED]))


# ---------------------------------------------- the calendar and same-day moves

def indian(clock, days=0):
    """The instant of ``clock`` (Indian time) on the Indian date ``days`` from today: a pinned server clock."""
    return datetime.combine(indian_today() + timedelta(days=days), clock, tzinfo=BOOKING_TIMEZONE)


class RescheduleWindowTests(OperationsTestCase):
    """
    The picker's calendar (``?date=``) and moves beyond the pages' window: any
    Indian date from today through RESCHEDULE_DAYS days on, a time starting at
    least RESCHEDULE_MIN_LEAD (30 minutes) after the server's clock -- for both
    types -- with every other rule of a move as it was. The server clock is
    pinned on today's Indian date; the schedule is MORNING 10:00 and EVENING 19:30.
    """

    def options(self, booking, day=None, client=None):
        params = {} if day is None else {'date': day if isinstance(day, str) else day.isoformat()}
        return (client or self.client).get(ops_url(booking, 'reschedule-options'), params)

    def clock(self, at):
        return mock.patch('django.utils.timezone.now', return_value=at)

    def times(self, data):
        return [(entry['date'], [slot['time'] for slot in entry['slots']]) for entry in data['dates']]

    def test_the_date_buttons_keep_the_pages_window(self):
        today = indian_today()
        for booking_type in (DEMO, DIAGNOSTIC):
            with self.subTest(booking_type=booking_type), self.clock(indian(time(9, 0))):
                booking = self.book(f'Riya {booking_type}', booking_type=booking_type)
                data = self.options(booking).data
                self.assertEqual([entry['date'] for entry in data['dates']],
                                 [day.isoformat() for day in booking_window(booking_type)])
                self.assertEqual(data['dates'][0]['date'], (today + timedelta(days=1)).isoformat())
                self.assertEqual(data['window'], {
                    'today': today.isoformat(), 'first': today.isoformat(),
                    'last': (today + timedelta(days=RESCHEDULE_DAYS)).isoformat(), 'min_lead_minutes': 30,
                })

    def test_today_offers_only_times_starting_thirty_minutes_on_or_later(self):
        today = indian_today().isoformat()
        tomorrow = (indian_today() + timedelta(days=1)).isoformat()
        cases = [
            (time(9, 0), ['10:00', '19:30']),
            (time(9, 30), ['10:00', '19:30']),  # exactly 30 minutes ahead is still offered
            (time(9, 31), ['19:30']),
            (time(19, 0), ['19:30']),
            (time(19, 1), []),  # nothing left today: the calendar starts tomorrow
        ]
        for booking_type in (DEMO, DIAGNOSTIC):
            booking = self.book(f'Riya {booking_type}', booking_type=booking_type)
            for clock, shown in cases:
                with self.subTest(booking_type=booking_type, clock=str(clock)), self.clock(indian(clock)):
                    data = self.options(booking, today).data
                    self.assertEqual(self.times(data), [(today, shown)])
                    self.assertTrue(all(slot['bookable'] for slot in data['dates'][0]['slots']))
                    self.assertEqual(data['window']['first'], today if shown else tomorrow)

    def test_a_calendar_date_outside_the_window_is_refused(self):
        booking = self.book('Riya')
        today = indian_today()
        last = today + timedelta(days=RESCHEDULE_DAYS)
        with self.clock(indian(time(9, 0))):
            cases = [
                (today - timedelta(days=1), 'DATE_OUT_OF_WINDOW'),
                (last + timedelta(days=1), 'DATE_OUT_OF_WINDOW'),
                ('tomorrow', 'VALIDATION_ERROR'),
                ('2026-13-01', 'VALIDATION_ERROR'),
                ('', 'VALIDATION_ERROR'),
            ]
            for day, code in cases:
                with self.subTest(day=str(day)):
                    res = self.options(booking, day)
                    self.assertEqual((res.status_code, res.data['error']), (400, code))
            res = self.options(booking, last)
            self.assertEqual((res.status_code, self.times(res.data)), (200, [(last.isoformat(), ['10:00', '19:30'])]))

    def test_a_move_later_today_or_up_to_thirty_days_on(self):
        today = indian_today()
        for booking_type in (DEMO, DIAGNOSTIC):
            for day in (today, today + timedelta(days=RESCHEDULE_DAYS)):
                with self.subTest(booking_type=booking_type, day=str(day)), self.clock(indian(time(9, 0))):
                    old = self.book(f'Riya {booking_type} {day}', booking_type=booking_type)
                    res = self.move(old, day, at=MORNING)
                    self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.data)
                    new = type(old).objects.select_related('slot').get(pk=res.data['booking']['id'])
                    old.refresh_from_db()
                    self.assertEqual((new.slot.local_date, new.slot.local_time, new.status, new.rescheduled_from_id),
                                     (day, MORNING, BookingStatus.BOOKED, old.id))
                    self.assertEqual((old.status, old.slot.local_date), (BookingStatus.RESCHEDULED, self.day))
                    self.assertEqual(self.kinds(old), [BookingEventKind.CREATED, BookingEventKind.RESCHEDULED])
                    self.assertEqual(self.kinds(new), [BookingEventKind.CREATED])
                    self.assertTrue(ActivityLog.objects.filter(action='booking.reschedule', entity_id=str(new.id)).exists())
                    self.assertTrue(CommunicationEvent.objects.filter(
                        kind=EventKind.BOOKING_RESCHEDULED, subject_id=old.id, payload__new_booking_id=str(new.id),
                    ).exists())

    def test_a_time_starting_too_soon_or_already_started_is_refused(self):
        today = indian_today()
        for booking_type in (DEMO, DIAGNOSTIC):
            booking = self.book(f'Riya {booking_type}', booking_type=booking_type)
            for clock in (time(9, 31), time(10, 0), time(10, 30)):
                with self.subTest(booking_type=booking_type, clock=str(clock)), self.clock(indian(clock)):
                    res = self.move(booking, today, at=MORNING)
                    self.assertEqual((res.status_code, res.data['error']), (409, 'SLOT_TOO_SOON'))
            # The service itself, with its clock given, refuses it as well.
            with self.assertRaises(SlotTooSoon):
                reschedule_booking(booking, today, MORNING, reason_code=RescheduleReason.OTHER, now=indian(time(9, 45)))
            booking.refresh_from_db()
            self.assertEqual((booking.status, self.kinds(booking)), (BookingStatus.BOOKED, [BookingEventKind.CREATED]))
            # Rolled back whole: not even the new slot's row is left.
            self.assertFalse(BookingSlot.objects.filter(booking_type=booking_type, local_date=today).exists())

    def test_slot_capacity_still_holds_on_a_calendar_date(self):
        today = indian_today()
        with self.clock(indian(time(9, 0))):
            movers = [self.book(f'Kid {n}', at=MORNING if n < 2 else EVENING) for n in range(4)]
            for booking in movers[:3]:
                self.assertEqual(self.move(booking, today, at=EVENING).status_code, status.HTTP_201_CREATED)
            slot = next(s for s in self.options(movers[3], today).data['dates'][0]['slots'] if s['time'] == '19:30')
            self.assertEqual((slot['bookable'], slot['unavailable_reason'], slot['seats_left']), (False, 'FULL', 0))
            res = self.move(movers[3], today, at=EVENING)
        self.assertEqual((res.status_code, res.data['error']), (409, 'SLOT_FULL'))
        self.assertEqual(DemoBooking.objects.filter(slot__local_date=today, status=BookingStatus.BOOKED).count(), 3)
        # A closed slot beyond the date buttons is as closed as one among them.
        later = today + timedelta(days=12)
        close_slot(DEMO, later, MORNING, actor=self.admin)
        with self.clock(indian(time(9, 0))):
            slot = next(s for s in self.options(movers[3], later).data['dates'][0]['slots'] if s['time'] == '10:00')
            self.assertEqual((slot['bookable'], slot['unavailable_reason']), (False, 'CLOSED'))
            res = self.move(movers[3], later, at=MORNING)
        self.assertEqual((res.status_code, res.data['error']), (409, 'SLOT_FULL'))

    def test_tutor_and_child_conflicts_still_hold_on_a_calendar_date(self):
        today = indian_today()
        booking = self.book('Riya')
        assign_tutor(booking, self.tutor_a, actor=self.admin)
        self.class_for(self.tutor_a, indian(time(19, 0)), 'EDP31')
        with self.clock(indian(time(9, 0))):
            slots = {s['time']: s for s in self.options(booking, today).data['dates'][0]['slots']}
            self.assertEqual((slots['10:00']['tutor_free'], slots['19:30']['tutor_free'],
                              slots['19:30']['tutor_reason']['code']), (True, False, 'CLASS_CONFLICT'))
            # Busy then: the move goes ahead, and the booking waits for a tutor (Q24).
            res = self.move(booking, today, at=EVENING)
        self.assertEqual((res.status_code, res.data['tutor']['carried_over']), (201, False))
        moved = DemoBooking.objects.get(pk=res.data['booking']['id'])
        self.assertIsNone(moved.assigned_tutor_id)
        # The child's own Diagnostic, moved to today's morning, keeps their Demo from that time (Q26).
        diagnostic = self.same_lead(moved, DIAGNOSTIC, day=self.day, at=MORNING)
        with self.clock(indian(time(9, 0))):
            reschedule_booking(diagnostic, today, MORNING, reason_code=RescheduleReason.OTHER, actor=self.admin)
            slot = next(s for s in self.options(moved, today).data['dates'][0]['slots'] if s['time'] == '10:00')
            self.assertEqual((slot['bookable'], slot['unavailable_reason']), (False, 'LEAD_TIME_CONFLICT'))
            res = self.move(moved, today, at=MORNING)
        self.assertEqual((res.status_code, res.data['error']), (409, 'LEAD_TIME_CONFLICT'))

    def test_the_pages_invitations_and_new_redemos_keep_their_window(self):
        today = indian_today()
        lead = self.book('Riya').lead
        with self.clock(indian(time(9, 0))):
            now = timezone.now()
            self.assertEqual([entry['date'] for entry in calendar(DEMO)],
                             [(today + timedelta(days=n)).isoformat() for n in range(1, 8)])
            for day in (today, today + timedelta(days=8)):
                with self.subTest(day=str(day)):
                    with self.assertRaises(DateOutOfWindow):
                        create_booking(request(student='Late', phone='0507009999', day=day, at=EVENING))
                    # The Demo invitation and a new Re-Demo both book through this check.
                    with self.assertRaises(DateOutOfWindow):
                        _check_offered(DEMO, day, EVENING, now)
            # The Re-Demo pickers read the pages' window, never the reschedule's.
            self.assertEqual([entry['date'] for entry in coordination.slot_options(DEMO, lead, None, now)],
                             [day.isoformat() for day in booking_window(DEMO)])

    def test_only_the_reschedule_permission_reaches_the_calendar(self):
        booking = self.book('Riya')
        today = indian_today()
        callers = [self.mentor, self.tutor_a, self.bde, account('sales_cal', role='SALES_TL'), None]
        with self.clock(indian(time(9, 0))):
            for user in callers:
                client = APIClient()
                if user is not None:
                    client.force_authenticate(user=user)
                with self.subTest(caller=getattr(user, 'role', 'anonymous')):
                    self.assertEqual(self.options(booking, today, client=client).status_code, status.HTTP_403_FORBIDDEN)
                    self.assertEqual(self.move(booking, today, client=client).status_code, status.HTTP_403_FORBIDDEN)
            group = RoleGroup.objects.select_related('group').get(role='ADMIN').group
            group.permissions.remove(Permission.objects.get(codename='reschedule_booking'))
            client = APIClient()
            client.force_authenticate(user=type(self.admin).objects.get(pk=self.admin.pk))
            self.assertEqual(self.options(booking, today, client=client).status_code, status.HTTP_403_FORBIDDEN)
            self.assertEqual(self.move(booking, today, client=client).status_code, status.HTTP_403_FORBIDDEN)
        booking.refresh_from_db()
        self.assertEqual((booking.status, self.kinds(booking)), (BookingStatus.BOOKED, [BookingEventKind.CREATED]))

    @override_settings(COMMUNICATIONS_OUTBOX_INLINE=True)
    def test_a_same_day_move_is_planned_from_its_new_slot(self):
        today = indian_today()
        booking = self.book('Riya', booking_type=DIAGNOSTIC)
        with self.clock(indian(time(9, 0))):
            res = self.move(booking, today, at=EVENING)
        new = DiagnosticBooking.objects.select_related('slot').get(pk=res.data['booking']['id'])
        tasks = {task.step: task for task in CommunicationTask.objects.filter(diagnostic_booking=new)}
        starts_at = new.slot.starts_at
        self.assertEqual(starts_at, indian(EVENING))
        # Within 12 hours of its start the confirmation request is due at once; the call opens 15 minutes before.
        self.assertEqual(tasks[Step.CONFIRMATION_REQUEST].due_at, indian(time(9, 0)))
        self.assertEqual(tasks[Step.PRE_ACTIVITY_CALL].active_from, starts_at - timedelta(minutes=15))
        self.assertEqual(tasks[Step.PARENT_CONFIRMATION].due_at, starts_at)
        self.assertFalse(CommunicationTask.objects.filter(diagnostic_booking=booking, status=TaskStatus.OPEN).exists())


class OptionsAndHistoryTests(OperationsTestCase):
    def slot(self, data, day, at):
        dates = {entry['date']: entry['slots'] for entry in data['dates']}
        return next(slot for slot in dates[day.isoformat()] if slot['time'] == at.strftime('%H:%M'))

    def test_where_a_booking_may_move(self):
        booking = self.book('Riya')
        assign_tutor(booking, self.tutor_a, actor=self.admin)
        d1, d2, d3 = (self.day + timedelta(days=n) for n in (1, 2, 3))
        self.class_for(self.tutor_a, self.ist(MORNING, days=1), 'EDP92')
        self.same_lead(booking, DIAGNOSTIC, day=d1, at=EVENING)
        close_slot(DEMO, d2, MORNING, actor=self.admin)
        for _ in range(3):
            self.book('Filler', day=d3)

        data = self.client.get(ops_url(booking, 'reschedule-options')).data
        self.assertEqual((data['reschedulable'], data['refusal'], data['tutor']['id']), (True, None, str(self.tutor_a.id)))
        self.assertEqual(len(data['dates']), 7)
        current = self.slot(data, self.day, EVENING)
        self.assertEqual((current['bookable'], current['unavailable_reason']), (False, 'CURRENT'))
        clash = self.slot(data, d1, EVENING)
        self.assertEqual((clash['bookable'], clash['unavailable_reason'], clash['lead_conflict']['booking_type']),
                         (False, 'LEAD_TIME_CONFLICT', 'DIAGNOSTIC'))
        self.assertEqual(self.slot(data, d2, MORNING)['unavailable_reason'], 'CLOSED')
        full = self.slot(data, d3, EVENING)
        self.assertEqual((full['unavailable_reason'], full['seats_left'], full['status']), ('FULL', 0, 'Fully Booked'))
        busy = self.slot(data, d1, MORNING)
        self.assertEqual((busy['bookable'], busy['seats_left'], busy['tutor_free'], busy['tutor_reason']['code']),
                         (True, 3, False, 'CLASS_CONFLICT'))
        free = self.slot(data, d2, EVENING)
        self.assertEqual((free['bookable'], free['tutor_free'], free['tutor_reason']), (True, True, None))
        self.assertNotIn('Riya', json.dumps(data))

        cancel_booking(booking, reason_code=CancelReason.OTHER, actor=self.admin)
        data = self.client.get(ops_url(booking, 'reschedule-options')).data
        self.assertEqual((data['reschedulable'], data['refusal']['code']), (False, 'BOOKING_CANCELLED'))

    def test_the_timeline_reads_back_who_and_why(self):
        old = self.book('Riya')
        assign_tutor(old, self.tutor_a, actor=self.admin)
        new = DemoBooking.objects.get(pk=self.move(old, self.day + timedelta(days=1)).data['booking']['id'])
        self.cancel(new)
        data = self.client.get(ops_url(new, 'history')).data
        self.assertEqual([(link['id'], link['current']) for link in data['chain']], [(str(old.id), False), (str(new.id), True)])
        events = data['events']
        self.assertEqual([event['kind'] for event in events], [
            'CREATED', 'TUTOR_ASSIGNED', 'RESCHEDULED', 'CREATED', 'TUTOR_ASSIGNED', 'CANCELLED',
        ])
        assigned, moved, cancelled = events[1], events[2], events[5]
        self.assertEqual((assigned['details']['new_tutor']['full_name'], assigned['actor']['full_name']), ('Tutor Anu', 'Admin One'))
        self.assertEqual(moved['details']['reason'], {'code': 'PARENT_REQUEST', 'label': 'Parent asked to move'})
        self.assertEqual((moved['details']['old_slot']['date'], moved['details']['new_slot']['date']),
                         (self.day.isoformat(), (self.day + timedelta(days=1)).isoformat()))
        self.assertEqual(cancelled['details']['reason'], {'code': 'PARENT_REQUEST', 'label': 'Parent asked to cancel'})
        self.assertIsNone(events[0]['actor'])  # the public booking page
        for private in (*PRIVATE, 'Riya'):
            self.assertNotIn(private, json.dumps(data))
        # Read from the first booking, the timeline is the same chain.
        self.assertEqual(len(self.client.get(ops_url(old, 'history')).data['events']), 6)


# -------------------------------------------------------------- permissions

class OperationPermissionTests(OperationsTestCase):
    def test_only_holders_of_the_admin_permissions_reach_the_operations(self):
        booking = self.book('Riya')
        callers = {
            'tutor': self.tutor_a, 'mentor': self.mentor, 'sales_tl': account('sales_ops', role='SALES_TL'),
            # A BDE holds cancel_booking for their own leads (Q22) -- never these Admin routes.
            'bde': self.bde, 'student': account('parent_ops', role='STUDENT'),
        }
        tomorrow = (self.day + timedelta(days=1)).isoformat()
        calls = [('get', 'history', None), ('get', 'reschedule-options', None),
                 ('post', 'reschedule', {'date': tomorrow, 'time': '19:30', 'reason': 'OTHER'}),
                 ('post', 'cancel', {'reason': 'OTHER'})]
        for name, user in [*callers.items(), ('anonymous', None)]:
            client = APIClient()
            if user is not None:
                client.force_authenticate(user=user)
            for method, action, body in calls:
                with self.subTest(caller=name, action=action):
                    res = getattr(client, method)(ops_url(booking, action), body, format='json')
                    self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        booking.refresh_from_db()
        self.assertEqual((booking.status, self.kinds(booking)), (BookingStatus.BOOKED, [BookingEventKind.CREATED]))

    def test_each_operation_needs_its_own_permission(self):
        booking = self.book('Riya')
        group = RoleGroup.objects.select_related('group').get(role='ADMIN').group
        group.permissions.remove(Permission.objects.get(codename='reschedule_booking'))
        client = APIClient()
        client.force_authenticate(user=type(self.admin).objects.get(pk=self.admin.pk))
        self.assertEqual(client.get(detail_url(booking)).data['actions'],
                         {'cancel': True, 'no_show': False, 'reschedule': False, 'demo_invite': False, 'request_redemo': False})
        self.assertEqual(self.move(booking, self.day + timedelta(days=1), client=client).status_code, 403)
        self.assertEqual(client.get(ops_url(booking, 'reschedule-options')).status_code, 403)
        self.assertEqual(self.cancel(booking, client=client).status_code, 200)

    def test_a_superuser_whatever_their_role(self):
        booking = self.book('Riya')
        client = APIClient()
        client.force_authenticate(user=account('su_ops', role='MENTOR', is_superuser=True))
        self.assertEqual(self.move(booking, self.day + timedelta(days=1), client=client).status_code, 201)


class DjangoAdminActionTests(OperationsTestCase):
    def run_action(self, name, queryset):
        model_admin = DemoBookingAdmin(DemoBooking, django_admin.site)
        model_admin.message_user = mock.Mock()
        req = RequestFactory().post('/admin/')
        req.user = self.admin
        getattr(model_admin, name)(req, queryset)
        return model_admin.message_user.call_args[0][1]

    def test_cancel_with_other_and_no_show_only_for_started_slots(self):
        ahead, past = self.book('Riya'), self.last_week('Old Kid')
        message = self.run_action('mark_selected_no_show', DemoBooking.objects.filter(pk__in=[ahead.pk, past.pk]))
        self.assertEqual(message, 'Cancelled 1 booking(s). Skipped 1 that could not be cancelled this way.')
        past.refresh_from_db()
        ahead.refresh_from_db()
        self.assertEqual((past.cancel_reason_code, ahead.status), ('NO_SHOW', BookingStatus.BOOKED))
        self.run_action('cancel_selected', DemoBooking.objects.filter(pk=ahead.pk))
        ahead.refresh_from_db()
        self.assertEqual((ahead.status, ahead.cancel_reason_code, ahead.cancel_reason), (BookingStatus.CANCELLED, 'OTHER', ''))


# --------------------------------------------------------------- concurrency

@skipUnless(connection.vendor == 'postgresql', 'the slot locks need PostgreSQL row locking')
class RescheduleRaceTests(TransactionTestCase):
    """Two moves into the last seat of one slot, at once: one gets it, the other is told the slot is full."""

    def test_the_last_seat_goes_once(self):
        schedule()
        admin = account('admin_race', role='ADMIN')
        day = indian_today() + timedelta(days=2)
        target = day + timedelta(days=1)
        first, _ = create_booking(request(student='A', phone='0507001001', day=day, at=EVENING))
        second, _ = create_booking(request(student='B', phone='0507001002', day=day, at=MORNING))
        for n in range(2):
            create_booking(request(student=f'F{n}', phone=f'050700200{n}', day=target, at=EVENING))
        barrier = threading.Barrier(2)
        outcomes = []

        def run(booking):
            try:
                barrier.wait(timeout=10)
                reschedule_booking(booking, target, EVENING, reason_code=RescheduleReason.OTHER, actor=admin)
                outcomes.append('moved')
            except SlotFull:
                outcomes.append('full')
            except Exception as exc:  # reported in the assertion, not lost in the thread
                outcomes.append(repr(exc))
            finally:
                connection.close()

        threads = [threading.Thread(target=run, args=(booking,)) for booking in (first, second)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        self.assertEqual(sorted(outcomes), ['full', 'moved'])
        self.assertEqual(DemoBooking.objects.filter(slot__local_date=target, status=BookingStatus.BOOKED).count(), 3)
        self.assertEqual(DiagnosticBooking.objects.count(), 0)
