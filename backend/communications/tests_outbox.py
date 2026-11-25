"""
The communication outbox (communications.outbox): business writes record an
event and never run the planner, so a planner that fails -- or Celery that is
not running -- can never undo a booking, an answer, a cancellation, a move, a
tutor or Meet link change, a report, or a lead or staff correction. The
events wait in their table, are applied in order per booking, retried with a
backoff, taken back when their processor stops, claimed by one processor at
a time, applied once however often they are delivered, and never make the
sender write to a parent about a booking that has since changed.
"""
import threading
import time
from contextlib import ExitStack, contextmanager
from datetime import timedelta
from unittest import mock, skipUnless

from django.conf import settings
from django.db import OperationalError, connection, transaction
from django.test import TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from bookings.scheduling import indian_today
from bookings.tests_demo_invites import DemoInviteTestCase

from bookings import lead_admin, student_timezones
from bookings.booking_service import (
    _locked_booking,
    assign_tutor,
    cancel_booking,
    create_booking,
    record_parent_confirmation,
    reschedule_booking,
    set_tutor_meet_link,
    unassign_tutor,
)
from bookings.models import (
    BookingStatus,
    CancelReason,
    DemoBooking,
    DiagnosticBooking,
    Lead,
    NotConfirmedReason,
    ParentConfirmation,
    RescheduleReason,
)
from bookings.ownership import assign_owner
from bookings.tests_booking import DAY, DEMO, DIAGNOSTIC, EVENING, MORNING, NOW, account, link, request, schedule, start
from reports.services import submit_report
from reports.tests_services import report_input
from sales.account_models import StudentAccount
from sales.student_accounts import correct_identity, next_reference

from . import outbox, tasks
from .event_handlers import apply_event
from .models import (
    CommunicationEvent,
    CommunicationTask,
    EventKind,
    EventStatus,
    Message,
    MessageCancelReason,
    MessageStatus,
    Step,
    TaskResolution,
    TaskStatus,
)
from .providers.base import SendResult
from .sending import SendOutcome, send_message
from .overview import booking_communication
from .services import (
    CommunicationPlanFailed,
    CommunicationPlanPending,
    request_confirmation,
)
from .tests_planning import CommunicationTestCase
from .tests_providers import FakeProvider, use_fake_provider
from .tests_sending import SENDING, SENT

NEW_LINK = 'https://meet.google.com/kln-opqr-stu'
# Every planner operation a business change used to call in its own transaction.
PLANNER_OPERATIONS = (
    'plan_booking', 'parent_confirmed', 'booking_cancelled', 'booking_rescheduled', 'refresh_messages',
    'booking_completed', 'lead_owner_changed', 'lead_timezone_changed', 'lead_details_changed',
    'sender_contact_changed',
)


@contextmanager
def planner_down():
    """Every planner operation raises; yields the mocks, to see whether any was called."""
    with ExitStack() as stack:
        mocks = {
            name: stack.enter_context(
                mock.patch(f'communications.planner.{name}', side_effect=RuntimeError('planner down')),
            )
            for name in PLANNER_OPERATIONS
        }
        yield mocks


def events_of(subject_id):
    return CommunicationEvent.objects.filter(subject_id=subject_id).order_by('pk')


def due_now():
    """Move every waiting retry to now, as if its delay had passed."""
    CommunicationEvent.objects.filter(status=EventStatus.PENDING).update(available_at=timezone.now())


@override_settings(COMMUNICATIONS_OUTBOX_INLINE=False)  # the real path; CommunicationTestCase applies events inline
class OutboxTestCase(CommunicationTestCase):
    def drain(self):
        return outbox.run()

    def assert_planner_not_called(self, mocks):
        if getattr(settings, 'COMMUNICATIONS_OUTBOX_INLINE', False):
            return  # inline (tests only), the planner runs in a savepoint of the business write
        called = [name for name, fake in mocks.items() if fake.called]
        self.assertEqual(called, [], 'a business write ran the planner')

    def assert_waiting(self, subject_id, kind):
        """An event of ``kind`` for ``subject_id`` is stored, still to be applied (or to be retried)."""
        event = events_of(subject_id).filter(kind=kind).last()
        self.assertIsNotNone(event, f'no {kind} event')
        self.assertEqual(event.status, EventStatus.PENDING)
        return event

    def planned(self, booking_type=DEMO, **slot):
        booking = self.book(booking_type, **slot)
        self.drain()
        return type(booking).objects.select_related('slot', 'lead').get(pk=booking.pk)


class BusinessSurvivesPlannerFailureTests(OutboxTestCase):
    """Scenarios 1-8: the planner raising on every operation never undoes the business change."""

    def test_1_a_booking_is_made(self):
        for booking_type, model in ((DEMO, DemoBooking), (DIAGNOSTIC, DiagnosticBooking)):
            with self.subTest(booking_type=booking_type), planner_down() as mocks:
                booking = self.book(booking_type)
                self.assert_planner_not_called(mocks)
                self.assertEqual(model.objects.get(pk=booking.pk).status, BookingStatus.BOOKED)
                self.assert_waiting(booking.pk, EventKind.BOOKING_CREATED)

    def test_2_the_parent_answer_is_saved(self):
        booking = self.planned()
        with planner_down() as mocks:
            record_parent_confirmation(booking, ParentConfirmation.CONFIRMED, actor=self.bde, now=NOW)
        self.assert_planner_not_called(mocks)
        booking.refresh_from_db()
        self.assertEqual((booking.parent_confirmation, booking.parent_confirmation_by), (ParentConfirmation.CONFIRMED, self.bde))
        self.assert_waiting(booking.pk, EventKind.PARENT_CONFIRMED)

    def test_3_a_cancellation_stands(self):
        cancelled, refused = self.planned(), self.planned()
        with planner_down() as mocks:
            cancel_booking(cancelled, reason_code=CancelReason.PARENT_REQUEST, actor=self.admin, now=NOW)
            record_parent_confirmation(refused, ParentConfirmation.NOT_CONFIRMED, reason_code=NotConfirmedReason.NO_RESPONSE,
                                       confirm_cancellation=True, actor=self.bde, now=NOW)
        self.assert_planner_not_called(mocks)
        for booking in (cancelled, refused):
            booking.refresh_from_db()
            self.assertEqual(booking.status, BookingStatus.CANCELLED)
            self.assert_waiting(booking.pk, EventKind.BOOKING_CANCELLED)

    def test_4_a_reschedule_stands(self):
        old = self.planned()
        with planner_down() as mocks:
            new = reschedule_booking(old, DAY + timedelta(days=1), MORNING, reason_code=RescheduleReason.PARENT_REQUEST,
                                     actor=self.admin, now=NOW).booking
        self.assert_planner_not_called(mocks)
        old.refresh_from_db()
        self.assertEqual((old.status, DemoBooking.objects.get(pk=new.pk).status), (BookingStatus.RESCHEDULED, BookingStatus.BOOKED))
        event = self.assert_waiting(old.pk, EventKind.BOOKING_RESCHEDULED)
        self.assertEqual(event.payload, {'new_booking_id': str(new.pk)})
        self.assertEqual(sorted(event.streams), sorted([outbox.booking_stream(old), outbox.booking_stream(new),
                                                        outbox.stream_of('LEAD', old.lead_id)]))

    def test_5_a_tutor_assignment_stands(self):
        booking = self.planned()
        with planner_down() as mocks:
            assign_tutor(booking, self.tutor, actor=self.admin, now=NOW)
        booking.refresh_from_db()
        self.assertEqual(booking.assigned_tutor, self.tutor)
        with planner_down() as more:
            unassign_tutor(booking, actor=self.admin, now=NOW)
        booking.refresh_from_db()
        self.assertIsNone(booking.assigned_tutor)
        self.assert_planner_not_called({**mocks, **{f'{name}_2': fake for name, fake in more.items()}})
        self.assertEqual(list(events_of(booking.pk).filter(kind=EventKind.TUTOR_CHANGED).values_list('status', flat=True)),
                         [EventStatus.PENDING, EventStatus.PENDING])

    def test_6_a_meet_link_change_stands(self):
        booking = self.ready(self.planned())
        self.drain()
        with planner_down() as mocks:
            _tutor, changed, bookings = set_tutor_meet_link(self.tutor, NEW_LINK, actor=self.admin, now=NOW)
        self.assert_planner_not_called(mocks)
        self.assertTrue(changed)
        booking.refresh_from_db()
        self.tutor.refresh_from_db()
        self.assertEqual((self.tutor.tutor_meet_link, booking.tutor_meet_link), (NEW_LINK, NEW_LINK))
        self.assert_waiting(booking.pk, EventKind.MEET_LINK_CHANGED)

    def test_7_a_report_is_saved_and_the_booking_completed(self):
        for booking_type, at in ((DEMO, EVENING), (DIAGNOSTIC, MORNING)):  # one tutor: two different times
            with self.subTest(booking_type=booking_type):
                booking = start(self.ready(self.planned(booking_type, at=at)))
                self.drain()
                with planner_down() as mocks:
                    report = submit_report(booking, self.tutor, report_input(booking),
                                           now=booking.slot.starts_at + timedelta(minutes=50))
                self.assert_planner_not_called(mocks)
                booking.refresh_from_db()
                self.assertEqual((booking.status, booking.completed_by), (BookingStatus.COMPLETED, self.tutor))
                self.assertEqual(booking.report.pk, report.pk)
                self.assert_waiting(booking.pk, EventKind.BOOKING_COMPLETED)

    def test_8_lead_and_staff_corrections_stand(self):
        booking = self.planned()
        lead_id = booking.lead_id
        with planner_down() as mocks:
            assign_owner(lead_id, self.other_bde.pk, actor=self.admin, via='test', now=NOW)
            student_timezones.correct(lead_id, 'Asia/Dubai', actor=self.admin, via='test')
            lead_admin.update_lead_details(self.admin, lead_id, {'parent_name': 'Corrected Parent'})
            student = StudentAccount.objects.create(reference=next_reference(), origin_lead_id=lead_id,
                                                    student_name=booking.lead.student_name)
            correct_identity(self.admin, student.pk, {'student_name': 'Corrected Child',
                                                      'reason': 'Spelling confirmed by the parent.'})
            client = APIClient()
            client.force_authenticate(self.admin)
            response = client.patch(f'/api/team/{self.bde.pk}/', {'mobile_number': '+91 90000 11111'}, format='json')
        self.assert_planner_not_called(mocks)
        self.assertEqual(response.status_code, 200, response.content)
        lead = Lead.objects.get(pk=lead_id)
        self.assertEqual(
            (lead.owner_bde_id, lead.student_timezone, lead.parent_name, lead.student_name),
            (self.other_bde.pk, 'Asia/Dubai', 'Corrected Parent', 'Corrected Child'),
        )
        self.bde.refresh_from_db()
        self.assertEqual(self.bde.mobile_number, '+91 90000 11111')
        self.assertEqual(
            list(events_of(lead_id).values_list('kind', 'status')),
            [(EventKind.LEAD_OWNER_CHANGED, EventStatus.PENDING), (EventKind.LEAD_TIMEZONE_CHANGED, EventStatus.PENDING),
             (EventKind.LEAD_DETAILS_CHANGED, EventStatus.PENDING), (EventKind.LEAD_DETAILS_CHANGED, EventStatus.PENDING)],
        )
        self.assert_waiting(self.bde.pk, EventKind.SENDER_CONTACT_CHANGED)


@override_settings(COMMUNICATIONS_OUTBOX_INLINE=True)
class InlineBusinessSurvivesPlannerFailureTests(BusinessSurvivesPlannerFailureTests):
    """The same in the tests' inline mode: the planner raising in its savepoint leaves the business write standing."""


class OutboxReliabilityTests(OutboxTestCase):
    def test_9_an_event_rolls_back_with_its_business_write(self):
        with self.assertRaises(RuntimeError), transaction.atomic():
            booking = self.book()
            self.assertTrue(events_of(booking.pk).exists())
            raise RuntimeError('the business write fails after recording its event')
        self.assertFalse(DemoBooking.objects.filter(pk=booking.pk).exists())
        self.assertFalse(CommunicationEvent.objects.exists())

    def test_10_without_celery_events_wait_and_nothing_is_lost(self):
        # A business write never talks to the broker -- not even once it commits (on_commit callbacks run here).
        with mock.patch('celery.app.task.Task.apply_async') as broker, \
                self.captureOnCommitCallbacks(execute=True):
            booking = self.book()
            record_parent_confirmation(booking, ParentConfirmation.CONFIRMED, actor=self.bde, now=NOW)
        broker.assert_not_called()
        self.assertEqual(list(events_of(booking.pk).values_list('kind', 'status')),
                         [(EventKind.BOOKING_CREATED, EventStatus.PENDING), (EventKind.PARENT_CONFIRMED, EventStatus.PENDING)])
        self.assertFalse(booking.communication_tasks.exists())

    def test_11_once_celery_is_back_the_plan_follows_as_it_would_have(self):
        booking = self.book()
        record_parent_confirmation(booking, ParentConfirmation.CONFIRMED, actor=self.bde, now=NOW)
        cancelled = self.book()
        cancel_booking(cancelled, reason_code=CancelReason.PARENT_REQUEST, actor=self.admin, now=NOW)

        summary = tasks.process_communication_events()

        self.assertEqual(summary.get(outbox.Outcome.DONE), 4)
        self.assertFalse(CommunicationEvent.objects.exclude(status=EventStatus.DONE).exists())
        request_task = self.tasks(booking)[Step.CONFIRMATION_REQUEST]
        # Applied as of the business change, with its actor: as the planner wrote it in the booking's own transaction.
        self.assertEqual((request_task.status, request_task.resolution, request_task.resolved_by, request_task.resolved_at),
                         (TaskStatus.DONE, TaskResolution.NOT_NEEDED, self.bde, NOW))
        self.assertEqual(self.tasks(booking)[Step.ACKNOWLEDGEMENT].due_at, NOW + timedelta(hours=3))
        self.assertEqual({(t.status, t.resolution, t.resolved_at) for t in self.tasks(cancelled).values()},
                         {(TaskStatus.CANCELLED, TaskResolution.BOOKING_CANCELLED, NOW)})
        self.assertEqual({(m.status, m.cancelled_at) for m in self.messages(cancelled).values()},
                         {(MessageStatus.CANCELLED, NOW)})

    def test_12_a_failed_event_is_retried_in_order_and_then_applied(self):
        booking = self.book()
        cancel_booking(booking, reason_code=CancelReason.PARENT_REQUEST, actor=self.admin, now=NOW)
        with mock.patch('communications.planner.plan_booking', side_effect=RuntimeError('planner down')):
            before = timezone.now()
            self.assertEqual(self.drain().get(outbox.Outcome.RETRYING), 1)
        created, cancelled = events_of(booking.pk)
        self.assertEqual((created.status, created.attempts), (EventStatus.PENDING, 1))
        self.assertEqual(created.last_error, 'RuntimeError: planner down')
        self.assertGreaterEqual(created.available_at, before + outbox.RETRY_DELAYS[0])
        # The cancellation waits behind it: applied first, it would leave a plan written after it open.
        self.assertEqual((cancelled.status, cancelled.attempts), (EventStatus.PENDING, 0))
        self.assertEqual(self.drain(), {})  # nothing ready before the retry's time
        booking.refresh_from_db()
        self.assertEqual(booking.status, BookingStatus.CANCELLED)

        due_now()
        self.drain()
        self.assertEqual(list(events_of(booking.pk).values_list('status', flat=True)), [EventStatus.DONE, EventStatus.DONE])
        self.assertEqual({(t.status, t.resolution) for t in self.tasks(booking).values()},
                         {(TaskStatus.CANCELLED, TaskResolution.BOOKING_CANCELLED)})

    def test_12b_an_event_that_keeps_failing_is_failed_and_no_longer_holds_its_booking(self):
        booking = self.book()
        cancel_booking(booking, reason_code=CancelReason.PARENT_REQUEST, actor=self.admin, now=NOW)
        with mock.patch('communications.planner.plan_booking', side_effect=RuntimeError('planner down')):
            for _ in range(outbox.MAX_ATTEMPTS):
                due_now()
                self.drain()
        created, cancelled = events_of(booking.pk)
        self.assertEqual((created.status, created.attempts), (EventStatus.FAILED, outbox.MAX_ATTEMPTS))
        self.assertEqual(cancelled.status, EventStatus.DONE)
        self.assertEqual(outbox.health()['counts'][EventStatus.FAILED], 1)
        # Put back, it would plan a cancelled booking after its cancellation: refused unless forced.
        self.assertEqual(outbox.requeue([created.pk]), ([], [created.pk]))
        self.assertEqual(outbox.requeue([created.pk], force=True), ([created.pk], []))
        created.refresh_from_db()
        self.assertEqual((created.status, created.attempts), (EventStatus.PENDING, 0))

    def test_13_a_claim_whose_processor_stopped_is_taken_back(self):
        booking = self.book()
        claimed = outbox.claim_next()  # ... and the worker dies before applying it
        self.assertEqual((claimed.status, claimed.attempts), (EventStatus.PROCESSING, 1))
        self.assertEqual(outbox.recover_stuck(), [])  # not yet stuck
        later = timezone.now() + outbox.STUCK_AFTER + timedelta(minutes=1)
        self.assertEqual(outbox.recover_stuck(later), [claimed.pk])
        event = CommunicationEvent.objects.get(pk=claimed.pk)
        self.assertEqual((event.status, event.attempts, event.claimed_at), (EventStatus.PENDING, 1, None))
        self.assertIn('worker lost', event.last_error)
        # The stopped processor coming back finds its claim gone and does nothing.
        self.assertEqual(outbox.apply_claimed(claimed), outbox.Outcome.SKIPPED)
        self.assertFalse(booking.communication_tasks.exists())
        outbox.run(now=later + outbox.RETRY_DELAYS[0])
        event.refresh_from_db()
        self.assertEqual((event.status, event.attempts), (EventStatus.DONE, 2))
        self.assertEqual(len(self.tasks(booking)), 5)

    def test_15_an_event_applied_twice_changes_nothing_more(self):
        booking = self.ready(self.book())
        record_parent_confirmation(booking, ParentConfirmation.CONFIRMED, actor=self.bde, now=NOW)
        booking = start(booking)
        submit_report(booking, self.tutor, report_input(booking), now=booking.slot.starts_at + timedelta(minutes=50))
        moved = self.book()
        new = reschedule_booking(moved, DAY + timedelta(days=1), MORNING, reason_code=RescheduleReason.PARENT_REQUEST,
                                 actor=self.admin, now=NOW).booking
        self.drain()

        def state():
            rows = CommunicationTask.objects.order_by('pk').values_list('pk', 'status', 'resolution', 'resolved_at')
            messages = Message.objects.order_by('pk').values_list('pk', 'template_id', 'status', 'body', 'cancel_reason')
            return list(rows), list(messages)

        before = state()
        self.assertEqual(len(before[0]), 15)
        # Delivered again, in order or not -- the booking's creation after its completion included.
        for event in CommunicationEvent.objects.order_by('-pk'):
            with transaction.atomic():
                apply_event(event)
        CommunicationEvent.objects.update(status=EventStatus.PENDING, processed_at=None)
        self.drain()
        self.assertEqual(state(), before)
        self.assertEqual(new.communication_messages.filter(template__step=Step.ACKNOWLEDGEMENT).count(), 1)
        self.assertEqual(booking.communication_messages.filter(template__step=Step.AFTER_ACTIVITY).count(), 1)

    def test_events_hold_ids_only(self):
        booking = self.book()
        record_parent_confirmation(booking, ParentConfirmation.CONFIRMED, actor=self.bde, now=NOW)
        payloads = list(CommunicationEvent.objects.values_list('payload', flat=True))
        self.assertEqual(payloads, [{}, {'actor_id': str(self.bde.pk)}])
        for value in (booking.lead.parent_name, booking.lead.student_name, booking.lead.phone_key):
            self.assertNotIn(value, str(list(CommunicationEvent.objects.values())))

    def test_a_bde_asking_too_early_is_told_it_is_being_prepared(self):
        booking = self.book()
        with self.assertRaises(CommunicationPlanPending):
            request_confirmation(booking, actor=self.bde, now=NOW)
        self.drain()
        message, created = request_confirmation(booking, actor=self.bde, now=NOW)
        self.assertTrue(created)
        self.assertEqual(message.status, MessageStatus.PENDING)

    def test_health_and_purge(self):
        booking = self.book()
        self.drain()
        self.assertEqual(outbox.health()['counts'][EventStatus.DONE], 1)
        self.assertEqual(outbox.purge_done(), 0)
        later = timezone.now() + outbox.DONE_RETENTION + timedelta(days=1)
        self.assertEqual(outbox.purge_done(later), 1)
        self.assertFalse(events_of(booking.pk).exists())
        self.assertEqual(len(self.tasks(booking)), 5)  # the plan stays: only the event is gone

    def test_the_job_is_scheduled(self):
        entry = settings.CELERY_BEAT_SCHEDULE['process-communication-events']
        self.assertEqual(entry['task'], tasks.process_communication_events.name)
        self.assertLessEqual(entry['schedule'], timedelta(seconds=15))


class ProcessingRulesTests(OutboxTestCase):
    """The review's coverage gaps: recovery through the job, PROCESSING holding a stream, the claim token, two streams."""

    def test_the_job_itself_takes_back_a_stuck_claim_and_applies_it(self):
        booking = self.book()
        outbox.claim_next()  # ... and the worker dies
        later = timezone.now() + outbox.STUCK_AFTER + timedelta(minutes=1)
        # This run takes it back (a failed attempt, due again RETRY_DELAYS[0] later); the next one applies it.
        summary = outbox.run(now=later)
        self.assertEqual((summary.get('recovered'), summary.get(outbox.Outcome.DONE)), (1, None))
        summary = outbox.run(now=later + outbox.RETRY_DELAYS[0])
        self.assertEqual(summary.get(outbox.Outcome.DONE), 1)
        self.assertEqual(len(self.tasks(booking)), 5)

    def test_an_event_being_applied_holds_back_the_later_events_of_its_booking(self):
        booking = self.book()
        first = outbox.claim_next()  # PROCESSING, not applied yet
        cancel_booking(booking, reason_code=CancelReason.PARENT_REQUEST, actor=self.admin, now=NOW)
        self.assertIsNone(outbox.claim_next(), 'the cancellation was claimed while its booking\'s creation was applying')
        self.assertEqual(outbox.apply_claimed(first), outbox.Outcome.DONE)
        second = outbox.claim_next()
        self.assertEqual(second.kind, EventKind.BOOKING_CANCELLED)

    def test_a_stale_claim_never_applies_an_event_claimed_again(self):
        booking = self.book()
        stale = outbox.claim_next()
        later = timezone.now() + outbox.STUCK_AFTER + timedelta(minutes=1)
        outbox.recover_stuck(later)
        fresh = outbox.claim_next(now=later + outbox.RETRY_DELAYS[0])
        self.assertEqual((fresh.pk, fresh.status), (stale.pk, EventStatus.PROCESSING))
        self.assertEqual(outbox.apply_claimed(stale), outbox.Outcome.SKIPPED)  # PROCESSING, but under the new claim
        self.assertFalse(booking.communication_tasks.exists())
        self.assertEqual(outbox.apply_claimed(fresh), outbox.Outcome.DONE)

    def test_a_reschedule_waits_for_the_old_booking_and_the_new_booking_waits_for_it(self):
        old = self.book()
        with mock.patch('communications.planner.plan_booking', side_effect=RuntimeError('planner down')):
            self.drain()  # the old booking's creation is now retrying
        new = reschedule_booking(old, DAY + timedelta(days=1), MORNING, reason_code=RescheduleReason.PARENT_REQUEST,
                                 actor=self.admin, now=NOW).booking
        assign_tutor(new, self.tutor, actor=self.admin, now=NOW)
        self.assertIsNone(outbox.claim_next())  # all three wait behind the retrying creation
        due_now()
        self.drain()
        kinds = list(CommunicationEvent.objects.order_by('processed_at').values_list('kind', flat=True))
        self.assertEqual(kinds, [EventKind.BOOKING_CREATED, EventKind.BOOKING_RESCHEDULED, EventKind.TUTOR_CHANGED])
        self.assertEqual({t.status for t in self.tasks(old).values()}, {TaskStatus.CANCELLED})
        self.assertEqual(len(self.tasks(new)), 5)

    def test_a_plan_and_its_leads_owner_change_are_applied_one_after_the_other(self):
        booking = self.book()
        with mock.patch('communications.planner.plan_booking', side_effect=RuntimeError('planner down')):
            self.drain()
        assign_owner(booking.lead_id, self.other_bde.pk, actor=self.admin, via='test', now=NOW)
        # The owner change shares the plan's lead stream: it waits, never runs beside it.
        self.assertIsNone(outbox.claim_next())
        due_now()
        self.drain()
        self.assertEqual({t.owner_id for t in self.tasks(booking).values() if t.status == TaskStatus.OPEN},
                         {self.other_bde.pk})

    def test_requeue_refuses_while_a_later_event_waits_and_after_the_later_one_was_purged(self):
        booking = self.book()
        with mock.patch('communications.planner.plan_booking', side_effect=RuntimeError('planner down')):
            for _ in range(outbox.MAX_ATTEMPTS):
                due_now()
                self.drain()
        created = events_of(booking.pk).get()
        self.assertEqual(created.status, EventStatus.FAILED)
        cancel_booking(booking, reason_code=CancelReason.PARENT_REQUEST, actor=self.admin, now=NOW)  # PENDING
        self.assertEqual(outbox.requeue([created.pk]), ([], [created.pk]))
        self.drain()  # the cancellation is applied (a FAILED event holds nothing back)
        far = timezone.now() + outbox.DONE_RETENTION + timedelta(days=1)
        self.assertEqual(outbox.purge_done(far), 0)  # kept: it follows a FAILED event of its booking
        self.assertEqual(outbox.requeue([created.pk]), ([], [created.pk]))


class PlanStatusTests(OutboxTestCase):
    """A booking whose plan is on its way, or whose event failed, is never described as one made before communication."""

    def test_pending_then_planned(self):
        booking = self.book()
        self.assertEqual(booking_communication(booking, NOW, self.admin)['plan_status'], outbox.PlanStatus.PENDING)
        self.drain()
        self.assertEqual(booking_communication(booking, NOW, self.admin)['plan_status'], outbox.PlanStatus.PLANNED)

    def test_failed(self):
        booking = self.book()
        with mock.patch('communications.planner.plan_booking', side_effect=RuntimeError('planner down')):
            for _ in range(outbox.MAX_ATTEMPTS):
                due_now()
                self.drain()
        data = booking_communication(booking, NOW, self.admin)
        self.assertEqual((data['planned'], data['plan_status']), (False, outbox.PlanStatus.FAILED))
        with self.assertRaises(CommunicationPlanFailed):
            request_confirmation(booking, actor=self.bde, now=NOW)

    def test_a_reschedules_failure_marks_the_new_booking_not_the_old_one(self):
        old = self.planned()
        with mock.patch('communications.planner.booking_rescheduled', side_effect=RuntimeError('planner down')):
            new = reschedule_booking(old, DAY + timedelta(days=1), MORNING,
                                     reason_code=RescheduleReason.PARENT_REQUEST, actor=self.admin, now=NOW).booking
            for _ in range(outbox.MAX_ATTEMPTS):
                due_now()
                self.drain()
        self.assertEqual(outbox.plan_status(new), outbox.PlanStatus.FAILED)
        self.assertEqual(outbox.plan_status(old), outbox.PlanStatus.PLANNED)


class CommunicationViewsTests(OutboxTestCase):
    """The communication API catches up with a booking's own events (apply_ready_for) without ever failing because of them."""

    def setUp(self):
        super().setUp()
        self.api = APIClient()
        self.api.force_authenticate(self.admin)

    def live(self):
        return self.book(day=indian_today() + timedelta(days=2), now=timezone.now())

    def post(self, booking, action, body):
        return self.api.post(f'/api/communications/bookings/demo/{booking.pk}/{action}/', body, format='json')

    def test_the_parent_answer_answers_the_plan_after_the_answer(self):
        cancelled, confirmed = self.live(), self.live()
        response = self.post(cancelled, 'parent-confirmation',
                             {'outcome': 'NOT_CONFIRMED', 'reason': 'NO_RESPONSE', 'confirm_cancellation': True})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual({task['status'] for task in response.json()['tasks']}, {TaskStatus.CANCELLED})
        response = self.post(confirmed, 'parent-confirmation', {'outcome': 'CONFIRMED'})
        self.assertEqual(response.status_code, 200, response.content)
        asked = {task['step']: task for task in response.json()['tasks']}['CONFIRMATION_REQUEST']
        self.assertEqual((asked['status'], asked['resolution']), (TaskStatus.DONE, TaskResolution.NOT_NEEDED))

    def test_asking_straight_after_booking_finds_the_plan(self):
        booking = self.live()
        response = self.post(booking, 'confirmation-request/mark-sent', {})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.json()['changed'])

    def test_a_failing_planner_never_fails_the_request(self):
        booking = self.live()
        with mock.patch('communications.planner.plan_booking', side_effect=RuntimeError('planner down')):
            response = self.post(booking, 'parent-confirmation', {'outcome': 'CONFIRMED'})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(DemoBooking.objects.get(pk=booking.pk).parent_confirmation, ParentConfirmation.CONFIRMED)
        self.assertEqual(response.json()['plan_status'], outbox.PlanStatus.PENDING)
        self.assertEqual(events_of(booking.pk).first().attempts, 1)  # left for the job's retry
        awaiting = self.live()
        with mock.patch('communications.planner.plan_booking', side_effect=RuntimeError('planner down')):
            response = self.post(awaiting, 'confirmation-request/mark-sent', {})
        self.assertEqual((response.status_code, response.json()['error']), (409, 'COMMUNICATION_PLAN_PENDING'))



class RecordedInsideTheBusinessTransactionTests(OutboxTestCase):
    """
    Every recording site writes its event inside the business write's own transaction: a failure right
    after recording undoes both. Recorded after the commit instead, the business change would stand.
    """

    def boom_after(self, recorder):
        real = getattr(outbox, recorder)

        def record_then_fail(*args, **kwargs):
            real(*args, **kwargs)
            raise RuntimeError('after the event')
        return mock.patch(f'communications.outbox.{recorder}', side_effect=record_then_fail)

    def assert_undone(self, recorder, write, check):
        before = CommunicationEvent.objects.count()
        with self.subTest(recorder=recorder), self.boom_after(recorder):
            with self.assertRaises(RuntimeError):
                write()
            self.assertEqual(CommunicationEvent.objects.count(), before)
            check()

    def test_every_recording_site(self):
        booking = self.ready(self.planned())
        lead_id = booking.lead_id
        fresh = lambda: DemoBooking.objects.get(pk=booking.pk)  # noqa: E731
        lead = lambda: Lead.objects.get(pk=lead_id)  # noqa: E731
        children = DemoBooking.objects.count()

        self.assert_undone('booking_created', lambda: self.book(), lambda: self.assertEqual(DemoBooking.objects.count(), children))
        self.assert_undone(
            'parent_confirmed',
            lambda: record_parent_confirmation(booking, ParentConfirmation.CONFIRMED, actor=self.bde, now=NOW),
            lambda: self.assertEqual(fresh().parent_confirmation, ParentConfirmation.AWAITING))
        self.assert_undone(
            'booking_cancelled',
            lambda: cancel_booking(booking, reason_code=CancelReason.PARENT_REQUEST, actor=self.admin, now=NOW),
            lambda: self.assertEqual(fresh().status, BookingStatus.BOOKED))
        self.assert_undone(
            'booking_rescheduled',
            lambda: reschedule_booking(booking, DAY + timedelta(days=1), MORNING,
                                       reason_code=RescheduleReason.PARENT_REQUEST, actor=self.admin, now=NOW),
            lambda: self.assertEqual(fresh().status, BookingStatus.BOOKED))
        self.assert_undone('tutor_changed', lambda: unassign_tutor(booking, actor=self.admin, now=NOW),
                           lambda: self.assertEqual(fresh().assigned_tutor, self.tutor))
        self.assert_undone('meet_link_changed',
                           lambda: set_tutor_meet_link(self.tutor, NEW_LINK, actor=self.admin, now=NOW),
                           lambda: self.assertNotEqual(fresh().tutor_meet_link, NEW_LINK))
        started = start(booking)
        self.assert_undone(
            'booking_completed',
            lambda: submit_report(started, self.tutor, report_input(started),
                                  now=started.slot.starts_at + timedelta(minutes=50)),
            lambda: self.assertEqual(fresh().status, BookingStatus.BOOKED))
        self.assert_undone('lead_owner_changed',
                           lambda: assign_owner(lead_id, self.other_bde.pk, actor=self.admin, via='test', now=NOW),
                           lambda: self.assertEqual(lead().owner_bde_id, self.bde.pk))
        self.assert_undone('lead_timezone_changed',
                           lambda: student_timezones.correct(lead_id, 'Asia/Dubai', actor=self.admin, via='test'),
                           lambda: self.assertEqual(lead().student_timezone, ''))
        self.assert_undone('lead_details_changed',
                           lambda: lead_admin.update_lead_details(self.admin, lead_id, {'parent_name': 'Changed'}),
                           lambda: self.assertNotEqual(lead().parent_name, 'Changed'))
        account = StudentAccount.objects.create(reference=next_reference(), origin_lead_id=lead_id,
                                                student_name=lead().student_name)
        self.assert_undone(
            'lead_details_changed',
            lambda: correct_identity(self.admin, account.pk, {'student_name': 'Renamed Child',
                                                             'reason': 'Spelling confirmed by the parent.'}),
            lambda: self.assertNotEqual(lead().student_name, 'Renamed Child'))
        client = APIClient()
        client.force_authenticate(self.admin)
        self.assert_undone(
            'sender_contact_changed',
            lambda: client.patch(f'/api/team/{self.bde.pk}/', {'mobile_number': '+91 90000 22222'}, format='json'),
            lambda: self.assertNotEqual(type(self.bde).objects.get(pk=self.bde.pk).mobile_number, '+91 90000 22222'))


@override_settings(COMMUNICATIONS_OUTBOX_INLINE=False)
class InvitedDemoTests(DemoInviteTestCase):
    """Scenario 1 for the other way a Demo is booked: the Diagnostic's invitation."""

    def test_an_invited_demo_is_booked_whatever_the_planner_does(self):
        invite, _ = self.invite()
        with planner_down() as mocks:
            booking, created = self.book(invite)
        self.assertTrue(created)
        self.assertEqual([name for name, fake in mocks.items() if fake.called], [])
        self.assertEqual(DemoBooking.objects.get(pk=booking.pk).status, BookingStatus.BOOKED)
        event = CommunicationEvent.objects.get(subject_id=booking.pk)
        self.assertEqual((event.kind, event.status), (EventKind.BOOKING_CREATED, EventStatus.PENDING))
        self.assertIn(outbox.stream_of('LEAD', booking.lead_id), event.streams)


class SessionNeverWaitsForCommunicationTests(OutboxTestCase):
    """
    The Communication tab only tracks. Whatever state communication is in -- no records at all (no worker), failed
    acknowledgement and confirmation messages, missed reminder tasks, a plan whose event failed, an after-activity
    message the provider refused -- a tutor is offered Start from exactly five minutes before the slot, starts,
    submits the report and completes the booking through the tutor API, Demo and Diagnostic alike. What the BDE
    decides (Not Confirmed) still cancels, as before.
    """
    SLOTS = ((DEMO, EVENING), (DIAGNOSTIC, MORNING))  # one tutor: two different times

    def setUp(self):
        super().setUp()
        self.tutor_api = APIClient()
        self.tutor_api.force_authenticate(self.tutor)
        self.staff_api = APIClient()
        self.staff_api.force_authenticate(self.admin)

    @staticmethod
    def at(moment):
        return mock.patch('django.utils.timezone.now', return_value=moment)

    @staticmethod
    def url(booking, suffix=''):
        return f'/api/tutor/bookings/{booking.booking_type.lower()}/{booking.pk}/{suffix}'

    def start_offered(self, booking, moment):
        """(detail's actions.start, the list row's, the detail's start_refusal code) as the tutor API answers at ``moment``."""
        with self.at(moment):
            detail = self.tutor_api.get(self.url(booking)).json()
            rows = {row['id']: row for row in self.tutor_api.get('/api/tutor/bookings/', {'when': 'all'}).json()['results']}
        refusal = detail['start_refusal']
        return detail['actions']['start'], rows[str(booking.pk)]['actions']['start'], refusal and refusal['code']

    def conduct(self, booking):
        """Start offered from T-5 exactly, then Start and the report through the tutor API; the booking as saved."""
        starts = booking.slot.starts_at
        self.assertEqual(self.start_offered(booking, starts - timedelta(minutes=5, seconds=1)), (False, False, 'START_TOO_EARLY'))
        self.assertEqual(self.start_offered(booking, starts - timedelta(minutes=5)), (True, True, None))
        with self.at(starts - timedelta(minutes=4)):
            started = self.tutor_api.post(self.url(booking, 'start/'))
        self.assertEqual(started.status_code, 200, started.content)
        with self.at(starts + timedelta(minutes=50)):
            report = self.tutor_api.post(self.url(booking, 'report/'), report_input(booking), format='json')
        self.assertEqual(report.status_code, 201, report.content)
        saved = type(booking).objects.get(pk=booking.pk)
        self.assertEqual((saved.status, saved.started_by, saved.completed_by), (BookingStatus.COMPLETED, self.tutor, self.tutor))
        return saved

    def test_no_communication_records_no_worker_and_a_broken_planner(self):
        for booking_type, at in self.SLOTS:
            with self.subTest(booking_type=booking_type), planner_down() as mocks, \
                    mock.patch('celery.app.task.Task.apply_async') as broker, self.captureOnCommitCallbacks(execute=True):
                booking = self.ready(self.book(booking_type, at=at))
                self.assertFalse(booking.communication_tasks.exists() or booking.communication_messages.exists())
                completed = self.conduct(booking)
                self.assert_planner_not_called(mocks)
                broker.assert_not_called()
                self.assertFalse(completed.communication_tasks.exists())  # the plan still waits for a worker
                self.assertEqual(set(events_of(booking.pk).values_list('status', flat=True)), {EventStatus.PENDING})

    def test_failed_messages_missed_tasks_and_no_parent_answer(self):
        for booking_type, at in self.SLOTS:
            with self.subTest(booking_type=booking_type):
                booking = self.ready(self.planned(booking_type, at=at))
                self.drain()
                field = {f'{booking.booking_type.lower()}_booking': booking}
                self.assertEqual(Message.objects.filter(**field).update(
                    status=MessageStatus.FAILED, failed_at=NOW, failure_code='PROVIDER_ERROR'), 2)
                CommunicationTask.objects.filter(**field, status=TaskStatus.OPEN).exclude(step=Step.AFTER_ACTIVITY).update(
                    status=TaskStatus.MISSED, resolved_at=NOW)
                self.assertEqual(booking.parent_confirmation, ParentConfirmation.AWAITING)
                self.conduct(booking)

    @override_settings(**SENDING)
    def test_a_refused_after_activity_message_leaves_the_booking_completed(self):
        patcher = use_fake_provider()
        patcher.start()
        self.addCleanup(patcher.stop)
        for booking_type, at in self.SLOTS:
            with self.subTest(booking_type=booking_type):
                completed = self.conduct(self.ready(self.planned(booking_type, at=at)))
                self.drain()
                after = completed.communication_messages.get(template__step=Step.AFTER_ACTIVITY)
                FakeProvider.reset(SendResult(accepted=False, error_code='REJECTED', error_message='Template rejected'))
                outcome = send_message(after.pk, now=completed.completed_at + timedelta(minutes=5)).outcome
                self.assertEqual(outcome, SendOutcome.FAILED)
                saved = type(completed).objects.get(pk=completed.pk)
                self.assertEqual((saved.status, saved.completed_at), (BookingStatus.COMPLETED, completed.completed_at))
                with self.at(completed.completed_at + timedelta(minutes=10)):
                    edited = self.tutor_api.put(self.url(saved, 'report/'), {'version': 1, **report_input(saved, **(
                        {'teacher_remarks': 'Edited after the message failed.'} if booking_type == DIAGNOSTIC
                        else {'suggested_strategy': 'Edited after the message failed.'}))}, format='json')
                self.assertEqual((edited.status_code, edited.json()['booking']['status']), (200, 'COMPLETED'))

    def test_a_failed_plan_refuses_only_communication_actions(self):
        for booking_type, at in self.SLOTS:
            with self.subTest(booking_type=booking_type):
                # Still to come by the real clock, so the communication API is called as it is in production.
                booking = self.book(booking_type, at=at, day=indian_today() + timedelta(days=2), now=timezone.now())
                with mock.patch('communications.planner.plan_booking', side_effect=RuntimeError('planner down')):
                    for _ in range(outbox.MAX_ATTEMPTS):
                        due_now()
                        self.drain()
                self.assertEqual(outbox.plan_status(booking), outbox.PlanStatus.FAILED)
                path = f'/api/communications/bookings/{booking.booking_type.lower()}/{booking.pk}/'
                # Communication actions: refused, saying why.
                asked = self.staff_api.post(path + 'confirmation-request/mark-sent/', {}, format='json')
                self.assertEqual((asked.status_code, asked.json()['error']), (409, 'COMMUNICATION_PLAN_FAILED'))
                # The BDE's answer is a business decision: recorded whatever the plan's state.
                with planner_down():  # and not even waiting on the worker to say how the plan stands
                    answered = self.staff_api.post(path + 'parent-confirmation/', {'outcome': 'CONFIRMED'}, format='json')
                self.assertEqual(answered.status_code, 200, answered.content)
                self.assertEqual(answered.json()['plan_status'], outbox.PlanStatus.FAILED)
                booking = self.ready(booking)
                self.conduct(booking)

    def test_the_bdes_not_confirmed_still_cancels_and_closes_start(self):
        for booking_type, at in self.SLOTS:
            with self.subTest(booking_type=booking_type), planner_down():
                booking = self.ready(self.book(booking_type, at=at))
                record_parent_confirmation(booking, ParentConfirmation.NOT_CONFIRMED, reason_code=NotConfirmedReason.NO_RESPONSE,
                                           confirm_cancellation=True, actor=self.bde, now=NOW)
                starts = type(booking).objects.get(pk=booking.pk).slot.starts_at
                self.assertEqual(self.start_offered(booking, starts - timedelta(minutes=5)), (False, False, 'BOOKING_CANCELLED'))
                with self.at(starts - timedelta(minutes=4)):
                    refused = self.tutor_api.post(self.url(booking, 'start/'))
                self.assertEqual((refused.status_code, refused.json()['error']), (409, 'BOOKING_CANCELLED'))


@override_settings(**SENDING)
class StaleMessageTests(OutboxTestCase):
    """Scenario 16: however late the events are applied, the sender never writes about a booking that changed."""

    def setUp(self):
        super().setUp()
        FakeProvider.reset(SENT, SENT, SENT, SENT)
        patcher = use_fake_provider()
        patcher.start()
        self.addCleanup(patcher.stop)

    @staticmethod
    def message(booking, step):
        return Message.objects.get(**{f'{booking.booking_type.lower()}_booking': booking}, template__step=step)

    def test_cancelled_before_its_event_is_applied(self):
        booking = self.planned()
        ack = self.message(booking, Step.ACKNOWLEDGEMENT)
        self.assertEqual(ack.status, MessageStatus.PENDING)
        cancel_booking(booking, reason_code=CancelReason.PARENT_REQUEST, actor=self.admin, now=NOW)
        self.assertEqual(send_message(ack.pk, now=NOW).outcome, SendOutcome.CANCELLED)
        self.drain()
        ack.refresh_from_db()
        self.assertEqual((ack.status, ack.cancel_reason), (MessageStatus.CANCELLED, MessageCancelReason.BOOKING_CANCELLED))
        self.assertEqual(FakeProvider.outbox, [])

    def test_moved_before_its_event_is_applied(self):
        old = self.planned()
        ack = self.message(old, Step.ACKNOWLEDGEMENT)
        new = reschedule_booking(old, DAY + timedelta(days=1), MORNING, reason_code=RescheduleReason.PARENT_REQUEST,
                                 actor=self.admin, now=NOW).booking
        self.assertEqual(send_message(ack.pk, now=NOW).outcome, SendOutcome.CANCELLED)
        self.assertEqual(FakeProvider.outbox, [])
        self.drain()
        # The new booking's own acknowledgement goes, once, with its own slot.
        new_ack = self.message(new, Step.ACKNOWLEDGEMENT)
        self.assertEqual(send_message(new_ack.pk, now=NOW).outcome, SendOutcome.SENT)
        self.assertEqual(len(FakeProvider.outbox), 1)

    def test_answered_or_started_before_its_event_is_applied(self):
        booking = self.ready(self.planned())
        self.drain()
        ask, _ = request_confirmation(booking, actor=self.bde, now=NOW)
        record_parent_confirmation(booking, ParentConfirmation.CONFIRMED, actor=self.bde, now=NOW)
        self.assertEqual(send_message(ask.pk, now=NOW).outcome, SendOutcome.CANCELLED)
        self.drain()
        confirmed = self.message(booking, Step.PARENT_CONFIRMATION)
        self.assertEqual(confirmed.status, MessageStatus.PENDING)
        # Started early, while the message is still within its window: started is enough to hold it.
        started = start(booking, minutes=-3)
        self.assertEqual(send_message(confirmed.pk, now=started.started_at).outcome, SendOutcome.WAITING)
        self.assertEqual(FakeProvider.outbox, [])

    def test_created_and_cancelled_while_no_worker_ran(self):
        booking = self.book()
        cancel_booking(booking, reason_code=CancelReason.PARENT_REQUEST, actor=self.admin, now=NOW)
        self.drain()
        self.assertEqual({m.status for m in self.messages(booking).values()}, {MessageStatus.CANCELLED})
        tasks.run_dispatch(now=NOW)
        self.assertEqual(FakeProvider.outbox, [])


@override_settings(COMMUNICATIONS_OUTBOX_INLINE=True)
class InlineModeTests(OutboxTestCase):
    def test_the_plan_is_there_straight_after_the_business_write(self):
        booking = self.book()
        self.assertEqual(events_of(booking.pk).get().status, EventStatus.DONE)
        self.assertEqual(len(self.tasks(booking)), 5)

    def test_a_planner_failure_is_caught_and_left_for_a_retry(self):
        with mock.patch('communications.planner.plan_booking', side_effect=RuntimeError('planner down')):
            booking = self.book()
        event = events_of(booking.pk).get()
        self.assertEqual((event.status, event.attempts, event.last_error), (EventStatus.PENDING, 1, 'RuntimeError: planner down'))
        self.assertEqual(DemoBooking.objects.get(pk=booking.pk).status, BookingStatus.BOOKED)
        cancel_booking(booking, reason_code=CancelReason.PARENT_REQUEST, actor=self.admin, now=NOW)
        # Held behind the failed creation, as in the real path.
        self.assertEqual(events_of(booking.pk).last().status, EventStatus.PENDING)
        due_now()
        self.drain()
        self.assertEqual({(t.status, t.resolution) for t in self.tasks(booking).values()},
                         {(TaskStatus.CANCELLED, TaskResolution.BOOKING_CANCELLED)})


@skipUnless(connection.vendor == 'postgresql', 'the claims need PostgreSQL')
class ConcurrentProcessingTests(TransactionTestCase):
    """Scenarios 13-14 under real concurrency: several processors at once, each with its own connection."""

    def setUp(self):
        schedule()
        self.bde = account('bde_anil', role='BDE', mobile_number='+91 98470 12345')
        self.admin = account('admin_ops', role='ADMIN')
        self.token = link(self.bde, DEMO).token

    def book(self, child):
        # Two children a slot (three seats each), over two days and both times.
        day, at = DAY + timedelta(days=(child - 1) // 4), (MORNING if child % 2 else EVENING)
        booking, _ = create_booking(request(student=f'Child {child}', phone=f'05077{child:05d}', ref=self.token,
                                            day=day, at=at), now=NOW)
        return booking

    @staticmethod
    def in_thread(target, *args):
        def run():
            try:
                target(*args)
            finally:
                connection.close()
        thread = threading.Thread(target=run)
        thread.start()
        return thread

    def test_14_four_processors_never_apply_an_event_twice_and_keep_each_booking_in_order(self):
        bookings = [self.book(child) for child in range(1, 9)]
        for booking in bookings[::2]:
            record_parent_confirmation(booking, ParentConfirmation.CONFIRMED, actor=self.bde, now=NOW)
        for booking in bookings[1::4]:
            cancel_booking(booking, reason_code=CancelReason.PARENT_REQUEST, actor=self.admin, now=NOW)
        total = CommunicationEvent.objects.count()
        claimed, lock = [], threading.Lock()
        barrier = threading.Barrier(4)

        def processor():
            barrier.wait()
            while True:
                event = outbox.claim_next()
                if event is None:
                    if not CommunicationEvent.objects.exclude(status=EventStatus.DONE).exists():
                        return
                    time.sleep(0.005)  # another processor holds an earlier event of the same booking
                    continue
                with lock:
                    claimed.append(event.pk)
                outbox.apply_claimed(event)

        threads = [self.in_thread(processor) for _ in range(4)]
        for thread in threads:
            thread.join(60)
        self.assertEqual(sorted(claimed), sorted(set(claimed)), 'an event was claimed twice')
        self.assertEqual(len(claimed), total)
        self.assertFalse(CommunicationEvent.objects.exclude(status=EventStatus.DONE).exists())
        self.assertEqual(set(CommunicationEvent.objects.values_list('attempts', flat=True)), {1})
        for booking in bookings:
            with self.subTest(booking=booking.pk):
                self.assertEqual(CommunicationTask.objects.filter(demo_booking=booking).count(), 5)
                applied = list(events_of(booking.pk).values_list('processed_at', flat=True))
                self.assertEqual(applied, sorted(applied), 'a booking\'s events were applied out of order')
        for booking in bookings[1::4]:
            self.assertEqual(set(CommunicationTask.objects.filter(demo_booking=booking).values_list('status', flat=True)),
                             {TaskStatus.CANCELLED})

    def test_13b_a_claim_being_applied_is_never_taken_back(self):
        booking = self.book(1)
        entered, release = threading.Event(), threading.Event()
        released = []

        def slow(event):
            entered.set()
            released.append(release.wait(10))
            apply_event(event)  # the real one, imported before the patch

        claimed = outbox.claim_next()
        with mock.patch('communications.event_handlers.apply_event', side_effect=slow):
            outcome = []
            thread = self.in_thread(lambda: outcome.append(outbox.apply_claimed(claimed)))
            self.assertTrue(entered.wait(10))
            far = timezone.now() + outbox.STUCK_AFTER + timedelta(minutes=1)
            began = time.monotonic()
            self.assertEqual(outbox.recover_stuck(far), [])  # its row is held: skipped
            self.assertLess(time.monotonic() - began, 3, 'recover_stuck waited for the row instead of skipping it')
            release.set()
            thread.join(30)
        self.assertEqual(released, [True], 'the apply was not held while recovery ran')
        self.assertEqual(outcome, [outbox.Outcome.DONE])
        self.assertEqual(CommunicationTask.objects.filter(demo_booking=booking).count(), 5)


@skipUnless(connection.vendor == 'postgresql', 'the deferred foreign-key check needs PostgreSQL')
class CommitFailureTests(TransactionTestCase):
    """
    The communication tables' foreign keys are checked when their transaction
    COMMITs, and a booking row a business write holds FOR UPDATE makes that
    check wait -- past the lock timeout, the COMMIT fails. The whole
    transaction is rolled back (the planner's writes and the event's DONE
    with it), so the failure is recorded in a transaction of its own as any
    failed attempt is: retried after its delay, or FAILED after the last --
    never left PROCESSING for stuck-claim recovery, never DONE, and never
    half applied or applied twice.
    """

    def setUp(self):
        schedule()
        self.bde = account('bde_anil', role='BDE', mobile_number='+91 98470 12345')
        self.token = link(self.bde, DEMO).token
        self.booking = create_booking(request(student='Child 1', phone='0507700001', ref=self.token), now=NOW)[0]

    @contextmanager
    def booking_held(self):
        """The booking's slot and row locked, as a business write holds them, in a thread of its own."""
        held, release = threading.Event(), threading.Event()

        def hold():
            try:
                with transaction.atomic():
                    _locked_booking(self.booking)
                    held.set()
                    release.wait(timeout=30)
            finally:
                connection.close()

        thread = threading.Thread(target=hold)
        thread.start()
        self.assertTrue(held.wait(10))
        try:
            with mock.patch.object(outbox, 'LOCK_TIMEOUT', '300ms'):
                yield
        finally:
            release.set()
            thread.join(30)

    def event(self):
        return CommunicationEvent.objects.get()

    def written(self):
        return (CommunicationTask.objects.filter(demo_booking=self.booking).count(),
                Message.objects.filter(demo_booking=self.booking).count())

    def test_a_commit_that_waits_out_the_lock_timeout_leaves_the_event_to_be_retried(self):
        event = outbox.claim_next()
        self.assertEqual((event.kind, event.status), (EventKind.BOOKING_CREATED, EventStatus.PROCESSING))
        with self.booking_held():
            began = time.monotonic()
            outcome = outbox.apply_claimed(event)
            seconds = time.monotonic() - began
        self.assertEqual(outcome, outbox.Outcome.RETRYING)
        self.assertLess(seconds, 4)
        stored = self.event()
        self.assertEqual((stored.status, stored.attempts, stored.claimed_at, stored.processed_at),
                         (EventStatus.PENDING, 1, None, None))
        self.assertGreater(stored.available_at, timezone.now() + timedelta(seconds=30))
        self.assertIn('lock timeout', stored.last_error)
        # The planner's writes went with the transaction, and nothing is left for stuck-claim recovery.
        self.assertEqual(self.written(), (0, 0))
        self.assertEqual(outbox.recover_stuck(timezone.now() + outbox.STUCK_AFTER + timedelta(minutes=1)), [])

        # Due again, with the booking free: applied once, whole -- and a run after that finds nothing to do.
        due_now()
        self.assertEqual(outbox.run(), {'done': 1})
        self.assertEqual(self.written(), (5, 2))
        stored = self.event()
        self.assertEqual((stored.status, stored.attempts, stored.last_error), (EventStatus.DONE, 2, ''))
        due_now()
        self.assertEqual(outbox.run(), {})
        self.assertEqual(self.written(), (5, 2))

    def test_the_last_attempt_failing_at_the_commit_is_failed_not_left_processing(self):
        CommunicationEvent.objects.update(attempts=outbox.MAX_ATTEMPTS - 1)
        event = outbox.claim_next()
        self.assertEqual(event.attempts, outbox.MAX_ATTEMPTS)
        with self.booking_held():
            self.assertEqual(outbox.apply_claimed(event), outbox.Outcome.FAILED)
        stored = self.event()
        self.assertEqual((stored.status, stored.claimed_at, stored.processed_at), (EventStatus.FAILED, None, None))
        self.assertIn('lock timeout', stored.last_error)
        self.assertEqual(self.written(), (0, 0))

    def test_the_job_and_the_views_helper_count_it_as_a_retry_and_never_raise(self):
        with self.booking_held():
            self.assertEqual(outbox.run(), {'retrying': 1})
        due_now()
        with self.booking_held():
            self.assertEqual(outbox.apply_ready_for(self.booking), 0)
        stored = self.event()
        self.assertEqual((stored.status, stored.attempts), (EventStatus.PENDING, 2))
        due_now()
        self.assertEqual(outbox.apply_ready_for(self.booking), 1)
        self.assertEqual(self.written(), (5, 2))

    def test_when_recording_the_failure_fails_too_the_claim_is_left_for_recovery(self):
        event = outbox.claim_next()
        with self.booking_held(), mock.patch.object(outbox, '_failed', side_effect=OperationalError('cannot record')):
            with self.assertRaises(OperationalError):
                outbox.apply_claimed(event)
        stored = self.event()
        self.assertEqual(stored.status, EventStatus.PROCESSING)
        self.assertIsNotNone(stored.claimed_at)
        self.assertEqual(self.written(), (0, 0))
        self.assertEqual(outbox.recover_stuck(timezone.now() + outbox.STUCK_AFTER + timedelta(minutes=1)), [event.pk])
        self.assertEqual((self.event().status, self.event().attempts), (EventStatus.PENDING, 1))

    def test_an_event_that_already_committed_is_not_recorded_as_failed(self):
        """A commit whose outcome is unknown (the connection died) that had in fact succeeded: the event is DONE, left alone."""
        event = outbox.claim_next()
        self.assertEqual(outbox.apply_claimed(event), outbox.Outcome.DONE)
        self.assertEqual(outbox._record_commit_failure(event, OperationalError('connection lost')), outbox.Outcome.SKIPPED)
        stored = self.event()
        self.assertEqual((stored.status, stored.attempts, stored.last_error), (EventStatus.DONE, 1, ''))
        self.assertEqual(self.written(), (5, 2))
