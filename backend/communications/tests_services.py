"""
The BDE's communication actions (communications.services): the confirmation
request -- available from the moment the booking is made, written once
however often it is asked for -- and its preview. The 15-minute call is a
reminder only, with nothing to record (communications.tests_bde_followups,
tests_planning.CallExpiryTests). Plus the database rules the communication
tables keep whatever writes them, the call outcomes of old among them.
"""
from django.db import IntegrityError, connection, transaction
from django.test import override_settings

from bookings.booking_service import BookingNotOwned, cancel_booking, record_parent_confirmation
from bookings.models import CancelReason, ParentConfirmation
from bookings.tests_booking import NOW

from .models import (
    CallOutcome,
    Channel,
    CommunicationTask,
    Message,
    MessageAttempt,
    MessageStatus,
    MessageStatusEvent,
    MessageTemplate,
    OwnerRole,
    Step,
    TaskResolution,
    TaskStatus,
)
from .rendering import Requirement
from .services import (
    BookingNotUpcoming,
    ConfirmationNotNeeded,
    MessageBlocked,
    preview,
    request_confirmation,
)
from .tests_planning import CommunicationTestCase
from .tests_templates import prd_text


class ConfirmationRequestTests(CommunicationTestCase):
    def test_available_as_soon_as_the_booking_is_made_and_written_once(self):
        booking = self.book()
        # The moment it is made, 31 hours before the start -- long before its
        # 12-hour target: the target is a target, not a gate.
        early = NOW
        message, created = request_confirmation(booking, actor=self.bde, owner_bde=self.bde, now=early)
        self.assertTrue(created)
        self.assertEqual((message.status, message.created_by, message.scheduled_for, message.send_before),
                         (MessageStatus.PENDING, self.bde, early, booking.slot.starts_at))
        self.assertEqual(message.body, prd_text('DEMO_CONFIRMATION_REQUEST')
                         .replace('{{demo_date}}', 'Wed, 28 Oct 2026').replace('{{demo_time}}', '7:30 PM')
                         .replace('{{bde_name}}', 'Bde Anil'))
        again, created = request_confirmation(booking, actor=self.bde, now=early)
        self.assertEqual((again.pk, created), (message.pk, False))
        self.assertEqual(booking.communication_messages.filter(template__step=Step.CONFIRMATION_REQUEST).count(), 1)
        # Written, not sent; the step stays open until it is.
        self.assertEqual(booking.communication_tasks.get(step=Step.CONFIRMATION_REQUEST).status, TaskStatus.OPEN)

    def test_diagnostic_uses_its_own_template(self):
        message, _ = request_confirmation(self.book('DIAGNOSTIC'), actor=self.bde, now=NOW)
        self.assertEqual(message.template_id, 'DIAGNOSTIC_CONFIRMATION_REQUEST')
        self.assertIn('Eduport Plus Diagnostic Test is scheduled for **Wed, 28 Oct 2026 at 7:30 PM IST**', message.body)

    def test_refusals(self):
        confirmed = self.book()
        record_parent_confirmation(confirmed, ParentConfirmation.CONFIRMED, actor=self.bde, now=NOW)
        cancelled = self.book()
        cancel_booking(cancelled, reason_code=CancelReason.PARENT_REQUEST, actor=self.admin, now=NOW)
        booking = self.book()
        cases = (
            (lambda: request_confirmation(confirmed, actor=self.bde, now=NOW), ConfirmationNotNeeded),
            (lambda: request_confirmation(cancelled, actor=self.bde, now=NOW), BookingNotUpcoming),
            (lambda: request_confirmation(booking, actor=self.bde, now=booking.slot.starts_at), BookingNotUpcoming),
            (lambda: request_confirmation(booking, actor=self.other_bde, owner_bde=self.other_bde, now=NOW), BookingNotOwned),
        )
        for attempt, error in cases:
            with self.subTest(error=error.__name__), self.assertRaises(error):
                attempt()
        self.assertFalse(Message.objects.filter(template__step=Step.CONFIRMATION_REQUEST).exists())

    def test_blocked_rather_than_sent_with_a_blank_signature(self):
        with self.assertRaises(MessageBlocked) as caught:
            request_confirmation(self.book(owned=False), actor=self.admin, now=NOW)
        self.assertEqual(caught.exception.missing, [Requirement.CENTRAL_CONTACT])

    @override_settings(COMMUNICATIONS_FALLBACK_SENDER_NAME='Eduport Plus Team', COMMUNICATIONS_FALLBACK_SENDER_PHONE='+91 80000 00000')
    def test_an_unowned_leads_request_signs_with_the_central_contact(self):
        message, _ = request_confirmation(self.book(owned=False), actor=self.admin, now=NOW)
        self.assertIn('**Eduport Plus Team**', message.body)

    def test_preview_shows_the_text_and_writes_nothing(self):
        booking = self.book()
        shown = preview(booking, Step.CONFIRMATION_REQUEST, now=NOW)
        self.assertIn('**Bde Anil**', shown.body)
        self.assertEqual(shown.requirements, [(Requirement.BOOKING_ACTIVE, True), (Requirement.BDE_CONTACT, True)])
        waiting = preview(booking, Step.PARENT_CONFIRMATION, now=NOW)
        self.assertIsNone(waiting.body)
        self.assertFalse(Message.objects.filter(template__step=Step.CONFIRMATION_REQUEST).exists())


class TableRuleTests(CommunicationTestCase):
    """What the database refuses, whatever writes it."""

    def refused(self, write):
        with self.assertRaises(IntegrityError), transaction.atomic():
            write()

    def test_message_rules(self):
        booking = self.book()
        ack = booking.communication_messages.get(template__step=Step.ACKNOWLEDGEMENT)
        task = ack.task
        diagnostic_template = MessageTemplate.objects.get(key='DIAGNOSTIC_ACKNOWLEDGEMENT')
        update = Message.objects.filter(pk=ack.pk).update
        # A Demo booking's message from a Diagnostic template; a second message from one template.
        self.refused(lambda: Message.objects.create(demo_booking=booking, task=task, template=diagnostic_template,
                                                    recipient_phone='+971500000000'))
        self.refused(lambda: Message.objects.create(demo_booking=booking, task=task, template=ack.template,
                                                    recipient_phone='+971500000000'))
        # Sent by hand is Sent, by someone -- never Delivered or Read.
        self.refused(lambda: update(channel=Channel.MANUAL_WHATSAPP, status=MessageStatus.SENT, sent_at=NOW))
        self.refused(lambda: update(channel=Channel.MANUAL_WHATSAPP, status=MessageStatus.DELIVERED, sent_at=NOW,
                                    sent_by=self.bde))
        update(channel=Channel.MANUAL_WHATSAPP, status=MessageStatus.SENT, sent_at=NOW, sent_by=self.bde)
        # WhatsApp is the only channel.
        self.refused(lambda: update(channel='SMS'))
        self.refused(lambda: MessageAttempt.objects.create(
            message=ack, number=1, channel='SMS', provider='console', started_at=NOW, finished_at=NOW, outcome='FAILED',
            error_code='X'))
        # A failure says why; a cancellation says why.
        self.refused(lambda: Message.objects.filter(pk=ack.pk).update(channel='', status=MessageStatus.FAILED, failed_at=NOW))
        self.refused(lambda: Message.objects.filter(pk=ack.pk).update(channel='', status=MessageStatus.CANCELLED, cancelled_at=NOW))

    def test_task_rules(self):
        booking = self.book()
        call = booking.communication_tasks.get(step=Step.PRE_ACTIVITY_CALL)
        ack = booking.communication_tasks.get(step=Step.ACKNOWLEDGEMENT)
        self.refused(lambda: CommunicationTask.objects.filter(pk=call.pk).update(
            status=TaskStatus.DONE, resolution=TaskResolution.SENT, resolved_at=NOW))
        self.refused(lambda: CommunicationTask.objects.filter(pk=ack.pk).update(
            status=TaskStatus.DONE, resolution=TaskResolution.CALLED, resolved_at=NOW))
        # The finished reminder is the call's alone, and only ever Done.
        self.refused(lambda: CommunicationTask.objects.filter(pk=ack.pk).update(
            status=TaskStatus.DONE, resolution=TaskResolution.REMINDED, resolved_at=NOW))
        self.refused(lambda: CommunicationTask.objects.filter(pk=call.pk).update(
            status=TaskStatus.MISSED, resolution=TaskResolution.REMINDED, resolved_at=NOW))
        self.refused(lambda: CommunicationTask.objects.filter(pk=ack.pk).update(status=TaskStatus.DONE))
        self.refused(lambda: CommunicationTask.objects.filter(pk=ack.pk).update(owner_role=OwnerRole.ADMIN))
        self.refused(lambda: CommunicationTask.objects.create(demo_booking=booking, step=Step.ACKNOWLEDGEMENT,
                                                              owner_role=OwnerRole.ADMIN))

    def test_history_tables_are_append_only(self):
        booking = self.book()
        ack = booking.communication_messages.get(template__step=Step.ACKNOWLEDGEMENT)
        call = booking.communication_tasks.get(step=Step.PRE_ACTIVITY_CALL)
        rows = {
            'communication_message_attempts': MessageAttempt.objects.create(
                message=ack, number=1, channel=Channel.WHATSAPP, provider='console', started_at=NOW,
                finished_at=NOW, outcome='FAILED', error_code='TIMEOUT', retryable=True,
            ),
            'communication_message_status_events': MessageStatusEvent.objects.create(
                message=ack, provider='console', status=MessageStatus.SENT, dedupe_key='console:1:SENT',
            ),
            'communication_call_outcomes': CallOutcome.objects.create(
                task=call, outcome=TaskResolution.CALLED, recorded_by=self.bde,
            ),
        }
        for table, row in rows.items():
            for statement in (f'UPDATE {table} SET id = id WHERE id = %s', f'DELETE FROM {table} WHERE id = %s'):
                with self.subTest(statement=statement.split(' WHERE')[0]), self.assertRaisesMessage(Exception, 'append-only'):
                    with transaction.atomic(), connection.cursor() as cursor:
                        cursor.execute(statement, [row.id])
        self.refused(lambda: MessageStatusEvent.objects.create(
            message=ack, provider='console', status=MessageStatus.SENT, dedupe_key='console:1:SENT'))
