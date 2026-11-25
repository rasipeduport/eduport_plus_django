"""
The parent's confirmation from the Hub (communications.views, Phase 3.2):
seeing the confirmation request exactly as WhatsApp would show it, what it
still lacks and the number WhatsApp opens with; the BDE sending it from their
own WhatsApp and marking it as sent -- recorded once, by hand, never as
delivered -- while the retired endpoint that had the system send it answers
410; and recording their answer: Confirmed, or Not Confirmed with a reason
and the cancellation agreed to. Each within the caller's scope (every booking
for the Admin, a BDE's own leads only), refused as the services refuse it,
and by nobody else. Bookings are made on the real clock. Nothing is sent
anywhere.
"""
from datetime import timedelta

from django.contrib.auth.models import Permission
from django.test import override_settings
from django.utils import timezone

from accounts.models import RoleGroup
from activity.models import ActivityLog
from bookings.booking_service import cancel_booking, create_booking, reschedule_booking, slot_label
from bookings.models import BookingEvent, BookingStatus, CancelReason, RescheduleReason
from bookings.scheduling import indian_today
from bookings.tests_booking import DIAGNOSTIC, MORNING, account, link, request

from .models import Channel, Message, MessageStatus, Step, TaskResolution, TaskStatus
from .sending import SendOutcome, due_message_ids, send_message
from .services import request_confirmation
from .tests_api import CommunicationApiTestCase
from .tests_providers import FakeProvider, use_fake_provider
from .tests_sending import SENDING


def url(booking, action):
    return f'/api/communications/bookings/{booking.booking_type.lower()}/{booking.pk}/{action}/'


class ActionTestCase(CommunicationApiTestCase):
    def preview(self, user, booking, step='CONFIRMATION_REQUEST'):
        self.api.force_authenticate(user)
        return self.api.get(url(booking, 'preview'), {'step': step} if step is not None else {})

    def ask(self, user, booking):
        """The retired endpoint that had the system send the request."""
        self.api.force_authenticate(user)
        return self.api.post(url(booking, 'confirmation-request'), {}, format='json')

    def mark(self, user, booking):
        self.api.force_authenticate(user)
        return self.api.post(url(booking, 'confirmation-request/mark-sent'), {}, format='json')

    def marked(self, user, booking):
        """Marked as sent by ``user``: the communication it answers."""
        response = self.mark(user, booking)
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def answer(self, user, booking, **body):
        self.api.force_authenticate(user)
        return self.api.post(url(booking, 'parent-confirmation'), body, format='json')

    def assert_refused(self, response, status_code, code):
        self.assertEqual(response.status_code, status_code, response.content)
        self.assertEqual(response.json()['error'], code, response.content)

    @staticmethod
    def revoke(role, codename):
        RoleGroup.objects.get(role=role).group.permissions.remove(Permission.objects.get(codename=codename))

    @staticmethod
    def requests_for(booking):
        return Message.objects.filter(**{f'{booking.booking_type.lower()}_booking': booking},
                                      template__step=Step.CONFIRMATION_REQUEST)

    def others_booking(self):
        """A booking of another BDE's lead."""
        booking, _ = create_booking(request(student='Meera', phone='0507799999', ref=link(self.other_bde).token,
                                            day=indian_today() + timedelta(days=3)), now=timezone.now())
        return booking


class PreviewTests(ActionTestCase):
    def test_the_request_exactly_as_whatsapp_would_show_it(self):
        booking = self.live()
        for user in (self.admin, self.bde):
            with self.subTest(user=user.username):
                response = self.preview(user, booking)
                self.assertEqual(response.status_code, 200, response.content)
                data = response.json()
                self.assertEqual((data['step'], data['step_label'], data['ready']),
                                 ('CONFIRMATION_REQUEST', 'Confirmation request', True))
                # WhatsApp's own bold, never the template's markers.
                self.assertIn('*Bde Anil*', data['text'])
                self.assertNotIn('**', data['text'])
                self.assertEqual(data['requirements'], [
                    {'code': 'BOOKING_ACTIVE', 'label': 'Booking still upcoming and not started', 'met': True},
                    {'code': 'BDE_CONTACT', 'label': "BDE's name and mobile number", 'met': True},
                ])
        # Seeing it writes nothing.
        self.assertFalse(self.requests_for(booking).exists())

    def test_what_whatsapp_opens_with_and_whose_name_signs_it(self):
        for booking_type in ('DEMO', DIAGNOSTIC):
            booking = self.live(booking_type=booking_type)
            with self.subTest(booking_type=booking_type):
                mine = self.preview(self.bde, booking).json()
                # The parent's number as WhatsApp addresses it: the country code and number, digits only.
                self.assertEqual(mine['whatsapp_number'], booking.lead.phone_key.lstrip('+'))
                self.assertTrue(mine['whatsapp_number'].isdigit())
                self.assertEqual((mine['signed_by'], mine['signed_by_caller']),
                                 ({'id': str(self.bde.pk), 'full_name': 'Bde Anil'}, True))
                # The Admin sends it from their own WhatsApp, under the BDE's name: the Hub warns them.
                admins = self.preview(self.admin, booking).json()
                self.assertEqual((admins['text'], admins['signed_by']['id'], admins['signed_by_caller']),
                                 (mine['text'], str(self.bde.pk), False))
                # Line breaks and WhatsApp's bold reach WhatsApp as written (the Hub encodes them into the link).
                self.assertIn('\n\n', mine['text'])
                self.assertIn('*Bde Anil*', mine['text'])
        # A lead nobody owns: no BDE's name to sign with.
        data = self.preview(self.admin, self.live(owned=False, at=MORNING)).json()
        self.assertEqual((data['signed_by'], data['signed_by_caller']), (None, False))

    def test_a_number_whatsapp_cannot_open_is_null(self):
        booking = self.live()
        type(booking.lead).objects.filter(pk=booking.lead_id).update(phone_key='+0507799990')
        data = self.preview(self.bde, booking).json()
        # The message is still shown, to copy; there is just no chat to open.
        self.assertEqual((data['ready'], data['whatsapp_number']), (True, None))

    def test_what_is_missing_is_named_and_no_text_shown(self):
        # A lead nobody owns signs with the central contact, which is not set here.
        booking = self.live(owned=False)
        data = self.preview(self.admin, booking).json()
        self.assertEqual((data['ready'], data['text']), (False, None))
        self.assertIn({'code': 'CENTRAL_CONTACT', 'label': 'Central contact (this lead has no BDE)', 'met': False},
                      data['requirements'])
        # Any message step: the confirmed message also waits for the answer, the tutor and the Meet link.
        data = self.preview(self.admin, booking, step='parent_confirmation').json()
        self.assertEqual([item['code'] for item in data['requirements'] if not item['met']],
                         ['PARENT_CONFIRMED', 'TUTOR_ASSIGNED', 'MEET_LINK', 'CENTRAL_CONTACT'])

    def test_a_step_that_sends_nothing_is_refused(self):
        booking = self.live()
        for step in ('PRE_ACTIVITY_CALL', 'TELEGRAM', '', None):
            with self.subTest(step=step):
                self.assert_refused(self.preview(self.admin, booking, step=step), 400, 'INVALID_INPUT')


class RetiredRequestTests(ActionTestCase):
    def test_the_system_is_never_asked_to_send_the_request_any_more(self):
        booking = self.live()
        for user in (self.admin, self.bde):
            with self.subTest(user=user.username):
                self.assert_refused(self.ask(user, booking), 410, 'CONFIRMATION_REQUESTS_RETIRED')
        # Nothing written, nothing logged, and the request is still the BDE's to send.
        self.assertFalse(self.requests_for(booking).exists())
        self.assertFalse(ActivityLog.objects.filter(action='booking.confirmation_request').exists())
        self.assertTrue(self.ok(self.bde, booking)['actions']['mark_request_sent'])
        # Whoever may not ask is answered as before.
        self.assertEqual(self.ask(self.tutor, booking).status_code, 403)


class MarkSentTests(ActionTestCase):
    def test_marked_as_sent_by_hand_once_for_a_demo_and_a_diagnostic(self):
        for booking_type in ('DEMO', DIAGNOSTIC):
            booking = self.live(booking_type=booking_type)
            with self.subTest(booking_type=booking_type):
                shown = self.preview(self.bde, booking).json()['text']
                before = timezone.now()
                data = self.marked(self.bde, booking)
                self.assertTrue(data['changed'])
                sent = self.by_step(data['messages'])['CONFIRMATION_REQUEST']
                # Sent by hand, by the BDE, now -- the text they were shown -- and nothing WhatsApp reports.
                self.assertEqual(
                    (sent['status'], sent['channel'], sent['channel_label'], sent['provider'], sent['text']),
                    ('SENT', 'MANUAL_WHATSAPP', 'WhatsApp (sent manually)', '', shown),
                )
                self.assertEqual((sent['sent_by']['id'], sent['created_by']['id']), (str(self.bde.pk), str(self.bde.pk)))
                self.assertGreaterEqual(sent['sent_at'], before.isoformat())
                self.assertEqual((sent['queued_at'], sent['delivered_at'], sent['read_at'], sent['attempts'], sent['events']),
                                 (None, None, None, [], []))
                step = self.by_step(data['tasks'])['CONFIRMATION_REQUEST']
                self.assertEqual((step['status'], step['resolution'], step['resolution_label'], step['resolved_by']['id']),
                                 ('DONE', 'MARKED_SENT', 'Sent manually', str(self.bde.pk)))
                # The parent has not answered: that is still the BDE's to record, and WhatsApp may still be opened.
                self.assertEqual((data['parent_confirmation']['status'], data['booking']['status']), ('AWAITING', 'BOOKED'))
                self.assertEqual(data['actions'],
                                 {'open_whatsapp': True, 'mark_request_sent': False, 'record_confirmation': True})
                # Marked again -- by the Admin this time -- nothing changes, and no second row.
                again = self.marked(self.admin, booking)
                self.assertFalse(again['changed'])
                message = self.requests_for(booking).get()
                self.assertEqual((message.sent_by, message.status), (self.bde, MessageStatus.SENT))

    def test_logged_once_by_ids(self):
        booking = self.live()
        self.marked(self.bde, booking)
        self.marked(self.bde, booking)
        # Opening WhatsApp is the preview: it writes and logs nothing.
        self.preview(self.bde, booking)
        entry = ActivityLog.objects.get(action='booking.confirmation_request_sent_manually')
        self.assertEqual((entry.actor, entry.entity_type, entry.entity_id, entry.entity_label),
                         (self.bde, 'booking', str(booking.pk), slot_label(booking.slot)))
        self.assertEqual(entry.context, {'booking_type': 'DEMO', 'lead_id': str(booking.lead_id),
                                         'message_id': str(self.requests_for(booking).get().pk),
                                         'channel': 'MANUAL_WHATSAPP'})

    def test_a_request_the_system_was_asked_to_send_becomes_the_record_and_is_never_sent(self):
        booking = self.live()
        asked, _created = request_confirmation(booking, actor=self.admin, now=timezone.now())
        self.assertEqual(asked.status, MessageStatus.PENDING)
        data = self.marked(self.bde, booking)
        message = self.requests_for(booking).get()
        # The same row, now the BDE's send by hand; who asked first is kept.
        self.assertEqual((message.pk, message.status, message.channel, message.sent_by, message.created_by),
                         (asked.pk, MessageStatus.SENT, Channel.MANUAL_WHATSAPP, self.bde, self.admin))
        self.assertEqual(self.by_step(data['tasks'])['CONFIRMATION_REQUEST']['resolution'], 'MARKED_SENT')
        # The sending engine never picks it up again.
        FakeProvider.reset()
        with use_fake_provider(), override_settings(**SENDING):
            self.assertNotIn(message.pk, due_message_ids())
            self.assertEqual(send_message(message.pk).outcome, SendOutcome.NOT_PENDING)
        self.assertEqual(FakeProvider.outbox, [])
        self.assertFalse(message.attempts.exists())

    def test_a_refused_send_may_be_marked_but_never_one_a_provider_may_have(self):
        refused = self.live()
        asked, _ = request_confirmation(refused, actor=self.bde, now=timezone.now())
        Message.objects.filter(pk=asked.pk).update(
            status=MessageStatus.FAILED, failed_at=timezone.now(), failure_code='131026', provider='fake')
        self.marked(self.bde, refused)
        self.assertEqual(self.requests_for(refused).get().channel, Channel.MANUAL_WHATSAPP)

        held = {
            'being sent': dict(claimed_at=timezone.now()),
            'outcome unknown': dict(status=MessageStatus.FAILED, failed_at=timezone.now(),
                                    failure_code='OUTCOME_UNKNOWN'),
            'not delivered': dict(status=MessageStatus.FAILED, failed_at=timezone.now(), failure_code='131047',
                                  provider='fake', provider_message_id='wamid.HELD'),
        }
        for name, fields in held.items():
            with self.subTest(name):
                booking = self.live(offset=3)
                asked, _ = request_confirmation(booking, actor=self.bde, now=timezone.now())
                Message.objects.filter(pk=asked.pk).update(**fields)
                self.assertFalse(self.ok(self.bde, booking)['actions']['mark_request_sent'])
                self.assert_refused(self.mark(self.bde, booking), 409, 'REQUEST_NOT_MARKABLE')
                message = self.requests_for(booking).get()
                self.assertEqual((message.channel, message.sent_by), ('', None))

    def test_one_the_provider_already_sent_is_left_as_it_is(self):
        booking = self.live()
        asked, _ = request_confirmation(booking, actor=self.bde, now=timezone.now())
        Message.objects.filter(pk=asked.pk).update(
            status=MessageStatus.DELIVERED, channel=Channel.WHATSAPP, provider='fake',
            provider_message_id='wamid.GONE', sent_at=timezone.now(), delivered_at=timezone.now())
        data = self.marked(self.bde, booking)
        self.assertFalse(data['changed'])
        sent = self.by_step(data['messages'])['CONFIRMATION_REQUEST']
        self.assertEqual((sent['status'], sent['channel'], sent['sent_by']), ('DELIVERED', 'WHATSAPP', None))
        self.assertFalse(ActivityLog.objects.filter(action='booking.confirmation_request_sent_manually').exists())

    def test_refused_as_the_service_refuses(self):
        confirmed = self.live()
        self.answer(self.bde, confirmed, outcome='CONFIRMED')
        self.assert_refused(self.mark(self.bde, confirmed), 409, 'CONFIRMATION_NOT_NEEDED')
        started = self.book()  # at NOW, days ago by the real clock
        self.assert_refused(self.mark(self.admin, started), 409, 'BOOKING_NOT_UPCOMING')
        unplanned = self.live(at=MORNING)
        unplanned.communication_messages.all().delete()
        unplanned.communication_tasks.all().delete()
        self.assert_refused(self.mark(self.admin, unplanned), 409, 'NOT_PLANNED')
        cancelled = self.live(offset=3)
        cancel_booking(cancelled, reason_code=CancelReason.PARENT_REQUEST, actor=self.admin, now=timezone.now())
        self.assert_refused(self.mark(self.bde, cancelled), 409, 'BOOKING_NOT_UPCOMING')
        for booking in (confirmed, started, unplanned, cancelled):
            self.assertFalse(self.requests_for(booking).exists())

    def test_a_moved_booking_is_asked_again_for_its_new_time(self):
        moved = self.live(offset=4)
        self.marked(self.bde, moved)
        new = reschedule_booking(moved, indian_today() + timedelta(days=5), MORNING,
                                 reason_code=RescheduleReason.PARENT_REQUEST, actor=self.admin, now=timezone.now()).booking
        # The old booking's request stays as it was sent: nothing more is offered or done for it.
        self.assertEqual(self.ok(self.bde, moved)['actions'],
                         {'open_whatsapp': False, 'mark_request_sent': False, 'record_confirmation': False})
        self.assert_refused(self.mark(self.bde, moved), 409, 'BOOKING_NOT_UPCOMING')
        old = self.requests_for(moved).get()
        self.assertEqual((old.status, old.channel), (MessageStatus.SENT, Channel.MANUAL_WHATSAPP))
        # The new booking has its own request, still to send, with its own date and time.
        data = self.ok(self.bde, new)
        self.assertEqual((data['parent_confirmation']['status'], data['actions']['mark_request_sent']), ('AWAITING', True))
        text = self.preview(self.bde, new).json()['text']
        self.assertNotEqual(text, self.by_step(self.ok(self.bde, moved)['messages'])['CONFIRMATION_REQUEST']['text'])
        self.assertTrue(self.marked(self.bde, new)['changed'])
        self.assertEqual(self.requests_for(new).get().channel, Channel.MANUAL_WHATSAPP)

    def test_blocked_while_the_message_lacks_something(self):
        # A lead nobody owns signs with the central contact, which is not set here.
        booking = self.live(owned=False)
        response = self.mark(self.admin, booking)
        self.assert_refused(response, 409, 'MESSAGE_BLOCKED')
        self.assertEqual(response.json()['missing'],
                         [{'code': 'CENTRAL_CONTACT', 'label': 'Central contact (this lead has no BDE)'}])
        self.assertFalse(self.requests_for(booking).exists())

    def test_the_parents_answer_is_recorded_as_before_after_it(self):
        confirmed, declined = self.ready(self.live(), now=timezone.now()), self.live(offset=3)
        for booking in (confirmed, declined):
            self.marked(self.bde, booking)
        data = self.answer(self.bde, confirmed, outcome='CONFIRMED').json()
        # The request stays sent by hand; the confirmed message goes on as it always has.
        self.assertEqual(self.by_step(data['messages'])['CONFIRMATION_REQUEST']['status'], 'SENT')
        self.assertEqual(self.by_step(data['tasks'])['CONFIRMATION_REQUEST']['resolution'], 'MARKED_SENT')
        self.assertEqual(self.by_step(data['messages'])['PARENT_CONFIRMATION']['status'], 'PENDING')
        data = self.answer(self.bde, declined, outcome='NOT_CONFIRMED', reason='NO_RESPONSE',
                           confirm_cancellation=True).json()
        self.assertEqual(data['booking']['status'], 'CANCELLED')
        self.assertEqual(self.by_step(data['messages'])['CONFIRMATION_REQUEST']['status'], 'SENT')
        tasks = self.by_step(data['tasks'])
        self.assertEqual((tasks['CONFIRMATION_REQUEST']['resolution'], tasks['ACKNOWLEDGEMENT']['status']),
                         ('MARKED_SENT', TaskStatus.CANCELLED))

    def test_a_bde_marks_their_own_leads_only(self):
        nobodys, others = self.live(owned=False, at=MORNING), self.others_booking()
        for booking in (nobodys, others):
            with self.subTest(owner=booking.lead.owner_bde_id):
                self.assert_refused(self.mark(self.bde, booking), 404, 'NOT_FOUND')
                self.assertFalse(self.requests_for(booking).exists())
        # The Admin may mark any lead's -- their own WhatsApp, the BDE's name (the preview says so).
        others_data = self.marked(self.admin, others)
        self.assertEqual(self.by_step(others_data['messages'])['CONFIRMATION_REQUEST']['sent_by']['id'], str(self.admin.pk))

    def test_nobody_else_may_mark_it(self):
        booking = self.ready(self.live(), now=timezone.now())  # taught by self.tutor
        for user in (self.tutor, account('mentor_maya', role='MENTOR'), account('tl_tara', role='SALES_TL')):
            with self.subTest(role=user.role):
                self.assertEqual(self.mark(user, booking).status_code, 403)
                self.assertEqual(self.preview(user, booking).status_code, 403)
        self.revoke('BDE', 'send_lead_communications')
        self.assertEqual(self.mark(self.bde, booking).status_code, 403)
        self.assertEqual(self.preview(self.bde, booking).status_code, 403)
        self.assertFalse(self.requests_for(booking).exists())


class MissingContactTests(ActionTestCase):
    def test_a_lead_with_no_bde_waits_for_the_central_contact_and_says_so(self):
        # The central contact is not set here, and nothing stands in for it.
        booking = self.live(owned=False)
        ack = self.by_step(self.ok(self.admin, booking)['messages'])['ACKNOWLEDGEMENT']
        self.assertEqual((ack['status'], ack['text'], ack['waiting_for']),
                         ('WAITING', '', [{'code': 'CENTRAL_CONTACT', 'label': 'Central contact (this lead has no BDE)'}]))

    def test_a_bde_without_a_mobile_number_is_named_as_such(self):
        type(self.bde).objects.filter(pk=self.bde.pk).update(mobile_number='')
        data = self.preview(self.admin, self.live(), step='PARENT_CONFIRMATION').json()
        self.assertIn({'code': 'BDE_CONTACT', 'label': "BDE's name and mobile number", 'met': False}, data['requirements'])


class AnswerTests(ActionTestCase):
    def test_confirmed(self):
        booking = self.live()
        response = self.answer(self.bde, booking, outcome='CONFIRMED')
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        self.assertTrue(data['changed'])
        self.assertEqual((data['parent_confirmation']['status'], data['parent_confirmation']['by']['id']),
                         ('CONFIRMED', str(self.bde.pk)))
        asked = self.by_step(data['tasks'])['CONFIRMATION_REQUEST']
        self.assertEqual((asked['status'], asked['resolution']), ('DONE', 'NOT_NEEDED'))
        self.assertEqual(data['booking']['status'], 'BOOKED')
        # Said again: nothing changes.
        self.assertFalse(self.answer(self.admin, booking, outcome='CONFIRMED').json()['changed'])

    def test_not_confirmed_needs_a_reason_and_the_cancellation_agreed_to(self):
        booking = self.live()
        self.assert_refused(self.answer(self.bde, booking, outcome='NOT_CONFIRMED'), 400, 'INVALID_REASON')
        self.assert_refused(self.answer(self.bde, booking, outcome='NOT_CONFIRMED', reason='NO_RESPONSE'),
                            400, 'CANCELLATION_NOT_CONFIRMED')
        self.assert_refused(self.answer(self.bde, booking, outcome='NOT_CONFIRMED', reason='BUSY', confirm_cancellation=True),
                            400, 'INVALID_REASON')
        booking.refresh_from_db()
        self.assertEqual((booking.status, booking.parent_confirmation), (BookingStatus.BOOKED, 'AWAITING'))

        response = self.answer(self.bde, booking, outcome='NOT_CONFIRMED', reason='NO_RESPONSE', confirm_cancellation=True)
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        self.assertEqual((data['changed'], data['booking']['status'], data['parent_confirmation']['reason']),
                         (True, 'CANCELLED', {'code': 'NO_RESPONSE', 'label': 'No response'}))
        self.assertEqual({task['status'] for task in data['tasks']}, {TaskStatus.CANCELLED})
        self.assertEqual(data['actions'],
                         {'open_whatsapp': False, 'mark_request_sent': False, 'record_confirmation': False})
        kinds = list(BookingEvent.objects.filter(demo_booking=booking).values_list('kind', flat=True))
        self.assertEqual(kinds[-2:], ['PARENT_NOT_CONFIRMED', 'CANCELLED'])
        # Now cancelled: nothing more can be recorded.
        self.assert_refused(self.answer(self.bde, booking, outcome='CONFIRMED'), 409, 'BOOKING_CANCELLED')

    def test_an_answer_that_cannot_be_recorded(self):
        booking = self.live()
        self.assert_refused(self.answer(self.bde, booking, outcome='MAYBE'), 400, 'INVALID_CONFIRMATION')
        self.assert_refused(self.answer(self.bde, booking, outcome='AWAITING'), 400, 'INVALID_CONFIRMATION')
        self.assert_refused(self.answer(self.bde, booking), 400, 'VALIDATION_ERROR')
        response = self.answer(self.bde, booking, outcome='NOT_CONFIRMED', reason='NO_RESPONSE', confirm_cancellation='perhaps')
        self.assert_refused(response, 400, 'VALIDATION_ERROR')
        self.assertIn('confirm_cancellation', response.json()['fields'])

        self.assert_refused(self.answer(self.admin, self.book(), outcome='CONFIRMED'), 409, 'SLOT_STARTED')
        cancelled = self.live(at=MORNING)
        cancel_booking(cancelled, reason_code=CancelReason.PARENT_REQUEST, actor=self.admin, now=timezone.now())
        self.assert_refused(self.answer(self.admin, cancelled, outcome='CONFIRMED'), 409, 'BOOKING_CANCELLED')
        moved = self.live(offset=4)
        reschedule_booking(moved, indian_today() + timedelta(days=5), MORNING, reason_code=RescheduleReason.PARENT_REQUEST,
                           actor=self.admin, now=timezone.now())
        self.assert_refused(self.answer(self.admin, moved, outcome='CONFIRMED'), 409, 'BOOKING_RESCHEDULED')

    def test_scope_and_permissions(self):
        nobodys, others = self.live(owned=False, at=MORNING), self.others_booking()
        for booking in (nobodys, others):
            with self.subTest(owner=booking.lead.owner_bde_id):
                self.assert_refused(self.answer(self.bde, booking, outcome='CONFIRMED'), 404, 'NOT_FOUND')
        self.assertEqual(self.answer(self.admin, nobodys, outcome='CONFIRMED').status_code, 200)
        booking = self.ready(self.live(), now=timezone.now())
        for user in (self.tutor, account('mentor_maya', role='MENTOR'), account('tl_tara', role='SALES_TL')):
            with self.subTest(role=user.role):
                self.assertEqual(self.answer(user, booking, outcome='CONFIRMED').status_code, 403)
        self.revoke('BDE', 'record_parent_confirmation')
        self.assertEqual(self.answer(self.bde, booking, outcome='CONFIRMED').status_code, 403)
        booking.refresh_from_db()
        self.assertEqual(booking.parent_confirmation, 'AWAITING')
        # Without the permission to record it, the overview offers it no more either.
        self.assertFalse(self.ok(self.bde, booking)['actions']['record_confirmation'])
