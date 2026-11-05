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
"""
import threading
import time as clock
from datetime import timedelta
from unittest import mock, skipUnless

from django.db import connection, transaction
from django.test import TransactionTestCase, override_settings

from bookings.booking_service import (
    assign_tutor,
    cancel_booking,
    create_booking,
    record_parent_confirmation,
    reschedule_booking,
)
from bookings.models import CancelReason, ParentConfirmation, RescheduleReason
from bookings.tests_booking import DAY, DEMO, MORNING, NOW, account, link, request, schedule

from . import planner, sending
from .models import (
    AttemptOutcome,
    CommunicationTask,
    Message,
    MessageCancelReason,
    MessageStatus,
    Step,
    TaskResolution,
    TaskStatus,
)
from .providers.base import SendResult
from .sending import SendOutcome, _claim, _finish
from .services import request_confirmation
from .tests_planning import MEET_LINK
from .tests_providers import FakeProvider, use_fake_provider
from .tests_sending import SENDING

ACCEPTED = SendResult(accepted=True, status=MessageStatus.QUEUED, provider_message_id='wamid.LOCKS')
# Long enough for the other connection to reach the rows it waits on.
SETTLE = 0.5


@skipUnless(connection.vendor == 'postgresql', 'the locks need PostgreSQL')
@override_settings(**SENDING)
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
        assigned at that moment refreshes the booking's messages. Each is
        locked before it is read, so the refresh waits for the sweep and then
        sees the message cancelled: no error, nothing written back.
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
