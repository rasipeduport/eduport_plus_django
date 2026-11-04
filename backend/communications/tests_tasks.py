"""
The scheduled jobs (communications.tasks, Phase 2B step 4): the dispatcher
hands due messages to the sender -- which still makes every check -- and
checks Waiting ones again; recovery takes back stuck sends; the expiry sweep
closes what can no longer be done, never an unknown outcome. One run of each
at a time, one message's trouble never stops a run, and beat schedules each
once. Nothing reaches WhatsApp: the provider is the test-only fake.
"""
import threading
import time as clock
from datetime import timedelta
from types import SimpleNamespace
from unittest import mock, skipUnless

from django.conf import settings
from django.db import connection
from django.test import SimpleTestCase, TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from accounts.models import User
from bookings.booking_service import create_booking, record_parent_confirmation, reschedule_booking
from bookings.models import ParentConfirmation, RescheduleReason
from bookings.scheduling import indian_today
from bookings.tests_booking import DEMO, EVENING, MORNING, NOW, account, link, request, schedule

from . import planner, sending, status_updates, tasks
from .models import OUTCOME_UNKNOWN, Message, MessageCancelReason, MessageStatus, Step, TaskStatus
from .providers.base import SendResult
from .safety import SendBlock
from .sending import SendOutcome, _claim
from .tests_providers import FakeProvider, use_fake_provider
from .tests_sending import MINUTE, RETRYABLE, SENDING, SenderTestCase

JOBS = {
    'dispatch_messages': tasks.dispatch_messages,
    'recover_stuck_sends': tasks.recover_stuck_sends,
    'close_expired_communications': tasks.close_expired_communications,
    'reconcile_status_updates': tasks.reconcile_status_updates,
}


def soon():
    """A booking day still to come by the real clock, which the jobs run on."""
    return indian_today() + timedelta(days=2)


class DispatchTests(SenderTestCase):
    def sent_ids(self):
        return {outgoing.message_id for outgoing, _timeout in FakeProvider.outbox}

    def test_due_messages_are_sent_and_the_rest_left_alone(self):
        first, second = self.message(self.book()), self.message(self.book())
        later = self.message(self.book())
        Message.objects.filter(pk=later.pk).update(scheduled_for=NOW + timedelta(minutes=10))
        # A slot holds three bookings: these two take the morning one.
        claimed = self.message(self.book(at=MORNING))
        _claim(claimed.pk, NOW)
        unknown = self.message(self.book(at=MORNING))
        Message.objects.filter(pk=unknown.pk).update(status=MessageStatus.FAILED, failed_at=NOW,
                                                     failure_code=OUTCOME_UNKNOWN)

        summary = tasks.run_dispatch(now=NOW)
        self.assertEqual((summary['outcomes'], summary['errors'], summary['stopped_early']),
                         ({SendOutcome.QUEUED: 2}, 0, False))
        self.assertEqual(self.sent_ids(), {str(first.pk), str(second.pk)})
        self.assertEqual((self.fresh(later).status, self.fresh(claimed).claimed_at, self.fresh(unknown).status),
                         (MessageStatus.PENDING, NOW, MessageStatus.FAILED))
        # The confirmed messages were Waiting, and still are.
        self.assertEqual({m.status for m in Message.objects.filter(template__step=Step.PARENT_CONFIRMATION)},
                         {MessageStatus.WAITING})
        # A second run finds nothing more to send.
        self.assertEqual(tasks.run_dispatch(now=NOW)['outcomes'], {})
        self.assertEqual(len(FakeProvider.outbox), 2)

    def test_nothing_is_picked_up_while_sending_is_off_or_the_provider_sends_nothing(self):
        ack = self.message(self.book())
        written = ack.updated_at
        for changes, block in ((dict(COMMUNICATIONS_SENDING_ENABLED=False), SendBlock.SENDING_DISABLED),
                               (dict(COMMUNICATIONS_WHATSAPP_PROVIDER='none'), SendBlock.NO_PROVIDER)):
            with self.subTest(block=block), override_settings(**changes), \
                    mock.patch.object(sending, 'send_message', side_effect=AssertionError('picked up')):
                summary = tasks.run_dispatch(now=NOW)
                self.assertEqual((summary['held_back'], summary['outcomes'], summary['errors']), (block, {}, 0))
        # Not claimed, not written, not sent.
        ack = self.fresh(ack)
        self.assertEqual((ack.status, ack.claimed_at, ack.updated_at, FakeProvider.outbox),
                         (MessageStatus.PENDING, None, written, []))
        # Switched on again, it goes.
        self.assertEqual(tasks.run_dispatch(now=NOW)['outcomes'], {SendOutcome.QUEUED: 1})

    def test_only_messages_to_allowed_numbers_are_picked_up(self):
        held_back, allowed = self.message(self.book()), self.book()
        with override_settings(COMMUNICATIONS_ALLOW_ALL_RECIPIENTS=False,
                               COMMUNICATIONS_RECIPIENT_ALLOWLIST=[allowed.lead.phone_key]):
            summary = tasks.run_dispatch(now=NOW)
        # Never a BLOCKED: the message the gate would hold back is not picked up at all.
        self.assertEqual((summary['held_back'], summary['outcomes']), ('', {SendOutcome.QUEUED: 1}))
        self.assertEqual(self.sent_ids(), {str(self.message(allowed).pk)})
        self.assertEqual((self.fresh(held_back).status, self.fresh(held_back).updated_at),
                         (MessageStatus.PENDING, held_back.updated_at))

    def test_each_message_is_sent_on_the_clock_as_it_is_then(self):
        """A run reads the clock afresh for each message: its claim and a retry's time are not the run's start."""
        ack = self.message(self.book(day=soon(), now=timezone.now()))
        run_started = timezone.now() - timedelta(seconds=40)  # a run already 40 seconds in
        Message.objects.filter(pk=ack.pk).update(scheduled_for=run_started - MINUTE)
        claims = []

        def refuse_for_now(_outgoing):
            claims.append(Message.objects.get(pk=ack.pk).claimed_at)
            return RETRYABLE

        FakeProvider.reset(refuse_for_now)
        before = timezone.now()
        with mock.patch.object(tasks, 'timezone', SimpleNamespace(now=lambda: run_started)):
            self.assertEqual(tasks.run_dispatch()['outcomes'], {SendOutcome.RETRYING: 1})
        self.assertGreaterEqual(claims[0], before)
        self.assertGreaterEqual(self.fresh(ack).next_attempt_at, before + MINUTE)

    def test_trouble_checking_waiting_messages_never_stops_the_sending(self):
        self.message(self.book())
        with mock.patch.object(planner, 'refresh_waiting', side_effect=RuntimeError('database hiccup')), \
                self.assertLogs('communications.tasks', 'ERROR'):
            summary = tasks.run_dispatch(now=NOW)
        self.assertEqual((summary['errors'], summary['outcomes']), (1, {SendOutcome.QUEUED: 1}))

    def test_a_retry_is_dispatched_only_when_it_is_due(self):
        ack = self.message(self.book())
        FakeProvider.reset(RETRYABLE)
        tasks.run_dispatch(now=NOW)
        self.assertEqual(tasks.run_dispatch(now=NOW + timedelta(seconds=59))['outcomes'], {})
        self.assertEqual(tasks.run_dispatch(now=NOW + timedelta(minutes=1))['outcomes'], {SendOutcome.QUEUED: 1})
        self.assertEqual(self.fresh(ack).attempt_count, 2)

    def test_one_messages_trouble_never_stops_the_batch(self):
        first, second = self.message(self.book()), self.message(self.book())
        real_send = sending.send_message

        def flaky(message_id, now=None, triggered_by=None):
            if message_id == first.pk:
                raise RuntimeError('database hiccup')
            return real_send(message_id, now=now, triggered_by=triggered_by)

        with mock.patch.object(sending, 'send_message', flaky), self.assertLogs('communications.tasks', 'ERROR'):
            summary = tasks.run_dispatch(now=NOW)
        self.assertEqual((summary['errors'], summary['outcomes']), (1, {SendOutcome.QUEUED: 1}))
        self.assertEqual(self.sent_ids(), {str(second.pk)})

    def test_a_run_keeps_to_its_time(self):
        self.message(self.book())
        summary = tasks.run_dispatch(now=NOW, time_budget=-1)
        self.assertEqual((summary['stopped_early'], summary['outcomes'], FakeProvider.outbox), (True, {}, []))

    def test_waiting_messages_are_checked_again_for_changes_no_hook_saw(self):
        User.objects.filter(pk=self.bde.pk).update(mobile_number='')
        booking = self.ready(self.book())
        record_parent_confirmation(booking, ParentConfirmation.CONFIRMED, actor=self.bde, now=NOW)
        confirmed = self.message(booking, Step.PARENT_CONFIRMATION)
        untouched = self.message(self.book(), Step.PARENT_CONFIRMATION)  # not confirmed: keeps waiting
        self.assertEqual(confirmed.status, MessageStatus.WAITING)
        # The mobile number set the way the Django admin does: no hook runs.
        User.objects.filter(pk=self.bde.pk).update(mobile_number='+971 50 111 2222')

        summary = tasks.run_dispatch(now=NOW)
        self.assertEqual(summary['refreshed'], 1)
        self.assertEqual(self.fresh(confirmed).status, MessageStatus.QUEUED)
        self.assertIn('contact me at +971 50 111 2222.', next(
            outgoing.text for outgoing, _ in FakeProvider.outbox if outgoing.message_id == str(confirmed.pk)))
        # A message that did not change is not written.
        still = self.fresh(untouched)
        self.assertEqual((still.status, still.updated_at), (MessageStatus.WAITING, untouched.updated_at))

    def test_the_task_runs_on_the_real_clock(self):
        ack = self.message(self.book(day=soon(), now=timezone.now()))
        result = tasks.dispatch_messages()
        self.assertEqual(result['outcomes'], {SendOutcome.QUEUED: 1})
        self.assertEqual(self.fresh(ack).status, MessageStatus.QUEUED)


class RefreshWaitingTests(SenderTestCase):
    """The fallback check of Waiting messages: in short chunks, and one bad row never stops the rest."""

    def confirmed_waiting_on_the_bdes_number(self):
        """Two confirmed bookings whose confirmed messages wait only on the BDE's number -- then set behind the hooks' back."""
        User.objects.filter(pk=self.bde.pk).update(mobile_number='')
        messages = []
        for at in (MORNING, EVENING):  # the tutor teaches both, so not at the same time
            booking = self.ready(self.book(at=at))
            record_parent_confirmation(booking, ParentConfirmation.CONFIRMED, actor=self.bde, now=NOW)
            messages.append(self.message(booking, Step.PARENT_CONFIRMATION))
        User.objects.filter(pk=self.bde.pk).update(mobile_number='+971 50 111 2222')
        return messages

    def test_every_waiting_message_is_checked_one_chunk_at_a_time(self):
        messages = self.confirmed_waiting_on_the_bdes_number()
        with mock.patch.object(planner, 'REFRESH_CHUNK', 1):
            self.assertEqual(planner.refresh_waiting(NOW), 2)
        self.assertEqual({self.fresh(message).status for message in messages}, {MessageStatus.PENDING})

    def test_one_message_that_cannot_be_checked_never_stops_the_rest(self):
        bad, good = self.confirmed_waiting_on_the_bdes_number()  # the morning one comes first
        real = planner.refresh_message

        def flaky(message, booking, now, save=True):
            if message.pk == bad.pk:
                with connection.cursor() as cursor:
                    cursor.execute('SELECT 1 / 0')  # a database error, in the same chunk as the good one
            return real(message, booking, now, save=save)

        with mock.patch.object(planner, 'refresh_message', flaky), self.assertLogs('communications.planner', 'ERROR'):
            self.assertEqual(planner.refresh_waiting(NOW), 1)
        self.assertEqual((self.fresh(bad).status, self.fresh(good).status), (MessageStatus.WAITING, MessageStatus.PENDING))


class ReconcileTaskTests(TestCase):
    def test_trouble_applying_kept_statuses_never_stops_the_purge(self):
        with mock.patch.object(status_updates, 'reconcile_unmatched', side_effect=RuntimeError('database hiccup')), \
                mock.patch.object(status_updates, 'purge_unmatched', return_value=2), \
                self.assertLogs('communications.tasks', 'ERROR'):
            self.assertEqual(tasks.reconcile_status_updates(), {'applied': 0, 'purged': 2})


class RecoveryTaskTests(SenderTestCase):
    def test_stuck_sends_are_recovered_once(self):
        ack = self.message(self.book())
        _claim(ack.pk, NOW)  # its sender never came back; NOW is days ago by the real clock
        with self.assertLogs('communications.tasks', 'WARNING') as logged:
            self.assertEqual(tasks.recover_stuck_sends(), {'recovered': 1})
        self.assertIn('1 message(s) recovered as unknown', logged.output[0])
        ack = self.fresh(ack)
        self.assertEqual((ack.status, ack.failure_code, ack.claimed_at), (MessageStatus.FAILED, OUTCOME_UNKNOWN, None))
        self.assertEqual(tasks.recover_stuck_sends(), {'recovered': 0})
        self.assertEqual(ack.attempts.count(), 1)

    def test_one_messages_trouble_never_stops_recovery(self):
        first, second = self.message(self.book()), self.message(self.book())
        _claim(first.pk, NOW)
        _claim(second.pk, NOW)
        real_recover = sending._recover

        def flaky(message_id, stuck_since, now):
            if message_id == first.pk:
                raise RuntimeError('database hiccup')
            return real_recover(message_id, stuck_since, now)

        with mock.patch.object(sending, '_recover', flaky), self.assertLogs('communications.sending', 'ERROR'):
            self.assertEqual(tasks.recover_stuck_sends(), {'recovered': 1})
        self.assertEqual((self.fresh(first).claimed_at, self.fresh(second).status), (NOW, MessageStatus.FAILED))


class ExpiryTaskTests(SenderTestCase):
    """Bookings made at NOW have long started by the real clock the sweep runs on."""

    def test_what_can_no_longer_be_done_is_closed_and_unknown_outcomes_kept(self):
        retrying = self.message(self.book())
        FakeProvider.reset(RETRYABLE)
        self.assertEqual(sending.send_message(retrying.pk, now=NOW).outcome, SendOutcome.RETRYING)
        unknown = self.message(self.book())
        Message.objects.filter(pk=unknown.pk).update(status=MessageStatus.FAILED, failed_at=NOW,
                                                     failure_code=OUTCOME_UNKNOWN)
        in_flight = self.message(self.book())
        _claim(in_flight.pk, NOW)

        with self.assertLogs('communications.tasks', 'INFO'):
            result = tasks.close_expired_communications()
        self.assertGreater(result['missed'], 0)
        retrying = self.fresh(retrying)
        # A retry left Pending does not stay Pending once its window has closed.
        self.assertEqual((retrying.status, retrying.cancel_reason), (MessageStatus.CANCELLED, MessageCancelReason.EXPIRED))
        unknown, in_flight = self.fresh(unknown), self.fresh(in_flight)
        self.assertEqual((unknown.status, unknown.failure_code, unknown.cancel_reason),
                         (MessageStatus.FAILED, OUTCOME_UNKNOWN, ''))
        self.assertEqual((in_flight.status, in_flight.claimed_at), (MessageStatus.PENDING, NOW))
        self.assertEqual({m.status for m in Message.objects.filter(template__step=Step.PARENT_CONFIRMATION)},
                         {MessageStatus.CANCELLED})
        self.assertFalse(retrying.task.status == TaskStatus.OPEN)
        # Running again changes nothing.
        self.assertEqual(tasks.close_expired_communications(), {'missed': 0, 'expired': 0})

    def test_an_unknown_acknowledgement_in_a_reschedule_chain_is_kept(self):
        booking = self.book()
        ack = self.message(booking)
        Message.objects.filter(pk=ack.pk).update(status=MessageStatus.FAILED, failed_at=NOW, failure_code=OUTCOME_UNKNOWN)
        new = reschedule_booking(booking, booking.slot.local_date + timedelta(days=1), MORNING,
                                 reason_code=RescheduleReason.OTHER, actor=self.admin, now=NOW).booking
        tasks.close_expired_communications()
        self.assertEqual(self.fresh(ack).failure_code, OUTCOME_UNKNOWN)
        self.assertEqual(self.message(new).cancel_reason, MessageCancelReason.EXPIRED)


class ScheduleTests(SimpleTestCase):
    EXPECTED = {
        'dispatch-whatsapp-messages': ('communications.tasks.dispatch_messages', set(range(60))),
        'recover-stuck-whatsapp-sends': ('communications.tasks.recover_stuck_sends', set(range(0, 60, 5))),
        'close-expired-communications': ('communications.tasks.close_expired_communications', set(range(2, 60, 5))),
        'reconcile-whatsapp-statuses': ('communications.tasks.reconcile_status_updates', set(range(4, 60, 5))),
    }

    def test_each_job_is_scheduled_once_on_the_projects_timezone(self):
        schedule = settings.CELERY_BEAT_SCHEDULE
        names = [entry['task'] for entry in schedule.values()]
        self.assertEqual(len(names), len(set(names)))
        for key, (task, minutes) in self.EXPECTED.items():
            with self.subTest(key=key):
                entry = schedule[key]
                self.assertEqual(entry['task'], task)
                self.assertEqual(entry['schedule'].minute, minutes)
                self.assertEqual(entry['schedule'].hour, set(range(24)))
                # A tick no worker takes in time expires before the next one is due.
                self.assertLess(entry['options']['expires'], 60 if minutes == set(range(60)) else 300)
        self.assertEqual(settings.CELERY_TIMEZONE, settings.TIME_ZONE)

    def test_the_worker_discovers_the_tasks(self):
        from config.celery import app
        app.autodiscover_tasks(force=True)
        for name in ('communications.tasks.dispatch_messages', 'communications.tasks.recover_stuck_sends',
                     'communications.tasks.close_expired_communications', 'communications.tasks.reconcile_status_updates'):
            with self.subTest(name=name):
                self.assertIn(name, app.tasks)
        self.assertEqual({task.name for task in JOBS.values()}, {task for task, _minutes in self.EXPECTED.values()})


@skipUnless(connection.vendor == 'postgresql', 'the advisory locks need PostgreSQL')
@override_settings(**SENDING)
class OverlapTests(TransactionTestCase):
    """Real threads, each with its own database connection."""

    def setUp(self):
        schedule()
        bde = account('bde_anil', role='BDE', mobile_number='+91 98470 12345')
        token = link(bde, DEMO).token
        self.booking, _ = create_booking(request(student='Riya', phone='0507712345', ref=token, day=soon()),
                                         now=timezone.now())
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

    def test_a_job_whose_lock_another_run_holds_does_nothing(self):
        for job, task in JOBS.items():
            with self.subTest(job=job):
                holding, release = threading.Event(), threading.Event()

                def hold(job=job):
                    with tasks.single_run(job) as only_run:
                        holding.set()
                        release.wait(timeout=10)
                    return only_run

                def second_run(task=task):
                    holding.wait(timeout=10)
                    try:
                        return task()
                    finally:
                        release.set()

                self.assertEqual(self.run_threads(hold, second_run), [True, {'skipped': True}])
        # Nothing was sent while the dispatcher's lock was held; with it free, the run goes ahead.
        self.assertEqual(FakeProvider.outbox, [])
        self.assertEqual(tasks.dispatch_messages()['outcomes'], {SendOutcome.QUEUED: 1})

    def test_two_overlapping_dispatch_runs_send_each_message_once(self):
        def slow_accept(_outgoing):
            clock.sleep(0.5)
            return SendResult(accepted=True, status=MessageStatus.QUEUED, provider_message_id='wamid.once')

        FakeProvider.reset(slow_accept, slow_accept)
        barrier = threading.Barrier(2)

        def run():
            barrier.wait(timeout=10)
            return tasks.dispatch_messages()

        results = self.run_threads(run, run)
        self.assertIn({'skipped': True}, results, results)
        self.assertEqual(len(FakeProvider.outbox), 1)
        ack = self.booking.communication_messages.get(template__step=Step.ACKNOWLEDGEMENT)
        self.assertEqual((ack.status, ack.attempts.count()), (MessageStatus.QUEUED, 1))
