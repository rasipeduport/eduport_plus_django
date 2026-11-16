"""
End-to-end runs of parent WhatsApp communication (Phase 2B, step 6), through
the entry points production uses: bookings made and moved by the booking
service, the Celery jobs run as Celery tasks (``apply``: in process, no
broker), and Meta's callbacks posted, signed, to the webhook. The provider is
the test-only fake under Meta's name and the secrets are test values: nothing
is ever sent anywhere.
"""
from datetime import timedelta
from unittest import mock

from django.test import override_settings
from django.utils import timezone

from bookings.booking_service import cancel_booking, reschedule_booking
from bookings.models import CancelReason, RescheduleReason
from bookings.scheduling import indian_today
from bookings.tests_booking import MORNING, NOW

from . import sending, tasks
from .models import (
    OUTCOME_UNKNOWN,
    Message,
    MessageCancelReason,
    MessageStatus,
    Step,
    TaskResolution,
    TaskStatus,
    UnmatchedStatusEvent,
)
from .providers import PROVIDERS
from .providers.base import SendResult
from .safety import SendBlock
from .sending import SendOutcome
from .tests_providers import CLOSED
from .tests_sending import RETRYABLE, SENDING
from .tests_webhooks import FakeMeta, T1, T2, T3, WebhookTestCase, callback, status

SENDING_THROUGH_META = {**SENDING, 'COMMUNICATIONS_WHATSAPP_PROVIDER': 'meta'}


def accept(wamid):
    return SendResult(accepted=True, status=MessageStatus.QUEUED, provider_message_id=wamid)


@override_settings(**SENDING_THROUGH_META)
class IntegrationTestCase(WebhookTestCase):
    def setUp(self):
        super().setUp()
        FakeMeta.reset()
        patcher = mock.patch.dict(PROVIDERS, {'meta': FakeMeta})
        patcher.start()
        self.addCleanup(patcher.stop)

    def live_booking(self, offset=2):
        """A booking still to come by the real clock, which the Celery jobs run on."""
        return self.book(day=indian_today() + timedelta(days=offset), now=timezone.now())

    @staticmethod
    def dispatch():
        return tasks.dispatch_messages.apply().get()

    @staticmethod
    def ack(booking):
        return booking.communication_messages.select_related('task').filter(template__step=Step.ACKNOWLEDGEMENT).first()


class HappyPathTests(IntegrationTestCase):
    def test_a_booking_from_planning_to_read(self):
        booking = self.live_booking()
        self.assertEqual(booking.communication_tasks.count(), 5)
        self.assertEqual(self.ack(booking).status, MessageStatus.PENDING)
        FakeMeta.reset(accept('wamid.HAPPY'))

        self.assertEqual(self.dispatch()['outcomes'], {SendOutcome.QUEUED: 1})
        ack = self.ack(booking)
        self.assertEqual((ack.status, ack.task.status, ack.task.resolution),
                         (MessageStatus.QUEUED, TaskStatus.DONE, TaskResolution.ACCEPTED))
        outgoing, _timeout = FakeMeta.outbox[0]
        self.assertNotIn('**', outgoing.text)
        self.assertEqual(outgoing.to, booking.lead.phone_key[1:])

        self.post(callback(status('wamid.HAPPY', 'sent', T1)))
        self.post(callback(status('wamid.HAPPY', 'delivered', T2), status('wamid.HAPPY', 'read', T3)))
        ack = self.ack(booking)
        self.assertEqual((ack.status, ack.task.resolution), (MessageStatus.READ, TaskResolution.SENT))
        self.assertEqual((ack.status_events.count(), ack.attempts.count()), (3, 1))
        # Nothing more to send.
        self.assertEqual(self.dispatch()['outcomes'], {})

    @override_settings(**CLOSED)
    def test_with_the_shipped_settings_nothing_is_sent(self):
        booking = self.live_booking()
        summary = self.dispatch()
        # Not even picked up: nothing claimed, attempted or written.
        self.assertEqual((summary['held_back'], summary['outcomes']), (SendBlock.SENDING_DISABLED, {}))
        ack = self.ack(booking)
        self.assertEqual((ack.status, ack.claimed_at, ack.attempt_count, FakeMeta.outbox),
                         (MessageStatus.PENDING, None, 0, []))


class FailureTests(IntegrationTestCase):
    def test_a_temporary_failure_is_retried_by_the_dispatcher(self):
        booking = self.live_booking()
        FakeMeta.reset(RETRYABLE, accept('wamid.RETRY'))
        self.assertEqual(self.dispatch()['outcomes'], {SendOutcome.RETRYING: 1})
        retry_at = self.ack(booking).next_attempt_at
        self.assertEqual(self.dispatch()['outcomes'], {})  # not due yet
        self.assertEqual(tasks.run_dispatch(now=retry_at)['outcomes'], {SendOutcome.QUEUED: 1})
        ack = self.ack(booking)
        self.assertEqual((ack.status, ack.attempt_count, ack.task.resolution),
                         (MessageStatus.QUEUED, 2, TaskResolution.ACCEPTED))

    def test_a_permanent_failure_stays_failed(self):
        booking = self.live_booking()
        FakeMeta.reset(SendResult(accepted=False, error_code='131026', error_message='Not a WhatsApp user'))
        self.assertEqual(self.dispatch()['outcomes'], {SendOutcome.FAILED: 1})
        self.assertEqual(tasks.run_dispatch(now=timezone.now() + timedelta(hours=1))['outcomes'], {})
        ack = self.ack(booking)
        self.assertEqual((ack.status, ack.failure_code, ack.task.status), (MessageStatus.FAILED, '131026', TaskStatus.OPEN))

    def test_an_unknown_outcome_and_a_stuck_send_are_never_resent(self):
        timed_out, stuck = self.live_booking(), self.live_booking()
        FakeMeta.reset(TimeoutError('read timed out'))
        sending.send_message(self.ack(timed_out).pk)
        self.assertEqual(self.ack(timed_out).failure_code, OUTCOME_UNKNOWN)
        # A sender that stopped mid-call: its claim ages past 5 minutes.
        sending._claim(self.ack(stuck).pk, timezone.now())
        Message.objects.filter(pk=self.ack(stuck).pk).update(claimed_at=timezone.now() - timedelta(minutes=6))
        self.assertEqual(tasks.recover_stuck_sends.apply().get(), {'recovered': 1})
        self.assertEqual((self.ack(stuck).status, self.ack(stuck).failure_code), (MessageStatus.FAILED, OUTCOME_UNKNOWN))
        self.assertEqual(tasks.recover_stuck_sends.apply().get(), {'recovered': 0})
        self.assertEqual(self.dispatch()['outcomes'], {})
        self.assertEqual(len(FakeMeta.outbox), 1)


class RescheduleTests(IntegrationTestCase):
    def test_a_moved_booking_and_a_delivery_failure_afterwards(self):
        old = self.live_booking()
        FakeMeta.reset(accept('wamid.OLD'), accept('wamid.NEW'))
        self.dispatch()
        new = reschedule_booking(old, indian_today() + timedelta(days=3), MORNING,
                                 reason_code=RescheduleReason.PARENT_REQUEST, actor=self.admin, now=timezone.now()).booking
        new_task = new.communication_tasks.get(step=Step.ACKNOWLEDGEMENT)
        self.assertEqual(new_task.resolution, TaskResolution.ALREADY_ACKNOWLEDGED)
        self.assertEqual(self.dispatch()['outcomes'], {})

        self.post(callback(status('wamid.OLD', 'failed', T1, errors=[{'code': 131026, 'title': 'Message undeliverable'}])))
        self.assertTrue(Message.objects.get(provider_message_id='wamid.OLD').is_delivery_failure)
        self.assertEqual(self.dispatch()['outcomes'], {SendOutcome.QUEUED: 1})
        ack = self.ack(new)
        self.assertEqual((ack.provider_message_id, ack.task.status, ack.task.resolution),
                         ('wamid.NEW', TaskStatus.DONE, TaskResolution.ACCEPTED))
        self.assertEqual(len(FakeMeta.outbox), 2)


class WebhookTimingTests(IntegrationTestCase):
    def test_an_early_callback_is_reconciled_when_the_send_is_recorded(self):
        booking = self.live_booking()
        self.post(callback(status('wamid.EARLY', 'sent', T1)))
        self.assertEqual(UnmatchedStatusEvent.objects.count(), 1)
        FakeMeta.reset(accept('wamid.EARLY'))
        self.dispatch()
        ack = self.ack(booking)
        self.assertEqual((ack.status, ack.task.resolution), (MessageStatus.SENT, TaskResolution.SENT))
        self.assertEqual(tasks.reconcile_status_updates.apply().get(), {'applied': 0, 'purged': 0})
        self.assertFalse(UnmatchedStatusEvent.objects.exists())


class CancellationTests(IntegrationTestCase):
    def test_cancelled_while_being_sent(self):
        accepted, refused = self.live_booking(), self.live_booking()

        def cancel_then(booking, result):
            def run(_outgoing):
                cancel_booking(booking, reason_code=CancelReason.PARENT_REQUEST, actor=self.admin, now=timezone.now())
                return result
            return run

        FakeMeta.reset(cancel_then(accepted, accept('wamid.TOOK')),
                       cancel_then(refused, SendResult(accepted=False, error_code='131000')))
        self.dispatch()
        took, closed = self.ack(accepted), self.ack(refused)
        # Sent is the truth once the provider took it; its step stays as the cancellation closed it.
        self.assertEqual((took.status, took.task.status), (MessageStatus.QUEUED, TaskStatus.CANCELLED))
        self.assertEqual((closed.status, closed.cancel_reason), (MessageStatus.CANCELLED, MessageCancelReason.BOOKING_CANCELLED))


class ExpiryTests(IntegrationTestCase):
    def test_expired_messages_and_missed_tasks(self):
        # Made at NOW, days ago by the real clock the expiry job runs on.
        retrying, unknown = self.book(), self.book()
        FakeMeta.reset(RETRYABLE)
        sending.send_message(self.ack(retrying).pk, now=NOW)
        Message.objects.filter(pk=self.ack(unknown).pk).update(status=MessageStatus.FAILED, failed_at=NOW,
                                                              failure_code=OUTCOME_UNKNOWN)
        result = tasks.close_expired_communications.apply().get()
        self.assertGreater(result['missed'], 0)
        self.assertEqual((self.ack(retrying).status, self.ack(retrying).cancel_reason),
                         (MessageStatus.CANCELLED, MessageCancelReason.EXPIRED))
        self.assertEqual(self.ack(unknown).failure_code, OUTCOME_UNKNOWN)
        self.assertEqual(tasks.close_expired_communications.apply().get(), {'missed': 0, 'expired': 0})
