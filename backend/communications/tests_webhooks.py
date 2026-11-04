"""
The WhatsApp webhook (communications.webhooks, providers.meta, status_updates;
Phase 2B step 5): Meta's subscription check, the signature every callback
must carry, and the delivery statuses applied to messages -- forward only,
each kept once, the step moved from ACCEPTED to SENT on a Sent report and
never touched by Delivered or Read, unknown outcomes left alone. The secrets
here are test values; nothing reaches Meta.
"""
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone as dt_timezone
from unittest import mock

from django.db import OperationalError
from django.test import SimpleTestCase, override_settings

from django.utils import timezone

from bookings.booking_service import cancel_booking, reschedule_booking
from bookings.models import CancelReason, RescheduleReason
from bookings.scheduling import indian_today
from bookings.tests_booking import MORNING, NOW

from . import planner
from .models import (
    DELIVERY_FAILURES,
    OUTCOME_UNKNOWN,
    CommunicationTask,
    Message,
    MessageAttempt,
    MessageStatus,
    MessageStatusEvent,
    Step,
    TaskResolution,
    TaskStatus,
    UnmatchedStatusEvent,
)
from .providers import PROVIDERS
from .providers.base import ProviderNotConfigured, SendResult
from .providers.meta import MetaCloudProvider, is_temporary_error, status_updates, valid_signature
from .rendering import Requirement, requirements
from .sending import SendOutcome, due_message_ids, send_message
from .status_updates import UNMATCHED_RETENTION, purge_unmatched, reconcile, reconcile_unmatched
from .tests_planning import CommunicationTestCase
from .tests_providers import FakeProvider
from .tests_sending import SENDING

SECRET = 'test-app-secret'
TOKEN = 'test-verify-token'
URL = '/api/communications/webhooks/whatsapp/'
# Unix timestamps, seconds: T1 < T2 < T3.
T1, T2, T3 = 1793000000, 1793000060, 1793000120


def moment(timestamp):
    return datetime.fromtimestamp(timestamp, tz=dt_timezone.utc)


def sign(body, secret=SECRET):
    return 'sha256=' + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def status(wamid, word, timestamp, **extra):
    return {'id': wamid, 'status': word, 'timestamp': str(timestamp), 'recipient_id': '971501234567', **extra}


def callback(*statuses, field='messages', obj='whatsapp_business_account'):
    return {'object': obj, 'entry': [{'id': 'WABA-1', 'changes': [{'field': field, 'value': {
        'messaging_product': 'whatsapp',
        'metadata': {'display_phone_number': '971500000000', 'phone_number_id': 'PN-1'},
        'statuses': list(statuses),
    }}]}]}


class FakeMeta(FakeProvider):
    """The test fake under the Meta provider's name: a message sent through it is matched as Meta's."""
    name = 'meta'


@override_settings(COMMUNICATIONS_META_APP_SECRET=SECRET, COMMUNICATIONS_META_VERIFY_TOKEN=TOKEN)
class WebhookTestCase(CommunicationTestCase):
    def post(self, payload, signature=None, raw=None):
        body = raw if raw is not None else json.dumps(payload).encode()
        headers = {} if signature is False else {'HTTP_X_HUB_SIGNATURE_256': signature or sign(body)}
        return self.client.post(URL, data=body, content_type='application/json', **headers)

    def accepted(self, wamid='wamid.ACK1', status=MessageStatus.QUEUED, booking=None, now=NOW):
        """A booking's acknowledgement, accepted by "Meta" through the real sender."""
        booking = booking or self.book()
        ack = booking.communication_messages.get(template__step=Step.ACKNOWLEDGEMENT)
        FakeMeta.reset(SendResult(accepted=True, status=status, provider_message_id=wamid))
        with mock.patch.dict(PROVIDERS, {'meta': FakeMeta}), override_settings(**{
            **SENDING, 'COMMUNICATIONS_WHATSAPP_PROVIDER': 'meta',
        }):
            send_message(ack.pk, now=now)
        return self.fresh(ack)

    @staticmethod
    def fresh(message):
        return Message.objects.select_related('task').get(pk=message.pk)


class VerificationTests(WebhookTestCase):
    def test_the_subscription_check_echoes_the_challenge(self):
        res = self.client.get(URL, {'hub.mode': 'subscribe', 'hub.verify_token': TOKEN, 'hub.challenge': '1158201444'})
        self.assertEqual((res.status_code, res.content, res['Content-Type']), (200, b'1158201444', 'text/plain'))

    def test_a_wrong_or_missing_token_is_refused(self):
        for params in ({'hub.mode': 'subscribe', 'hub.verify_token': 'guess', 'hub.challenge': '1'},
                       {'hub.mode': 'unsubscribe', 'hub.verify_token': TOKEN, 'hub.challenge': '1'},
                       {'hub.mode': 'subscribe', 'hub.challenge': '1'},
                       {}):
            with self.subTest(params=params):
                res = self.client.get(URL, params)
                self.assertEqual((res.status_code, res.json()['error']), (403, 'VERIFICATION_FAILED'))
                self.assertNotEqual(res.content, b'1')

    @override_settings(COMMUNICATIONS_META_VERIFY_TOKEN='')
    def test_without_a_configured_token_nothing_is_verified(self):
        res = self.client.get(URL, {'hub.mode': 'subscribe', 'hub.verify_token': '', 'hub.challenge': '1'})
        self.assertEqual(res.status_code, 403)

    def test_only_get_and_post(self):
        self.assertEqual(self.client.put(URL, data='{}', content_type='application/json').status_code, 405)


class SignatureTests(WebhookTestCase):
    def test_a_correctly_signed_callback_is_accepted(self):
        ack = self.accepted()
        res = self.post(callback(status('wamid.ACK1', 'sent', T1)))
        self.assertEqual((res.status_code, res.json()), (200, {'received': 1}))
        self.assertEqual(self.fresh(ack).status, MessageStatus.SENT)

    def test_a_missing_wrong_or_tampered_signature_is_refused(self):
        ack = self.accepted()
        payload = callback(status('wamid.ACK1', 'read', T1))
        body = json.dumps(payload).encode()
        cases = {
            'missing': dict(signature=False),
            'other secret': dict(signature=sign(body, 'not-the-secret')),
            'tampered body': dict(signature=sign(body), raw=body.replace(b'read', b'sent')),
            'no sha256= prefix': dict(signature=sign(body)[len('sha256='):]),
            'garbage': dict(signature='sha256=zz'),
        }
        for name, kwargs in cases.items():
            with self.subTest(name), self.assertLogs('communications.webhooks', 'WARNING') as logged:
                res = self.post(payload, **kwargs)
                self.assertEqual((res.status_code, res.json()['error']), (403, 'INVALID_SIGNATURE'))
                self.assertNotIn(SECRET, ''.join(logged.output))
                self.assertNotIn('971501234567', ''.join(logged.output))
        self.assertEqual((self.fresh(ack).status, MessageStatusEvent.objects.count()), (MessageStatus.QUEUED, 0))

    @override_settings(COMMUNICATIONS_META_APP_SECRET='')
    def test_without_a_configured_secret_nothing_is_accepted(self):
        body = json.dumps(callback()).encode()
        self.assertEqual(self.post(None, signature=sign(body, ''), raw=body).status_code, 403)


class StatusTests(WebhookTestCase):
    def test_sent_delivered_read_move_the_message_forward(self):
        ack = self.accepted()
        self.assertEqual((ack.task.status, ack.task.resolution), (TaskStatus.DONE, TaskResolution.ACCEPTED))

        self.post(callback(status('wamid.ACK1', 'sent', T1)))
        ack = self.fresh(ack)
        self.assertEqual((ack.status, ack.sent_at), (MessageStatus.SENT, moment(T1)))
        # Sent confirmed: the step says so.
        self.assertEqual(ack.task.resolution, TaskResolution.SENT)

        self.post(callback(status('wamid.ACK1', 'delivered', T2)))
        ack = self.fresh(ack)
        self.assertEqual((ack.status, ack.delivered_at, ack.task.resolution),
                         (MessageStatus.DELIVERED, moment(T2), TaskResolution.SENT))

        self.post(callback(status('wamid.ACK1', 'read', T3)))
        ack = self.fresh(ack)
        self.assertEqual((ack.status, ack.read_at, ack.task.resolution),
                         (MessageStatus.READ, moment(T3), TaskResolution.SENT))
        events = list(ack.status_events.order_by('received_at').values_list('provider_status', 'status', 'occurred_at'))
        self.assertEqual(events, [('sent', MessageStatus.SENT, moment(T1)), ('delivered', MessageStatus.DELIVERED, moment(T2)),
                                  ('read', MessageStatus.READ, moment(T3))])
        # The webhook writes no attempt: attempts are sends.
        self.assertEqual(ack.attempts.count(), 1)

    def test_delivered_and_read_never_change_the_task(self):
        ack = self.accepted()
        self.post(callback(status('wamid.ACK1', 'delivered', T2), status('wamid.ACK1', 'read', T3)))
        ack = self.fresh(ack)
        self.assertEqual((ack.status, ack.task.status, ack.task.resolution),
                         (MessageStatus.READ, TaskStatus.DONE, TaskResolution.ACCEPTED))
        # Delivered means sent: the moment fills in, the step does not move without a Sent report.
        self.assertEqual((ack.sent_at, ack.delivered_at, ack.read_at), (moment(T2), moment(T2), moment(T3)))

    def test_a_failure_records_metas_error_and_is_not_retried(self):
        for code, title, kind in (('131026', 'Message undeliverable', 'Permanent'),
                                  ('131049', 'This message was not delivered to maintain healthy ecosystem engagement.',
                                   'Temporary')):
            with self.subTest(code=code):
                wamid = f'wamid.F{code}'
                ack = self.accepted(wamid=wamid)
                res = self.post(callback(status(wamid, 'failed', T1, errors=[{
                    'code': int(code), 'title': title, 'message': title,
                    'error_data': {'details': 'Recipient phone number not on WhatsApp.'},
                }])))
                self.assertEqual(res.status_code, 200)
                ack = self.fresh(ack)
                self.assertEqual((ack.status, ack.failure_code, ack.failed_at), (MessageStatus.FAILED, code, moment(T1)))
                self.assertEqual(ack.failure_reason,
                                 f'{kind} delivery failure: {title} -- Recipient phone number not on WhatsApp.')
                # Not retried from the webhook; the step keeps what happened at acceptance.
                self.assertNotIn(ack.pk, due_message_ids(NOW))
                self.assertEqual((ack.attempts.count(), ack.task.resolution), (1, TaskResolution.ACCEPTED))
                event = ack.status_events.get()
                self.assertEqual((event.error_code, event.provider_status), (code, 'failed'))

    def test_a_failure_after_delivery_does_not_undo_it(self):
        ack = self.accepted()
        self.post(callback(status('wamid.ACK1', 'delivered', T2)))
        self.post(callback(status('wamid.ACK1', 'failed', T3, errors=[{'code': 131000, 'title': 'Something went wrong'}])))
        ack = self.fresh(ack)
        self.assertEqual((ack.status, ack.failure_code), (MessageStatus.DELIVERED, ''))
        self.assertEqual(ack.status_events.count(), 2)


class DuplicateAndOrderTests(WebhookTestCase):
    def test_a_callback_delivered_twice_changes_nothing_the_second_time(self):
        ack = self.accepted()
        payload = callback(status('wamid.ACK1', 'sent', T1))
        self.post(payload)
        before = self.fresh(ack)
        self.assertEqual(self.post(payload).status_code, 200)
        after = self.fresh(ack)
        self.assertEqual((after.status, after.sent_at, after.updated_at), (before.status, before.sent_at, before.updated_at))
        self.assertEqual((after.status_events.count(), MessageAttempt.objects.count()), (1, 1))

    def test_out_of_order_callbacks_never_lower_the_status(self):
        ack = self.accepted()
        self.post(callback(status('wamid.ACK1', 'read', T3)))
        self.post(callback(status('wamid.ACK1', 'delivered', T2)))
        self.post(callback(status('wamid.ACK1', 'sent', T1)))
        ack = self.fresh(ack)
        self.assertEqual(ack.status, MessageStatus.READ)
        # Every moment kept, the earliest known for each.
        self.assertEqual((ack.sent_at, ack.delivered_at, ack.read_at), (moment(T1), moment(T2), moment(T3)))
        # The late Sent report still confirms the send for the step.
        self.assertEqual(ack.task.resolution, TaskResolution.SENT)
        self.assertEqual(ack.status_events.count(), 3)

    def test_several_statuses_for_one_message_in_one_callback(self):
        ack = self.accepted()
        res = self.post(callback(status('wamid.ACK1', 'sent', T1), status('wamid.ACK1', 'delivered', T2),
                                 status('wamid.ACK1', 'read', T3)))
        self.assertEqual((res.status_code, res.json()), (200, {'received': 3}))
        self.assertEqual(self.fresh(ack).status, MessageStatus.READ)

    def test_a_status_for_an_id_no_message_holds_is_kept_and_logged_by_its_tail_only(self):
        ack = self.accepted()
        with self.assertLogs('communications.webhooks', 'INFO') as logged:
            res = self.post(callback(status('wamid.HBgMOTcxNTAxMjM0NTY3UNKNOWN9', 'delivered', T1)))
        self.assertEqual(res.status_code, 200)
        output = ''.join(logged.output)
        self.assertIn('...UNKNOWN9', output)
        self.assertNotIn('HBgMOTcxNTAx', output)
        self.assertNotIn('971501234567', output)
        self.assertEqual((self.fresh(ack).status, MessageStatusEvent.objects.count()), (MessageStatus.QUEUED, 0))
        kept = UnmatchedStatusEvent.objects.get()
        self.assertEqual((kept.provider, kept.provider_message_id, kept.status, kept.occurred_at),
                         ('meta', 'wamid.HBgMOTcxNTAxMjM0NTY3UNKNOWN9', MessageStatus.DELIVERED, moment(T1)))


class EarlyCallbackTests(WebhookTestCase):
    """A callback that comes before the sender has recorded the message's id is kept, then applied."""

    def test_an_early_sent_is_applied_when_the_id_is_recorded(self):
        self.assertEqual(self.post(callback(status('wamid.EARLY', 'sent', T1))).status_code, 200)
        kept = UnmatchedStatusEvent.objects.get()
        self.assertEqual((kept.provider_message_id, kept.provider_status, kept.occurred_at),
                         ('wamid.EARLY', 'sent', moment(T1)))
        # The report only: no recipient number is kept.
        self.assertNotIn('recipient', {field.name for field in UnmatchedStatusEvent._meta.get_fields()})

        ack = self.accepted(wamid='wamid.EARLY')
        self.assertEqual((ack.status, ack.sent_at), (MessageStatus.SENT, moment(T1)))
        self.assertEqual((ack.task.status, ack.task.resolution), (TaskStatus.DONE, TaskResolution.SENT))
        self.assertEqual(list(ack.status_events.values_list('provider_status', flat=True)), ['sent'])
        self.assertFalse(UnmatchedStatusEvent.objects.exists())
        # Webhooks never make attempts: the one send is the one attempt.
        self.assertEqual(ack.attempts.count(), 1)

    def test_an_early_callback_delivered_again_is_kept_and_applied_once(self):
        payload = callback(status('wamid.EARLY', 'delivered', T2))
        self.post(payload)
        self.post(payload)
        self.assertEqual(UnmatchedStatusEvent.objects.count(), 1)
        ack = self.accepted(wamid='wamid.EARLY')
        # And again after it was applied: recognised, nothing changes.
        self.post(payload)
        ack = self.fresh(ack)
        self.assertEqual((ack.status, ack.status_events.count(), UnmatchedStatusEvent.objects.count()),
                         (MessageStatus.DELIVERED, 1, 0))

    def test_early_callbacks_out_of_order_keep_the_forward_only_rules(self):
        self.post(callback(status('wamid.EARLY', 'read', T3)))
        self.post(callback(status('wamid.EARLY', 'delivered', T2)))
        ack = self.accepted(wamid='wamid.EARLY')
        self.assertEqual((ack.status, ack.read_at, ack.delivered_at, ack.sent_at),
                         (MessageStatus.READ, moment(T3), moment(T2), moment(T2)))
        # No Sent report yet: the step stays ACCEPTED -- until one comes.
        self.assertEqual(ack.task.resolution, TaskResolution.ACCEPTED)
        self.post(callback(status('wamid.EARLY', 'sent', T1)))
        ack = self.fresh(ack)
        self.assertEqual((ack.status, ack.sent_at, ack.task.resolution), (MessageStatus.READ, moment(T1), TaskResolution.SENT))

    def test_an_early_failure_leaves_a_delivery_failure(self):
        self.post(callback(status('wamid.EARLY', 'failed', T1, errors=[{'code': 131026, 'title': 'Message undeliverable'}])))
        ack = self.accepted(wamid='wamid.EARLY')
        self.assertEqual((ack.status, ack.failure_code, ack.is_delivery_failure), (MessageStatus.FAILED, '131026', True))
        self.assertEqual((ack.task.status, ack.task.resolution), (TaskStatus.DONE, TaskResolution.ACCEPTED))

    def test_one_recorded_just_after_the_callback_looked_is_applied_by_the_periodic_pass(self):
        ack = self.accepted(wamid='wamid.LATE')
        self.post(callback(status('wamid.RACE', 'delivered', T2)))
        # The sender committed its id just after the callback looked, so it never saw the kept status.
        Message.objects.filter(pk=ack.pk).update(provider_message_id='wamid.RACE')
        self.assertEqual(reconcile_unmatched(), 1)
        ack = self.fresh(ack)
        self.assertEqual((ack.status, ack.delivered_at, UnmatchedStatusEvent.objects.count()),
                         (MessageStatus.DELIVERED, moment(T2), 0))
        self.assertEqual(reconcile_unmatched(), 0)

    def test_trouble_applying_early_statuses_never_undoes_the_send(self):
        self.post(callback(status('wamid.EARLY', 'delivered', T2)))
        with mock.patch('communications.status_updates.reconcile', side_effect=OperationalError('lock timeout')), \
                self.assertLogs('communications.sending', 'ERROR'):
            ack = self.accepted(wamid='wamid.EARLY')
        # Recorded all the same, apart from the statuses: those stay kept...
        self.assertEqual((ack.status, ack.provider_message_id, ack.attempts.count()),
                         (MessageStatus.QUEUED, 'wamid.EARLY', 1))
        self.assertEqual((ack.task.status, ack.task.resolution), (TaskStatus.DONE, TaskResolution.ACCEPTED))
        self.assertEqual(UnmatchedStatusEvent.objects.count(), 1)
        # ...for the periodic pass, which applies them.
        self.assertEqual(reconcile_unmatched(), 1)
        self.assertEqual((self.fresh(ack).status, UnmatchedStatusEvent.objects.count()), (MessageStatus.DELIVERED, 0))

    def test_one_messages_trouble_never_stops_the_periodic_pass(self):
        first, second = self.accepted(wamid='wamid.A'), self.accepted(wamid='wamid.B')
        self.post(callback(status('wamid.X', 'delivered', T2), status('wamid.Y', 'delivered', T2)))
        Message.objects.filter(pk=first.pk).update(provider_message_id='wamid.X')
        Message.objects.filter(pk=second.pk).update(provider_message_id='wamid.Y')
        def flaky(message, now):
            if message.pk == first.pk:
                raise RuntimeError('database hiccup')
            return reconcile(message, now)

        with mock.patch('communications.status_updates.reconcile', flaky), \
                self.assertLogs('communications.status_updates', 'ERROR'):
            self.assertEqual(reconcile_unmatched(), 1)
        self.assertEqual((self.fresh(first).status, self.fresh(second).status), (MessageStatus.QUEUED, MessageStatus.DELIVERED))
        # The one that failed stays kept, for the next pass.
        self.assertEqual(UnmatchedStatusEvent.objects.get().provider_message_id, 'wamid.X')
        self.assertEqual(reconcile_unmatched(), 1)

    def test_a_status_no_message_takes_is_forgotten_after_a_week(self):
        self.post(callback(status('wamid.OLD', 'sent', T1), status('wamid.NEW', 'sent', T2)))
        old = UnmatchedStatusEvent.objects.get(provider_message_id='wamid.OLD')
        UnmatchedStatusEvent.objects.filter(pk=old.pk).update(received_at=old.received_at - UNMATCHED_RETENTION - timedelta(minutes=1))
        self.assertEqual(purge_unmatched(), 1)
        self.assertEqual(list(UnmatchedStatusEvent.objects.values_list('provider_message_id', flat=True)), ['wamid.NEW'])


class DeliveryFailureTests(WebhookTestCase):
    """Failed after the provider accepted it: on record for the BDE, never reopened, retried, cancelled or expired."""

    def fail(self, wamid, timestamp=T2):
        self.post(callback(status(wamid, 'failed', timestamp, errors=[{
            'code': 131026, 'title': 'Message undeliverable', 'error_data': {'details': 'Not on WhatsApp.'}}])))

    def test_a_delivery_failure_keeps_the_step_closed_and_is_never_retried(self):
        for sent_first in (False, True):
            with self.subTest(sent_first=sent_first):
                wamid = f'wamid.DF{int(sent_first)}'
                ack = self.accepted(wamid=wamid)
                if sent_first:
                    self.post(callback(status(wamid, 'sent', T1)))
                self.fail(wamid)
                ack = self.fresh(ack)
                self.assertEqual((ack.status, ack.failure_code, ack.failed_at), (MessageStatus.FAILED, '131026', moment(T2)))
                self.assertEqual(ack.failure_reason, 'Permanent delivery failure: Message undeliverable -- Not on WhatsApp.')
                self.assertTrue(ack.is_delivery_failure)
                self.assertTrue(Message.objects.filter(DELIVERY_FAILURES, pk=ack.pk).exists())
                # The step stays as it closed at acceptance -- or at the Sent report.
                self.assertEqual((ack.task.status, ack.task.resolution),
                                 (TaskStatus.DONE, TaskResolution.SENT if sent_first else TaskResolution.ACCEPTED))
                self.assertNotIn(ack.pk, due_message_ids(NOW))
                self.assertEqual(send_message(ack.pk, now=NOW).outcome, SendOutcome.NOT_PENDING)
                self.assertEqual(ack.attempts.count(), 1)

    def test_it_stays_a_delivery_failure_when_the_booking_is_cancelled_or_its_window_closes(self):
        booking = self.book()
        ack = self.accepted(wamid='wamid.KEEP', booking=booking)
        self.fail('wamid.KEEP')
        cancel_booking(booking, reason_code=CancelReason.PARENT_REQUEST, actor=self.admin, now=NOW)
        planner.close_expired(booking.slot.ends_at)
        ack = self.fresh(ack)
        self.assertEqual((ack.status, ack.cancel_reason, ack.is_delivery_failure), (MessageStatus.FAILED, '', True))

    def test_a_send_the_provider_refused_is_not_a_delivery_failure(self):
        booking = self.book()
        ack = booking.communication_messages.get(template__step=Step.ACKNOWLEDGEMENT)
        FakeMeta.reset(SendResult(accepted=False, error_code='131026', error_message='Not a WhatsApp user'))
        with mock.patch.dict(PROVIDERS, {'meta': FakeMeta}), override_settings(**{
            **SENDING, 'COMMUNICATIONS_WHATSAPP_PROVIDER': 'meta',
        }):
            send_message(ack.pk, now=NOW)
        ack = self.fresh(ack)
        self.assertEqual((ack.status, ack.is_delivery_failure), (MessageStatus.FAILED, False))
        self.assertFalse(Message.objects.filter(DELIVERY_FAILURES, pk=ack.pk).exists())


class RescheduleDeliveryFailureTests(WebhookTestCase):
    """
    An earlier booking's acknowledgement accepted, the booking moved -- the new
    booking's closed as already acknowledged -- and then Meta reports the
    earlier one undelivered: the new booking gets its own back. Run on the real
    clock, which the webhook's release checks the new booking against.
    """

    def day(self, offset):
        return indian_today() + timedelta(days=offset)

    def move(self, booking, offset):
        return reschedule_booking(booking, self.day(offset), MORNING, reason_code=RescheduleReason.PARENT_REQUEST,
                                  actor=self.admin, now=timezone.now()).booking

    def ack_of(self, booking):
        return booking.communication_messages.select_related('task', 'template').filter(
            template__step=Step.ACKNOWLEDGEMENT).first()

    def ack_task(self, booking):
        return booking.communication_tasks.get(step=Step.ACKNOWLEDGEMENT)

    def failure(self, wamid, timestamp=T2):
        return callback(status(wamid, 'failed', timestamp, errors=[{'code': 131026, 'title': 'Message undeliverable'}]))

    def moved_after_acceptance(self, wamid='wamid.OLD'):
        old = self.book(day=self.day(2), now=timezone.now())
        old_ack = self.accepted(wamid=wamid, booking=old, now=timezone.now())
        new = self.move(old, 3)
        task = self.ack_task(new)
        self.assertEqual((task.status, task.resolution), (TaskStatus.DONE, TaskResolution.ALREADY_ACKNOWLEDGED))
        self.assertIsNone(self.ack_of(new))
        return old_ack, new

    def test_a_delivery_failure_after_the_move_releases_the_new_bookings_acknowledgement(self):
        old_ack, new = self.moved_after_acceptance()
        self.assertEqual(self.post(self.failure('wamid.OLD')).status_code, 200)
        old_ack = self.fresh(old_ack)
        self.assertTrue(old_ack.is_delivery_failure)
        task = self.ack_task(new)
        self.assertEqual((task.status, task.resolution, task.resolved_at), (TaskStatus.OPEN, '', None))
        new_ack = self.ack_of(new)
        self.assertEqual(new_ack.status, MessageStatus.PENDING)
        self.assertIn(f'*{new_ack.variables["demo_date"]} at 10:00 AM IST*', new_ack.body.replace('**', '*'))
        with override_settings(**SENDING):  # due, for a number the gate lets through
            self.assertIn(new_ack.pk, due_message_ids(timezone.now()))
        # The earlier one is never retried; the new one goes through the ordinary sender.
        self.assertEqual(send_message(old_ack.pk).outcome, SendOutcome.NOT_PENDING)
        self.assertEqual(old_ack.attempts.count(), 1)
        sent = self.accepted(wamid='wamid.NEW', booking=new, now=timezone.now())
        self.assertEqual((sent.status, sent.task.status, sent.task.resolution),
                         (MessageStatus.QUEUED, TaskStatus.DONE, TaskResolution.ACCEPTED))

    def test_one_closed_while_the_earlier_was_being_sent_is_revived(self):
        old = self.book(day=self.day(2), now=timezone.now())
        old_ack = self.ack_of(old)
        moved = {}

        def move_then_accept(_outgoing):
            moved['booking'] = self.move(old, 3)
            return SendResult(accepted=True, status=MessageStatus.QUEUED, provider_message_id='wamid.FLIGHT')

        FakeMeta.reset(move_then_accept)
        with mock.patch.dict(PROVIDERS, {'meta': FakeMeta}), override_settings(**{
            **SENDING, 'COMMUNICATIONS_WHATSAPP_PROVIDER': 'meta',
        }):
            send_message(old_ack.pk, now=timezone.now())
        new = moved['booking']
        closed = self.ack_of(new)
        self.assertEqual((closed.status, closed.task.resolution), (MessageStatus.CANCELLED, TaskResolution.ALREADY_ACKNOWLEDGED))

        self.post(self.failure('wamid.FLIGHT'))
        revived = self.ack_of(new)
        self.assertEqual((revived.pk, revived.status, revived.cancel_reason, revived.task.status),
                         (closed.pk, MessageStatus.PENDING, '', TaskStatus.OPEN))

    def test_a_failure_reported_again_releases_once(self):
        old_ack, new = self.moved_after_acceptance()
        self.post(self.failure('wamid.OLD'))
        self.post(self.failure('wamid.OLD'))
        self.assertEqual(new.communication_messages.filter(template__step=Step.ACKNOWLEDGEMENT).count(), 1)
        self.accepted(wamid='wamid.NEW', booking=new, now=timezone.now())
        # Again, after the new one was sent: nothing changes.
        self.post(self.failure('wamid.OLD'))
        new_ack = self.ack_of(new)
        self.assertEqual((new_ack.status, new_ack.task.resolution), (MessageStatus.QUEUED, TaskResolution.ACCEPTED))
        self.assertEqual(self.fresh(old_ack).status_events.count(), 1)

    def test_a_failure_after_delivery_releases_nothing(self):
        old_ack, new = self.moved_after_acceptance()
        self.post(callback(status('wamid.OLD', 'delivered', T1)))
        self.post(self.failure('wamid.OLD', timestamp=T2))
        self.assertEqual(self.fresh(old_ack).status, MessageStatus.DELIVERED)
        task = self.ack_task(new)
        self.assertEqual((task.status, task.resolution), (TaskStatus.DONE, TaskResolution.ALREADY_ACKNOWLEDGED))
        self.assertIsNone(self.ack_of(new))

    def test_a_later_delivered_after_the_failure_changes_nothing(self):
        old_ack, new = self.moved_after_acceptance()
        self.post(self.failure('wamid.OLD', timestamp=T2))
        self.post(callback(status('wamid.OLD', 'delivered', T1)))
        self.assertTrue(self.fresh(old_ack).is_delivery_failure)
        self.assertEqual(self.ack_of(new).status, MessageStatus.PENDING)
        self.assertEqual(new.communication_messages.filter(template__step=Step.ACKNOWLEDGEMENT).count(), 1)

    def test_an_unknown_outcome_earlier_in_the_chain_keeps_it_for_someone_to_check(self):
        first = self.book(day=self.day(2), now=timezone.now())
        Message.objects.filter(pk=self.ack_of(first).pk).update(
            status=MessageStatus.FAILED, failed_at=timezone.now(), failure_code=OUTCOME_UNKNOWN)
        second = self.move(first, 3)
        # Someone checked and sent the second booking's by hand through the provider: accepted.
        second_ack = self.ack_of(second)
        Message.objects.filter(pk=second_ack.pk).update(
            status=MessageStatus.QUEUED, queued_at=timezone.now(), provider='meta', provider_message_id='wamid.SECOND')
        third = self.move(second, 4)
        self.assertEqual(self.ack_task(third).resolution, TaskResolution.ALREADY_ACKNOWLEDGED)

        self.post(self.failure('wamid.SECOND'))
        task, third_ack = self.ack_task(third), self.ack_of(third)
        self.assertEqual(task.status, TaskStatus.OPEN)
        # Reopened, but not sent by itself: the first booking's outcome is still unknown.
        self.assertEqual(third_ack.status, MessageStatus.WAITING)
        checks = dict(requirements(third, Step.ACKNOWLEDGEMENT, third_ack.template.current_version().body, timezone.now()))
        self.assertFalse(checks[Requirement.EARLIER_ACKNOWLEDGEMENT])
        self.assertEqual(send_message(third_ack.pk).outcome, SendOutcome.NOT_PENDING)
        self.assertEqual(self.fresh(Message.objects.get(pk=self.ack_of(first).pk)).failure_code, OUTCOME_UNKNOWN)

    def test_a_cancelled_new_booking_gets_nothing_back(self):
        old_ack, new = self.moved_after_acceptance()
        cancel_booking(new, reason_code=CancelReason.PARENT_REQUEST, actor=self.admin, now=timezone.now())
        self.post(self.failure('wamid.OLD'))
        task = self.ack_task(new)
        self.assertEqual((task.status, task.resolution), (TaskStatus.DONE, TaskResolution.ALREADY_ACKNOWLEDGED))
        self.assertIsNone(self.ack_of(new))


class ProtectedStateTests(WebhookTestCase):
    def test_an_unknown_outcome_is_never_changed_by_a_callback(self):
        ack = self.accepted()
        Message.objects.filter(pk=ack.pk).update(status=MessageStatus.FAILED, failed_at=NOW,
                                                 failure_code=OUTCOME_UNKNOWN, failure_reason='Check WhatsApp.')
        self.post(callback(status('wamid.ACK1', 'delivered', T2)))
        ack = self.fresh(ack)
        self.assertEqual((ack.status, ack.failure_code, ack.delivered_at), (MessageStatus.FAILED, OUTCOME_UNKNOWN, None))
        # The report is kept beside it, for whoever checks it.
        self.assertEqual(ack.status_events.get().provider_status, 'delivered')

    def test_a_cancelled_step_is_never_reopened_or_completed(self):
        booking = self.book()
        ack = booking.communication_messages.get(template__step=Step.ACKNOWLEDGEMENT)

        def cancel_then_accept(_outgoing):
            cancel_booking(booking, reason_code=CancelReason.PARENT_REQUEST, actor=self.admin, now=NOW)
            return SendResult(accepted=True, status=MessageStatus.QUEUED, provider_message_id='wamid.CXL')

        FakeMeta.reset(cancel_then_accept)
        with mock.patch.dict(PROVIDERS, {'meta': FakeMeta}), override_settings(**{
            **SENDING, 'COMMUNICATIONS_WHATSAPP_PROVIDER': 'meta',
        }):
            send_message(ack.pk, now=NOW)
        self.post(callback(status('wamid.CXL', 'sent', T1), status('wamid.CXL', 'read', T2)))
        ack = self.fresh(ack)
        self.assertEqual(ack.status, MessageStatus.READ)
        self.assertEqual((ack.task.status, ack.task.resolution), (TaskStatus.CANCELLED, TaskResolution.BOOKING_CANCELLED))

    def test_a_missed_step_is_not_completed_by_a_callback(self):
        ack = self.accepted()
        CommunicationTask.objects.filter(pk=ack.task_id).update(status=TaskStatus.MISSED, resolution='', resolved_by=None)
        self.post(callback(status('wamid.ACK1', 'sent', T1), status('wamid.ACK1', 'delivered', T2),
                           status('wamid.ACK1', 'read', T3)))
        ack = self.fresh(ack)
        self.assertEqual((ack.status, ack.task.status, ack.task.resolution), (MessageStatus.READ, TaskStatus.MISSED, ''))


class MalformedTests(WebhookTestCase):
    def test_a_signed_body_that_is_not_a_whatsapp_callback_is_refused(self):
        for raw in (b'not json', b'[1, 2]', json.dumps({'object': 'whatsapp_business_account'}).encode(),
                    json.dumps({'object': 'whatsapp_business_account', 'entry': [{'changes': 'x'}]}).encode(),
                    json.dumps({'object': 'whatsapp_business_account', 'entry': [{'changes': [
                        {'field': 'messages', 'value': {'statuses': 'x'}}]}]}).encode(),
                    b'\xff\xfe'):
            with self.subTest(raw=raw[:40]):
                res = self.post(None, signature=sign(raw), raw=raw)
                self.assertEqual((res.status_code, res.json()['error']), (400, 'INVALID_PAYLOAD'))

    def test_what_is_not_a_delivery_status_is_skipped(self):
        ack = self.accepted()
        incoming = callback()
        incoming['entry'][0]['changes'][0]['value']['messages'] = [{'from': '971501234567', 'type': 'text'}]
        for payload in (callback(obj='page'), callback(field='account_update'), incoming,
                        callback({'status': 'sent'}, status('', 'sent', T1), status('wamid.ACK1', 'deleted', T1), 'x')):
            with self.subTest(payload=str(payload)[:60]):
                res = self.post(payload)
                self.assertEqual((res.status_code, res.json()), (200, {'received': 0}))
        self.assertEqual((self.fresh(ack).status, MessageStatusEvent.objects.count()), (MessageStatus.QUEUED, 0))


class MetaParsingTests(SimpleTestCase):
    def test_the_signature_is_metas_hmac_sha256_of_the_body(self):
        body = b'{"object":"whatsapp_business_account"}'
        self.assertTrue(valid_signature(body, sign(body), SECRET))
        self.assertTrue(valid_signature(body, sign(body).upper().replace('SHA256=', 'sha256='), SECRET))
        for header in ('', 'sha256=', sign(body, 'other'), sign(body + b' ')):
            self.assertFalse(valid_signature(body, header, SECRET))
        self.assertFalse(valid_signature(body, sign(body, ''), ''))

    def test_statuses_and_errors_are_read_from_the_payload(self):
        updates, skipped = status_updates(callback(
            status('wamid.A', 'delivered', T1),
            status('wamid.B', 'failed', 'not-a-time', errors=[{'code': 130429, 'title': 'Rate limit hit'}]),
            status('wamid.C', 'failed', T2),
        ))
        self.assertEqual(skipped, 0)
        delivered, rate_limited, unspecified = updates
        self.assertEqual((delivered.status, delivered.occurred_at, delivered.error_code),
                         (MessageStatus.DELIVERED, moment(T1), ''))
        self.assertEqual((rate_limited.error_code, rate_limited.error_message, rate_limited.error_temporary,
                          rate_limited.occurred_at), ('130429', 'Rate limit hit', True, None))
        self.assertEqual((unspecified.error_code, unspecified.error_temporary), ('META_FAILED', False))
        self.assertNotEqual(delivered.event_key, status_updates(callback(status('wamid.A', 'delivered', T2)))[0][0].event_key)

    def test_temporary_and_permanent_errors(self):
        for code in ('131000', '130429', '131049', 131056):
            self.assertTrue(is_temporary_error(code), code)
        for code in ('131026', '131047', '132000', '133010', ''):
            self.assertFalse(is_temporary_error(code), code)

    def test_the_cloud_api_cannot_be_chosen_to_send_yet(self):
        self.assertNotIn('meta', PROVIDERS)
        with self.assertRaises(ProviderNotConfigured):
            MetaCloudProvider().send(None, timeout=10)
