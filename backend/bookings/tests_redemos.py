"""
Re-Demos (bookings.redemos): a completed Demo taught again. Only a COMPLETED
Demo, once, with a reason; an administrator for any lead, a BDE for their own
-- the Demo is RE-DEMO REQUIRED at once and otherwise left as it was. An
administrator then schedules it: an active tutor free for a Demo slot the
booking pages offer, and remarks for them, book a new Demo of the same lead
and owner straight away, under the rules and locks of a move -- no parent
invitation, and no message to the parent at all: the BDE tells them by
hand. Its tutor sees it as a RE-DEMO with its context, starts and reports on
it like any Demo; each Demo keeps its own report, and Re-Demos chain.
"""
import json
import threading
from datetime import date, datetime, timedelta
from unittest import skipUnless

from django.contrib.auth.models import Permission
from django.db import IntegrityError, connection, transaction
from django.test import TransactionTestCase
from rest_framework.test import APIClient, APITestCase

from accounts.models import RoleGroup
from activity.models import ActivityLog
from communications.models import CommunicationTask, Message
from communications.overview import booking_communication
from communications.services import RedemoManual, request_confirmation
from reports.models import DemoReport, DemoReportRevision
from reports.services import edit_report, submit_report
from reports.tests_services import demo_input

from . import redemos
from .booking_service import (
    BookingCompleted,
    BookingNotOwned,
    DateOutOfWindow,
    DemoAlreadyHeld,
    LeadAlreadyBooked,
    RedemoAlreadyRequested,
    RedemoCompleted,
    RedemoNotEligible,
    RedemoOriginalTutor,
    RedemoReasonRequired,
    RedemoReasonTooLong,
    RedemoRemarksTooLong,
    RedemoScheduled,
    SlotFull,
    TutorNotAssignable,
    TutorUnavailable,
    assign_tutor,
    cancel_booking,
    close_slot,
    create_booking,
    demo_invite_refusal,
    record_parent_confirmation,
    request_redemo,
    reschedule_booking,
    schedule_redemo,
)
from .lead_status import LeadStatus, with_status
from .lifecycle import ActivityState, activity_state
from .models import (
    BookingChannel,
    BookingEvent,
    BookingEventKind,
    BookingStatus,
    CancelReason,
    DemoBooking,
    Lead,
    ParentConfirmation,
    ReDemoRequest,
    ReDemoStatus,
    RescheduleReason,
)
from .redemo_chain import state
from .scheduling import BOOKING_TIMEZONE, booking_window
from .tests_booking import DIAGNOSTIC, EVENING, MORNING, NOW, BookingTestCase, account, request, schedule, start
from .tests_demo_invites import diagnostic_with_report
from .tutor_bookings import booking_row as tutor_row

# The day after the Demo (19:30 IST on 28 Oct): the Demo window runs 30 Oct - 5 Nov.
AFTER = datetime(2026, 10, 29, 12, 0, tzinfo=BOOKING_TIMEZONE)
REDEMO_DAY = date(2026, 10, 31)
REASON = 'The parent felt the pace was too fast and wants another teacher.'
REMARKS = 'Go slower with fractions; the parent will join the call.'
MEET = 'https://meet.google.com/abc-defg-hij'


def completed_demo(student='Riya', phone='0501234567', tutor=None, day=date(2026, 10, 28), at=EVENING, now=NOW):
    """A Demo booked for ``day``, started by its tutor and reported on: its booking, read again."""
    booking = create_booking(request(student=student, phone=phone, day=day, at=at), now=now)[0]
    tutor = tutor or account(f'tutor_{student.lower().replace(" ", "_")}', role='TUTOR')
    booking = assign_tutor(booking, tutor, now=now)[0]
    booking = start(booking)
    submit_report(booking, tutor, demo_input(), now=booking.slot.starts_at + timedelta(minutes=50))
    return DemoBooking.objects.select_related('report', 'lead', 'slot').get(pk=booking.pk)


def complete(booking, tutor):
    """``booking`` as its tutor starts it and reports on it."""
    booking = start(booking)
    submit_report(booking, tutor, demo_input(suggested_strategy='A slower start.'),
                  now=booking.slot.starts_at + timedelta(minutes=50))
    return DemoBooking.objects.select_related('report', 'lead', 'slot').get(pk=booking.pk)


def row(model, pk, *exclude):
    """Every column of one row, to compare before and after."""
    return {key: value for key, value in model.objects.filter(pk=pk).values().get().items() if key not in exclude}


def shown_to_tutor(booking):
    """``booking`` as its tutor's list reads it (tutor_bookings.assigned_to's relations)."""
    booking = DemoBooking.objects.select_related(
        'slot', 'lead', 'report', 'redemo_for__demo_booking__slot', 'redemo_for__demo_booking__assigned_tutor',
    ).get(pk=booking.pk)
    return tutor_row(booking, AFTER, can_start=True)


class RedemoTestCase(BookingTestCase):
    def setUp(self):
        super().setUp()
        self.admin = account('admin_ops', role='ADMIN')
        self.bde = account('bde_anil', role='BDE')
        self.other_bde = account('bde_bina', role='BDE')
        self.original_tutor = account('tutor_orla', role='TUTOR')
        self.tutor = account('tutor_neel', role='TUTOR', tutor_meet_link=MEET)
        self.demo = completed_demo(tutor=self.original_tutor)
        self.lead = self.demo.lead
        Lead.objects.filter(pk=self.lead.pk).update(owner_bde=self.bde, owner_assigned_at=NOW)

    def ask(self, booking=None, actor=None, reason=REASON, **kwargs):
        return request_redemo(booking or self.demo, reason, actor=actor or self.bde, now=AFTER, **kwargs)

    def book(self, redemo, tutor=None, day=REDEMO_DAY, at=EVENING, remarks=REMARKS, now=AFTER):
        """``redemo`` as an administrator schedules it: the new Demo."""
        return schedule_redemo(redemo, tutor or self.tutor, day, at, actor=self.admin, remarks=remarks, now=now)

    def status(self, redemo, now=AFTER):
        return state(ReDemoRequest.objects.get(pk=redemo.pk), now).status


# ------------------------------------------------------------------ requesting

class RequestTests(RedemoTestCase):
    def test_only_a_completed_demo(self):
        upcoming = create_booking(request(student='Kiran', phone='0507000001', day=REDEMO_DAY), now=AFTER)[0]
        cancelled = create_booking(request(student='Mira', phone='0507000002', day=REDEMO_DAY), now=AFTER)[0]
        cancel_booking(cancelled, reason_code=CancelReason.PARENT_REQUEST, now=AFTER)
        no_show = create_booking(request(student='Ravi', phone='0507000003', day=date(2026, 10, 28)), now=NOW)[0]
        cancel_booking(no_show, reason_code=CancelReason.NO_SHOW, now=AFTER)
        diagnostic = create_booking(request(student='Diya', phone='0507000004', booking_type=DIAGNOSTIC), now=NOW)[0]
        for booking in (upcoming, DemoBooking.objects.get(pk=cancelled.pk), DemoBooking.objects.get(pk=no_show.pk),
                        diagnostic):
            with self.subTest(status=booking.status, type=booking.booking_type):
                with self.assertRaises(RedemoNotEligible):
                    self.ask(booking, actor=self.admin)
        self.assertFalse(ReDemoRequest.objects.exists())
        self.assertEqual(self.ask().demo_booking_id, self.demo.pk)

    def test_the_reason_is_required(self):
        for reason in ('', '   ', None, 42):
            with self.subTest(reason=reason), self.assertRaises(RedemoReasonRequired):
                self.ask(reason=reason)
        with self.assertRaises(RedemoReasonTooLong):
            self.ask(reason='x' * 1001)
        self.assertFalse(ReDemoRequest.objects.exists())
        self.assertEqual(DemoBooking.objects.get(pk=self.demo.pk).status, BookingStatus.COMPLETED)
        self.assertEqual(self.ask(reason=f'  {REASON}  ').reason, REASON)

    def test_the_demo_is_redemo_required_at_once_and_nothing_else_changes(self):
        before = row(DemoBooking, self.demo.pk, 'status', 'updated_at')
        report = row(DemoReport, self.demo.report.pk)
        revisions = list(DemoReportRevision.objects.filter(report=self.demo.report).values())
        lead = row(Lead, self.lead.pk)
        events = list(BookingEvent.objects.filter(demo_booking=self.demo).values_list('id', flat=True))

        redemo = self.ask(owner_bde=self.bde)
        self.assertEqual(DemoBooking.objects.get(pk=self.demo.pk).status, BookingStatus.REDEMO_REQUIRED)
        self.assertEqual(row(DemoBooking, self.demo.pk, 'status', 'updated_at'), before)
        self.assertEqual(row(DemoReport, self.demo.report.pk), report)
        self.assertEqual(list(DemoReportRevision.objects.filter(report=self.demo.report).values()), revisions)
        self.assertEqual(row(Lead, self.lead.pk), lead)
        self.assertEqual((redemo.reason, redemo.requested_by, redemo.requested_at, redemo.lead_id),
                         (REASON, self.bde, AFTER, self.lead.pk))
        added = BookingEvent.objects.filter(demo_booking=self.demo).exclude(id__in=events).get()
        self.assertEqual((added.kind, added.actor, added.data), (BookingEventKind.REDEMO_REQUESTED, self.bde, {
            'from_status': 'COMPLETED', 'to_status': 'REDEMO_REQUIRED', 'redemo_request_id': str(redemo.id)}))
        log = ActivityLog.objects.get(action='redemo.request')
        self.assertEqual((log.entity_id, log.context['booking_id'], log.context['via']),
                         (str(redemo.id), str(self.demo.pk), 'bde_workspace'))
        self.assertEqual(self.status(redemo), ReDemoStatus.AWAITING_SCHEDULING)

    def test_the_reason_and_remarks_reach_no_history_or_log(self):
        self.book(self.ask())
        for data in BookingEvent.objects.values_list('data', flat=True):
            self.assertNotIn(REASON, json.dumps(data))
            self.assertNotIn(REMARKS, json.dumps(data))
        for context in ActivityLog.objects.values_list('context', flat=True):
            self.assertNotIn(REASON, json.dumps(context))
            self.assertNotIn(REMARKS, json.dumps(context))

    def test_once_per_demo(self):
        self.ask()
        with self.assertRaises(RedemoAlreadyRequested):
            self.ask(actor=self.admin)
        self.assertEqual(ReDemoRequest.objects.count(), 1)
        # The database refuses a second request for one Demo, whatever the code checked.
        with self.assertRaises(IntegrityError), transaction.atomic():
            ReDemoRequest.objects.create(lead=self.lead, demo_booking=self.demo, reason='Again', requested_by=self.admin)

    def test_a_bde_asks_for_their_own_leads_demo_only(self):
        with self.assertRaises(BookingNotOwned):
            self.ask(owner_bde=self.other_bde, actor=self.other_bde)
        Lead.objects.filter(pk=self.lead.pk).update(owner_bde=None, owner_assigned_at=None)
        with self.assertRaises(BookingNotOwned):
            self.ask(owner_bde=self.bde)
        self.assertEqual(DemoBooking.objects.get(pk=self.demo.pk).status, BookingStatus.COMPLETED)
        # The Admin asks for any lead's, one nobody owns included.
        self.assertTrue(self.ask(actor=self.admin))

    def test_a_demo_sent_for_a_redemo_stays_a_completed_class(self):
        self.ask()
        demo = DemoBooking.objects.select_related('slot', 'lead', 'report').get(pk=self.demo.pk)
        self.assertEqual(activity_state(demo, AFTER), ActivityState.COMPLETED)
        # Its tutor reads it Completed -- an ordinary Demo -- with its report still theirs to edit.
        self.assertEqual((tutor_row(demo, AFTER)['status'], tutor_row(demo, AFTER)['redemo']),
                         (BookingStatus.COMPLETED, None))
        report, changed = edit_report(demo, self.original_tutor, demo_input(assessment_review='Edited.'), 1)
        self.assertEqual((changed, report.version), (True, 2))
        for change in (lambda: cancel_booking(demo, reason_code=CancelReason.OTHER, now=AFTER),
                       lambda: reschedule_booking(demo, REDEMO_DAY, EVENING, reason_code=RescheduleReason.OTHER,
                                                  now=AFTER),
                       lambda: assign_tutor(demo, self.tutor, now=AFTER)):
            with self.assertRaises(BookingCompleted):
                change()
        lead = with_status(Lead.objects.filter(pk=self.lead.pk), AFTER).get()
        self.assertEqual(lead.lead_status, LeadStatus.DEMO_REDEMO_REQUIRED)


# ------------------------------------------------------------------ scheduling

class ScheduleTests(RedemoTestCase):
    def test_the_admin_books_the_redemo_with_its_tutor_slot_and_remarks(self):
        redemo = self.ask()
        original = row(DemoBooking, self.demo.pk)
        lead = row(Lead, self.lead.pk)
        booking = DemoBooking.objects.select_related('slot').get(pk=self.book(redemo).pk)
        self.assertEqual(
            (booking.lead_id, booking.status, booking.channel, booking.created_by, booking.assigned_tutor,
             booking.tutor_assigned_by, booking.tutor_meet_link, booking.redemo_for_id, booking.referral_status),
            (self.lead.pk, BookingStatus.BOOKED, BookingChannel.BDE_HANDOFF, self.admin, self.tutor, self.admin, MEET,
             redemo.pk, None),
        )
        self.assertEqual((booking.slot.local_date, booking.slot.local_time), (REDEMO_DAY, EVENING))
        self.assertEqual(booking.details['student_name'], 'Riya')
        redemo = ReDemoRequest.objects.get(pk=redemo.pk)
        self.assertEqual((redemo.admin_remarks, redemo.remarks_updated_by), (REMARKS, self.admin))
        # The lead -- its owner included -- and the Demo taught again are as they were.
        self.assertEqual(row(Lead, self.lead.pk), lead)
        self.assertEqual(row(DemoBooking, self.demo.pk), original)
        self.assertEqual(self.status(redemo), ReDemoStatus.SCHEDULED)
        self.assertEqual(
            [(event.kind, event.actor, event.data.get('via'), event.data.get('redemo_request_id'))
             for event in booking.events.all()],
            [(BookingEventKind.CREATED, self.admin, 'redemo', str(redemo.id)),
             (BookingEventKind.TUTOR_ASSIGNED, self.admin, 'redemo', None)],
        )
        # No communication plan: nothing is written to the parent; the BDE tells them by hand.
        self.assertFalse(CommunicationTask.objects.filter(demo_booking=booking).exists())
        self.assertFalse(Message.objects.filter(demo_booking=booking).exists())
        log = ActivityLog.objects.get(action='booking.create', entity_id=str(booking.id))
        self.assertEqual((log.actor, log.context['via'], log.context['redemo_request_id']),
                         (self.admin, 'redemo', str(redemo.id)))

    def test_another_active_tutor_free_then_never_the_original_one(self):
        redemo = self.ask()
        for user in (account('mentor_mo', role='MENTOR'), account('tutor_gone', role='TUTOR', is_active=False), self.bde):
            with self.subTest(user=user.username), self.assertRaises(TutorNotAssignable):
                self.book(redemo, tutor=user)
        # The tutor who taught the Demo being repeated, free as they are, never teaches its Re-Demo.
        with self.assertRaises(RedemoOriginalTutor):
            self.book(redemo, tutor=self.original_tutor)
        other = create_booking(request(student='Kiran', phone='0507000001', day=REDEMO_DAY), now=AFTER)[0]
        assign_tutor(other, self.tutor, now=AFTER)
        with self.assertRaises(TutorUnavailable):
            self.book(redemo)
        self.assertFalse(DemoBooking.objects.filter(redemo_for=redemo).exists())
        self.assertEqual(ReDemoRequest.objects.get(pk=redemo.pk).admin_remarks, '')
        third = account('tutor_tara', role='TUTOR')
        self.assertEqual(self.book(redemo, tutor=third).assigned_tutor, third)

    def test_a_slot_the_booking_pages_offer_with_a_seat_and_the_child_free(self):
        redemo = self.ask()
        with self.assertRaises(DateOutOfWindow):
            self.book(redemo, day=date(2026, 11, 20))
        close_slot('DEMO', REDEMO_DAY, EVENING)
        with self.assertRaises(SlotFull):
            self.book(redemo)
        public = create_booking(request(student='Riya', day=date(2026, 11, 1)), now=AFTER)[0]
        with self.assertRaises(LeadAlreadyBooked):
            self.book(redemo, at=MORNING)
        cancel_booking(public, reason_code=CancelReason.PARENT_REQUEST, now=AFTER)
        with self.assertRaises(RedemoRemarksTooLong):
            self.book(redemo, at=MORNING, remarks='x' * 2001)
        self.assertEqual(self.book(redemo, at=MORNING).slot.local_time, MORNING)

    def test_a_scheduled_redemo_changes_as_a_booking(self):
        redemo = self.ask()
        booking = self.book(redemo)
        with self.assertRaises(RedemoScheduled):
            self.book(redemo, day=date(2026, 11, 1))
        # Moved, it stays the request's Re-Demo, with its tutor.
        moved = reschedule_booking(booking, date(2026, 11, 3), EVENING, reason_code=RescheduleReason.PARENT_REQUEST,
                                   now=AFTER).booking
        self.assertEqual((moved.redemo_for_id, moved.assigned_tutor), (redemo.pk, self.tutor))
        current = state(ReDemoRequest.objects.get(pk=redemo.pk), AFTER)
        self.assertEqual((current.status, current.booking.pk), (ReDemoStatus.SCHEDULED, moved.pk))
        # Given another tutor, as any booking is -- but never the one who taught the Demo it repeats.
        with self.assertRaises(RedemoOriginalTutor):
            assign_tutor(moved, self.original_tutor, now=AFTER)
        self.assertEqual(DemoBooking.objects.get(pk=moved.pk).assigned_tutor, self.tutor)
        third = account('tutor_tara', role='TUTOR')
        self.assertEqual(assign_tutor(moved, third, now=AFTER)[0].assigned_tutor, third)
        # Cancelled, it leaves the request to be scheduled again.
        cancel_booking(moved, reason_code=CancelReason.PARENT_REQUEST, now=AFTER)
        self.assertEqual(self.status(redemo), ReDemoStatus.AWAITING_SCHEDULING)
        again = self.book(redemo, day=date(2026, 11, 2), remarks=None)
        self.assertEqual(ReDemoRequest.objects.get(pk=redemo.pk).admin_remarks, REMARKS)
        self.assertEqual([b.pk for b in state(ReDemoRequest.objects.get(pk=redemo.pk), AFTER).bookings],
                         [moved.pk, again.pk])
        # The database holds one booked or taught Demo per request, whatever the code checked.
        with self.assertRaises(IntegrityError), transaction.atomic():
            DemoBooking.objects.filter(pk=moved.pk).update(
                status=BookingStatus.BOOKED, cancelled_at=None, cancelled_by=None, cancel_reason_code='',
            )

    def test_the_pickers(self):
        redemo = self.ask()
        options = {option['id']: option for option in redemos.tutor_options(redemo, AFTER)}
        self.assertEqual((options[str(self.tutor.pk)]['free_slots'], options[str(self.tutor.pk)]['tutor_meet_link'],
                          options[str(self.tutor.pk)]['eligible']), (14, MEET, True))
        # The original Demo's tutor is listed, free as they are, but never eligible, with why.
        original = options[str(self.original_tutor.pk)]
        self.assertEqual((original['original'], original['eligible'], original['status'], original['reason']['code']),
                         (True, False, 'AVAILABLE', 'REDEMO_ORIGINAL_TUTOR'))
        other = create_booking(request(student='Kiran', phone='0507000001', day=REDEMO_DAY), now=AFTER)[0]
        assign_tutor(other, self.tutor, now=AFTER)
        options = {option['id']: option for option in redemos.tutor_options(redemo, AFTER)}
        self.assertEqual(options[str(self.tutor.pk)]['free_slots'], 13)
        dates = {entry['date']: entry for entry in redemos.slot_options(redemo, self.tutor, AFTER)}
        slots = {slot['time']: slot for slot in dates[REDEMO_DAY.isoformat()]['slots']}
        self.assertEqual((slots['19:30']['bookable'], slots['19:30']['unavailable_reason']), (False, redemos.TUTOR_BUSY))
        self.assertEqual(slots['19:30']['tutor_reason']['code'], 'BOOKING_CONFLICT')
        self.assertTrue(slots['10:00']['bookable'])
        for day in booking_window('DEMO', AFTER):
            for at in (MORNING, EVENING):
                close_slot('DEMO', day, at)
        options = {option['id']: option for option in redemos.tutor_options(redemo, AFTER)}
        self.assertEqual(options[str(self.tutor.pk)]['status'], 'UNAVAILABLE')


# ------------------------------------------------------------------ parent communication

def communication_rows(booking):
    """Every task and message of ``booking``'s, by every column, to compare before and after."""
    return (list(CommunicationTask.objects.filter(demo_booking=booking).order_by('id').values()),
            list(Message.objects.filter(demo_booking=booking).order_by('id').values()))


class CommunicationTests(RedemoTestCase):
    def test_nothing_is_ever_written_to_a_redemos_parent(self):
        redemo = self.ask()
        booking = self.book(redemo)
        moved = reschedule_booking(booking, date(2026, 11, 3), EVENING, reason_code=RescheduleReason.PARENT_REQUEST,
                                   now=AFTER).booking
        complete(moved, self.tutor)
        for demo in (booking, moved):
            self.assertEqual(communication_rows(demo), ([], []), demo.pk)
        # An ordinary Demo made the same day is planned as ever: five tasks, its acknowledgement and confirmed message.
        other = create_booking(request(student='Kiran', phone='0507000001', day=REDEMO_DAY), now=AFTER)[0]
        self.assertEqual(CommunicationTask.objects.filter(demo_booking=other).count(), 5)
        self.assertEqual(Message.objects.filter(demo_booking=other).count(), 2)

    def test_no_confirmation_request_but_the_bde_may_record_the_answer(self):
        booking = self.book(self.ask())
        with self.assertRaises(RedemoManual):
            request_confirmation(booking, actor=self.bde, owner_bde=self.bde, now=AFTER)
        shown = booking_communication(DemoBooking.objects.select_related('slot', 'lead__owner_bde').get(pk=booking.pk),
                                      AFTER, user=self.admin)
        self.assertEqual((shown['redemo'], shown['planned'], shown['tasks'], shown['messages']), (True, False, [], []))
        self.assertEqual(shown['actions'], {'request_confirmation': False, 'record_confirmation': True})
        # The BDE calls the parent and records what they said; still nothing is sent.
        record_parent_confirmation(booking, ParentConfirmation.CONFIRMED, actor=self.bde, owner_bde=self.bde, now=AFTER)
        self.assertEqual(DemoBooking.objects.get(pk=booking.pk).parent_confirmation, ParentConfirmation.CONFIRMED)
        self.assertEqual(communication_rows(booking), ([], []))

    def test_the_original_demos_communication_is_left_as_it_was(self):
        before = communication_rows(self.demo)
        self.assertTrue(before[0], 'the original Demo was planned as any Demo')
        complete(self.book(self.ask()), self.tutor)
        self.assertEqual(communication_rows(self.demo), before)


# ------------------------------------------------------------------ the tutor

class TutorPlatformTests(RedemoTestCase):
    def test_the_tutor_sees_a_redemo_with_why_and_the_remarks(self):
        booking = self.book(self.ask())
        shown = shown_to_tutor(booking)
        self.assertEqual((shown['booking_type'], shown['status'], shown['tutor_meet_link']), ('DEMO', 'BOOKED', MEET))
        self.assertEqual((shown['slot']['date'], shown['slot']['time']), (REDEMO_DAY.isoformat(), '19:30'))
        redemo = shown['redemo']
        self.assertEqual((redemo['number'], redemo['reason'], redemo['admin_remarks'], redemo['original']['tutor']),
                         (1, REASON, REMARKS, {'full_name': 'Tutor Orla'}))
        self.assertEqual((redemo['original']['slot']['date'], redemo['original']['slot']['time']), ('2026-10-28', '19:30'))
        self.assertEqual(set(redemo), {'number', 'reason', 'admin_remarks', 'original'})
        # Never who asked, nor the original Demo's report.
        text = json.dumps(shown, default=str)
        for hidden in ('Bde Anil', 'Admin Ops', self.demo.report.assessment_review):
            self.assertNotIn(hidden, text)
        # The remarks the administrators change later reach the tutor.
        redemos.set_remarks(ReDemoRequest.objects.get(pk=booking.redemo_for_id), 'Bring the worksheet.', self.admin)
        self.assertEqual(shown_to_tutor(booking)['redemo']['admin_remarks'], 'Bring the worksheet.')

    def test_it_is_started_and_reported_on_like_any_demo(self):
        redemo = self.ask()
        booking = self.book(redemo)
        original_report = row(DemoReport, self.demo.report.pk)
        booking = complete(booking, self.tutor)
        self.assertEqual(booking.status, BookingStatus.COMPLETED)
        self.assertNotEqual(booking.report.pk, self.demo.report.pk)
        self.assertEqual(booking.report.suggested_strategy, 'A slower start.')
        report, changed = edit_report(booking, self.tutor, demo_input(assessment_review='Much better.'), 1)
        self.assertEqual((changed, report.version), (True, 2))
        self.assertEqual(row(DemoReport, self.demo.report.pk), original_report)
        self.assertEqual(self.status(redemo), ReDemoStatus.COMPLETED)
        with self.assertRaises(RedemoCompleted):
            self.book(redemo, day=date(2026, 11, 2))
        self.assertEqual(shown_to_tutor(booking)['redemo']['number'], 1)


# ------------------------------------------------------------------ chains

class ChainTests(RedemoTestCase):
    def test_redemos_chain_each_with_its_own_report(self):
        first = self.ask()
        booking = complete(self.book(first), self.tutor)
        # The Re-Demo, now completed, may be taught again: a second request in the chain.
        later = datetime(2026, 11, 1, 12, 0, tzinfo=BOOKING_TIMEZONE)
        second = request_redemo(booking, 'Still unsure about the tutor.', actor=self.admin, now=later)
        # Re-Demo 2 repeats Re-Demo 1: its tutor is the one who may not teach it; the first Demo's tutor may.
        with self.assertRaises(RedemoOriginalTutor):
            schedule_redemo(second, self.tutor, date(2026, 11, 4), EVENING, actor=self.admin, now=later)
        options = {option['id']: option['eligible'] for option in redemos.tutor_options(second, later)}
        self.assertEqual((options[str(self.tutor.pk)], options[str(self.original_tutor.pk)]), (False, True))
        third = schedule_redemo(second, self.original_tutor, date(2026, 11, 4), EVENING, actor=self.admin, now=later)
        self.assertEqual(shown_to_tutor(third)['redemo']['number'], 2)
        self.assertEqual(shown_to_tutor(third)['redemo']['original']['tutor'], {'full_name': 'Tutor Neel'})
        third = complete(third, self.original_tutor)
        self.assertEqual(len({self.demo.report.pk, booking.report.pk, third.report.pk}), 3)
        self.assertEqual(DemoBooking.objects.get(pk=booking.pk).status, BookingStatus.REDEMO_REQUIRED)

        chain = redemos.request_chain(ReDemoRequest.objects.get(pk=second.pk), later)
        self.assertEqual([(link['id'], link['original']['id'], link['booking']['id'], link['current']) for link in chain], [
            (str(first.pk), str(self.demo.pk), str(booking.pk), False),
            (str(second.pk), str(booking.pk), str(third.pk), True),
        ])
        # Read from the first request, the chain is the same.
        self.assertEqual([link['id'] for link in redemos.request_chain(ReDemoRequest.objects.get(pk=first.pk), later)],
                         [str(first.pk), str(second.pk)])

    def test_a_redemo_required_demo_still_blocks_a_diagnostic_demo_invitation(self):
        self.ask()
        diagnostic = diagnostic_with_report(student='Riya')
        self.assertIsInstance(demo_invite_refusal(diagnostic, diagnostic.lead, AFTER), DemoAlreadyHeld)


# ------------------------------------------------------------------ the APIs

def redemo_url(booking_id, bde=False):
    return f"/api/{'bde/' if bde else ''}bookings/demo/{booking_id}/redemo/"


class RedemoApiTestCase(APITestCase):
    def setUp(self):
        schedule()
        self.admin = account('admin_ops', role='ADMIN')
        self.bde = account('bde_anil', role='BDE')
        self.other_bde = account('bde_bina', role='BDE')
        self.original_tutor = account('tutor_orla', role='TUTOR')
        self.tutor = account('tutor_neel', role='TUTOR', tutor_meet_link=MEET)
        self.demo = completed_demo(tutor=self.original_tutor)
        self.lead = self.demo.lead
        Lead.objects.filter(pk=self.lead.pk).update(owner_bde=self.bde, owner_assigned_at=NOW)
        self.day = booking_window('DEMO')[1]

    def as_user(self, user):
        client = APIClient()
        if user is not None:
            client.force_authenticate(user=type(user).objects.get(pk=user.pk))
        return client

    def entry(self, booking, user=None):
        enquiry = self.as_user(user or self.bde).get(f'/api/bde/enquiries/{self.lead.pk}/').data
        return next(entry for entry in enquiry['bookings'] if entry['id'] == str(booking.pk))

    def schedule_body(self, tutor=None, at='19:30', **extra):
        return {'tutor_id': str((tutor or self.tutor).pk), 'date': self.day.isoformat(), 'time': at, **extra}


class AdminApiTests(RedemoApiTestCase):
    def test_the_admin_asks_for_a_redemo_with_a_reason(self):
        detail = self.as_user(self.admin).get(f'/api/bookings/demo/{self.demo.pk}/').data
        self.assertTrue(detail['actions']['request_redemo'])
        self.assertEqual((detail['redemo_request'], detail['redemo_from']), (None, None))
        for body in ({}, {'reason': ''}, {'reason': '   '}, {'reason': 'x' * 1001}):
            with self.subTest(body=body):
                res = self.as_user(self.admin).post(redemo_url(self.demo.pk), body, format='json')
                self.assertEqual((res.status_code, res.data['error']), (400, 'VALIDATION_ERROR'))
        res = self.as_user(self.admin).post(redemo_url(self.demo.pk), {'reason': REASON}, format='json')
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual((res.data['status'], res.data['reason'], res.data['requested_by']['id'], res.data['original']['id'],
                          res.data['actions']), ('AWAITING_SCHEDULING', REASON, str(self.admin.pk), str(self.demo.pk),
                                                 {'schedule': True, 'edit_remarks': True}))
        again = self.as_user(self.admin).post(redemo_url(self.demo.pk), {'reason': REASON}, format='json')
        self.assertEqual((again.status_code, again.data['error']), (409, 'REDEMO_ALREADY_REQUESTED'))
        detail = self.as_user(self.admin).get(f'/api/bookings/demo/{self.demo.pk}/').data
        self.assertEqual((detail['status'], detail['actions']['request_redemo'], detail['redemo_request']['status']),
                         ('REDEMO_REQUIRED', False, 'AWAITING_SCHEDULING'))
        # The original keeps its report, to read.
        self.assertEqual(self.as_user(self.admin).get(f'/api/bookings/demo/{self.demo.pk}/report/').status_code, 200)

    def test_the_admin_schedules_it_and_the_tutor_sees_a_redemo(self):
        redemo = request_redemo(self.demo, REASON, actor=self.bde)
        client = self.as_user(self.admin)
        listed = client.get('/api/bookings/redemos/').data
        self.assertEqual((listed['count'], listed['results'][0]['id'], listed['results'][0]['status']),
                         (1, str(redemo.pk), 'AWAITING_SCHEDULING'))
        self.assertEqual(client.get('/api/bookings/redemos/', {'q': 'Riya'}).data['count'], 1)
        self.assertEqual(client.get('/api/bookings/redemos/', {'status': 'SCHEDULED'}).data['count'], 0)
        self.assertEqual(client.get('/api/bookings/redemos/', {'status': 'INVITED'}).status_code, 400)

        tutors = client.get(f'/api/bookings/redemos/{redemo.pk}/tutors/').data
        self.assertEqual((tutors['schedulable'], tutors['refusal']), (True, None))
        self.assertEqual({t['id']: t['tutor_meet_link'] for t in tutors['tutors']}[str(self.tutor.pk)], MEET)
        res = client.get(f'/api/bookings/redemos/{redemo.pk}/slots/', {'tutor_id': str(self.bde.pk)})
        self.assertEqual((res.status_code, res.data['error']), (400, 'INVALID_TUTOR'))
        slots = client.get(f'/api/bookings/redemos/{redemo.pk}/slots/', {'tutor_id': str(self.tutor.pk)}).data
        self.assertEqual((slots['tutor']['tutor_meet_link'], len(slots['dates'])), (MEET, 7))

        for body in ({}, {'tutor_id': str(self.tutor.pk)}, self.schedule_body(time='7pm')):
            with self.subTest(body=body):
                res = client.post(f'/api/bookings/redemos/{redemo.pk}/schedule/', body, format='json')
                self.assertEqual((res.status_code, res.data['error']), (400, 'VALIDATION_ERROR'))
        res = client.post(f'/api/bookings/redemos/{redemo.pk}/schedule/', self.schedule_body(remarks=REMARKS),
                          format='json')
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual((res.data['status'], res.data['tutor']['id'], res.data['admin_remarks'], res.data['actions']),
                         ('SCHEDULED', str(self.tutor.pk), REMARKS, {'schedule': False, 'edit_remarks': True}))
        booking_id = res.data['booking_id']
        self.assertEqual((res.data['booking']['id'], res.data['booking']['tutor_meet_link']), (booking_id, MEET))
        again = client.post(f'/api/bookings/redemos/{redemo.pk}/schedule/', self.schedule_body(at='10:00'), format='json')
        self.assertEqual((again.status_code, again.data['error']), (409, 'REDEMO_SCHEDULED'))

        # Staff see it as a Re-Demo of the original, in the Demo list and the BDE's lead alike.
        shown = client.get(f'/api/bookings/demo/{booking_id}/').data
        self.assertEqual((shown['redemo_for_id'], shown['redemo_from']['id'], shown['redemo_from']['original']['id'],
                          shown['created_by']['id'], shown['lead']['owner_bde']['id']),
                         (str(redemo.pk), str(redemo.pk), str(self.demo.pk), str(self.admin.pk), str(self.bde.pk)))
        entry = self.entry(DemoBooking.objects.get(pk=booking_id))
        self.assertEqual((entry['status'], entry['redemo_from']['id']), ('BOOKED', str(redemo.pk)))
        # Its tutor sees it among their bookings at once, as a RE-DEMO with why and the remarks.
        mine = self.as_user(self.tutor).get('/api/tutor/bookings/').data['results']
        self.assertEqual([(row['id'], row['redemo']['reason'], row['redemo']['admin_remarks']) for row in mine],
                         [(booking_id, REASON, REMARKS)])
        detail = self.as_user(self.tutor).get(f'/api/tutor/bookings/demo/{booking_id}/').data
        self.assertEqual((detail['redemo']['number'], detail['redemo']['original']['tutor']), (1, {'full_name': 'Tutor Orla'}))
        theirs = self.as_user(self.original_tutor).get(f'/api/tutor/bookings/demo/{self.demo.pk}/').data
        self.assertEqual((theirs['status'], theirs['redemo']), ('COMPLETED', None))

    def test_its_communication_says_it_is_manual_and_sends_nothing(self):
        redemo = request_redemo(self.demo, REASON, actor=self.bde)
        booking = schedule_redemo(redemo, self.tutor, self.day, EVENING, actor=self.admin)
        base = f'/api/communications/bookings/demo/{booking.pk}/'
        shown = self.as_user(self.admin).get(base).data
        self.assertEqual((shown['redemo'], shown['planned'], shown['actions']['request_confirmation']), (True, False, False))
        res = self.as_user(self.admin).post(f'{base}confirmation-request/', {}, format='json')
        self.assertEqual((res.status_code, res.data['error']), (409, 'REDEMO_MANUAL'))
        self.assertFalse(Message.objects.filter(demo_booking=booking).exists())
        # An ordinary Demo's communication says it is no Re-Demo.
        self.assertFalse(self.as_user(self.admin).get(f'/api/communications/bookings/demo/{self.demo.pk}/').data['redemo'])

    def test_the_original_tutor_is_refused_however_the_request_is_made(self):
        redemo = request_redemo(self.demo, REASON, actor=self.bde)
        client = self.as_user(self.admin)
        base = f'/api/bookings/redemos/{redemo.pk}/'
        res = client.get(f'{base}slots/', {'tutor_id': str(self.original_tutor.pk)})
        self.assertEqual((res.status_code, res.data['error']), (400, 'REDEMO_ORIGINAL_TUTOR'))
        res = client.post(f'{base}schedule/', self.schedule_body(tutor=self.original_tutor), format='json')
        self.assertEqual((res.status_code, res.data['error']), (400, 'REDEMO_ORIGINAL_TUTOR'))
        self.assertFalse(DemoBooking.objects.filter(redemo_for=redemo).exists())
        # Another tutor books it; then the booking's own tutor change refuses the original tutor too.
        res = client.post(f'{base}schedule/', self.schedule_body(), format='json')
        self.assertEqual(res.status_code, 201, res.data)
        booking_id = res.data['booking_id']
        booking_url = f'/api/bookings/demo/{booking_id}/'
        tutors = {t['id']: t for t in client.get(f'{booking_url}tutors/').data['tutors']}
        self.assertEqual((tutors[str(self.original_tutor.pk)]['status'], tutors[str(self.original_tutor.pk)]['reason']['code']),
                         ('UNAVAILABLE', 'REDEMO_ORIGINAL_TUTOR'))
        self.assertEqual(tutors[str(self.tutor.pk)]['current'], True)
        res = client.put(f'{booking_url}tutor/', {'tutor_id': str(self.original_tutor.pk)}, format='json')
        self.assertEqual((res.status_code, res.data['error']), (400, 'REDEMO_ORIGINAL_TUTOR'))
        self.assertEqual(DemoBooking.objects.get(pk=booking_id).assigned_tutor, self.tutor)
        # An ordinary Demo's tutor list marks nobody so.
        ordinary = create_booking(request(student='Kiran', phone='0507000001', day=self.day))[0]
        reasons = [t['reason'] for t in client.get(f'/api/bookings/demo/{ordinary.pk}/tutors/').data['tutors']]
        self.assertFalse(any(reason and reason['code'] == 'REDEMO_ORIGINAL_TUTOR' for reason in reasons))

    def test_a_tutor_not_free_is_refused_with_why(self):
        redemo = request_redemo(self.demo, REASON, actor=self.bde)
        other = create_booking(request(student='Kiran', phone='0507000001', day=self.day))[0]
        assign_tutor(other, self.tutor)
        res = self.as_user(self.admin).post(f'/api/bookings/redemos/{redemo.pk}/schedule/', self.schedule_body(),
                                            format='json')
        self.assertEqual((res.status_code, res.data['error'], res.data['conflict']['code']),
                         (409, 'TUTOR_UNAVAILABLE', 'BOOKING_CONFLICT'))
        self.assertFalse(DemoBooking.objects.filter(redemo_for=redemo).exists())

    def test_who_may_read_and_schedule_redemos(self):
        redemo = request_redemo(self.demo, REASON, actor=self.bde)
        base = f'/api/bookings/redemos/{redemo.pk}/'
        reads = ('/api/bookings/redemos/', base, f'{base}tutors/', f'{base}slots/?tutor_id={self.tutor.pk}')
        for user in (None, self.bde, self.tutor, account('mentor_x', role='MENTOR')):
            name = getattr(user, 'username', 'anonymous')
            for path in reads:
                with self.subTest(user=name, path=path):
                    self.assertIn(self.as_user(user).get(path).status_code, (401, 403))
            with self.subTest(user=name, path='schedule'):
                res = self.as_user(user).post(f'{base}schedule/', self.schedule_body(), format='json')
                self.assertIn(res.status_code, (401, 403))
            with self.subTest(user=name, path='remarks'):
                self.assertIn(self.as_user(user).put(f'{base}remarks/', {'remarks': 'x'}, format='json').status_code,
                              (401, 403))
        group = RoleGroup.objects.select_related('group').get(role='ADMIN').group
        group.permissions.remove(Permission.objects.get(codename='assign_booking_tutor'))
        client = self.as_user(self.admin)
        self.assertEqual(client.get(base).data['actions'], {'schedule': False, 'edit_remarks': False})
        self.assertEqual(client.post(f'{base}schedule/', self.schedule_body(), format='json').status_code, 403)
        self.assertFalse(DemoBooking.objects.filter(redemo_for=redemo).exists())
        self.assertEqual(client.get(f'/api/bookings/redemos/{self.lead.pk}/').status_code, 404)


class BdeApiTests(RedemoApiTestCase):
    def test_the_bde_asks_and_sees_what_the_admin_scheduled(self):
        entry = self.entry(self.demo)
        self.assertEqual((entry['actions']['request_redemo'], entry['redemo']), (True, None))
        res = self.as_user(self.bde).post(redemo_url(self.demo.pk, bde=True), {'reason': ''}, format='json')
        self.assertEqual((res.status_code, res.data['error']), (400, 'VALIDATION_ERROR'))
        res = self.as_user(self.bde).post(redemo_url(self.demo.pk, bde=True), {'reason': REASON}, format='json')
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(res.data['status'], 'DEMO_REDEMO_REQUIRED')
        entry = next(e for e in res.data['bookings'] if e['id'] == str(self.demo.pk))
        self.assertEqual((entry['status'], entry['redemo']['status'], entry['redemo']['reason'],
                          entry['redemo']['booking'], entry['actions']['request_redemo']),
                         ('REDEMO_REQUIRED', 'AWAITING_SCHEDULING', REASON, None, False))
        # At once in the administrators' list: no approval step.
        self.assertEqual(self.as_user(self.admin).get('/api/bookings/redemos/').data['count'], 1)

        redemo = ReDemoRequest.objects.get()
        booking = schedule_redemo(redemo, self.tutor, self.day, EVENING, actor=self.admin, remarks=REMARKS)
        entry = self.entry(self.demo)
        self.assertEqual((entry['redemo']['status'], entry['redemo']['booking']['id'], entry['redemo']['tutor']),
                         ('SCHEDULED', str(booking.pk), {'full_name': 'Tutor Neel'}))
        self.assertNotIn(REMARKS, json.dumps(self.as_user(self.bde).get(f'/api/bde/enquiries/{self.lead.pk}/').data,
                                             default=str))

    def test_never_for_another_bdes_lead_and_no_parent_invitation(self):
        res = self.as_user(self.other_bde).post(redemo_url(self.demo.pk, bde=True), {'reason': REASON}, format='json')
        self.assertEqual((res.status_code, res.data), (404, {'error': 'NOT_FOUND', 'message': 'No such booking.'}))
        for user in (self.admin, self.tutor):
            res = self.as_user(user).post(redemo_url(self.demo.pk, bde=True), {'reason': REASON}, format='json')
            self.assertEqual(res.status_code, 403)
        self.assertFalse(ReDemoRequest.objects.exists())
        request_redemo(self.demo, REASON, actor=self.bde)
        # A Re-Demo is never sent to the parent to book: there is no such route.
        self.assertEqual(self.as_user(self.bde).post(f'/api/bde/bookings/demo/{self.demo.pk}/redemo-invite/').status_code,
                         404)
        self.assertNotIn('redemo_invite', self.entry(self.demo)['actions'])


# ------------------------------------------------------------------ concurrency

@skipUnless(connection.vendor == 'postgresql', 'the booking locks need PostgreSQL row locking')
class ConcurrentRedemoTests(TransactionTestCase):
    """Real threads, each with its own database connection, starting together."""

    def setUp(self):
        schedule()
        self.admin = account('admin_race', role='ADMIN')
        self.bde = account('bde_race', role='BDE')
        self.tutor = account('tutor_race', role='TUTOR')
        self.demo = completed_demo()
        Lead.objects.filter(pk=self.demo.lead_id).update(owner_bde=self.bde, owner_assigned_at=NOW)

    def race(self, calls):
        barrier = threading.Barrier(len(calls))
        outcomes = [None] * len(calls)

        def run(index, call):
            try:
                barrier.wait(timeout=10)
                outcomes[index] = call()
            except Exception as exc:  # reported in the assertion, not lost in the thread
                outcomes[index] = type(exc).__name__
            finally:
                connection.close()

        threads = [threading.Thread(target=run, args=(i, call)) for i, call in enumerate(calls)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        return outcomes

    def test_two_requests_at_once_make_one(self):
        outcomes = self.race([lambda: request_redemo(self.demo, REASON, actor=self.bde, now=AFTER).pk] * 3)
        self.assertEqual(ReDemoRequest.objects.count(), 1, outcomes)
        self.assertEqual(outcomes.count('RedemoAlreadyRequested'), 2, outcomes)

    def test_two_schedulings_at_once_book_one_demo(self):
        redemo = request_redemo(self.demo, REASON, actor=self.bde, now=AFTER)
        outcomes = self.race([
            lambda: schedule_redemo(redemo, self.tutor, REDEMO_DAY, EVENING, actor=self.admin, now=AFTER).pk,
            lambda: schedule_redemo(redemo, self.tutor, date(2026, 11, 1), MORNING, actor=self.admin, now=AFTER).pk,
        ])
        self.assertEqual(outcomes.count('RedemoScheduled'), 1, outcomes)
        self.assertEqual(DemoBooking.objects.filter(redemo_for=redemo, status=BookingStatus.BOOKED).count(), 1)

