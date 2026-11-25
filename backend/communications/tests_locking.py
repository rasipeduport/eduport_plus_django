"""
Lock order under real concurrency (Phase 2B step 6): two database connections
at once, in real threads. Recording a send and closing its booking -- a
cancellation, a reschedule, the parent's answer, the expiry sweep -- both take
the message before its task, so they take turns instead of deadlocking, and
the provider's acceptance is never lost; a step closed while a result waited
stays closed; a booking change refreshing its messages waits for a job
cancelling one and leaves it cancelled; the Waiting-message check holds its
locks one short chunk at a time. Nothing reaches WhatsApp: the provider is
the test-only fake.

The last two classes run the real path -- a business write only records an
outbox event, the planner applies it in a transaction of its own -- and
cover F3: a sender claim never holds a booking's slot and row while it waits
for a message (it is Busy at once), and the sender's result, the stuck-send
recovery, the webhook and the expiry sweep give up at a lock timeout instead of
waiting without end.
"""
import threading
import time as clock
from datetime import timedelta
from unittest import mock, skipUnless

from django.db import OperationalError, connection, transaction
from django.test import TransactionTestCase, override_settings

from activity.models import ActivityLog
from bookings.booking_service import (
    _locked_booking,
    assign_tutor,
    cancel_booking,
    create_booking,
    record_parent_confirmation,
    reschedule_booking,
)
from bookings.models import BookingStatus, CancelReason, ParentConfirmation, RescheduleReason
from bookings.tests_booking import DAY, DEMO, MORNING, NOW, account, link, request, schedule

from . import outbox, planner, sending, tasks
from .models import (
    AttemptOutcome,
    Channel,
    CommunicationTask,
    Message,
    MessageCancelReason,
    MessageStatus,
    MessageStatusEvent,
    Step,
    TaskResolution,
    TaskStatus,
)
from .providers.base import SendResult, StatusUpdate
from .sending import SendOutcome, SendReport, _claim, _finish, recover_stuck_sends, send_message
from .services import BookingNotUpcoming, RequestNotMarkable, mark_confirmation_request_sent, request_confirmation
from .status_updates import StatusResult, apply_status_update
from .tests_planning import MEET_LINK
from .tests_providers import FakeProvider, use_fake_provider
from .tests_sending import SENDING

ACCEPTED = SendResult(accepted=True, status=MessageStatus.QUEUED, provider_message_id='wamid.LOCKS')
# Long enough for the other connection to reach the rows it waits on.
SETTLE = 0.5


@skipUnless(connection.vendor == 'postgresql', 'the locks need PostgreSQL')
@override_settings(**SENDING, COMMUNICATIONS_OUTBOX_INLINE=True)  # reads the plan straight after each business call
class LockingTestCase(TransactionTestCase):
    """Real threads, each with its own database connection."""

    def setUp(self):
        schedule()
        self.bde = account('bde_anil', role='BDE', mobile_number='+91 98470 12345')
        self.admin = account('admin_ops', role='ADMIN')
        self.tutor = account('tutor_anu', role='TUTOR', tutor_meet_link=MEET_LINK)
        self.token = link(self.bde, DEMO).token
        self.children = iter(range(1, 100))
        FakeProvider.reset()
        patcher = use_fake_provider()
        patcher.start()
        self.addCleanup(patcher.stop)

    def book(self):
        child = next(self.children)
        booking, _ = create_booking(request(student=f'Child {child}', phone=f'05077{child:05d}', ref=self.token), now=NOW)
        return booking

    @staticmethod
    def message(booking, step=Step.ACKNOWLEDGEMENT):
        return Message.objects.select_related('task').get(**planner.booking_field(booking), template__step=step)

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


class RecordingMeetsClosingTests(LockingTestCase):
    """
    The provider has accepted a message; while its result is being recorded --
    the message locked, its task not written yet -- the booking is closed. The
    closing takes the message before the tasks, so it waits for the recording
    rather than holding the task the recording needs: no deadlock, nothing
    lost, and the closing then finds the step done.
    """

    def record_while(self, message, close):
        claim = _claim(message.pk, NOW)
        locked = threading.Event()
        real = sending._attempt_result

        def attempt_result_slowly(result, error):
            locked.set()
            clock.sleep(SETTLE)  # the closing reaches the booking's rows meanwhile
            return real(result, error)

        def record():
            return _finish(claim, ACCEPTED, None, NOW, NOW, NOW, None).outcome

        def closing():
            locked.wait(timeout=10)
            close()
            return 'closed'

        with mock.patch.object(sending, '_attempt_result', attempt_result_slowly):
            outcomes = self.run_threads(record, closing)
        self.assertEqual(outcomes, [SendOutcome.QUEUED, 'closed'], outcomes)
        message = Message.objects.select_related('task').get(pk=message.pk)
        self.assertEqual((message.status, message.provider_message_id, message.claimed_at),
                         (MessageStatus.QUEUED, 'wamid.LOCKS', None))
        self.assertEqual(list(message.attempts.values_list('outcome', flat=True)), [AttemptOutcome.ACCEPTED])
        self.assertEqual((message.task.status, message.task.resolution), (TaskStatus.DONE, TaskResolution.ACCEPTED))
        return message

    def test_a_cancellation(self):
        booking = self.book()
        self.record_while(self.message(booking), lambda: cancel_booking(
            booking, reason_code=CancelReason.PARENT_REQUEST, actor=self.admin, now=NOW))
        others = booking.communication_tasks.exclude(step=Step.ACKNOWLEDGEMENT)
        self.assertEqual(set(others.values_list('status', flat=True)), {TaskStatus.CANCELLED})

    def test_a_reschedule(self):
        booking = self.book()
        moved = []
        self.record_while(self.message(booking), lambda: moved.append(reschedule_booking(
            booking, DAY + timedelta(days=1), MORNING, reason_code=RescheduleReason.PARENT_REQUEST,
            actor=self.admin, now=NOW).booking))
        # The acknowledgement went, so the new booking sends no second one.
        task = moved[0].communication_tasks.get(step=Step.ACKNOWLEDGEMENT)
        self.assertEqual((task.status, task.resolution), (TaskStatus.DONE, TaskResolution.ALREADY_ACKNOWLEDGED))

    def test_the_parents_answer(self):
        booking = self.book()
        asked, _created = request_confirmation(booking, actor=self.bde, now=NOW)
        self.record_while(asked, lambda: record_parent_confirmation(
            booking, ParentConfirmation.CONFIRMED, actor=self.bde, now=NOW))
        self.assertEqual(self.message(booking, Step.PARENT_CONFIRMATION).status, MessageStatus.WAITING)

    def test_the_expiry_sweep(self):
        booking = self.book()
        ack = self.message(booking)
        Message.objects.filter(pk=ack.pk).update(send_before=NOW + timedelta(minutes=1))
        CommunicationTask.objects.filter(pk=ack.task_id).update(expires_at=NOW + timedelta(minutes=1))
        swept = []
        self.record_while(ack, lambda: swept.append(planner.close_expired(NOW + timedelta(minutes=2))))
        # The sweep came after the recording: nothing left for it to miss or expire.
        self.assertEqual(swept, [(0, 0)])

    def test_a_step_closed_while_the_result_waited_stays_closed(self):
        """
        Here the cancellation got the message first, and the recording waited
        for it. The task it read with the message was still open then, but
        the step is written only as the row stands when written: Cancelled,
        it stays Cancelled -- while the message is Queued, as the provider took it.
        """
        booking = self.book()
        ack = self.message(booking)
        claim = _claim(ack.pk, NOW)
        messages_locked = threading.Event()
        real = planner._cancel_messages

        def cancel_messages_slowly(messages, reason, now):
            cancelled = real(messages, reason, now)
            messages_locked.set()
            clock.sleep(SETTLE)  # the recording reaches the message meanwhile, and waits
            return cancelled

        def cancel():
            cancel_booking(booking, reason_code=CancelReason.PARENT_REQUEST, actor=self.admin, now=NOW)
            return 'cancelled'

        def record():
            messages_locked.wait(timeout=10)
            return _finish(claim, ACCEPTED, None, NOW, NOW, NOW, None).outcome

        with mock.patch.object(planner, '_cancel_messages', cancel_messages_slowly):
            outcomes = self.run_threads(cancel, record)
        self.assertEqual(outcomes, ['cancelled', SendOutcome.QUEUED], outcomes)
        ack = self.message(booking)
        self.assertEqual((ack.status, ack.provider_message_id), (MessageStatus.QUEUED, 'wamid.LOCKS'))
        self.assertEqual((ack.task.status, ack.task.resolution), (TaskStatus.CANCELLED, TaskResolution.BOOKING_CANCELLED))


class RefreshTests(LockingTestCase):
    def test_a_booking_change_waits_for_a_job_cancelling_its_message_and_leaves_it_cancelled(self):
        """
        The expiry sweep has cancelled a message but not committed; a tutor
        assigned at that moment refreshes the booking's messages (here as its
        outbox event is recorded, COMMUNICATIONS_OUTBOX_INLINE; in production
        when the event is applied, with the same locks). Each is locked before
        it is read, so the refresh waits for the sweep and then sees the
        message cancelled: no error, nothing written back.
        """
        booking = self.book()
        ack = self.message(booking)
        Message.objects.filter(pk=ack.pk).update(send_before=NOW + timedelta(minutes=1))
        cancelled = threading.Event()
        real = planner._cancel_messages

        def cancel_messages_slowly(messages, reason, now):
            count = real(messages, reason, now)
            cancelled.set()
            clock.sleep(SETTLE)  # the tutor is assigned meanwhile
            return count

        def sweep():
            return planner.close_expired(NOW + timedelta(minutes=2))

        def assign():
            cancelled.wait(timeout=10)
            assign_tutor(booking, self.tutor, actor=self.admin, now=NOW)
            return 'assigned'

        with mock.patch.object(planner, '_cancel_messages', cancel_messages_slowly):
            outcomes = self.run_threads(sweep, assign)
        self.assertEqual(outcomes, [(0, 1), 'assigned'], outcomes)
        ack = self.message(booking)
        self.assertEqual((ack.status, ack.cancel_reason), (MessageStatus.CANCELLED, MessageCancelReason.EXPIRED))

    def test_the_waiting_check_locks_one_chunk_at_a_time(self):
        """While refresh_waiting checks one chunk, the Waiting messages of the next are free to lock at once."""
        self.book()
        self.book()
        waiting = list(Message.objects.filter(status=MessageStatus.WAITING).values_list('pk', flat=True))
        self.assertEqual(len(waiting), 2)
        inside, probed, first = threading.Event(), threading.Event(), []
        real = planner.refresh_message

        def refresh_slowly(message, booking, now, save=True):
            if not first:
                first.append(message.pk)
                inside.set()
                probed.wait(timeout=10)
            return real(message, booking, now, save=save)

        def check():
            return planner.refresh_waiting(NOW)

        def probe():
            inside.wait(timeout=10)
            try:
                other = next(pk for pk in waiting if pk != first[0])
                with transaction.atomic():
                    return list(Message.objects.select_for_update(nowait=True).filter(pk=other).values_list('pk', flat=True))
            finally:
                probed.set()

        with mock.patch.object(planner, 'REFRESH_CHUNK', 1), mock.patch.object(planner, 'refresh_message', refresh_slowly):
            outcomes = self.run_threads(check, probe)
        other = next(pk for pk in waiting if pk != first[0])
        self.assertEqual(outcomes, [0, [other]], outcomes)


# ------------------------------------------------------------------ F3

@override_settings(COMMUNICATIONS_OUTBOX_INLINE=False)  # the real path: a business write only records an event
class SeparateTransactionsTestCase(LockingTestCase):
    """The communication side in transactions of its own, as in production."""

    def planned(self):
        booking = self.book()
        outbox.run()
        return booking

    def hold_message(self, message, held, release, seconds=8):
        """A target for run_threads: the message's row locked until ``release`` is set (or ``seconds``)."""
        def hold():
            with transaction.atomic():
                Message.objects.select_for_update().get(pk=message.pk)
                held.set()
                release.wait(timeout=seconds)
            return 'held'
        return hold

    @staticmethod
    def sqlstate(exc):
        return getattr(exc.__cause__, 'sqlstate', None)


class ClaimContentionTests(SeparateTransactionsTestCase):
    """
    A sender claim takes the booking's slot and row (as every booking write
    does) and then its message. A message another transaction holds makes the
    claim Busy at once -- it does not wait for it with the slot and the
    booking held, which would make a cancellation or a move of that booking
    wait too. Nothing is claimed, so nothing is lost or sent twice: the next
    dispatch run tries again.
    """

    def claim_beside_a_held_message(self, business):
        """The message held; a claim started on it; then ``business(booking)`` run meanwhile. Returns (ack, outcomes)."""
        booking = self.planned()
        ack = self.message(booking)
        held, claiming, release = threading.Event(), threading.Event(), threading.Event()

        def claim():
            held.wait(timeout=10)
            claiming.set()
            began = clock.monotonic()
            report = _claim(ack.pk, NOW)
            return report, clock.monotonic() - began

        def operate():
            claiming.wait(timeout=10)
            clock.sleep(0.3)  # the claim is under way, whatever it waits for
            began = clock.monotonic()
            try:
                return business(booking), clock.monotonic() - began
            finally:
                release.set()

        return ack, self.run_threads(self.hold_message(ack, held, release), claim, operate)

    def test_a_message_another_transaction_holds_makes_the_claim_busy_at_once(self):
        # The message stays held for another second: the claim has all the time to wait, if it were to.
        ack, (holder, claimed, _operated) = self.claim_beside_a_held_message(lambda booking: clock.sleep(1.0))
        self.assertEqual(holder, 'held')
        report, seconds = claimed
        self.assertEqual(report, SendReport(SendOutcome.BUSY))
        self.assertLess(seconds, 1.5, 'the claim waited for the message instead of answering Busy')
        # Nothing was claimed or written, and nothing sent: the message is as it was, for the next run.
        message = Message.objects.get(pk=ack.pk)
        self.assertEqual((message.status, message.claimed_at, message.attempt_count), (MessageStatus.PENDING, None, 0))
        self.assertFalse(message.attempts.exists())
        self.assertEqual(FakeProvider.outbox, [])
        # Once the message is free it goes -- once.
        self.assertEqual(send_message(ack.pk, now=NOW).outcome, SendOutcome.QUEUED)
        self.assertEqual(send_message(ack.pk, now=NOW).outcome, SendOutcome.NOT_PENDING)
        self.assertEqual(len(FakeProvider.outbox), 1)

    def test_a_cancellation_is_not_held_up_by_a_claim_waiting_on_a_message(self):
        ack, (holder, claimed, operated) = self.claim_beside_a_held_message(
            lambda booking: cancel_booking(booking, reason_code=CancelReason.PARENT_REQUEST, actor=self.admin, now=NOW),
        )
        self.assertEqual(holder, 'held')
        self.assertEqual(claimed[0], SendReport(SendOutcome.BUSY), claimed)
        (_booking, changed), seconds = operated
        self.assertTrue(changed)
        self.assertLess(seconds, 1.0, 'the cancellation waited behind a claim that was waiting for a message')
        outbox.run()
        self.assertEqual(Message.objects.get(pk=ack.pk).status, MessageStatus.CANCELLED)
        self.assertEqual(FakeProvider.outbox, [])

    def test_a_reschedule_is_not_held_up_by_a_claim_waiting_on_a_message(self):
        ack, (holder, claimed, operated) = self.claim_beside_a_held_message(
            lambda booking: reschedule_booking(
                booking, DAY + timedelta(days=1), MORNING, reason_code=RescheduleReason.PARENT_REQUEST,
                actor=self.admin, now=NOW,
            ),
        )
        self.assertEqual(holder, 'held')
        self.assertEqual(claimed[0], SendReport(SendOutcome.BUSY), claimed)
        result, seconds = operated
        self.assertEqual(result.previous.status, BookingStatus.RESCHEDULED)
        self.assertLess(seconds, 1.0, 'the reschedule waited behind a claim that was waiting for a message')
        self.assertEqual(FakeProvider.outbox, [])

    def test_a_claim_still_waits_for_the_booking_and_sees_what_it_changed(self):
        """The slot, then the booking, then the message: the order is kept, so a cancellation in progress is still seen."""
        booking = self.planned()
        ack = self.message(booking)
        holding = threading.Event()

        def cancel_slowly():
            with transaction.atomic():
                sending._locked_booking(booking)
                holding.set()
                clock.sleep(0.5)
                cancel_booking(booking, reason_code=CancelReason.PARENT_REQUEST, actor=self.admin, now=NOW)
            return 'cancelled'

        def claim():
            holding.wait(timeout=10)
            return send_message(ack.pk, now=NOW).outcome

        self.assertEqual(self.run_threads(cancel_slowly, claim), ['cancelled', SendOutcome.CANCELLED])
        self.assertEqual(FakeProvider.outbox, [])


class LockTimeoutTests(SeparateTransactionsTestCase):
    """
    The communication transactions that only wait for communication rows give
    up at outbox.LOCK_TIMEOUT instead of waiting without end, and what handles
    the timeout does: the sender's result is tried again, then left to
    recovery; a recovery, a sweep or a webhook that gave up is done again by
    the next pass or redelivery -- none writes anything half way.
    """

    def test_a_result_that_waits_out_the_lock_timeout_is_tried_again_and_recorded_once(self):
        ack = self.message(self.planned())
        claim = _claim(ack.pk, NOW)
        held, release = threading.Event(), threading.Event()
        timeouts, real = [], sending._record_result

        def record_result(*args, **kwargs):
            try:
                return real(*args, **kwargs)
            except OperationalError as exc:
                timeouts.append(self.sqlstate(exc))
                release.set()  # the lock is let go once the first try has given up
                raise

        def record():
            held.wait(timeout=10)
            began = clock.monotonic()
            with mock.patch.object(outbox, 'LOCK_TIMEOUT', '300ms'), \
                    mock.patch.object(sending, '_record_result', record_result):
                outcome = _finish(claim, ACCEPTED, None, NOW, NOW, NOW, None).outcome
            return outcome, clock.monotonic() - began

        holder, (outcome, seconds) = self.run_threads(self.hold_message(ack, held, release), record)
        self.assertEqual((holder, outcome), ('held', SendOutcome.QUEUED))
        self.assertEqual(timeouts, ['55P03'])
        self.assertLess(seconds, 4)
        message = Message.objects.get(pk=ack.pk)
        self.assertEqual((message.status, message.provider_message_id, message.claimed_at, message.attempt_count),
                         (MessageStatus.QUEUED, 'wamid.LOCKS', None, 1))
        self.assertEqual(message.attempts.count(), 1)

    def test_a_lasting_lock_is_given_up_at_the_timeout_and_left_to_recovery(self):
        ack = self.message(self.planned())
        claim = _claim(ack.pk, NOW)
        held, release = threading.Event(), threading.Event()

        def record():
            held.wait(timeout=10)
            began = clock.monotonic()
            try:
                with mock.patch.object(outbox, 'LOCK_TIMEOUT', '300ms'), mock.patch.object(sending, 'RECORD_RETRY_PAUSE', 0):
                    _finish(claim, ACCEPTED, None, NOW, NOW, NOW, None)
            except OperationalError as exc:
                return self.sqlstate(exc), clock.monotonic() - began
            finally:
                release.set()
            return None, clock.monotonic() - began

        holder, (sqlstate, seconds) = self.run_threads(self.hold_message(ack, held, release), record)
        self.assertEqual((holder, sqlstate), ('held', '55P03'))
        self.assertLess(seconds, 4, 'the result waited for the lock instead of giving up')
        # Still claimed, nothing recorded: recovery takes it back as unknown, never sending it again.
        message = Message.objects.get(pk=ack.pk)
        self.assertEqual((message.status, message.claimed_at, message.attempt_count), (MessageStatus.PENDING, NOW, 0))
        self.assertEqual(recover_stuck_sends(now=NOW + timedelta(minutes=6)), [ack.pk])
        self.assertEqual(len(FakeProvider.outbox), 0)

    def test_a_status_update_gives_up_at_the_timeout_and_its_redelivery_applies(self):
        ack = self.message(self.planned())
        self.assertEqual(send_message(ack.pk, now=NOW).outcome, SendOutcome.QUEUED)
        update = StatusUpdate(provider_message_id='fake-1', status=MessageStatus.SENT, provider_status='sent', occurred_at=NOW)
        held, release = threading.Event(), threading.Event()

        def webhook():
            held.wait(timeout=10)
            began = clock.monotonic()
            try:
                with mock.patch.object(outbox, 'LOCK_TIMEOUT', '300ms'):
                    apply_status_update('fake', update)
            except OperationalError as exc:
                return self.sqlstate(exc), clock.monotonic() - began
            finally:
                release.set()
            return None, clock.monotonic() - began

        holder, (sqlstate, seconds) = self.run_threads(self.hold_message(ack, held, release), webhook)
        self.assertEqual((holder, sqlstate), ('held', '55P03'))
        self.assertLess(seconds, 4, 'the webhook waited for the lock instead of giving up')
        # Nothing half applied: Meta redelivers a callback answered 500, and it then applies once.
        self.assertEqual(MessageStatusEvent.objects.count(), 0)
        self.assertEqual(Message.objects.get(pk=ack.pk).status, MessageStatus.QUEUED)
        self.assertEqual(apply_status_update('fake', update), StatusResult.APPLIED)
        self.assertEqual(Message.objects.get(pk=ack.pk).status, MessageStatus.SENT)
        self.assertEqual(MessageStatusEvent.objects.count(), 1)

    def test_a_recovery_gives_up_at_the_timeout_and_is_done_by_the_next_pass(self):
        """The recovery of an acknowledgement locks the one of the booking that replaced it: held, it waits no longer than the timeout."""
        booking = self.planned()
        ack = self.message(booking)
        _claim(ack.pk, NOW)  # being sent...
        moved = reschedule_booking(
            booking, DAY + timedelta(days=1), MORNING, reason_code=RescheduleReason.PARENT_REQUEST, actor=self.admin, now=NOW,
        ).booking
        outbox.run()  # ...as the booking moves: the new booking's acknowledgement waits for it
        later = self.message(moved)
        held, release = threading.Event(), threading.Event()

        def recover():
            held.wait(timeout=10)
            began = clock.monotonic()
            try:
                with mock.patch.object(outbox, 'LOCK_TIMEOUT', '300ms'):
                    return recover_stuck_sends(now=NOW + timedelta(minutes=6)), clock.monotonic() - began
            finally:
                release.set()

        holder, (recovered, seconds) = self.run_threads(self.hold_message(later, held, release), recover)
        self.assertEqual((holder, recovered), ('held', []))
        self.assertLess(seconds, 4, 'the recovery waited for the lock instead of giving up')
        self.assertEqual(Message.objects.get(pk=ack.pk).claimed_at, NOW)  # untouched: rolled back whole
        self.assertEqual(recover_stuck_sends(now=NOW + timedelta(minutes=6)), [ack.pk])

    def test_the_expiry_sweep_is_busy_instead_of_waiting_and_runs_again_next_time(self):
        ack = self.message(self.planned())
        later = NOW + timedelta(days=30)
        held, release = threading.Event(), threading.Event()

        def sweep():
            held.wait(timeout=10)
            began = clock.monotonic()
            try:
                with mock.patch.object(outbox, 'LOCK_TIMEOUT', '300ms'), \
                        mock.patch.object(tasks, 'timezone', mock.Mock(now=lambda: later)):
                    return tasks.close_expired_communications(), clock.monotonic() - began
            finally:
                release.set()

        holder, (result, seconds) = self.run_threads(self.hold_message(ack, held, release), sweep)
        self.assertEqual((holder, result), ('held', {'busy': True}))
        self.assertLess(seconds, 4, 'the sweep waited for the lock instead of giving up')
        self.assertEqual(Message.objects.get(pk=ack.pk).status, MessageStatus.PENDING)
        with mock.patch.object(tasks, 'timezone', mock.Mock(now=lambda: later)):
            result = tasks.close_expired_communications()
        self.assertGreaterEqual(result['expired'], 1)
        self.assertEqual(Message.objects.get(pk=ack.pk).status, MessageStatus.CANCELLED)


class MarkSentConcurrencyTests(LockingTestCase):
    """
    Marking the confirmation request as sent by hand takes the booking's slot
    and row, then the request's -- the order the sender and every booking
    change take them: two marks at once write one record and one log entry; a
    mark that waits for a cancellation sees the booking cancelled; and a mark
    racing the sender for a request the system was asked to send never lets
    both win -- the parent gets it once, by hand or from the provider.
    """

    def test_two_marks_at_once_write_one_record(self):
        booking = self.book()
        together = threading.Barrier(2)

        def mark():
            together.wait(timeout=10)
            return mark_confirmation_request_sent(booking, actor=self.bde, now=NOW)[1]

        outcomes = self.run_threads(mark, mark)
        self.assertEqual(sorted(outcomes, key=str), [False, True], outcomes)
        message = self.message(booking, Step.CONFIRMATION_REQUEST)
        self.assertEqual((message.status, message.channel, message.sent_by), (MessageStatus.SENT, Channel.MANUAL_WHATSAPP, self.bde))
        self.assertEqual((message.task.status, message.task.resolution), (TaskStatus.DONE, TaskResolution.MARKED_SENT))
        self.assertEqual(ActivityLog.objects.filter(action='booking.confirmation_request_sent_manually').count(), 1)

    def test_a_mark_waits_for_a_cancellation_and_sees_it(self):
        booking = self.book()
        held = threading.Event()

        def cancel_slowly():
            with transaction.atomic():
                _locked_booking(booking)
                held.set()
                clock.sleep(SETTLE)  # the mark reaches the booking's rows meanwhile
                cancel_booking(booking, reason_code=CancelReason.PARENT_REQUEST, actor=self.admin, now=NOW)
            return 'cancelled'

        def mark():
            held.wait(timeout=10)
            try:
                mark_confirmation_request_sent(booking, actor=self.bde, now=NOW)
            except BookingNotUpcoming:
                return 'not upcoming'
            return 'marked'

        self.assertEqual(self.run_threads(cancel_slowly, mark), ['cancelled', 'not upcoming'])
        self.assertFalse(Message.objects.filter(demo_booking=booking, template__step=Step.CONFIRMATION_REQUEST).exists())

    def test_a_mark_and_the_sender_never_both_win(self):
        booking = self.book()
        asked, _created = request_confirmation(booking, actor=self.admin, now=NOW)
        together = threading.Barrier(2)

        def send():
            together.wait(timeout=10)
            return send_message(asked.pk, now=NOW).outcome

        def mark():
            together.wait(timeout=10)
            try:
                return mark_confirmation_request_sent(booking, actor=self.bde, now=NOW)[1]
            except RequestNotMarkable:
                return 'not markable'

        sent, marked = self.run_threads(send, mark)
        message = Message.objects.get(pk=asked.pk)
        if marked is True:
            # The mark came first: the sender found nothing to send.
            self.assertIn(sent, (SendOutcome.NOT_PENDING, SendOutcome.BUSY), (sent, marked))
            self.assertEqual((message.status, message.channel), (MessageStatus.SENT, Channel.MANUAL_WHATSAPP))
            self.assertEqual(FakeProvider.outbox, [])
        else:
            # The sender came first: the provider has it, and the mark changed nothing.
            self.assertEqual(sent, SendOutcome.QUEUED, (sent, marked))
            self.assertIn(marked, ('not markable', False))
            self.assertEqual((message.channel, message.sent_by), (Channel.WHATSAPP, None))
            self.assertEqual(len(FakeProvider.outbox), 1)
