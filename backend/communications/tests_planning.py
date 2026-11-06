"""
Planning a booking's communication (communications.planner), driven through
the booking writes themselves: every new Demo or Diagnostic booking gets its
five tasks, owned by its lead's BDE (the Admin without one), with the PRD's
deadlines, its acknowledgement and a Waiting confirmed message -- all in the
booking's own transaction. Cancelling stops what was not sent; a reschedule
plans the new booking afresh without a second acknowledgement; completion
writes the after-activity message once. Nothing is ever sent here.
"""
from datetime import datetime, timedelta
from unittest import mock

from django.test import TestCase, override_settings

from bookings.booking_service import assign_tutor, cancel_booking, create_booking, reschedule_booking
from bookings.lifecycle import ActivityState, activity_state
from bookings.models import (
    BookingEventKind,
    BookingStatus,
    CancelReason,
    DemoBooking,
    DiagnosticBooking,
    ParentConfirmation,
    RescheduleReason,
)
from bookings.scheduling import BOOKING_TIMEZONE
from bookings.tests_booking import DAY, DEMO, DIAGNOSTIC, EVENING, MORNING, NOW, account, link, request, schedule, start
from reports.services import edit_report, submit_report
from reports.tests_services import report_input

from . import planner
from .models import (
    CommunicationTask,
    Message,
    MessageAttempt,
    MessageCancelReason,
    MessageStatus,
    OwnerRole,
    Step,
    TaskResolution,
    TaskStatus,
)
from .rendering import format_date
from .tests_templates import prd_text

MEET_LINK = 'https://meet.google.com/abc-defg-hij'
BDE_PHONE = '+91 98470 12345'
HOUR = timedelta(hours=1)


class CommunicationTestCase(TestCase):
    def setUp(self):
        schedule()
        self.bde = account('bde_anil', role='BDE', mobile_number=BDE_PHONE)
        self.other_bde = account('bde_bina', role='BDE', mobile_number='+91 90000 00000')
        self.admin = account('admin_ops', role='ADMIN')
        self.tutor = account('tutor_anu', role='TUTOR', tutor_meet_link=MEET_LINK)
        self.links = {booking_type: link(self.bde, booking_type) for booking_type in (DEMO, DIAGNOSTIC)}
        self.children = iter(range(1, 1000))

    def book(self, booking_type=DEMO, owned=True, day=DAY, at=EVENING, now=NOW):
        """A public booking; its lead is the BDE's when ``owned`` (it came through their link)."""
        child = next(self.children)
        booking, _ = create_booking(request(
            student=f'Child {child}', phone=f'05077{child:05d}', booking_type=booking_type, day=day, at=at,
            ref=self.links[booking_type].token if owned else None,
        ), now=now)
        return booking

    def ready(self, booking, now=NOW):
        """``booking`` with a tutor who has a Meet link."""
        return assign_tutor(booking, self.tutor, actor=self.admin, now=now)[0]

    @staticmethod
    def tasks(booking):
        return {task.step: task for task in booking.communication_tasks.all()}

    @staticmethod
    def messages(booking):
        return {message.template_id: message for message in booking.communication_messages.all()}


class NewBookingTests(CommunicationTestCase):
    def test_every_booking_gets_its_five_tasks_in_its_own_tables(self):
        for booking_type, model in ((DEMO, DemoBooking), (DIAGNOSTIC, DiagnosticBooking)):
            with self.subTest(booking_type=booking_type):
                booking = self.book(booking_type)
                self.assertIsInstance(booking, model)
                tasks = self.tasks(booking)
                self.assertEqual(set(tasks), set(Step))
                self.assertEqual({task.number for task in tasks.values()}, {1, 2, 3, 4, 5})
                self.assertTrue(all(task.status == TaskStatus.OPEN for task in tasks.values()))
                self.assertEqual(set(self.messages(booking)), {f'{booking_type}_ACKNOWLEDGEMENT', f'{booking_type}_CONFIRMED'})

    def test_the_prd_deadlines(self):
        booking = self.book()
        starts, ends = booking.slot.starts_at, booking.slot.ends_at
        expected = {
            Step.ACKNOWLEDGEMENT: (NOW, NOW + 3 * HOUR, starts),
            Step.CONFIRMATION_REQUEST: (NOW, starts - 12 * HOUR, starts),
            Step.PARENT_CONFIRMATION: (NOW, starts, starts),
            Step.PRE_ACTIVITY_CALL: (starts - timedelta(minutes=15), starts, ends),
            Step.AFTER_ACTIVITY: (None, None, None),
        }
        for step, task in self.tasks(booking).items():
            with self.subTest(step=step):
                self.assertEqual((task.active_from, task.due_at, task.expires_at), expected[step])

    def test_a_booking_within_twelve_hours_has_its_confirmation_request_due_now(self):
        late = datetime(2026, 10, 27, 23, 0, tzinfo=BOOKING_TIMEZONE)  # 11 hours before 10:00 on 28 Oct
        booking = self.book(at=MORNING, now=late)
        self.assertEqual(self.tasks(booking)[Step.CONFIRMATION_REQUEST].due_at, late)

    def test_the_lead_owner_bde_owns_the_tasks_and_the_admin_owns_an_unowned_leads(self):
        owned, unowned = self.book(), self.book(owned=False)
        self.assertEqual({(t.owner_role, t.owner) for t in self.tasks(owned).values()}, {(OwnerRole.BDE, self.bde)})
        self.assertEqual({(t.owner_role, t.owner) for t in self.tasks(unowned).values()}, {(OwnerRole.ADMIN, None)})

    def test_the_acknowledgement_is_ready_with_the_prd_text_and_the_bookings_own_values(self):
        for booking_type in (DEMO, DIAGNOSTIC):
            with self.subTest(booking_type=booking_type):
                booking = self.book(booking_type)
                ack = self.messages(booking)[f'{booking_type}_ACKNOWLEDGEMENT']
                prefix = booking_type.lower()
                expected = (prd_text(f'{booking_type}_ACKNOWLEDGEMENT')
                            .replace(f'{{{{{prefix}_date}}}}', 'Wed, 28 Oct 2026')
                            .replace(f'{{{{{prefix}_time}}}}', '7:30 PM')
                            .replace('{{bde_name}}', 'Bde Anil'))
                self.assertEqual((ack.status, ack.body), (MessageStatus.PENDING, expected))
                self.assertEqual(ack.recipient_phone, booking.lead.phone_key)
                self.assertEqual(ack.template_version.version, 1)
                self.assertEqual(ack.variables, {f'{prefix}_date': 'Wed, 28 Oct 2026', f'{prefix}_time': '7:30 PM',
                                                 'bde_name': 'Bde Anil'})
                self.assertEqual((ack.scheduled_for, ack.send_before), (NOW, booking.slot.starts_at))
                # Written, not sent: no channel, no attempt, no sent time.
                self.assertEqual((ack.channel, ack.sent_at, ack.attempt_count), ('', None, 0))
                self.assertFalse(MessageAttempt.objects.exists())

    def test_the_confirmed_message_waits_from_the_start(self):
        booking = self.ready(self.book())
        confirmed = self.messages(booking)['DEMO_CONFIRMED']
        self.assertEqual((confirmed.status, confirmed.body, confirmed.template_version), (MessageStatus.WAITING, '', None))

    def test_an_unowned_leads_acknowledgement_waits_without_a_central_contact(self):
        ack = self.messages(self.book(owned=False))['DEMO_ACKNOWLEDGEMENT']
        self.assertEqual((ack.status, ack.body), (MessageStatus.WAITING, ''))

    @override_settings(COMMUNICATIONS_FALLBACK_SENDER_NAME='Eduport Plus Team', COMMUNICATIONS_FALLBACK_SENDER_PHONE='+91 80000 00000')
    def test_an_unowned_lead_signs_with_the_central_contact(self):
        ack = self.messages(self.book(owned=False))['DEMO_ACKNOWLEDGEMENT']
        self.assertEqual(ack.status, MessageStatus.PENDING)
        self.assertTrue(ack.body.endswith('**Eduport Plus Team**\n\n**Eduport Plus**'))

    def test_a_repeated_submission_plans_nothing_more(self):
        values = dict(student='Riya', phone='0507700001', ref=self.links[DEMO].token)
        first, _ = create_booking(request(**values), now=NOW)
        again, created = create_booking(request(**values), now=NOW)
        self.assertEqual((again.pk, created), (first.pk, False))
        self.assertEqual((CommunicationTask.objects.count(), Message.objects.count()), (5, 2))

    def test_a_booking_that_rolls_back_leaves_no_communication(self):
        with mock.patch.object(planner, '_add_message', side_effect=RuntimeError('planning failed')):
            with self.assertRaises(RuntimeError):
                self.book()
        self.assertFalse(DemoBooking.objects.exists())
        self.assertEqual((CommunicationTask.objects.count(), Message.objects.count()), (0, 0))


class CancellationTests(CommunicationTestCase):
    def test_cancelling_stops_what_was_not_sent_and_keeps_what_was(self):
        booking = self.book()
        ack = self.messages(booking)['DEMO_ACKNOWLEDGEMENT']
        Message.objects.filter(pk=ack.pk).update(status=MessageStatus.SENT, sent_at=NOW)  # as a sender would
        cancel_booking(booking, reason_code=CancelReason.PARENT_REQUEST, actor=self.admin, now=NOW)

        tasks, messages = self.tasks(booking), self.messages(booking)
        self.assertEqual({(t.status, t.resolution) for t in tasks.values()},
                         {(TaskStatus.CANCELLED, TaskResolution.BOOKING_CANCELLED)})
        self.assertEqual(messages['DEMO_ACKNOWLEDGEMENT'].status, MessageStatus.SENT)
        confirmed = messages['DEMO_CONFIRMED']
        self.assertEqual((confirmed.status, confirmed.cancel_reason), (MessageStatus.CANCELLED, MessageCancelReason.BOOKING_CANCELLED))


class RescheduleTests(CommunicationTestCase):
    def move(self, booking, day=DAY + timedelta(days=1), at=MORNING):
        return reschedule_booking(booking, day, at, reason_code=RescheduleReason.PARENT_REQUEST, actor=self.admin, now=NOW).booking

    def test_the_old_booking_stops_and_the_new_one_is_planned_from_its_own_slot(self):
        old = self.book()
        new = self.move(old)
        self.assertEqual({(t.status, t.resolution) for t in self.tasks(old).values()},
                         {(TaskStatus.CANCELLED, TaskResolution.BOOKING_RESCHEDULED)})
        self.assertEqual({m.status for m in self.messages(old).values()}, {MessageStatus.CANCELLED})

        tasks = self.tasks(new)
        self.assertEqual(len(tasks), 5)
        self.assertEqual(tasks[Step.PRE_ACTIVITY_CALL].active_from, new.slot.starts_at - timedelta(minutes=15))
        self.assertEqual(new.parent_confirmation, ParentConfirmation.AWAITING)
        # The old acknowledgement was never sent, so the new one goes, with the new date.
        ack = self.messages(new)['DEMO_ACKNOWLEDGEMENT']
        self.assertEqual(ack.status, MessageStatus.PENDING)
        self.assertIn(f'**{format_date(new.slot.local_date)} at 10:00 AM IST**', ack.body)

    def test_an_acknowledgement_already_sent_in_the_chain_is_not_sent_again(self):
        first = self.book()
        Message.objects.filter(demo_booking=first, template__step=Step.ACKNOWLEDGEMENT).update(
            status=MessageStatus.SENT, sent_at=NOW,
        )
        second = self.move(first)
        third = self.move(second, day=DAY + timedelta(days=2))
        for booking in (second, third):
            with self.subTest(booking=booking.pk):
                task = self.tasks(booking)[Step.ACKNOWLEDGEMENT]
                self.assertEqual((task.status, task.resolution), (TaskStatus.DONE, TaskResolution.ALREADY_ACKNOWLEDGED))
                self.assertNotIn('DEMO_ACKNOWLEDGEMENT', self.messages(booking))
        self.assertEqual(self.messages(first)['DEMO_ACKNOWLEDGEMENT'].status, MessageStatus.SENT)

    def test_the_whole_chain_is_checked_wherever_in_it_the_acknowledgement_went(self):
        first = self.book()  # its acknowledgement never goes: cancelled by the move
        second = self.move(first)  # so the second writes its own, which a provider accepts
        Message.objects.filter(demo_booking=second, template__step=Step.ACKNOWLEDGEMENT).update(
            status=MessageStatus.QUEUED, queued_at=NOW,
        )
        third = self.move(second, day=DAY + timedelta(days=2))
        fourth = self.move(third, day=DAY + timedelta(days=3), at=EVENING)
        for booking in (third, fourth):
            with self.subTest(booking=booking.pk):
                task = self.tasks(booking)[Step.ACKNOWLEDGEMENT]
                self.assertEqual((task.status, task.resolution), (TaskStatus.DONE, TaskResolution.ALREADY_ACKNOWLEDGED))
                self.assertNotIn('DEMO_ACKNOWLEDGEMENT', self.messages(booking))
        acks = Message.objects.filter(template__step=Step.ACKNOWLEDGEMENT)
        self.assertEqual(
            {(ack.demo_booking_id, ack.status, ack.cancel_reason) for ack in acks},
            {(first.pk, MessageStatus.CANCELLED, MessageCancelReason.BOOKING_RESCHEDULED),
             (second.pk, MessageStatus.QUEUED, '')},
        )


class CompletionTests(CommunicationTestCase):
    def complete(self, booking, minutes=50):
        at = booking.slot.starts_at + timedelta(minutes=minutes)
        start(booking)
        submit_report(booking, self.tutor, report_input(booking), now=at)
        return at

    def test_completion_writes_the_after_activity_message_once(self):
        for booking_type in (DEMO, DIAGNOSTIC):
            with self.subTest(booking_type=booking_type):
                # The tutor teaches both, so not at the same time.
                booking = self.ready(self.book(booking_type, at=MORNING if booking_type == DIAGNOSTIC else EVENING))
                at = self.complete(booking)
                key = f'{booking_type}_AFTER_ACTIVITY'
                after = self.messages(booking)[key]
                self.assertEqual(after.status, MessageStatus.PENDING)
                self.assertEqual(after.body, prd_text(key).replace('{{bde_name}}', 'Bde Anil'))
                task = self.tasks(booking)[Step.AFTER_ACTIVITY]
                self.assertEqual((task.active_from, task.due_at), (at, at + 3 * HOUR))
                # It goes within 24 hours of completion or not at all.
                self.assertEqual((after.scheduled_for, after.send_before), (at, at + 24 * HOUR))

                # Neither a second run nor a report edit writes another.
                booking.refresh_from_db()
                planner.booking_completed(booking, at + HOUR)
                edit_report(booking, self.tutor, report_input(booking, **(
                    {'suggested_strategy': 'Changed.'} if booking_type == DEMO else {'teacher_remarks': 'Changed.'})), 1)
                self.assertEqual(booking.communication_messages.filter(template_id=key).count(), 1)

    def test_steps_that_can_no_longer_be_done_are_missed_at_completion(self):
        booking = self.ready(self.book())
        self.complete(booking, minutes=50)
        tasks = self.tasks(booking)
        for step in (Step.ACKNOWLEDGEMENT, Step.CONFIRMATION_REQUEST, Step.PARENT_CONFIRMATION):
            self.assertEqual(tasks[step].status, TaskStatus.MISSED, step)
        # The call's reminder ended at the start; the after-activity step is open with its message.
        call = tasks[Step.PRE_ACTIVITY_CALL]
        self.assertEqual((call.status, call.resolution, call.resolved_at, tasks[Step.AFTER_ACTIVITY].status),
                         (TaskStatus.DONE, TaskResolution.REMINDED, booking.slot.starts_at, TaskStatus.OPEN))
        messages = self.messages(booking)
        self.assertEqual((messages['DEMO_ACKNOWLEDGEMENT'].status, messages['DEMO_ACKNOWLEDGEMENT'].cancel_reason),
                         (MessageStatus.CANCELLED, MessageCancelReason.EXPIRED))


class ExpiryTests(CommunicationTestCase):
    def test_tasks_and_messages_whose_time_ran_out(self):
        booking = self.book()
        starts, ends = booking.slot.starts_at, booking.slot.ends_at
        planner.close_expired(starts - timedelta(minutes=1))
        self.assertTrue(all(t.status == TaskStatus.OPEN for t in self.tasks(booking).values()))

        # The three steps before the start are Missed (the call is no longer counted among them).
        self.assertEqual(planner.close_expired(starts), (3, 2))
        tasks = self.tasks(booking)
        self.assertEqual({step for step, task in tasks.items() if task.status == TaskStatus.MISSED},
                         {Step.ACKNOWLEDGEMENT, Step.CONFIRMATION_REQUEST, Step.PARENT_CONFIRMATION})
        self.assertEqual({m.cancel_reason for m in self.messages(booking).values()}, {MessageCancelReason.EXPIRED})

        # Nothing else is Missed, at the slot's end or later; the after-activity step waits for completion.
        planner.close_expired(ends + timedelta(days=3))
        tasks = self.tasks(booking)
        self.assertEqual(tasks[Step.PRE_ACTIVITY_CALL].status, TaskStatus.DONE)
        self.assertEqual(tasks[Step.AFTER_ACTIVITY].status, TaskStatus.OPEN)


class CallReminderTests(CommunicationTestCase):
    """The 15-minute call is a reminder only: from 15 minutes before the start, done at it, never Missed."""

    @staticmethod
    def call(booking):
        return booking.communication_tasks.get(step=Step.PRE_ACTIVITY_CALL)

    def closed(self, booking):
        call = self.call(booking)
        return call.status, call.resolution, call.resolved_at, call.resolved_by

    def test_it_reminds_from_fifteen_minutes_before_and_is_done_at_the_start(self):
        for booking_type in (DEMO, DIAGNOSTIC):
            with self.subTest(booking_type=booking_type):
                booking = self.book(booking_type)
                starts = booking.slot.starts_at
                call = self.call(booking)
                self.assertEqual((call.active_from, call.due_at), (starts - timedelta(minutes=15), starts))
                # Open while it reminds, to the last second before the start.
                for moment in (starts - timedelta(minutes=15), starts - timedelta(seconds=1)):
                    planner.close_expired(moment)
                    self.assertEqual(self.call(booking).status, TaskStatus.OPEN)
                planner.close_expired(starts)
                self.assertEqual(self.closed(booking), (TaskStatus.DONE, TaskResolution.REMINDED, starts, None))

    def test_done_as_of_the_start_however_late_the_sweep_runs_and_never_missed(self):
        booking = self.book()
        starts, ends = booking.slot.starts_at, booking.slot.ends_at
        planner.close_expired(starts + timedelta(minutes=4))  # the sweep runs every 5 minutes
        done = (TaskStatus.DONE, TaskResolution.REMINDED, starts, None)
        self.assertEqual(self.closed(booking), done)
        for moment in (ends, ends + timedelta(days=3)):
            planner.close_expired(moment)
            self.assertEqual(self.closed(booking), done)

    def test_it_never_starts_the_booking(self):
        booking = self.ready(self.book())
        starts = booking.slot.starts_at
        planner.close_expired(starts + timedelta(minutes=2))
        self.assertEqual(self.call(booking).status, TaskStatus.DONE)
        booking.refresh_from_db()
        self.assertEqual((booking.status, booking.started_at, booking.started_by), (BookingStatus.BOOKED, None, None))
        self.assertFalse(booking.events.filter(kind=BookingEventKind.STARTED).exists())
        self.assertEqual(activity_state(booking, starts + timedelta(minutes=2)), ActivityState.LATE)
        # Only its tutor's Start starts it, and that leaves the reminder as it was.
        started = start(booking, minutes=3)
        self.assertEqual((started.started_at, started.started_by), (starts + timedelta(minutes=3), self.tutor))
        self.assertEqual(self.closed(booking), (TaskStatus.DONE, TaskResolution.REMINDED, starts, None))

    def test_a_booking_cancelled_before_the_start_keeps_its_reminder_cancelled(self):
        booking = self.book()
        cancel_booking(booking, reason_code=CancelReason.PARENT_REQUEST, actor=self.admin, now=NOW)
        planner.close_expired(booking.slot.starts_at)
        self.assertEqual(self.call(booking).status, TaskStatus.CANCELLED)
