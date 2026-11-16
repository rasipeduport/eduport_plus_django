"""
The Re-Demo workflow's second pass (2026-11-08): closing and reopening a
request, every earlier tutor of a chain kept off it, the remarks locked once
it starts, the student's own clock in scheduling (by time and by tutor) and in
the booking's details, the list's order, counts and filters, the "Re-Demo
bookings" filter of the Demo lists, and the messages a BDE sends by hand.
"""
import json
import threading
import time as clock
from datetime import date, datetime, time, timedelta

from django.contrib.auth.models import Permission
from django.db import connection, transaction
from django.test import TransactionTestCase

from accounts.models import RoleGroup

from activity.models import ActivityLog
from communications.models import CommunicationTask, Message
from communications.redemo_messages import redemo_messages

from . import admissions, coordination, redemos, student_timezones
from .booking_service import (
    _locked_booking,
    BookingNotOwned,
    DateOutOfWindow,
    InvalidReason,
    RedemoClosed,
    RedemoCompleted,
    RedemoEarlierTutor,
    RedemoOriginalTutor,
    RedemoRemarksLocked,
    RedemoScheduled,
    assign_tutor,
    cancel_booking,
    close_redemo,
    create_booking,
    reopen_redemo,
    request_redemo,
    schedule_redemo,
)
from .lead_status import LeadStatus, with_status
from .models import (
    BookingEvent,
    BookingEventKind,
    BookingStatus,
    CancelReason,
    DemoBooking,
    Lead,
    RedemoCloseReason,
    ReDemoRequest,
    ReDemoStatus,
)
from .redemo_chain import request_of
from zoneinfo import ZoneInfo

from .scheduling import BOOKING_TIMEZONE, booking_window, slot_instants
from .tests_booking import EVENING, MORNING, NOW, account, request, schedule, start
from .tests_redemos import (
    AFTER,
    MEET,
    REASON,
    REDEMO_DAY,
    REMARKS,
    RedemoApiTestCase,
    RedemoTestCase,
    complete,
    completed_demo,
    redemo_url,
    row,
    shown_to_tutor,
)

DECLINED = RedemoCloseReason.PARENT_DECLINED


def slot_of(dates, day, at):
    """The slot of ``dates`` (a picker's) at the Indian ``day`` and ``at``."""
    entry = next(entry for entry in dates if entry['date'] == day.isoformat())
    return next(slot for slot in entry['slots'] if slot['time'] == at.strftime('%H:%M'))


def lead_status(lead):
    return with_status(Lead.objects.filter(pk=lead.pk), AFTER).get().lead_status


# ------------------------------------------------------------------ closing and reopening

class CloseReopenTests(RedemoTestCase):
    def test_a_waiting_request_closes_for_a_code_and_reopens(self):
        redemo = self.ask()
        with self.assertRaises(InvalidReason):
            close_redemo(redemo, 'The parent said no', actor=self.bde, owner_bde=self.bde)
        before = list(BookingEvent.objects.filter(demo_booking=self.demo).values())
        kept = row(DemoBooking, self.demo.pk, 'status', 'updated_at')

        closed, changed = close_redemo(redemo, DECLINED, actor=self.bde, owner_bde=self.bde, now=AFTER)
        self.assertTrue(changed)
        self.assertEqual((closed.closed_at, closed.closed_by, closed.close_reason_code), (AFTER, self.bde, DECLINED))
        self.assertEqual(self.status(redemo), ReDemoStatus.CLOSED)
        # Its Demo reads Completed again -- for the lead too -- and keeps everything else.
        self.assertEqual(DemoBooking.objects.get(pk=self.demo.pk).status, BookingStatus.COMPLETED)
        self.assertEqual(row(DemoBooking, self.demo.pk, 'status', 'updated_at'), kept, 'everything else is as it was')
        self.assertEqual(lead_status(self.lead), LeadStatus.DEMO_COMPLETED)
        # Nothing waits to be scheduled any more.
        self.assertEqual(admissions._pending(AFTER, True, False)['redemo_scheduling'], 0)
        event = BookingEvent.objects.filter(demo_booking=self.demo).latest('created_at')
        self.assertEqual((event.kind, event.actor, event.data), (BookingEventKind.REDEMO_CLOSED, self.bde, {
            'from_status': 'REDEMO_REQUIRED', 'to_status': 'COMPLETED', 'reason_code': DECLINED,
            'redemo_request_id': str(redemo.pk),
        }))
        # History is only added to: the events before are as they were.
        self.assertEqual(list(BookingEvent.objects.filter(demo_booking=self.demo).values())[:len(before)], before)
        entry = ActivityLog.objects.filter(action='redemo.close').get()
        self.assertEqual((entry.context['reason_code'], entry.context['via']), (DECLINED, 'bde_workspace'))
        self.assertNotIn(REASON, json.dumps(entry.context))

        # Closing again changes nothing.
        self.assertEqual(close_redemo(redemo, DECLINED, actor=self.admin)[1], False)
        self.assertEqual(BookingEvent.objects.filter(kind=BookingEventKind.REDEMO_CLOSED).count(), 1)

        reopened, changed = reopen_redemo(redemo, actor=self.admin, now=AFTER)
        self.assertTrue(changed)
        self.assertEqual((reopened.closed_at, reopened.closed_by, reopened.close_reason_code), (None, None, ''))
        self.assertEqual(self.status(redemo), ReDemoStatus.AWAITING_SCHEDULING)
        self.assertEqual(DemoBooking.objects.get(pk=self.demo.pk).status, BookingStatus.REDEMO_REQUIRED)
        self.assertEqual(lead_status(self.lead), LeadStatus.DEMO_REDEMO_REQUIRED)
        self.assertEqual(admissions._pending(AFTER, True, False)['redemo_scheduling'], 1)
        self.assertEqual(BookingEvent.objects.filter(demo_booking=self.demo).latest('created_at').kind,
                         BookingEventKind.REDEMO_REOPENED)
        self.assertEqual(reopen_redemo(redemo, actor=self.admin)[1], False)
        # ... and it is scheduled as before.
        self.assertEqual(self.book(redemo).redemo_for_id, redemo.pk)

    def test_only_with_nothing_booked_for_it(self):
        redemo = self.ask()
        booking = self.book(redemo)
        with self.assertRaises(RedemoScheduled):
            close_redemo(redemo, DECLINED, actor=self.admin)
        cancel_booking(booking, reason_code=CancelReason.PARENT_REQUEST, actor=self.admin, now=AFTER)
        self.assertEqual(redemos.attention(ReDemoRequest.objects.get(pk=redemo.pk),
                                           redemos.state(ReDemoRequest.objects.get(pk=redemo.pk), AFTER), AFTER),
                         [redemos.LAST_ATTEMPT_CANCELLED])
        self.assertTrue(close_redemo(redemo, DECLINED, actor=self.admin)[1])
        reopen_redemo(redemo, actor=self.admin)
        complete(self.book(redemo, day=date(2026, 11, 1)), self.tutor)
        with self.assertRaises(RedemoCompleted):
            close_redemo(redemo, DECLINED, actor=self.admin)

    def test_a_closed_request_is_reopened_never_asked_for_again_nor_scheduled(self):
        redemo = self.ask()
        close_redemo(redemo, DECLINED, actor=self.admin)
        demo = DemoBooking.objects.get(pk=self.demo.pk)
        self.assertEqual(request_of(demo).pk, redemo.pk)
        with self.assertRaises(RedemoClosed):
            request_redemo(demo, REASON, actor=self.bde, now=AFTER)
        with self.assertRaises(RedemoClosed):
            self.book(redemo)
        self.assertEqual(ReDemoRequest.objects.count(), 1)
        self.assertFalse(coordination.booking_actions(demo, AFTER, self.admin)['request_redemo'])
        self.assertFalse(DemoBooking.objects.filter(redemo_for=redemo).exists())

    def test_a_bde_closes_and_reopens_only_their_own_leads(self):
        redemo = self.ask()
        with self.assertRaises(BookingNotOwned):
            close_redemo(redemo, DECLINED, actor=self.other_bde, owner_bde=self.other_bde)
        close_redemo(redemo, DECLINED, actor=self.admin)
        with self.assertRaises(BookingNotOwned):
            reopen_redemo(redemo, actor=self.other_bde, owner_bde=self.other_bde)
        self.assertEqual(self.status(redemo), ReDemoStatus.CLOSED)


class ConcurrentCloseTests(TransactionTestCase):
    def setUp(self):
        schedule()
        self.admin = account('admin_race', role='ADMIN')
        self.bde = account('bde_race', role='BDE')
        self.tutor = account('tutor_race', role='TUTOR')
        self.demo = completed_demo()
        Lead.objects.filter(pk=self.demo.lead_id).update(owner_bde=self.bde, owner_assigned_at=NOW)

    def test_a_close_and_a_scheduling_at_once_never_both_go_through(self):
        redemo = request_redemo(self.demo, REASON, actor=self.bde, now=AFTER)
        barrier = threading.Barrier(2)
        outcomes = [None, None]

        def run(index, call):
            try:
                barrier.wait(timeout=10)
                outcomes[index] = call()
            except Exception as exc:
                outcomes[index] = type(exc).__name__
            finally:
                connection.close()

        calls = [
            lambda: close_redemo(redemo, DECLINED, actor=self.bde, owner_bde=self.bde, now=AFTER)[1],
            lambda: schedule_redemo(redemo, self.tutor, REDEMO_DAY, EVENING, actor=self.admin, now=AFTER).pk,
        ]
        threads = [threading.Thread(target=run, args=(i, call)) for i, call in enumerate(calls)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        redemo = ReDemoRequest.objects.get(pk=redemo.pk)
        booked = DemoBooking.objects.filter(redemo_for=redemo, status=BookingStatus.BOOKED).exists()
        # Exactly one went through: closed with nothing booked, or booked and left open.
        self.assertNotEqual(redemo.closed_at is not None, booked, outcomes)
        self.assertTrue({'RedemoScheduled', 'RedemoClosed'} & set(map(str, outcomes)), outcomes)


# ------------------------------------------------------------------ tutors and remarks

class ChainTutorTests(RedemoTestCase):
    def test_no_tutor_of_an_earlier_demo_of_the_chain_teaches_a_later_redemo(self):
        first = self.ask()
        booking = complete(self.book(first), self.tutor)
        later = datetime(2026, 11, 1, 12, 0, tzinfo=BOOKING_TIMEZONE)
        second = request_redemo(booking, 'Still unsure.', actor=self.admin, now=later)
        third_tutor = account('tutor_tara', role='TUTOR')
        redemo2 = schedule_redemo(second, third_tutor, date(2026, 11, 4), EVENING, actor=self.admin, now=later)
        # Handing it to the first Demo's tutor afterwards is refused too, with the earlier tutor's message.
        with self.assertRaises(RedemoEarlierTutor):
            assign_tutor(redemo2, self.original_tutor, now=later)
        with self.assertRaises(RedemoOriginalTutor) as caught:
            assign_tutor(redemo2, self.tutor, now=later)
        self.assertIs(type(caught.exception), RedemoOriginalTutor, "the Demo it repeats, not an earlier one")
        # The by-time pickers keep both off it too.
        options = redemos.slot_tutor_options(ReDemoRequest.objects.get(pk=second.pk), date(2026, 11, 4), MORNING, later)
        eligible = {tutor['id']: (tutor['eligible'], tutor['original'], tutor['earlier']) for tutor in options['tutors']}
        self.assertEqual(eligible[str(self.tutor.pk)], (False, True, False))
        self.assertEqual(eligible[str(self.original_tutor.pk)], (False, False, True))
        availability = {row['id']: row for row in coordination.tutor_availability(redemo2.slot, redemo2)}
        self.assertEqual(availability[str(self.original_tutor.pk)]['reason']['code'], 'REDEMO_ORIGINAL_TUTOR')
        self.assertEqual(availability[str(self.original_tutor.pk)]['reason']['message'],
                         coordination.EARLIER_TUTOR_REASON)
        self.assertEqual(availability[str(self.tutor.pk)]['reason']['message'], coordination.ORIGINAL_TUTOR_REASON)
        # A tutor nobody in the chain is may still take it.
        fourth = account('tutor_fae', role='TUTOR')
        self.assertEqual(assign_tutor(redemo2, fourth, now=later)[0].assigned_tutor, fourth)


class RemarksLockTests(RedemoTestCase):
    def test_the_remarks_stay_as_the_tutor_read_them_once_the_redemo_starts(self):
        redemo = self.ask()
        booking = self.book(redemo)
        self.assertTrue(redemos.set_remarks(redemo, 'Bring the worksheet.', self.admin)[1])
        booking = start(booking)
        with self.assertRaises(RedemoRemarksLocked):
            redemos.set_remarks(redemo, 'Too late.', self.admin)
        detail = redemos.redemo_detail(redemos.listed().get(pk=redemo.pk), AFTER, self.admin)
        self.assertEqual((detail['remarks_locked'], detail['actions']['edit_remarks']), (True, False))
        self.assertEqual(ReDemoRequest.objects.get(pk=redemo.pk).admin_remarks, 'Bring the worksheet.')
        # A started Re-Demo marked a no-show leaves the request to schedule again: its remarks open again.
        cancel_booking(booking, reason_code=CancelReason.NO_SHOW, actor=self.admin,
                       now=booking.slot.starts_at + timedelta(minutes=30))
        self.assertTrue(redemos.set_remarks(redemo, 'For the next one.', self.admin)[1])
        # ... until the next one is taught (booked leaving the remarks as they are).
        complete(self.book(redemo, day=date(2026, 11, 1), remarks=None), self.tutor)
        with self.assertRaises(RedemoRemarksLocked):
            redemos.set_remarks(redemo, 'After the class.', self.admin)
        self.assertEqual(ReDemoRequest.objects.get(pk=redemo.pk).admin_remarks, 'For the next one.')


# ------------------------------------------------------------------ the student's own clock

class StudentClockTests(RedemoTestCase):
    def zone(self, zone):
        Lead.objects.filter(pk=self.lead.pk).update(student_timezone=zone)
        return ReDemoRequest.objects.select_related('lead', 'demo_booking').get(pk=self.redemo.pk)

    def setUp(self):
        super().setUp()
        self.redemo = self.ask()

    def test_slots_read_on_the_students_clock_beside_ist(self):
        redemo = self.zone('Asia/Dubai')
        slot = slot_of(redemos.slot_options(redemo, self.tutor, AFTER), REDEMO_DAY, EVENING)
        # 7:30 PM IST is 6:00 PM in the UAE: one instant, the one booked.
        self.assertEqual((slot['student_date'], slot['student_time'], slot['student_label']), ('2026-10-31', '18:00', 'UAE'))
        self.assertEqual(slot['starts_at'], slot_instants(REDEMO_DAY, EVENING)[0].isoformat())
        self.assertEqual(redemos.clock(redemo.lead, AFTER), {
            'student_timezone': 'Asia/Dubai', 'display_timezone': 'Asia/Dubai', 'display_timezone_label': 'UAE',
            'student_timezone_known': True,
        })

    def test_the_students_date_may_be_the_day_before_indias(self):
        redemo = self.zone('America/Los_Angeles')
        dates = redemos.time_options(redemo, AFTER)
        # 10:00 AM IST on 31 Oct is 9:30 PM the evening before in Los Angeles (PDT) ...
        slot = slot_of(dates, REDEMO_DAY, MORNING)
        self.assertEqual((slot['student_date'], slot['student_time'], slot['student_label']),
                         ('2026-10-30', '21:30', 'Los Angeles'))
        # ... and once daylight saving ends there (1 Nov), 10:00 AM IST on 2 Nov is 8:30 PM on 1 Nov (PST).
        slot = slot_of(dates, date(2026, 11, 2), MORNING)
        self.assertEqual((slot['student_date'], slot['student_time']), ('2026-11-01', '20:30'))

    def test_no_zone_or_an_unknown_one_reads_in_ist(self):
        for stored in ('', 'Mars/Olympus_Mons'):
            with self.subTest(stored=stored):
                redemo = self.zone(stored)
                slot = slot_of(redemos.slot_options(redemo, self.tutor, AFTER), REDEMO_DAY, EVENING)
                self.assertEqual((slot['student_date'], slot['student_time'], slot['student_label']),
                                 ('2026-10-31', '19:30', 'IST'))
                self.assertEqual(redemos.clock(redemo.lead, AFTER)['student_timezone'], None)
                self.assertFalse(redemos.clock(redemo.lead, AFTER)['student_timezone_known'])
        booking = self.book(ReDemoRequest.objects.get(pk=self.redemo.pk))
        self.assertEqual(booking.details['student_timezone'], '')

    def test_the_booking_keeps_the_zone_it_was_booked_in(self):
        redemo = self.zone('Asia/Dubai')
        original = row(DemoBooking, self.demo.pk, 'updated_at', 'status')
        booking = self.book(redemo)
        self.assertEqual(booking.details['student_timezone'], 'Asia/Dubai')
        self.assertEqual((booking.details['syllabus'], booking.details['student_name']), ('CBSE', 'Riya'))
        # A later correction of the lead's zone -- the way staff correct it -- leaves the booking's record as it was.
        _, changed = student_timezones.correct(self.lead.pk, 'Asia/Qatar', actor=self.admin, via='lead_management')
        self.assertTrue(changed)
        self.assertEqual(Lead.objects.get(pk=self.lead.pk).student_timezone, 'Asia/Qatar')
        self.assertEqual(DemoBooking.objects.get(pk=booking.pk).details['student_timezone'], 'Asia/Dubai')
        # The Demo taught before keeps its own submission.
        self.assertEqual(row(DemoBooking, self.demo.pk, 'updated_at', 'status'), original)

    def test_by_time_counts_the_tutors_who_may_teach_it_then(self):
        other = create_booking(request(student='Kiran', phone='0509999999', day=REDEMO_DAY, at=EVENING), now=AFTER)[0]
        assign_tutor(other, self.tutor, now=AFTER)
        dates = redemos.time_options(ReDemoRequest.objects.get(pk=self.redemo.pk), AFTER)
        # The original tutor never counts; the other tutor is busy at 7:30 PM on 31 Oct.
        busy, free = slot_of(dates, REDEMO_DAY, EVENING), slot_of(dates, REDEMO_DAY, MORNING)
        self.assertEqual((busy['free_tutors'], busy['bookable'], busy['unavailable_reason']),
                         (0, False, redemos.NO_TUTOR_FREE))
        self.assertEqual((free['free_tutors'], free['bookable']), (1, True))
        options = redemos.slot_tutor_options(ReDemoRequest.objects.get(pk=self.redemo.pk), REDEMO_DAY, EVENING, AFTER)
        tutors = {tutor['id']: tutor for tutor in options['tutors']}
        self.assertEqual((tutors[str(self.tutor.pk)]['status'], tutors[str(self.tutor.pk)]['reason']['code']),
                         ('UNAVAILABLE', 'BOOKING_CONFLICT'))
        self.assertEqual((tutors[str(self.original_tutor.pk)]['eligible'], tutors[str(self.original_tutor.pk)]['original']),
                         (False, True))
        self.assertEqual(options['slot']['free_tutors'], 0)
        with self.assertRaises(DateOutOfWindow):
            redemos.slot_tutor_options(self.redemo, date(2026, 12, 1), EVENING, AFTER)


# ------------------------------------------------------------------ the messages a BDE sends by hand

class ParentMessageTests(RedemoTestCase):
    def test_the_demo_wording_on_the_students_clock_and_nothing_is_sent(self):
        Lead.objects.filter(pk=self.lead.pk).update(student_timezone='Asia/Dubai')
        booking = self.book(self.ask())
        messages = redemo_messages(DemoBooking.objects.get(pk=booking.pk), AFTER)
        request_text = messages['confirmation_request']['text']
        self.assertIn('*Sat, 31 Oct 2026 at 6:00 PM UAE*', request_text)
        self.assertIn('we are awaiting your confirmation', request_text)
        self.assertNotIn('IST', request_text)
        # The confirmed message names the BDE's phone, which this BDE has not given: left out, saying why.
        self.assertEqual(messages['confirmed'], {'text': None, 'missing': ['bde_phone']})
        type(self.bde).objects.filter(pk=self.bde.pk).update(mobile_number='+971501112222')
        confirmed = redemo_messages(DemoBooking.objects.get(pk=booking.pk), AFTER)['confirmed']['text']
        for expected in ('Tutor: Tutor Neel', '⏰ Time: 6:00 PM UAE', MEET, '+971501112222'):
            self.assertIn(expected, confirmed)
        # Manual only: the Re-Demo still has no plan, no task and no message.
        self.assertFalse(CommunicationTask.objects.filter(demo_booking=booking).exists())
        self.assertFalse(Message.objects.filter(demo_booking=booking).exists())

    def test_ist_without_a_zone_and_none_for_any_other_booking(self):
        booking = self.book(self.ask())
        text = redemo_messages(DemoBooking.objects.get(pk=booking.pk), AFTER)['confirmation_request']['text']
        self.assertIn('*Sat, 31 Oct 2026 at 7:30 PM IST*', text)
        self.assertIsNone(redemo_messages(self.demo, AFTER))
        # Past its start, started or cancelled, there is nothing to send.
        self.assertIsNone(redemo_messages(DemoBooking.objects.get(pk=booking.pk), booking.slot.starts_at))
        started = start(booking)
        self.assertIsNone(redemo_messages(started, AFTER))


# ------------------------------------------------------------------ the APIs

class CloseApiTests(RedemoApiTestCase):
    def test_the_admin_closes_and_reopens_a_request(self):
        redemo = request_redemo(self.demo, REASON, actor=self.bde)
        client = self.as_user(self.admin)
        base = f'/api/bookings/redemos/{redemo.pk}/'
        # Closing needs the permission asking for one needs (reschedule_booking).
        group = RoleGroup.objects.select_related('group').get(role='ADMIN').group
        group.permissions.remove(Permission.objects.get(codename='reschedule_booking'))
        self.assertEqual(self.as_user(self.admin).post(f'{base}close/', {'reason': DECLINED}, format='json').status_code, 403)
        self.assertFalse(self.as_user(self.admin).get(base).data['actions']['close'])
        group.permissions.add(Permission.objects.get(codename='reschedule_booking'))
        client = self.as_user(self.admin)
        for body in ({}, {'reason': 'Because'}):
            with self.subTest(body=body):
                res = client.post(f'{base}close/', body, format='json')
                self.assertEqual((res.status_code, res.data['error']), (400, 'VALIDATION_ERROR'))
        res = client.post(f'{base}close/', {'reason': DECLINED}, format='json')
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual((res.data['status'], res.data['changed'], res.data['closed']['reason'], res.data['actions']),
                         ('CLOSED', True, {'code': DECLINED, 'label': 'Parent declined'},
                          {'schedule': False, 'edit_remarks': True, 'close': False, 'reopen': True}))
        self.assertEqual(client.get('/api/bookings/redemos/', {'status': 'CLOSED'}).data['count'], 1)
        detail = client.get(f'/api/bookings/demo/{self.demo.pk}/').data
        self.assertEqual((detail['status'], detail['redemo_request']['status'], detail['actions']['request_redemo']),
                         ('COMPLETED', 'CLOSED', False))
        again = client.post(redemo_url(self.demo.pk), {'reason': REASON}, format='json')
        self.assertEqual((again.status_code, again.data['error']), (409, 'REDEMO_CLOSED'))
        res = client.post(f'{base}schedule/', self.schedule_body(), format='json')
        self.assertEqual((res.status_code, res.data['error']), (409, 'REDEMO_CLOSED'))
        res = client.post(f'{base}reopen/', {}, format='json')
        self.assertEqual((res.status_code, res.data['status'], res.data['changed']), (200, 'AWAITING_SCHEDULING', True))

    def test_the_bde_closes_their_own_leads_request_only(self):
        request_redemo(self.demo, REASON, actor=self.bde)
        url = f'{redemo_url(self.demo.pk, bde=True)}close/'
        for user in (self.other_bde,):
            res = self.as_user(user).post(url, {'reason': DECLINED}, format='json')
            self.assertEqual((res.status_code, res.data['error']), (404, 'NOT_FOUND'))
        for user in (self.tutor, self.admin):
            self.assertEqual(self.as_user(user).post(url, {'reason': DECLINED}, format='json').status_code, 403)
        res = self.as_user(self.bde).post(url, {'reason': DECLINED}, format='json')
        self.assertEqual(res.status_code, 200, res.data)
        entry = next(entry for entry in res.data['bookings'] if entry['id'] == str(self.demo.pk))
        self.assertEqual((entry['status'], entry['redemo']['status'], entry['redemo']['closed']['reason']['code'],
                          entry['redemo']['actions'], entry['actions']['request_redemo']),
                         ('COMPLETED', 'CLOSED', DECLINED, {'close': False, 'reopen': True}, False))
        res = self.as_user(self.bde).post(f'{redemo_url(self.demo.pk, bde=True)}reopen/', {}, format='json')
        self.assertEqual((res.status_code, self.entry(self.demo)['redemo']['status']), (200, 'AWAITING_SCHEDULING'))
        # Without the permission BDEs ask with, nothing closes; nor does an administrator close without rescheduling.
        group = RoleGroup.objects.select_related('group').get(role='BDE').group
        group.permissions.remove(Permission.objects.get(codename='create_demo_booking'))
        self.assertEqual(self.as_user(self.bde).post(url, {'reason': DECLINED}, format='json').status_code, 403)
        group.permissions.add(Permission.objects.get(codename='create_demo_booking'))
        # A Demo with no request is answered as one that does not exist.
        other = completed_demo(student='Kiran', phone='0507777777', tutor=self.tutor)
        Lead.objects.filter(pk=other.lead_id).update(owner_bde=self.bde, owner_assigned_at=NOW)
        res = self.as_user(self.bde).post(f'{redemo_url(other.pk, bde=True)}close/', {'reason': DECLINED}, format='json')
        self.assertEqual(res.status_code, 404)


class ScheduleApiTests(RedemoApiTestCase):
    def test_the_slot_booked_is_the_instant_the_picker_showed(self):
        redemo = request_redemo(self.demo, REASON, actor=self.bde)
        Lead.objects.filter(pk=self.lead.pk).update(student_timezone='Asia/Dubai')
        client = self.as_user(self.admin)
        base = f'/api/bookings/redemos/{redemo.pk}/'
        times = client.get(f'{base}times/').data
        self.assertEqual((times['display_timezone'], times['student_timezone_known'], len(times['dates'])),
                         ('Asia/Dubai', True, 7))
        slot = slot_of(times['dates'], self.day, EVENING)
        self.assertEqual((slot['student_time'], slot['free_tutors']), ('18:00', 1))
        res = client.get(f'{base}slot-tutors/', {'date': self.day.isoformat(), 'time': '7pm'})
        self.assertEqual((res.status_code, res.data['error']), (400, 'VALIDATION_ERROR'))
        res = client.get(f'{base}slot-tutors/', {'date': self.day.isoformat(), 'time': '19:30'})
        self.assertEqual({t['id']: t['status'] for t in res.data['tutors']}[str(self.tutor.pk)], 'AVAILABLE')
        self.assertEqual(client.get(f'{base}tutors/').data['display_timezone_label'], 'UAE')

        wrong = slot_instants(self.day, MORNING)[0].isoformat()
        res = client.post(f'{base}schedule/', self.schedule_body(starts_at=wrong), format='json')
        self.assertEqual((res.status_code, res.data['error']), (400, 'SLOT_MISMATCH'))
        # The slot's Indian wall time labelled with the student's offset is another instant -- a relabel, not a conversion: refused.
        ist_wall = datetime.fromisoformat(slot['starts_at']).astimezone(BOOKING_TIMEZONE).replace(tzinfo=None).isoformat()
        res = client.post(f'{base}schedule/', self.schedule_body(starts_at=f'{ist_wall}+04:00'), format='json')
        self.assertEqual((res.status_code, res.data['error']), (400, 'SLOT_MISMATCH'))
        self.assertFalse(DemoBooking.objects.filter(redemo_for=redemo).exists())
        # The slot's own instant, written in the student's offset, is the slot: accepted.
        in_dubai = datetime.fromisoformat(slot['starts_at']).astimezone(ZoneInfo('Asia/Dubai')).isoformat()
        self.assertTrue(in_dubai.endswith('+04:00'))
        res = client.post(f'{base}schedule/', self.schedule_body(starts_at=in_dubai), format='json')
        self.assertEqual(res.status_code, 201, res.data)
        booking = DemoBooking.objects.get(pk=res.data['booking_id'])
        self.assertEqual((booking.slot.starts_at.isoformat(), booking.details['student_timezone']),
                         (slot['starts_at'], 'Asia/Dubai'))

    def test_the_tutor_reads_the_original_report_and_remarks_lock(self):
        redemo = request_redemo(self.demo, REASON, actor=self.bde)
        res = self.as_user(self.admin).post(f'/api/bookings/redemos/{redemo.pk}/schedule/',
                                            self.schedule_body(remarks=REMARKS), format='json')
        booking = DemoBooking.objects.get(pk=res.data['booking_id'])
        shown = self.as_user(self.tutor).get(f'/api/tutor/bookings/demo/{booking.pk}/').data
        self.assertEqual(shown['redemo']['original']['report']['fields']['assessment_review'],
                         self.demo.report.assessment_review)


class ListApiTests(RedemoApiTestCase):
    def setUp(self):
        super().setUp()
        self.first = request_redemo(self.demo, REASON, actor=self.bde)
        self.other_demo = completed_demo(student='Kiran', phone='0507777777')
        self.second = request_redemo(self.other_demo, 'Ownerless lead.', actor=self.admin)

    def listed(self, **params):
        return self.as_user(self.admin).get('/api/bookings/redemos/', params)

    def test_counts_order_and_filters(self):
        data = self.listed().data
        self.assertEqual([row['id'] for row in data['results']], [str(self.first.pk), str(self.second.pk)])
        self.assertEqual(data['counts'], {'ALL': 2, 'AWAITING_SCHEDULING': 2, 'ATTENTION': 1, 'SCHEDULED': 0,
                                          'COMPLETED': 0, 'CLOSED': 0})
        self.assertEqual(data['owners'], [{'id': str(self.bde.pk), 'full_name': 'Bde Anil'}])
        second = data['results'][1]
        self.assertEqual(([flag['code'] for flag in second['attention']], second['needs_action'], second['syllabus']),
                         (['NO_BDE'], True, 'CBSE'))
        cases = {
            'attention': ({'status': 'ATTENTION'}, [self.second]),
            'owner': ({'owner': str(self.bde.pk)}, [self.first]),
            'no owner': ({'owner': 'none'}, [self.second]),
            'lead': ({'lead': str(self.lead.pk)}, [self.first]),
            'original demo': ({'booking': str(self.other_demo.pk)}, [self.second]),
        }
        for name, (params, expected) in cases.items():
            with self.subTest(name):
                self.assertEqual([row['id'] for row in self.listed(**params).data['results']],
                                 [str(redemo.pk) for redemo in expected])
        res = self.as_user(self.admin).post(f'/api/bookings/redemos/{self.first.pk}/schedule/', self.schedule_body(),
                                            format='json')
        self.assertEqual([row['id'] for row in self.listed(booking=res.data['booking_id']).data['results']],
                         [str(self.first.pk)])
        # The request to schedule now leads; the scheduled one follows.
        self.assertEqual([row['status'] for row in self.listed().data['results']], ['AWAITING_SCHEDULING', 'SCHEDULED'])
        # The dates requested, in Indian dates: today's requests, none tomorrow.
        today = datetime.now(BOOKING_TIMEZONE).date()
        self.assertEqual(self.listed(**{'from': today.isoformat()}).data['count'], 2)
        self.assertEqual(self.listed(**{'from': (today + timedelta(days=1)).isoformat()}).data['count'], 0)
        self.assertEqual(self.listed(to=(today - timedelta(days=1)).isoformat()).data['count'], 0)
        for params, fields in (({'owner': 'x'}, ['owner']), ({'from': '2026-11-09', 'to': '2026-11-01'}, ['to']),
                               ({'status': 'INVITED'}, ['status']), ({'booking': 'nope'}, ['booking'])):
            with self.subTest(params=params):
                res = self.listed(**params)
                self.assertEqual((res.status_code, res.data['fields']), (400, fields))


class RedemoFilterTests(RedemoApiTestCase):
    def test_the_demo_lists_filter_redemo_bookings(self):
        redemo = request_redemo(self.demo, REASON, actor=self.bde)
        res = self.as_user(self.admin).post(f'/api/bookings/redemos/{redemo.pk}/schedule/', self.schedule_body(),
                                            format='json')
        for path, user in (('/api/bookings/demo/', self.admin), ('/api/bde/bookings/demo/', self.bde)):
            with self.subTest(path=path):
                rows = self.as_user(user).get(path, {'status': 'REDEMO'}).data['results']
                self.assertEqual([row['id'] for row in rows], [res.data['booking_id']])
                # The Demo it repeats reads Re-Demo required (no schedule filter: every date).
                rows = self.as_user(user).get(path, {'status': 'REDEMO_REQUIRED'}).data['results']
                self.assertEqual([row['id'] for row in rows], [str(self.demo.pk)])
        for path, user in (('/api/bookings/diagnostic/', self.admin), ('/api/bde/bookings/diagnostic/', self.bde)):
            with self.subTest(path=path):
                res = self.as_user(user).get(path, {'status': 'REDEMO'})
                self.assertEqual((res.status_code, res.data['fields']), (400, ['status']))


class ParentMessageApiTests(RedemoApiTestCase):
    def test_the_bde_gets_the_messages_on_the_redemo_and_its_follow_up(self):
        redemo = request_redemo(self.demo, REASON, actor=self.bde)
        res = self.as_user(self.admin).post(f'/api/bookings/redemos/{redemo.pk}/schedule/', self.schedule_body(),
                                            format='json')
        booking = DemoBooking.objects.get(pk=res.data['booking_id'])
        entry = self.entry(booking)
        self.assertIn('awaiting your confirmation', entry['parent_messages']['confirmation_request']['text'])
        self.assertIsNone(self.entry(self.demo)['parent_messages'])
        follow_ups = self.as_user(self.bde).get('/api/bde/follow-ups/').data['results']
        row_ = next(row for row in follow_ups if row['type'] == 'REDEMO_CONFIRMATION')
        self.assertEqual(row_['parent_messages']['confirmation_request']['text'],
                         entry['parent_messages']['confirmation_request']['text'])
        # The administrators' detail carries them too, for a lead with no BDE.
        detail = self.as_user(self.admin).get(f'/api/bookings/redemos/{redemo.pk}/').data
        self.assertEqual(detail['parent_messages']['confirmation_request']['text'],
                         entry['parent_messages']['confirmation_request']['text'])


class ConcurrentRemarksTests(TransactionTestCase):
    def setUp(self):
        schedule()
        self.admin = account('admin_race', role='ADMIN')
        self.bde = account('bde_race', role='BDE')
        self.tutor = account('tutor_race', role='TUTOR')
        self.demo = completed_demo()
        Lead.objects.filter(pk=self.demo.lead_id).update(owner_bde=self.bde, owner_assigned_at=NOW)

    def test_a_remarks_save_racing_the_start_waits_for_it_and_is_refused(self):
        redemo = request_redemo(self.demo, REASON, actor=self.bde, now=AFTER)
        booking = schedule_redemo(redemo, self.tutor, REDEMO_DAY, EVENING, actor=self.admin, remarks=REMARKS, now=AFTER)
        holding = threading.Event()

        def start_slowly():
            # What start_booking does, slowly: the slot's and the booking's locks, then the start.
            try:
                with transaction.atomic():
                    _locked_booking(booking)
                    holding.set()
                    clock.sleep(0.6)
                    DemoBooking.objects.filter(pk=booking.pk).update(
                        started_at=booking.slot.starts_at, started_by=self.tutor,
                    )
            finally:
                connection.close()

        thread = threading.Thread(target=start_slowly)
        thread.start()
        self.assertTrue(holding.wait(timeout=10))
        with self.assertRaises(RedemoRemarksLocked):
            redemos.set_remarks(redemo, 'Too late.', self.admin)
        thread.join(timeout=30)
        self.assertEqual(ReDemoRequest.objects.get(pk=redemo.pk).admin_remarks, REMARKS)
