"""
Sending one Pending message (communications.sending, Phase 2B step 2): the
claim under the booking's and the message's locks, the provider called outside
any transaction, and the result -- one attempt each time, the message Queued,
Sent or Failed as the provider said, the task Done only when it accepted. A
message is sent once at most; one cancelled before the claim never goes; one
whose booking is cancelled during the call is recorded truthfully; one whose
outcome is unknown is never sent again by itself. Nothing reaches WhatsApp:
the provider is the test-only fake, or the console.
"""
import threading
import time as clock
from datetime import timedelta
from unittest import mock, skipUnless

from django.db import OperationalError, connection, transaction
from django.test import TransactionTestCase, override_settings

from accounts.models import User
from bookings.booking_service import (
    _locked_booking,
    cancel_booking,
    create_booking,
    record_parent_confirmation,
    reschedule_booking,
)
from bookings.models import CancelReason, DemoBooking, Lead, ParentConfirmation, RescheduleReason
from bookings.tests_booking import DAY, DEMO, MORNING, NOW, account, link, request, schedule, start
from reports.services import submit_report
from reports.tests_services import report_input

from . import planner, sending
from .formatting import whatsapp_message
from .models import (
    AttemptOutcome,
    Channel,
    Message,
    MessageAttempt,
    MessageCancelReason,
    MessageStatus,
    MessageTemplate,
    OUTCOME_UNKNOWN,
    Step,
    TaskResolution,
    TaskStatus,
    template_key,
)
from .overview import booking_communication
from .providers.base import SendResult
from .rendering import Requirement, requirements
from .safety import SendBlock
from .sending import NO_OUTCOME, SendOutcome, _claim, _finish, due_message_ids, recover_stuck_sends, send_message
from .services import request_confirmation
from .tests_planning import CommunicationTestCase
from .tests_providers import FakeProvider, use_fake_provider

# Sending on, through the fake, to anyone: what each test then narrows.
SENDING = dict(
    COMMUNICATIONS_SENDING_ENABLED=True,
    COMMUNICATIONS_WHATSAPP_PROVIDER='fake',
    COMMUNICATIONS_RECIPIENT_ALLOWLIST=[],
    COMMUNICATIONS_ALLOW_ALL_RECIPIENTS=True,
    COMMUNICATIONS_PROVIDER_TIMEOUT=7,
)
SENT = SendResult(accepted=True, status=MessageStatus.SENT, provider_message_id='wamid.1')
RETRYABLE = SendResult(accepted=False, error_code='RATE_LIMITED', error_message='Too many messages', retryable=True)
MINUTE = timedelta(minutes=1)


@override_settings(**SENDING)
class SenderTestCase(CommunicationTestCase):
    def setUp(self):
        super().setUp()
        FakeProvider.reset()
        patcher = use_fake_provider()
        patcher.start()
        self.addCleanup(patcher.stop)

    @staticmethod
    def message(booking, step=Step.ACKNOWLEDGEMENT):
        return booking.communication_messages.select_related('template_version', 'task').get(template__step=step)

    @staticmethod
    def fresh(message):
        return Message.objects.select_related('task').get(pk=message.pk)

    def assert_untouched(self, message, status=MessageStatus.PENDING):
        message = self.fresh(message)
        self.assertEqual((message.status, message.claimed_at, message.attempt_count), (status, None, 0))
        self.assertFalse(message.attempts.exists())
        self.assertEqual(FakeProvider.outbox, [])


class AcceptedTests(SenderTestCase):
    def test_a_sent_message_is_recorded_and_its_task_done(self):
        booking = self.book()
        ack = self.message(booking)
        FakeProvider.reset(SENT)
        self.assertEqual(send_message(ack.pk, now=NOW).outcome, SendOutcome.SENT)

        ack = self.fresh(ack)
        self.assertEqual(
            (ack.status, ack.claimed_at, ack.attempt_count, ack.channel, ack.provider, ack.provider_message_id),
            (MessageStatus.SENT, None, 1, Channel.WHATSAPP, 'fake', 'wamid.1'),
        )
        self.assertIsNotNone(ack.sent_at)
        attempt = ack.attempts.get()
        self.assertEqual(
            (attempt.number, attempt.outcome, attempt.provider, attempt.provider_message_id, attempt.error_code,
             attempt.retryable, attempt.triggered_by),
            (1, AttemptOutcome.ACCEPTED, 'fake', 'wamid.1', '', False, None),
        )
        self.assertLessEqual(attempt.started_at, attempt.finished_at)
        self.assertEqual((ack.task.status, ack.task.resolution, ack.task.resolved_by),
                         (TaskStatus.DONE, TaskResolution.SENT, None))

        # What the provider was given: WhatsApp's text from the template and the values, the digits, the timeout.
        outgoing, timeout = FakeProvider.outbox[0]
        self.assertEqual(timeout, 7)
        self.assertEqual(outgoing.to, booking.lead.phone_key[1:])
        self.assertEqual(outgoing.text, whatsapp_message(ack.template_version.body, ack.variables))
        self.assertIn('Demo class on *Wed, 28 Oct 2026 at 7:30 PM IST*.', outgoing.text)
        self.assertNotIn('**', outgoing.text)
        self.assertEqual((outgoing.message_id, outgoing.template_key, outgoing.provider_ref),
                         (str(ack.pk), 'DEMO_ACKNOWLEDGEMENT', {}))

    def test_queued_is_accepted_too(self):
        ack = self.message(self.book())
        self.assertEqual(send_message(ack.pk, now=NOW).outcome, SendOutcome.QUEUED)
        ack = self.fresh(ack)
        self.assertEqual((ack.status, ack.sent_at, ack.task.status), (MessageStatus.QUEUED, None, TaskStatus.DONE))
        self.assertIsNotNone(ack.queued_at)
        # Done, and said as it is: accepted and queued, not sent -- let alone delivered or read.
        self.assertEqual(ack.task.resolution, TaskResolution.ACCEPTED)
        self.assertNotEqual(TaskResolution.ACCEPTED.label, TaskResolution.SENT.label)

    def test_a_message_is_sent_once(self):
        ack = self.message(self.book())
        send_message(ack.pk, now=NOW)
        self.assertEqual(send_message(ack.pk, now=NOW).outcome, SendOutcome.NOT_PENDING)
        self.assertEqual((len(FakeProvider.outbox), MessageAttempt.objects.count()), (1, 1))
        self.assertNotIn(ack.pk, due_message_ids(NOW))

    @override_settings(COMMUNICATIONS_WHATSAPP_PROVIDER='console', COMMUNICATIONS_ALLOW_ALL_RECIPIENTS=False)
    def test_the_console_provider_end_to_end(self):
        booking = self.book()
        ack = self.message(booking)
        with override_settings(COMMUNICATIONS_RECIPIENT_ALLOWLIST=[booking.lead.phone_key]):
            with self.assertLogs('communications.providers.console', 'INFO') as logged:
                self.assertEqual(send_message(ack.pk, now=NOW).outcome, SendOutcome.SENT)
        ack = self.fresh(ack)
        self.assertEqual((ack.status, ack.provider, ack.provider_message_id),
                         (MessageStatus.SENT, 'console', f'console-{ack.pk}'))
        self.assertIn('*Wed, 28 Oct 2026 at 7:30 PM IST*', logged.output[0])
        self.assertNotIn(booking.lead.phone_key[1:], logged.output[0])

    def test_the_after_activity_message_of_a_completed_booking(self):
        booking = self.ready(self.book())
        completed_at = booking.slot.starts_at + timedelta(minutes=50)
        start(booking)
        submit_report(booking, self.tutor, report_input(booking), now=completed_at)
        after = self.message(booking, Step.AFTER_ACTIVITY)
        self.assertEqual(send_message(after.pk, now=completed_at + timedelta(minutes=5)).outcome, SendOutcome.QUEUED)
        self.assertEqual(self.fresh(after).task.status, TaskStatus.DONE)


class StartedBookingTests(SenderTestCase):
    """
    Once the tutor has started a booking (booking_service.start_booking), the
    automatic messages before the class -- acknowledgement, confirmation
    request, confirmed message -- no longer go, however early the start: the
    sender's own check (rendering.Requirement.BOOKING_ACTIVE) leaves them
    Waiting, and the expiry sweep closes them at the scheduled start as it
    always did. A booking not started goes on as before.
    """

    def test_the_gate_reads_the_start_as_well_as_the_clock(self):
        started, upcoming = self.ready(self.book()), self.ready(self.book(day=DAY + timedelta(days=1)))
        start(started, minutes=-5)
        started.refresh_from_db()
        for booking, active in ((started, False), (upcoming, True)):
            early = booking.slot.starts_at - timedelta(minutes=4)
            for step in (Step.ACKNOWLEDGEMENT, Step.CONFIRMATION_REQUEST, Step.PARENT_CONFIRMATION):
                with self.subTest(step=step, active=active):
                    body = MessageTemplate.objects.get(key=template_key(booking.booking_type, step)).current_version().body
                    checks = dict(requirements(booking, step, body, early))
                    self.assertEqual(checks[Requirement.BOOKING_ACTIVE], active)
                    # The scheduled time passing closes it either way, as before.
                    self.assertFalse(dict(requirements(booking, step, body, booking.slot.starts_at))[Requirement.BOOKING_ACTIVE])
        self.assertEqual(Requirement.BOOKING_ACTIVE.label, 'Booking still upcoming and not started')

    def test_pending_messages_wait_once_started_and_expire_at_the_scheduled_start(self):
        # Asked to confirm, not yet answered: a Pending acknowledgement and confirmation request.
        asked = self.ready(self.book())
        request = request_confirmation(asked, actor=self.admin, now=NOW)[0]
        # Confirmed: a Pending confirmed message (tutor, Meet link and BDE in place).
        confirmed = self.ready(self.book(day=DAY + timedelta(days=1)))
        record_parent_confirmation(confirmed, ParentConfirmation.CONFIRMED, actor=self.bde, now=NOW)
        pending = [self.message(asked), request, self.message(confirmed), self.message(confirmed, Step.PARENT_CONFIRMATION)]
        for message in pending:
            self.assertEqual(self.fresh(message).status, MessageStatus.PENDING)
        # The control: the same shape, never started, goes at the same moment of its own slot.
        control = self.ready(self.book(day=DAY + timedelta(days=2)))

        for booking in (asked, confirmed):
            start(booking, minutes=-5)
        for message in pending:
            booking = message.booking
            early = booking.slot.starts_at - timedelta(minutes=4)
            with self.subTest(step=message.template.step):
                self.assertEqual(send_message(message.pk, now=early).outcome, SendOutcome.WAITING)
                message = self.fresh(message)
                self.assertEqual((message.status, message.body, message.attempt_count), (MessageStatus.WAITING, '', 0))
        self.assertEqual(FakeProvider.outbox, [])
        self.assertEqual(
            send_message(self.message(control).pk, now=control.slot.starts_at - timedelta(minutes=4)).outcome,
            SendOutcome.QUEUED,
        )
        self.assertEqual(len(FakeProvider.outbox), 1)

        # What the overview says such a message waits for; then the sweep closes it at the scheduled start, as always.
        asked.refresh_from_db()
        shown = booking_communication(asked, asked.slot.starts_at - timedelta(minutes=4), self.admin)['messages']
        by_step = {item['step']: item['waiting_for'] for item in shown}
        gate = {'code': 'BOOKING_ACTIVE', 'label': 'Booking still upcoming and not started'}
        self.assertEqual(by_step['ACKNOWLEDGEMENT'], [gate])
        self.assertEqual(by_step['CONFIRMATION_REQUEST'], [gate])
        # Its own confirmed message, never answered, waits for the parent as well.
        self.assertEqual(by_step['PARENT_CONFIRMATION'], [{'code': 'PARENT_CONFIRMED', 'label': 'Parent confirmation'}, gate])
        planner.close_expired(asked.slot.starts_at)
        for message in pending[:2]:
            message = self.fresh(message)
            self.assertEqual((message.status, message.cancel_reason), (MessageStatus.CANCELLED, MessageCancelReason.EXPIRED))


class RefusedTests(SenderTestCase):
    def test_a_refusal_is_failed_with_its_code_and_the_task_stays_open(self):
        ack = self.message(self.book())
        FakeProvider.reset(SendResult(accepted=False, error_code='131026', error_message='Not a WhatsApp user'))
        self.assertEqual(send_message(ack.pk, now=NOW).outcome, SendOutcome.FAILED)
        ack = self.fresh(ack)
        self.assertEqual((ack.status, ack.failure_code, ack.failure_reason, ack.claimed_at, ack.attempt_count),
                         (MessageStatus.FAILED, '131026', 'Not a WhatsApp user', None, 1))
        self.assertIsNotNone(ack.failed_at)
        attempt = ack.attempts.get()
        self.assertEqual((attempt.outcome, attempt.error_code, attempt.retryable), (AttemptOutcome.FAILED, '131026', False))
        self.assertEqual(ack.task.status, TaskStatus.OPEN)

    def test_whether_a_retry_may_work_is_kept_for_later(self):
        ack = self.message(self.book())
        FakeProvider.reset(SendResult(accepted=False, error_code='RATE_LIMITED', retryable=True))
        send_message(ack.pk, now=NOW)
        self.assertTrue(self.fresh(ack).attempts.get().retryable)

    def test_an_exception_or_timeout_is_an_unknown_outcome_never_sent_again(self):
        for error, code in ((TimeoutError('read timed out'), 'TIMEOUT'), (RuntimeError('connection reset'), 'PROVIDER_ERROR')):
            with self.subTest(code=code):
                FakeProvider.reset(error)
                ack = self.message(self.book())
                self.assertEqual(send_message(ack.pk, now=NOW).outcome, SendOutcome.UNKNOWN)
                ack = self.fresh(ack)
                self.assertEqual((ack.status, ack.failure_code, ack.claimed_at), (MessageStatus.FAILED, OUTCOME_UNKNOWN, None))
                self.assertIn('check WhatsApp before sending it again', ack.failure_reason)
                attempt = ack.attempts.get()
                self.assertEqual((attempt.outcome, attempt.error_code, attempt.retryable),
                                 (AttemptOutcome.UNKNOWN, code, False))
                self.assertEqual(ack.task.status, TaskStatus.OPEN)
                # Never by itself again.
                self.assertEqual(send_message(ack.pk, now=NOW).outcome, SendOutcome.NOT_PENDING)
                self.assertEqual(len(FakeProvider.outbox), 1)


class EligibilityTests(SenderTestCase):
    def test_held_back_by_the_safety_settings_it_stays_pending(self):
        booking = self.book()
        ack = self.message(booking)
        cases = (
            (dict(COMMUNICATIONS_SENDING_ENABLED=False), SendBlock.SENDING_DISABLED),
            (dict(COMMUNICATIONS_WHATSAPP_PROVIDER='none'), SendBlock.NO_PROVIDER),
            # The allow-list closed: empty means nobody.
            (dict(COMMUNICATIONS_ALLOW_ALL_RECIPIENTS=False), SendBlock.RECIPIENT_NOT_ALLOWED),
            (dict(COMMUNICATIONS_ALLOW_ALL_RECIPIENTS=False, COMMUNICATIONS_RECIPIENT_ALLOWLIST=['+966501234567']),
             SendBlock.RECIPIENT_NOT_ALLOWED),
        )
        for changes, block in cases:
            with self.subTest(block=block, changes=changes), override_settings(**changes):
                report = send_message(ack.pk, now=NOW)
                self.assertEqual((report.outcome, report.block), (SendOutcome.BLOCKED, block))
                self.assert_untouched(ack)
        with override_settings(COMMUNICATIONS_ALLOW_ALL_RECIPIENTS=False,
                               COMMUNICATIONS_RECIPIENT_ALLOWLIST=[booking.lead.phone_key]):
            self.assertEqual(send_message(ack.pk, now=NOW).outcome, SendOutcome.QUEUED)

    def test_an_invalid_recipient_fails_without_asking_the_provider(self):
        booking = self.book()
        Lead.objects.filter(pk=booking.lead_id).update(phone_key=booking.lead.phone_key[1:])  # its + and code lost
        ack = self.message(booking)
        self.assertEqual(send_message(ack.pk, now=NOW).outcome, SendOutcome.INVALID_RECIPIENT)
        ack = self.fresh(ack)
        self.assertEqual((ack.status, ack.failure_code), (MessageStatus.FAILED, 'INVALID_RECIPIENT'))
        self.assertFalse(ack.attempts.exists())
        self.assertEqual(FakeProvider.outbox, [])

    def test_only_when_due(self):
        ack = self.message(self.book())
        for changes in (dict(scheduled_for=NOW + timedelta(minutes=1)), dict(send_before=NOW),
                        dict(next_attempt_at=NOW + timedelta(minutes=5))):
            with self.subTest(changes=changes):
                Message.objects.filter(pk=ack.pk).update(scheduled_for=NOW, send_before=NOW + timedelta(days=1),
                                                         next_attempt_at=None)
                Message.objects.filter(pk=ack.pk).update(**changes)
                self.assertNotIn(ack.pk, due_message_ids(NOW))
                self.assertEqual(send_message(ack.pk, now=NOW).outcome, SendOutcome.NOT_DUE)
                self.assert_untouched(ack)

    def test_everything_is_checked_again_just_before_sending(self):
        booking = self.ready(self.book())
        record_parent_confirmation(booking, ParentConfirmation.CONFIRMED, actor=self.bde, now=NOW)
        confirmed = self.message(booking, Step.PARENT_CONFIRMATION)
        self.assertEqual(confirmed.status, MessageStatus.PENDING)

        # A tutor renamed behind the hooks' back: the text sent is the booking's as it is now.
        User.objects.filter(pk=self.tutor.pk).update(full_name='Tutor Anu Menon')
        send_message(confirmed.pk, now=NOW)
        self.assertIn('Tutor: Tutor Anu Menon', FakeProvider.outbox[0][0].text)

        # A tutor removed behind the hooks' back: Waiting, not sent.
        second = self.ready(self.book(at=MORNING))
        record_parent_confirmation(second, ParentConfirmation.CONFIRMED, actor=self.bde, now=NOW)
        DemoBooking.objects.filter(pk=second.pk).update(
            assigned_tutor=None, tutor_assigned_at=None, tutor_assigned_by=None, tutor_meet_link=None,
        )
        waiting = self.message(second, Step.PARENT_CONFIRMATION)
        self.assertEqual(send_message(waiting.pk, now=NOW).outcome, SendOutcome.WAITING)
        self.assertEqual((self.fresh(waiting).status, len(FakeProvider.outbox)), (MessageStatus.WAITING, 1))

    def test_an_after_activity_message_is_never_sent_after_its_window(self):
        """Within 24 hours of completion or not at all: one left Pending while sending was off never goes days late."""
        booking = self.ready(self.book())
        completed_at = booking.slot.starts_at + timedelta(minutes=50)
        start(booking)
        submit_report(booking, self.tutor, report_input(booking), now=completed_at)
        after = self.message(booking, Step.AFTER_ACTIVITY)
        closes = completed_at + timedelta(hours=24)
        self.assertEqual((after.status, after.send_before), (MessageStatus.PENDING, closes))
        self.assertIn(after.pk, due_message_ids(closes - timedelta(seconds=1)))
        self.assertNotIn(after.pk, due_message_ids(closes))
        self.assertEqual(send_message(after.pk, now=closes).outcome, SendOutcome.NOT_DUE)
        planner.close_expired(closes)
        after = self.fresh(after)
        self.assertEqual((after.status, after.cancel_reason), (MessageStatus.CANCELLED, MessageCancelReason.EXPIRED))
        self.assertEqual(FakeProvider.outbox, [])


class QueueTests(SenderTestCase):
    """What the dispatcher picks up: only what the safety gate would let through, the longest due first."""

    def test_messages_the_allow_list_holds_back_never_fill_a_batch(self):
        held_back = [self.message(self.book()).pk for _ in range(2)]
        allowed = self.book()
        ack = self.message(allowed)
        # Without the allow-list in force, the two older ones fill a batch of two.
        self.assertEqual(due_message_ids(NOW, limit=2), held_back)
        with override_settings(COMMUNICATIONS_ALLOW_ALL_RECIPIENTS=False,
                               COMMUNICATIONS_RECIPIENT_ALLOWLIST=[allowed.lead.phone_key]):
            self.assertEqual(due_message_ids(NOW, limit=2), [ack.pk])
        # An empty allow-list means nobody.
        with override_settings(COMMUNICATIONS_ALLOW_ALL_RECIPIENTS=False):
            self.assertEqual(due_message_ids(NOW), [])

    def test_the_longest_due_come_first_scheduled_or_not(self):
        late, early, unscheduled = (self.message(self.book()) for _ in range(3))
        Message.objects.filter(pk=late.pk).update(scheduled_for=NOW + 3 * MINUTE)
        Message.objects.filter(pk=early.pk).update(scheduled_for=NOW + 2 * MINUTE)
        # The confirmed message has no schedule: due from when it was written.
        Message.objects.filter(pk=unscheduled.pk).update(scheduled_for=None, created_at=NOW + MINUTE)
        self.assertEqual(due_message_ids(NOW + 5 * MINUTE), [unscheduled.pk, early.pk, late.pk])


class CancellationTests(SenderTestCase):
    def test_cancelled_before_the_claim_it_is_never_sent(self):
        booking = self.book()
        ack = self.message(booking)
        cancel_booking(booking, reason_code=CancelReason.PARENT_REQUEST, actor=self.admin, now=NOW)
        self.assertEqual(send_message(ack.pk, now=NOW).outcome, SendOutcome.NOT_PENDING)
        self.assert_untouched(ack, status=MessageStatus.CANCELLED)

    def test_cancelled_during_the_call_and_accepted_it_was_sent(self):
        booking = self.book()
        ack = self.message(booking)

        def cancel_then_accept(_outgoing):
            cancel_booking(booking, reason_code=CancelReason.PARENT_REQUEST, actor=self.admin, now=NOW)
            # The planner left the message being sent alone, and cancelled the rest.
            self.assertEqual(self.fresh(ack).status, MessageStatus.PENDING)
            return SENT

        FakeProvider.reset(cancel_then_accept)
        self.assertEqual(send_message(ack.pk, now=NOW).outcome, SendOutcome.SENT)
        ack = self.fresh(ack)
        self.assertEqual(ack.status, MessageStatus.SENT)
        # Its step stays as the cancellation closed it.
        self.assertEqual((ack.task.status, ack.task.resolution), (TaskStatus.CANCELLED, TaskResolution.BOOKING_CANCELLED))
        self.assertEqual(self.message(booking, Step.PARENT_CONFIRMATION).status, MessageStatus.CANCELLED)

    def test_cancelled_moved_or_answered_during_the_call_and_refused_it_is_cancelled(self):
        refused = SendResult(accepted=False, error_code='131000', error_message='Something went wrong')
        moves = {
            'cancelled': (lambda booking: cancel_booking(booking, reason_code=CancelReason.PARENT_REQUEST,
                                                       actor=self.admin, now=NOW),
                          Step.ACKNOWLEDGEMENT, MessageCancelReason.BOOKING_CANCELLED),
            'moved': (lambda booking: reschedule_booking(booking, DAY + timedelta(days=1), MORNING,
                                                       reason_code=RescheduleReason.OTHER, actor=self.admin, now=NOW),
                      Step.ACKNOWLEDGEMENT, MessageCancelReason.BOOKING_RESCHEDULED),
            'answered': (lambda booking: record_parent_confirmation(booking, ParentConfirmation.CONFIRMED,
                                                                  actor=self.bde, now=NOW),
                         Step.CONFIRMATION_REQUEST, MessageCancelReason.NOT_NEEDED),
        }
        for name, (change, step, reason) in moves.items():
            with self.subTest(name=name):
                booking = self.book()
                if step == Step.CONFIRMATION_REQUEST:
                    request_confirmation(booking, actor=self.bde, now=NOW)
                message = self.message(booking, step)
                FakeProvider.reset(lambda _outgoing, booking=booking, change=change: (change(booking), refused)[1])
                self.assertEqual(send_message(message.pk, now=NOW).outcome, SendOutcome.CANCELLED)
                message = self.fresh(message)
                self.assertEqual((message.status, message.cancel_reason, message.claimed_at),
                                 (MessageStatus.CANCELLED, reason, None))
                self.assertEqual(message.attempts.get().outcome, AttemptOutcome.FAILED)


class RescheduleDuringAcknowledgementTests(SenderTestCase):
    """
    One acknowledgement per reschedule chain. While an earlier booking's is
    being sent, or its outcome is unknown, the new booking's waits; accepted,
    the new booking's is not needed; refused, the new booking's goes.
    """

    def move(self, booking, day=DAY + timedelta(days=1)):
        return reschedule_booking(booking, day, MORNING, reason_code=RescheduleReason.PARENT_REQUEST,
                                  actor=self.admin, now=NOW).booking

    def earlier_settled(self, booking):
        ack = self.message(booking)
        return dict(requirements(booking, Step.ACKNOWLEDGEMENT, ack.template.current_version().body, NOW))[
            Requirement.EARLIER_ACKNOWLEDGEMENT]

    def send_while_moving(self, outcome):
        """Send a booking's acknowledgement, the booking moved during the call; then ``outcome``."""
        booking = self.book()
        ack = self.message(booking)
        moved = {}

        def move_then_answer(_outgoing):
            moved['booking'] = new = self.move(booking)
            # The old one is being sent, not sent: the new booking's waits.
            new_ack = self.message(new)
            self.assertEqual(new_ack.status, MessageStatus.WAITING)
            self.assertFalse(self.earlier_settled(new))
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        FakeProvider.reset(move_then_answer)
        report = send_message(ack.pk, now=NOW)
        return report, self.fresh(ack), moved['booking']

    def test_accepted_the_new_booking_sends_no_second_one(self):
        for accepted in (SendResult(accepted=True, status=MessageStatus.QUEUED, provider_message_id='wamid.q'),
                         SendResult(accepted=True, status=MessageStatus.SENT, provider_message_id='wamid.s')):
            with self.subTest(status=accepted.status):
                FakeProvider.reset()
                report, old_ack, new = self.send_while_moving(accepted)
                self.assertEqual(old_ack.status, accepted.status)
                new_ack = self.message(new)
                self.assertEqual((new_ack.status, new_ack.cancel_reason),
                                 (MessageStatus.CANCELLED, MessageCancelReason.NOT_NEEDED))
                self.assertEqual((new_ack.task.status, new_ack.task.resolution),
                                 (TaskStatus.DONE, TaskResolution.ALREADY_ACKNOWLEDGED))
                self.assertEqual(send_message(new_ack.pk, now=NOW).outcome, SendOutcome.NOT_PENDING)
                self.assertEqual(len(FakeProvider.outbox), 1)

    def test_refused_the_new_booking_sends_its_own(self):
        report, old_ack, new = self.send_while_moving(SendResult(accepted=False, error_code='131000'))
        self.assertEqual((report.outcome, old_ack.status, old_ack.cancel_reason),
                         (SendOutcome.CANCELLED, MessageStatus.CANCELLED, MessageCancelReason.BOOKING_RESCHEDULED))
        new_ack = self.message(new)
        self.assertEqual(new_ack.status, MessageStatus.PENDING)
        self.assertTrue(self.earlier_settled(new))
        self.assertEqual(send_message(new_ack.pk, now=NOW).outcome, SendOutcome.QUEUED)
        self.assertIn('*Thu, 29 Oct 2026 at 10:00 AM IST*', FakeProvider.outbox[-1][0].text)
        self.assertEqual(len(FakeProvider.outbox), 2)

    def test_unknown_the_new_booking_waits_for_someone_to_check(self):
        report, old_ack, new = self.send_while_moving(TimeoutError('read timed out'))
        self.assertEqual((report.outcome, old_ack.status, old_ack.failure_code),
                         (SendOutcome.UNKNOWN, MessageStatus.FAILED, OUTCOME_UNKNOWN))
        new_ack = self.message(new)
        self.assertEqual((new_ack.status, new_ack.task.status), (MessageStatus.WAITING, TaskStatus.OPEN))
        self.assertFalse(self.earlier_settled(new))
        self.assertEqual(send_message(new_ack.pk, now=NOW).outcome, SendOutcome.NOT_PENDING)
        self.assertEqual(len(FakeProvider.outbox), 1)

    def test_an_earlier_outcome_known_before_the_move(self):
        unknown = self.book()
        Message.objects.filter(demo_booking=unknown, template__step=Step.ACKNOWLEDGEMENT).update(
            status=MessageStatus.FAILED, failed_at=NOW, failure_code=OUTCOME_UNKNOWN,
        )
        second = self.move(unknown)
        third = self.move(second, day=DAY + timedelta(days=2))
        # Unknown anywhere earlier in the chain, and none accepted: still waiting, however often it moved.
        for booking in (second, third):
            with self.subTest(booking=booking.pk):
                self.assertEqual(self.message(booking).status, MessageStatus.WAITING if booking == third
                                 else MessageStatus.CANCELLED)
        self.assertFalse(self.earlier_settled(third))

        refused = self.book()
        Message.objects.filter(demo_booking=refused, template__step=Step.ACKNOWLEDGEMENT).update(
            status=MessageStatus.FAILED, failed_at=NOW, failure_code='131026',
        )
        moved = self.move(refused, day=DAY + timedelta(days=3))
        self.assertEqual(self.message(moved).status, MessageStatus.PENDING)


class UnknownOutcomeTests(SenderTestCase):
    def test_an_unknown_outcome_is_never_rewritten_by_a_cancellation_or_expiry(self):
        booking = self.book()
        ack = self.message(booking)
        FakeProvider.reset(TimeoutError('read timed out'))
        send_message(ack.pk, now=NOW)
        cancel_booking(booking, reason_code=CancelReason.PARENT_REQUEST, actor=self.admin, now=NOW)
        planner.close_expired(booking.slot.ends_at)
        ack = self.fresh(ack)
        self.assertEqual((ack.status, ack.failure_code, ack.cancel_reason), (MessageStatus.FAILED, OUTCOME_UNKNOWN, ''))


class MissedDuringTheCallTests(SenderTestCase):
    """
    The session starts while the message is being sent: the sweep marks its
    task Missed (and leaves the message, being sent, alone). The provider then
    accepts it -- the task is done after all, as Accepted or Sent.
    """

    def send_across_the_start(self, accepted):
        booking = self.book()
        ack = self.message(booking)

        def session_starts_then_accept(_outgoing):
            planner.close_expired(booking.slot.starts_at)
            self.assertEqual(self.fresh(ack).task.status, TaskStatus.MISSED)
            self.assertEqual((self.fresh(ack).status, self.fresh(ack).claimed_at), (MessageStatus.PENDING, NOW))
            return accepted

        FakeProvider.reset(session_starts_then_accept)
        return send_message(ack.pk, now=NOW), self.fresh(ack)

    def test_an_acceptance_after_the_task_was_missed(self):
        cases = (
            (SendResult(accepted=True, status=MessageStatus.QUEUED, provider_message_id='wamid.q'),
             SendOutcome.QUEUED, TaskResolution.ACCEPTED),
            (SendResult(accepted=True, status=MessageStatus.SENT, provider_message_id='wamid.s'),
             SendOutcome.SENT, TaskResolution.SENT),
        )
        for accepted, outcome, resolution in cases:
            with self.subTest(status=accepted.status):
                report, ack = self.send_across_the_start(accepted)
                self.assertEqual((report.outcome, ack.status, ack.provider_message_id),
                                 (outcome, accepted.status, accepted.provider_message_id))
                self.assertEqual((ack.task.status, ack.task.resolution, ack.task.resolved_by),
                                 (TaskStatus.DONE, resolution, None))

    def test_a_refusal_after_the_task_was_missed_leaves_it_missed(self):
        report, ack = self.send_across_the_start(SendResult(accepted=False, error_code='131000'))
        self.assertEqual((report.outcome, ack.task.status, ack.task.resolution), (SendOutcome.FAILED, TaskStatus.MISSED, ''))


class FinishRaceTests(SenderTestCase):
    def test_a_refused_message_is_cancelled_with_its_booking_afterwards(self):
        booking = self.book()
        ack = self.message(booking)
        FakeProvider.reset(SendResult(accepted=False, error_code='131000'))
        self.assertEqual(send_message(ack.pk, now=NOW).outcome, SendOutcome.FAILED)
        cancel_booking(booking, reason_code=CancelReason.PARENT_REQUEST, actor=self.admin, now=NOW)
        self.assertEqual(self.fresh(ack).status, MessageStatus.CANCELLED)

    def test_no_retry_can_send_for_a_booking_that_no_longer_wants_it(self):
        booking = self.book()
        ack = self.message(booking)
        cancel_booking(booking, reason_code=CancelReason.PARENT_REQUEST, actor=self.admin, now=NOW)
        # However a message ended up Pending again on that booking -- a retry, a race -- the claim closes it.
        Message.objects.filter(pk=ack.pk).update(status=MessageStatus.PENDING, cancel_reason='', cancelled_at=None)
        self.assertEqual(send_message(ack.pk, now=NOW).outcome, SendOutcome.CANCELLED)
        ack = self.fresh(ack)
        self.assertEqual((ack.status, ack.cancel_reason), (MessageStatus.CANCELLED, MessageCancelReason.BOOKING_CANCELLED))
        self.assertFalse(ack.attempts.exists())
        self.assertEqual(FakeProvider.outbox, [])


def lock_conflict(sqlstate):
    """The OperationalError a deadlock (40P01) or a lock timeout (55P03) raises."""
    error = OperationalError('deadlock detected' if sqlstate == '40P01' else 'canceling statement due to lock timeout')
    error.__cause__ = type('PostgresError', (Exception,), {'sqlstate': sqlstate})()
    return error


@mock.patch.object(sending, 'RECORD_RETRY_PAUSE', 0)
class RecordingRetryTests(SenderTestCase):
    """Recording a result that meets a deadlock or a lock timeout is tried again: the provider may have taken it."""

    def failing(self, *errors):
        """The recording's transaction raising ``errors`` in turn, after the message is locked; then working."""
        errors, real = list(errors), sending._attempt_result

        def attempt_result(result, error):
            if errors:
                raise errors.pop(0)
            return real(result, error)

        return mock.patch.object(sending, '_attempt_result', attempt_result)

    def test_a_deadlock_or_lock_timeout_is_tried_again_and_recorded_once(self):
        for sqlstate in ('40P01', '55P03'):
            with self.subTest(sqlstate=sqlstate):
                ack = self.message(self.book())
                FakeProvider.reset(SendResult(accepted=True, status=MessageStatus.SENT, provider_message_id=f'wamid.{sqlstate}'))
                with self.failing(lock_conflict(sqlstate)), self.assertLogs('communications.sending', 'WARNING') as logged:
                    self.assertEqual(send_message(ack.pk, now=NOW).outcome, SendOutcome.SENT)
                self.assertIn(f'lock conflict ({sqlstate}); trying again', logged.output[0])
                ack = self.fresh(ack)
                self.assertEqual((ack.status, ack.provider_message_id, ack.claimed_at, ack.attempt_count),
                                 (MessageStatus.SENT, f'wamid.{sqlstate}', None, 1))
                self.assertEqual(ack.attempts.get().outcome, AttemptOutcome.ACCEPTED)
                self.assertEqual((ack.task.status, ack.task.resolution), (TaskStatus.DONE, TaskResolution.SENT))

    def test_a_lasting_conflict_is_raised_and_left_to_recovery_never_resent(self):
        ack = self.message(self.book())
        FakeProvider.reset(SENT)
        conflicts = [lock_conflict('40P01') for _ in range(sending.RECORD_TRIES)]
        with self.failing(*conflicts), self.assertLogs('communications.sending', 'WARNING') as logged, \
                self.assertRaises(OperationalError):
            send_message(ack.pk, now=NOW)
        self.assertIn('accepted by fake (...wamid.1) but the result could not be recorded', logged.output[-1])
        self.assertEqual((self.fresh(ack).status, self.fresh(ack).claimed_at), (MessageStatus.PENDING, NOW))
        # Taken back as unknown, never sent again by itself.
        self.assertEqual(recover_stuck_sends(now=NOW + 6 * MINUTE), [ack.pk])
        self.assertEqual(self.fresh(ack).failure_code, OUTCOME_UNKNOWN)
        self.assertEqual(len(FakeProvider.outbox), 1)

    def test_any_other_database_error_is_not_tried_again(self):
        ack = self.message(self.book())
        tries = []

        def lost_connection(result, error):
            tries.append(result)
            raise OperationalError('server closed the connection unexpectedly')

        with mock.patch.object(sending, '_attempt_result', lost_connection), self.assertLogs('communications.sending', 'ERROR'), \
                self.assertRaises(OperationalError):
            send_message(ack.pk, now=NOW)
        self.assertEqual(len(tries), 1)


class RetryTests(SenderTestCase):
    """Only a retryable refusal is tried again: after 1, 5 and 15 minutes, 4 attempts in all, inside the window."""

    def test_tried_again_after_1_5_and_15_minutes_then_failed_after_4_attempts(self):
        booking = self.book()
        ack = self.message(booking)
        FakeProvider.reset(RETRYABLE, RETRYABLE, RETRYABLE, RETRYABLE, SENT)
        at = NOW
        for number, delay in enumerate((1, 5, 15), start=1):
            with self.subTest(attempt=number):
                self.assertEqual(send_message(ack.pk, now=at).outcome, SendOutcome.RETRYING)
                message = self.fresh(ack)
                self.assertEqual(
                    (message.status, message.next_attempt_at, message.attempt_count, message.failure_code,
                     message.failed_at, message.claimed_at),
                    (MessageStatus.PENDING, at + delay * MINUTE, number, 'RATE_LIMITED', None, None),
                )
                # Not a moment before its time.
                early = message.next_attempt_at - timedelta(seconds=1)
                self.assertEqual(send_message(ack.pk, now=early).outcome, SendOutcome.NOT_DUE)
                self.assertNotIn(ack.pk, due_message_ids(early))
                self.assertIn(ack.pk, due_message_ids(message.next_attempt_at))
                at = message.next_attempt_at
        self.assertEqual(send_message(ack.pk, now=at).outcome, SendOutcome.FAILED)
        message = self.fresh(ack)
        self.assertEqual((message.status, message.attempt_count, message.next_attempt_at, message.failure_code),
                         (MessageStatus.FAILED, 4, None, 'RATE_LIMITED'))
        self.assertIn('refused 4 times', message.failure_reason)
        self.assertEqual(list(message.attempts.values_list('number', 'outcome', 'retryable')),
                         [(number, AttemptOutcome.FAILED, True) for number in (1, 2, 3, 4)])
        self.assertEqual(message.task.status, TaskStatus.OPEN)
        # Never a fifth: the scripted success is never asked for.
        self.assertEqual(send_message(ack.pk, now=at + timedelta(hours=1)).outcome, SendOutcome.NOT_PENDING)
        self.assertEqual(len(FakeProvider.outbox), 4)

    def test_accepted_on_a_retry(self):
        ack = self.message(self.book())
        FakeProvider.reset(RETRYABLE, SENT)
        send_message(ack.pk, now=NOW)
        self.assertEqual(send_message(ack.pk, now=NOW + MINUTE).outcome, SendOutcome.SENT)
        ack = self.fresh(ack)
        self.assertEqual((ack.status, ack.attempt_count, ack.next_attempt_at, ack.failure_code, ack.failure_reason),
                         (MessageStatus.SENT, 2, None, '', ''))
        self.assertEqual((ack.task.status, ack.task.resolution), (TaskStatus.DONE, TaskResolution.SENT))

    def test_a_permanent_or_non_retryable_refusal_fails_at_once(self):
        for refusal in (SendResult(accepted=False, error_code='131026', error_message='Not a WhatsApp user'),
                        SendResult(accepted=False, error_code='132001', error_message='Template does not exist')):
            with self.subTest(code=refusal.error_code):
                FakeProvider.reset(refusal, SENT)
                ack = self.message(self.book())
                self.assertEqual(send_message(ack.pk, now=NOW).outcome, SendOutcome.FAILED)
                ack = self.fresh(ack)
                self.assertEqual((ack.status, ack.attempt_count, ack.next_attempt_at, ack.failure_reason),
                                 (MessageStatus.FAILED, 1, None, refusal.error_message))
                self.assertEqual(send_message(ack.pk, now=NOW + timedelta(hours=1)).outcome, SendOutcome.NOT_PENDING)
                self.assertEqual(len(FakeProvider.outbox), 1)

    def test_an_unknown_outcome_is_never_retried(self):
        ack = self.message(self.book())
        FakeProvider.reset(TimeoutError('read timed out'), SENT)
        self.assertEqual(send_message(ack.pk, now=NOW).outcome, SendOutcome.UNKNOWN)
        for later in (MINUTE, 5 * MINUTE, 15 * MINUTE, timedelta(hours=2)):
            self.assertEqual(send_message(ack.pk, now=NOW + later).outcome, SendOutcome.NOT_PENDING)
        self.assertNotIn(ack.pk, due_message_ids(NOW + timedelta(hours=2)))
        ack = self.fresh(ack)
        self.assertEqual((ack.status, ack.failure_code, ack.next_attempt_at), (MessageStatus.FAILED, OUTCOME_UNKNOWN, None))
        self.assertEqual(len(FakeProvider.outbox), 1)

    def test_no_retry_once_the_booking_is_cancelled_or_moved(self):
        cancelled, moved = self.book(), self.book()
        FakeProvider.reset(RETRYABLE, RETRYABLE, SENT, SENT)
        for booking in (cancelled, moved):
            self.assertEqual(send_message(self.message(booking).pk, now=NOW).outcome, SendOutcome.RETRYING)
        cancel_booking(cancelled, reason_code=CancelReason.PARENT_REQUEST, actor=self.admin, now=NOW)
        new = reschedule_booking(moved, DAY + timedelta(days=1), MORNING, reason_code=RescheduleReason.OTHER,
                                 actor=self.admin, now=NOW).booking
        for booking, reason in ((cancelled, MessageCancelReason.BOOKING_CANCELLED),
                                (moved, MessageCancelReason.BOOKING_RESCHEDULED)):
            with self.subTest(reason=reason):
                ack = self.message(booking)
                self.assertEqual((ack.status, ack.cancel_reason), (MessageStatus.CANCELLED, reason))
                self.assertEqual(send_message(ack.pk, now=NOW + MINUTE).outcome, SendOutcome.NOT_PENDING)
        # The old acknowledgement was refused, never accepted: the new booking sends its own.
        self.assertEqual(self.message(new).status, MessageStatus.PENDING)
        self.assertEqual(len(FakeProvider.outbox), 2)

    def test_no_retry_outside_the_sending_window(self):
        no_time, little_time = self.book(), self.book()
        FakeProvider.reset(RETRYABLE, RETRYABLE, RETRYABLE)
        # The window closes 30 seconds on: no time for the first retry.
        Message.objects.filter(pk=self.message(no_time).pk).update(send_before=NOW + timedelta(seconds=30))
        self.assertEqual(send_message(self.message(no_time).pk, now=NOW).outcome, SendOutcome.FAILED)
        self.assertIn('no time left to try again', self.fresh(self.message(no_time)).failure_reason)
        # It closes 3 minutes on: time for the 1-minute retry, not the 5-minute one.
        Message.objects.filter(pk=self.message(little_time).pk).update(send_before=NOW + 3 * MINUTE)
        ack = self.message(little_time)
        self.assertEqual(send_message(ack.pk, now=NOW).outcome, SendOutcome.RETRYING)
        self.assertEqual(send_message(ack.pk, now=NOW + MINUTE).outcome, SendOutcome.FAILED)
        self.assertEqual((self.fresh(ack).status, self.fresh(ack).attempt_count), (MessageStatus.FAILED, 2))

    def test_every_check_is_made_again_before_a_retry(self):
        booking = self.ready(self.book())
        record_parent_confirmation(booking, ParentConfirmation.CONFIRMED, actor=self.bde, now=NOW)
        confirmed = self.message(booking, Step.PARENT_CONFIRMATION)
        FakeProvider.reset(RETRYABLE, RETRYABLE)
        self.assertEqual(send_message(confirmed.pk, now=NOW).outcome, SendOutcome.RETRYING)
        # Sending switched off meanwhile: held back, and no attempt counted.
        with override_settings(COMMUNICATIONS_SENDING_ENABLED=False):
            self.assertEqual(send_message(confirmed.pk, now=NOW + MINUTE).block, SendBlock.SENDING_DISABLED)
        self.assertEqual(self.fresh(confirmed).attempt_count, 1)
        # The tutor removed behind the hooks' back: Waiting, not sent.
        DemoBooking.objects.filter(pk=booking.pk).update(
            assigned_tutor=None, tutor_assigned_at=None, tutor_assigned_by=None, tutor_meet_link=None,
        )
        self.assertEqual(send_message(confirmed.pk, now=NOW + MINUTE).outcome, SendOutcome.WAITING)
        self.assertEqual((self.fresh(confirmed).status, len(FakeProvider.outbox)), (MessageStatus.WAITING, 1))


class StuckSendTests(SenderTestCase):
    """A claim with no outcome for more than 5 minutes is taken back as unknown, once, and never resent."""

    def stuck(self, booking=None):
        """A message claimed at NOW whose sender never came back."""
        ack = self.message(booking or self.book())
        claim = _claim(ack.pk, NOW)
        self.assertEqual(self.fresh(ack).claimed_at, NOW)
        return ack, claim

    def test_more_than_5_minutes_without_an_outcome_is_unknown(self):
        ack, _ = self.stuck()
        recovered_at = NOW + 5 * MINUTE + timedelta(seconds=1)
        self.assertEqual(recover_stuck_sends(now=recovered_at), [ack.pk])
        ack = self.fresh(ack)
        self.assertEqual((ack.status, ack.failure_code, ack.claimed_at, ack.attempt_count, ack.failed_at),
                         (MessageStatus.FAILED, OUTCOME_UNKNOWN, None, 1, recovered_at))
        self.assertIn('check WhatsApp before sending it again', ack.failure_reason)
        attempt = ack.attempts.get()
        self.assertEqual((attempt.outcome, attempt.error_code, attempt.started_at, attempt.finished_at, attempt.provider),
                         (AttemptOutcome.UNKNOWN, NO_OUTCOME, NOW, recovered_at, 'fake'))
        self.assertEqual(ack.task.status, TaskStatus.OPEN)
        self.assertEqual(send_message(ack.pk, now=recovered_at + timedelta(hours=1)).outcome, SendOutcome.NOT_PENDING)
        self.assertEqual(FakeProvider.outbox, [])

    def test_5_minutes_or_less_is_left_alone(self):
        ack, _ = self.stuck()
        for at in (NOW + 4 * MINUTE + timedelta(seconds=59), NOW + 5 * MINUTE):
            self.assertEqual(recover_stuck_sends(now=at), [])
        ack = self.fresh(ack)
        self.assertEqual((ack.status, ack.claimed_at, ack.attempt_count), (MessageStatus.PENDING, NOW, 0))
        self.assertFalse(ack.attempts.exists())

    def test_recovery_running_again_changes_nothing(self):
        ack, _ = self.stuck()
        done = self.message(self.book())
        send_message(done.pk, now=NOW)  # finished normally: never recovered
        later = NOW + timedelta(minutes=10)
        self.assertEqual(recover_stuck_sends(now=later), [ack.pk])
        before = list(MessageAttempt.objects.order_by('message', 'number').values_list('id', 'outcome'))
        self.assertEqual(recover_stuck_sends(now=later + MINUTE), [])
        self.assertEqual(list(MessageAttempt.objects.order_by('message', 'number').values_list('id', 'outcome')), before)
        self.assertEqual(self.fresh(done).status, MessageStatus.QUEUED)

    def test_a_result_after_recovery_is_kept_and_an_acceptance_settles_it(self):
        cases = (
            (SENT, None, MessageStatus.SENT, AttemptOutcome.ACCEPTED),
            (SendResult(accepted=False, error_code='131000'), None, MessageStatus.FAILED, AttemptOutcome.FAILED),
            (None, TimeoutError('read timed out'), MessageStatus.FAILED, AttemptOutcome.UNKNOWN),
        )
        for result, error, status, late_outcome in cases:
            with self.subTest(late=late_outcome):
                ack, claim = self.stuck()
                recover_stuck_sends(now=NOW + 6 * MINUTE)
                report = _finish(claim, result, error, NOW, NOW + 7 * MINUTE, NOW, None)
                self.assertEqual(report.outcome, SendOutcome.LATE)
                ack = self.fresh(ack)
                self.assertEqual(ack.status, status)
                self.assertEqual(list(ack.attempts.values_list('outcome', flat=True)), [AttemptOutcome.UNKNOWN, late_outcome])
                if status == MessageStatus.SENT:
                    self.assertEqual((ack.failure_code, ack.task.status, ack.task.resolution),
                                     ('', TaskStatus.DONE, TaskResolution.SENT))
                else:
                    self.assertEqual((ack.failure_code, ack.task.status), (OUTCOME_UNKNOWN, TaskStatus.OPEN))
                self.assertEqual(recover_stuck_sends(now=NOW + timedelta(hours=1)), [])

    def test_a_stuck_acknowledgement_keeps_the_new_booking_waiting(self):
        booking = self.book()
        ack, _ = self.stuck(booking)
        new = reschedule_booking(booking, DAY + timedelta(days=1), MORNING, reason_code=RescheduleReason.OTHER,
                                 actor=self.admin, now=NOW).booking
        recover_stuck_sends(now=NOW + 6 * MINUTE)
        self.assertEqual(self.fresh(ack).failure_code, OUTCOME_UNKNOWN)
        new_ack = self.message(new)
        self.assertEqual((new_ack.status, new_ack.task.status), (MessageStatus.WAITING, TaskStatus.OPEN))


@skipUnless(connection.vendor == 'postgresql', 'the locks need PostgreSQL')
@override_settings(**SENDING)
class ConcurrentSendTests(TransactionTestCase):
    """Real threads, each with its own database connection."""

    def setUp(self):
        schedule()
        self.bde = account('bde_anil', role='BDE', mobile_number='+91 98470 12345')
        self.admin = account('admin_ops', role='ADMIN')
        token = link(self.bde, DEMO).token
        self.booking, _ = create_booking(request(student='Riya', phone='0507712345', ref=token), now=NOW)
        self.ack = self.booking.communication_messages.get(template__step=Step.ACKNOWLEDGEMENT)
        FakeProvider.reset()
        patcher = use_fake_provider()
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_threads(self, *targets):
        results = [None] * len(targets)

        def run(index, target):
            try:
                results[index] = target()
            except Exception as exc:  # reported in the assertion, not lost in the thread
                results[index] = ('error', repr(exc))
            finally:
                connection.close()

        threads = [threading.Thread(target=run, args=(i, target)) for i, target in enumerate(targets)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        return results

    def test_two_senders_at_once_send_it_once(self):
        def slow_accept(_outgoing):
            clock.sleep(0.3)
            return SendResult(accepted=True, status=MessageStatus.QUEUED, provider_message_id='wamid.race')

        FakeProvider.reset(slow_accept)
        barrier = threading.Barrier(2)

        def sender():
            barrier.wait(timeout=10)
            return send_message(self.ack.pk, now=NOW).outcome

        outcomes = self.run_threads(sender, sender)
        self.assertEqual(sorted(outcomes), [SendOutcome.NOT_PENDING, SendOutcome.QUEUED], outcomes)
        self.assertEqual((len(FakeProvider.outbox), MessageAttempt.objects.filter(message=self.ack).count()), (1, 1))
        self.assertEqual(Message.objects.get(pk=self.ack.pk).status, MessageStatus.QUEUED)

    def test_a_cancellation_holding_the_booking_is_seen_by_the_claim(self):
        holding = threading.Event()

        def cancel_slowly():
            with transaction.atomic():
                _locked_booking(self.booking)
                holding.set()
                clock.sleep(0.5)
                cancel_booking(self.booking, reason_code=CancelReason.PARENT_REQUEST, actor=self.admin, now=NOW)
            return 'cancelled'

        def sender():
            holding.wait(timeout=10)
            return send_message(self.ack.pk, now=NOW).outcome

        outcomes = self.run_threads(cancel_slowly, sender)
        self.assertEqual(outcomes, ['cancelled', SendOutcome.NOT_PENDING], outcomes)
        self.assertEqual(Message.objects.get(pk=self.ack.pk).status, MessageStatus.CANCELLED)
        self.assertEqual((FakeProvider.outbox, MessageAttempt.objects.count()), ([], 0))

    def test_a_cancellation_committing_after_the_refusal_is_recorded_still_cancels_it(self):
        """
        The race: the booking is cancelled while the provider is called, and the
        cancellation commits only after the provider refused. The cancellation
        locks the message being sent, so recording the refusal waits for it and
        then sees the booking cancelled: Cancelled, never Failed -- which a retry
        could pick up -- on a booking that no longer wants it.
        """
        in_call, cancelled = threading.Event(), threading.Event()

        def refuse_after_cancel(_outgoing):
            in_call.set()
            cancelled.wait(timeout=10)
            return SendResult(accepted=False, error_code='131000', retryable=True)

        FakeProvider.reset(refuse_after_cancel)

        def sender():
            return send_message(self.ack.pk, now=NOW).outcome

        def cancel_then_commit_late():
            in_call.wait(timeout=10)
            with transaction.atomic():
                cancel_booking(self.booking, reason_code=CancelReason.PARENT_REQUEST, actor=self.admin, now=NOW)
                cancelled.set()
                clock.sleep(0.5)  # the refusal is being recorded meanwhile
            return 'cancelled'

        outcomes = self.run_threads(sender, cancel_then_commit_late)
        self.assertEqual(outcomes, [SendOutcome.CANCELLED, 'cancelled'], outcomes)
        ack = Message.objects.get(pk=self.ack.pk)
        self.assertEqual((ack.status, ack.cancel_reason, ack.claimed_at),
                         (MessageStatus.CANCELLED, MessageCancelReason.BOOKING_CANCELLED, None))
        self.assertEqual(ack.attempts.get().outcome, AttemptOutcome.FAILED)

    def stuck_claim(self):
        claim = _claim(self.ack.pk, NOW)
        self.assertIsNotNone(Message.objects.get(pk=self.ack.pk).claimed_at)
        return claim

    def test_a_sender_recording_its_result_is_not_recovered(self):
        claim, locked = self.stuck_claim(), threading.Event()

        def finish_slowly():
            with transaction.atomic():
                report = _finish(claim, SENT, None, NOW, NOW, NOW, None)
                locked.set()
                clock.sleep(0.5)
            return report.outcome

        def recover():
            locked.wait(timeout=10)
            return recover_stuck_sends(now=NOW + 6 * MINUTE)

        outcomes = self.run_threads(finish_slowly, recover)
        self.assertEqual(outcomes, [SendOutcome.SENT, []], outcomes)
        ack = Message.objects.get(pk=self.ack.pk)
        self.assertEqual((ack.status, ack.claimed_at, ack.attempt_count), (MessageStatus.SENT, None, 1))
        self.assertEqual(recover_stuck_sends(now=NOW + 7 * MINUTE), [])

    def test_a_sender_finishing_while_recovery_runs_is_kept_as_a_late_result(self):
        claim, locked = self.stuck_claim(), threading.Event()

        def recover_slowly():
            with transaction.atomic():
                recovered = recover_stuck_sends(now=NOW + 6 * MINUTE)
                locked.set()
                clock.sleep(0.5)
            return recovered

        def finish():
            locked.wait(timeout=10)
            return _finish(claim, SENT, None, NOW, NOW, NOW, None).outcome

        outcomes = self.run_threads(recover_slowly, finish)
        self.assertEqual(outcomes, [[self.ack.pk], SendOutcome.LATE], outcomes)
        ack = Message.objects.get(pk=self.ack.pk)
        self.assertEqual((ack.status, ack.claimed_at, ack.attempt_count), (MessageStatus.SENT, None, 2))
        self.assertEqual(list(ack.attempts.values_list('outcome', flat=True)),
                         [AttemptOutcome.UNKNOWN, AttemptOutcome.ACCEPTED])
