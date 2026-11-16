"""
Recording the parent's answer (bookings.booking_service.
record_parent_confirmation, PRD 3.11 step 3). Confirmed is recorded at once
and sends nothing by itself: the confirmed message waits -- visibly -- until
the booking also has its tutor, their Meet link and the BDE's contact, then
becomes ready to go. Not Confirmed needs a reason and the BDE's agreement that
it cancels the booking, and then cancels it with the ordinary cancellation.
A BDE answers for their own leads only; the Admin for any.
"""
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.test import APIClient

from activity.models import ActivityLog
from bookings.booking_service import (
    BookingNotOwned,
    CancellationNotConfirmed,
    CancelledNotConfirmable,
    CompletedNotConfirmable,
    InvalidConfirmation,
    InvalidReason,
    PastStartNotConfirmable,
    RescheduledNotConfirmable,
    StartedNotConfirmable,
    assign_tutor,
    cancel_booking,
    record_parent_confirmation,
    reschedule_booking,
    set_tutor_meet_link,
    unassign_tutor,
)
from bookings.models import (
    BookingEventKind,
    BookingStatus,
    CancelReason,
    DemoBooking,
    NotConfirmedReason,
    ParentConfirmation,
    RescheduleReason,
)
from bookings.scheduling import indian_today
from bookings.tests_booking import DAY, DIAGNOSTIC, EVENING, MORNING, NOW, account, start
from reports.services import submit_report
from reports.tests_services import report_input

from .models import Message, MessageCancelReason, MessageStatus, Step, TaskResolution, TaskStatus
from .rendering import Requirement, requirements
from .services import request_confirmation
from .tests_planning import BDE_PHONE, MEET_LINK, CommunicationTestCase
from .tests_templates import prd_text

CONFIRMED, NOT_CONFIRMED = ParentConfirmation.CONFIRMED, ParentConfirmation.NOT_CONFIRMED
OTHER_LINK = 'https://meet.google.com/xyz-wxyz-xyz'


class ConfirmationTestCase(CommunicationTestCase):
    def confirm(self, booking, actor=None, owner_bde=None, now=NOW):
        return record_parent_confirmation(booking, CONFIRMED, actor=actor or self.bde, owner_bde=owner_bde, now=now)

    def decline(self, booking, reason=NotConfirmedReason.NO_RESPONSE, confirm_cancellation=True, actor=None,
                owner_bde=None, now=NOW):
        return record_parent_confirmation(
            booking, NOT_CONFIRMED, reason_code=reason, confirm_cancellation=confirm_cancellation,
            actor=actor or self.bde, owner_bde=owner_bde, now=now,
        )

    def confirmed_message(self, booking):
        return booking.communication_messages.get(template__step=Step.PARENT_CONFIRMATION)

    def untouched(self, booking):
        booking.refresh_from_db()
        self.assertEqual((booking.status, booking.parent_confirmation), (BookingStatus.BOOKED, ParentConfirmation.AWAITING))
        self.assertFalse(booking.events.filter(kind__in=[
            BookingEventKind.PARENT_CONFIRMED, BookingEventKind.PARENT_NOT_CONFIRMED, BookingEventKind.CANCELLED,
        ]).exists())


class ConfirmedTests(ConfirmationTestCase):
    def test_confirmed_is_recorded_at_once_and_only_once(self):
        booking = self.book()
        booking, changed = self.confirm(booking, owner_bde=self.bde)
        self.assertTrue(changed)
        booking.refresh_from_db()
        self.assertEqual((booking.parent_confirmation, booking.parent_confirmation_by), (CONFIRMED, self.bde))
        self.assertIsNotNone(booking.parent_confirmation_at)
        self.assertEqual(booking.status, BookingStatus.BOOKED)
        event = booking.events.get(kind=BookingEventKind.PARENT_CONFIRMED)
        self.assertEqual((event.actor, event.data), (self.bde, {}))
        entry = ActivityLog.objects.get(action='booking.parent_confirmation', entity_id=str(booking.id))
        self.assertEqual((entry.context['outcome'], entry.context['reason_code']), ('CONFIRMED', None))

        self.assertFalse(self.confirm(booking)[1])
        self.assertEqual(booking.events.filter(kind=BookingEventKind.PARENT_CONFIRMED).count(), 1)

    def test_confirming_sends_nothing_while_the_tutor_and_link_are_missing(self):
        booking = self.book()
        self.confirm(booking)
        message = self.confirmed_message(booking)
        self.assertEqual((message.status, message.body), (MessageStatus.WAITING, ''))
        booking.refresh_from_db()
        self.assertEqual(
            requirements(booking, Step.PARENT_CONFIRMATION, message.template.current_version().body, NOW),
            [(Requirement.PARENT_CONFIRMED, True), (Requirement.BOOKING_ACTIVE, True),
             (Requirement.TUTOR_ASSIGNED, False), (Requirement.MEET_LINK, False), (Requirement.BDE_CONTACT, True)],
        )

    def test_with_everything_in_place_the_confirmed_message_is_ready_but_not_sent(self):
        for booking_type in ('DEMO', DIAGNOSTIC):
            with self.subTest(booking_type=booking_type):
                # The tutor teaches both, so not at the same time.
                booking = self.ready(self.book(booking_type, at=MORNING if booking_type == DIAGNOSTIC else EVENING))
                self.confirm(booking)
                message = self.confirmed_message(booking)
                prefix = booking_type.lower()
                expected = (prd_text(f'{booking_type}_CONFIRMED')
                            .replace(f'{{{{{prefix}_date}}}}', 'Wed, 28 Oct 2026')
                            .replace(f'{{{{{prefix}_time}}}}', '10:00 AM' if booking_type == DIAGNOSTIC else '7:30 PM')
                            .replace('{{tutor_name}}', 'Tutor Anu')
                            .replace('{{meeting_link}}', MEET_LINK)
                            .replace('{{bde_phone}}', BDE_PHONE)
                            .replace('{{bde_name}}', 'Bde Anil'))
                self.assertEqual((message.status, message.body), (MessageStatus.PENDING, expected))
                self.assertEqual((message.channel, message.sent_at, message.attempt_count), ('', None, 0))

    def test_a_bde_without_a_mobile_number_keeps_it_waiting(self):
        type(self.bde).objects.filter(pk=self.bde.pk).update(mobile_number='')
        booking = self.ready(self.book())
        self.confirm(booking)
        booking.refresh_from_db()
        message = self.confirmed_message(booking)
        self.assertEqual(message.status, MessageStatus.WAITING)
        checks = dict(requirements(booking, Step.PARENT_CONFIRMATION, message.template.current_version().body, NOW))
        self.assertFalse(checks[Requirement.BDE_CONTACT])

    def test_confirming_closes_the_confirmation_request_as_not_needed(self):
        asked, unasked = self.book(), self.book()
        request_confirmation(asked, actor=self.bde, now=NOW)  # written, not yet sent
        for booking in (asked, unasked):
            self.confirm(booking)
            task = booking.communication_tasks.get(step=Step.CONFIRMATION_REQUEST)
            self.assertEqual((task.status, task.resolution, task.resolved_by),
                             (TaskStatus.DONE, TaskResolution.NOT_NEEDED, self.bde))
        request = asked.communication_messages.get(template__step=Step.CONFIRMATION_REQUEST)
        self.assertEqual((request.status, request.cancel_reason), (MessageStatus.CANCELLED, MessageCancelReason.NOT_NEEDED))


class WaitingConditionTests(ConfirmationTestCase):
    """
    The confirmed message is checked again the moment anything it waits for
    changes -- the parent's answer, the tutor, the Meet link, the BDE's
    contact -- not only when the sending engine next looks.
    """

    def state(self, booking):
        """The confirmed message as stored, and its requirements worked out afresh."""
        booking = type(booking).objects.select_related('slot', 'lead__owner_bde', 'assigned_tutor').get(pk=booking.pk)
        message = self.confirmed_message(booking)
        return message, dict(requirements(booking, Step.PARENT_CONFIRMATION, message.template.current_version().body, NOW))

    @staticmethod
    def unmet(checks):
        return [requirement for requirement, met in checks.items() if not met]

    def test_a_tutor_assigned_reassigned_and_unassigned(self):
        booking = self.book()
        self.confirm(booking)
        message, checks = self.state(booking)
        self.assertEqual((message.status, self.unmet(checks)),
                         (MessageStatus.WAITING, [Requirement.TUTOR_ASSIGNED, Requirement.MEET_LINK]))

        booking = assign_tutor(booking, self.tutor, actor=self.admin, now=NOW)[0]
        message, checks = self.state(booking)
        self.assertEqual((message.status, self.unmet(checks)), (MessageStatus.PENDING, []))
        self.assertIn('Tutor: Tutor Anu', message.body)
        self.assertIn(MEET_LINK, message.body)

        booking = assign_tutor(booking, account('tutor_bala', role='TUTOR', tutor_meet_link=OTHER_LINK),
                               actor=self.admin, now=NOW)[0]
        message, _checks = self.state(booking)
        self.assertEqual(message.status, MessageStatus.PENDING)
        self.assertIn('Tutor: Tutor Bala', message.body)
        self.assertIn(OTHER_LINK, message.body)
        self.assertNotIn(MEET_LINK, message.body)

        unassign_tutor(booking, actor=self.admin, now=NOW)
        message, checks = self.state(booking)
        self.assertEqual((message.status, message.body, self.unmet(checks)),
                         (MessageStatus.WAITING, '', [Requirement.TUTOR_ASSIGNED, Requirement.MEET_LINK]))

    def test_a_meet_link_set_or_removed_after_the_tutor_was_assigned(self):
        linkless = account('tutor_chitra', role='TUTOR')
        booking = self.book()
        self.confirm(booking)
        booking = assign_tutor(booking, linkless, actor=self.admin, now=NOW)[0]
        message, checks = self.state(booking)
        self.assertEqual((message.status, self.unmet(checks)), (MessageStatus.WAITING, [Requirement.MEET_LINK]))

        set_tutor_meet_link(linkless, OTHER_LINK, actor=self.admin, now=NOW)
        message, checks = self.state(booking)
        self.assertEqual((message.status, self.unmet(checks)), (MessageStatus.PENDING, []))
        self.assertIn(OTHER_LINK, message.body)

        set_tutor_meet_link(linkless, None, actor=self.admin, now=NOW)
        message, checks = self.state(booking)
        self.assertEqual((message.status, self.unmet(checks)), (MessageStatus.WAITING, [Requirement.MEET_LINK]))

    def test_the_bdes_contact_details_changed_in_team(self):
        # Team stamps the change with the real clock, so this booking is still to come by it.
        booking = self.ready(self.book(day=indian_today() + timedelta(days=2), now=timezone.now()))
        self.confirm(booking)
        self.assertEqual(self.state(booking)[0].status, MessageStatus.PENDING)
        client = APIClient()
        client.force_authenticate(self.admin)

        res = client.patch(f'/api/team/{self.bde.id}/', {'mobile_number': ''}, format='json')
        self.assertEqual(res.status_code, 200, res.data)
        message, checks = self.state(booking)
        self.assertEqual((message.status, self.unmet(checks)), (MessageStatus.WAITING, [Requirement.BDE_CONTACT]))

        res = client.patch(f'/api/team/{self.bde.id}/', {'mobile_number': '+91 99999 11111', 'full_name': 'Anil Kumar'},
                           format='json')
        self.assertEqual(res.status_code, 200, res.data)
        message, checks = self.state(booking)
        self.assertEqual((message.status, self.unmet(checks)), (MessageStatus.PENDING, []))
        self.assertIn('contact me at +91 99999 11111.', message.body)
        self.assertTrue(message.body.endswith('**Anil Kumar**\n\n**Eduport Plus**'))
        # The acknowledgement, still unsent, signs with the new name too.
        ack = booking.communication_messages.get(template__step=Step.ACKNOWLEDGEMENT)
        self.assertIn('**Anil Kumar**', ack.body)

    def test_a_message_already_handed_over_is_never_rewritten(self):
        booking = self.ready(self.book())
        self.confirm(booking)
        sent = self.confirmed_message(booking)
        Message.objects.filter(pk=sent.pk).update(status=MessageStatus.SENT, sent_at=NOW)  # as a sender would
        assign_tutor(booking, account('tutor_bala', role='TUTOR', tutor_meet_link=OTHER_LINK), actor=self.admin, now=NOW)
        message = self.confirmed_message(booking)
        self.assertEqual((message.status, message.body), (MessageStatus.SENT, sent.body))
        self.assertIn('Tutor: Tutor Anu', message.body)


class NotConfirmedTests(ConfirmationTestCase):
    def test_a_reason_and_the_cancellation_confirmation_are_both_needed(self):
        booking = self.book()
        with self.assertRaises(InvalidReason):
            self.decline(booking, reason='')
        with self.assertRaises(InvalidReason):
            self.decline(booking, reason='Parent busy')
        with self.assertRaises(CancellationNotConfirmed):
            self.decline(booking, confirm_cancellation=False)
        self.untouched(booking)

    def test_not_confirmed_cancels_the_booking_and_its_future_communication(self):
        booking = self.book()
        ack = booking.communication_messages.get(template__step=Step.ACKNOWLEDGEMENT)
        Message.objects.filter(pk=ack.pk).update(status=MessageStatus.SENT, sent_at=NOW)  # as a sender would
        booking, changed = self.decline(booking, reason=NotConfirmedReason.TIME_NOT_SUITABLE, owner_bde=self.bde)
        self.assertTrue(changed)
        booking.refresh_from_db()
        self.assertEqual(
            (booking.status, booking.cancel_reason_code, booking.cancelled_by,
             booking.parent_confirmation, booking.not_confirmed_reason, booking.parent_confirmation_by),
            (BookingStatus.CANCELLED, CancelReason.NOT_CONFIRMED, self.bde,
             NOT_CONFIRMED, NotConfirmedReason.TIME_NOT_SUITABLE, self.bde),
        )
        events = booking.events.exclude(kind=BookingEventKind.CREATED).values_list('kind', 'data')
        self.assertCountEqual(events, [
            (BookingEventKind.PARENT_NOT_CONFIRMED, {'reason_code': 'TIME_NOT_SUITABLE'}),
            (BookingEventKind.CANCELLED, {'from_status': 'BOOKED', 'to_status': 'CANCELLED', 'reason_code': 'NOT_CONFIRMED'}),
        ])
        self.assertEqual(ActivityLog.objects.get(action='booking.cancel', entity_id=str(booking.id)).context['reason_code'],
                         'NOT_CONFIRMED')

        tasks = {task.step: task for task in booking.communication_tasks.all()}
        self.assertEqual({(t.status, t.resolution) for t in tasks.values()},
                         {(TaskStatus.CANCELLED, TaskResolution.BOOKING_CANCELLED)})
        statuses = {m.template.step: m.status for m in booking.communication_messages.select_related('template')}
        self.assertEqual(statuses, {Step.ACKNOWLEDGEMENT: MessageStatus.SENT, Step.PARENT_CONFIRMATION: MessageStatus.CANCELLED})

    def test_a_confirmed_parent_may_still_not_confirm(self):
        booking = self.book()
        self.confirm(booking)
        self.decline(booking, reason=NotConfirmedReason.PARENT_DECLINED)
        booking.refresh_from_db()
        self.assertEqual((booking.parent_confirmation, booking.status), (NOT_CONFIRMED, BookingStatus.CANCELLED))

    def test_a_normal_cancellation_cannot_use_not_confirmed(self):
        booking = self.book()
        with self.assertRaises(InvalidReason):
            cancel_booking(booking, reason_code=CancelReason.NOT_CONFIRMED, actor=self.admin)
        client = APIClient()
        client.force_authenticate(self.bde)
        res = client.post(f'/api/bde/bookings/demo/{booking.id}/cancel/', {'reason': 'NOT_CONFIRMED'}, format='json')
        self.assertEqual((res.status_code, res.data['error']), (400, 'VALIDATION_ERROR'))
        self.untouched(booking)


class WhoAndWhenTests(ConfirmationTestCase):
    def test_a_bde_answers_for_their_own_leads_only_and_the_admin_for_any(self):
        booking = self.book()
        for attempt in (lambda: self.confirm(booking, actor=self.other_bde, owner_bde=self.other_bde),
                        lambda: self.decline(booking, actor=self.other_bde, owner_bde=self.other_bde)):
            with self.assertRaises(BookingNotOwned):
                attempt()
        self.untouched(booking)
        unowned = self.book(owned=False)
        with self.assertRaises(BookingNotOwned):
            self.confirm(unowned, owner_bde=self.bde)
        self.assertTrue(self.confirm(unowned, actor=self.admin)[1])

    def test_only_while_the_booking_is_booked_and_not_started(self):
        cancelled = self.book()
        cancel_booking(cancelled, reason_code=CancelReason.PARENT_REQUEST, actor=self.admin, now=NOW)
        moved = self.book()
        reschedule_booking(moved, DAY + timedelta(days=1), MORNING, reason_code=RescheduleReason.OTHER,
                           actor=self.admin, now=NOW)
        completed = start(self.ready(self.book()))
        submit_report(completed, self.tutor, report_input(completed), now=completed.slot.starts_at + timedelta(minutes=5))
        past_start = self.book()
        # Started five minutes early (another slot: one tutor teaches both): refused before the scheduled time comes.
        started = start(self.ready(self.book(at=MORNING)), minutes=-5)
        for booking, error, now in (
            (cancelled, CancelledNotConfirmable, NOW),
            (moved, RescheduledNotConfirmable, NOW),
            (completed, CompletedNotConfirmable, NOW),
            (past_start, PastStartNotConfirmable, past_start.slot.starts_at),
            (started, StartedNotConfirmable, started.slot.starts_at - timedelta(minutes=4)),
        ):
            with self.subTest(error=error.__name__):
                with self.assertRaises(error):
                    self.confirm(booking, now=now)
                with self.assertRaises(error):
                    self.decline(booking, now=now)

    def test_only_confirmed_or_not_confirmed(self):
        with self.assertRaises(InvalidConfirmation):
            record_parent_confirmation(self.book(), ParentConfirmation.AWAITING, actor=self.bde)


class AnswerRuleTests(ConfirmationTestCase):
    """The database keeps the answer and the cancellation together, whatever writes them."""

    def write(self, booking, **fields):
        with self.assertRaises(IntegrityError), transaction.atomic():
            DemoBooking.objects.filter(pk=booking.pk).update(**fields)

    def test_the_answer_rules(self):
        booking = self.book()
        stamp = timezone.now()
        # Not Confirmed on a booking still booked; the reason without the answer; an answer without its moment.
        self.write(booking, parent_confirmation=NOT_CONFIRMED, parent_confirmation_at=stamp,
                   not_confirmed_reason=NotConfirmedReason.OTHER)
        self.write(booking, not_confirmed_reason=NotConfirmedReason.OTHER)
        self.write(booking, parent_confirmation=CONFIRMED)
        # A cancellation for "Parent did not confirm" without that answer.
        self.write(booking, status=BookingStatus.CANCELLED, cancelled_at=stamp, cancel_reason_code=CancelReason.NOT_CONFIRMED)
        self.untouched(booking)
