"""
The parent's confirmation from the Hub (communications.views, Phase 3.2):
seeing the confirmation request exactly as WhatsApp would show it and what it
still lacks, asking the parent to confirm -- once, however often asked -- and
recording their answer: Confirmed, or Not Confirmed with a reason and the
cancellation agreed to. Each within the caller's scope (every booking for the
Admin, a BDE's own leads only), refused as the services refuse it, and by
nobody else. Bookings are made on the real clock. Nothing is sent anywhere.
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
from bookings.tests_booking import MORNING, account, link, request

from .models import Message, Step, TaskStatus
from .tests_api import CommunicationApiTestCase


def url(booking, action):
    return f'/api/communications/bookings/{booking.booking_type.lower()}/{booking.pk}/{action}/'


class ActionTestCase(CommunicationApiTestCase):
    def preview(self, user, booking, step='CONFIRMATION_REQUEST'):
        self.api.force_authenticate(user)
        return self.api.get(url(booking, 'preview'), {'step': step} if step is not None else {})

    def ask(self, user, booking):
        self.api.force_authenticate(user)
        return self.api.post(url(booking, 'confirmation-request'), {}, format='json')

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
                    {'code': 'BOOKING_ACTIVE', 'label': 'Booking still upcoming', 'met': True},
                    {'code': 'BDE_CONTACT', 'label': "BDE's name and mobile number", 'met': True},
                ])
        # Seeing it writes nothing.
        self.assertFalse(self.requests_for(booking).exists())

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


class RequestTests(ActionTestCase):
    def test_asking_writes_the_request_once(self):
        booking = self.live()
        response = self.ask(self.admin, booking)
        self.assertEqual(response.status_code, 201, response.content)
        data = response.json()
        self.assertTrue(data['created'])
        asked = self.by_step(data['messages'])['CONFIRMATION_REQUEST']
        self.assertEqual((asked['status'], asked['created_by']['id']), ('PENDING', str(self.admin.pk)))
        self.assertFalse(data['actions']['request_confirmation'], 'nothing more to ask')
        # Asked again -- by the BDE this time -- it answers the request already written, never a second.
        response = self.ask(self.bde, booking)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertFalse(response.json()['created'])
        self.assertEqual(self.requests_for(booking).count(), 1)

    def test_the_request_in_the_history_reads_as_the_preview_showed_it(self):
        booking = self.live()
        shown = self.preview(self.bde, booking).json()['text']
        asked = self.by_step(self.ask(self.bde, booking).json()['messages'])['CONFIRMATION_REQUEST']
        self.assertEqual(asked['text'], shown)
        self.assertNotIn('**', asked['text'])

    def test_writing_the_request_is_logged_once_by_ids(self):
        booking = self.live()
        self.assertEqual(self.ask(self.admin, booking).status_code, 201)
        # Asked again, or refused: nothing more is logged.
        self.assertEqual(self.ask(self.bde, booking).status_code, 200)
        self.assert_refused(self.ask(self.admin, self.live(owned=False, at=MORNING)), 409, 'MESSAGE_BLOCKED')
        entry = ActivityLog.objects.get(action='booking.confirmation_request')
        self.assertEqual((entry.actor, entry.entity_type, entry.entity_id, entry.entity_label),
                         (self.admin, 'booking', str(booking.pk), slot_label(booking.slot)))
        self.assertEqual(entry.context, {'booking_type': 'DEMO', 'lead_id': str(booking.lead_id),
                                         'message_id': str(self.requests_for(booking).get().pk)})

    def test_refused_as_the_service_refuses(self):
        confirmed = self.live()
        self.answer(self.bde, confirmed, outcome='CONFIRMED')
        self.assert_refused(self.ask(self.bde, confirmed), 409, 'CONFIRMATION_NOT_NEEDED')
        started = self.book()  # at NOW, days ago by the real clock
        self.assert_refused(self.ask(self.admin, started), 409, 'BOOKING_NOT_UPCOMING')
        unplanned = self.live(at=MORNING)
        unplanned.communication_messages.all().delete()
        unplanned.communication_tasks.all().delete()
        self.assert_refused(self.ask(self.admin, unplanned), 409, 'NOT_PLANNED')
        for booking in (confirmed, started, unplanned):
            self.assertFalse(self.requests_for(booking).exists())

    def test_blocked_while_the_message_lacks_something(self):
        # A lead nobody owns signs with the central contact, which is not set here.
        booking = self.live(owned=False)
        response = self.ask(self.admin, booking)
        self.assert_refused(response, 409, 'MESSAGE_BLOCKED')
        self.assertEqual(response.json()['missing'],
                         [{'code': 'CENTRAL_CONTACT', 'label': 'Central contact (this lead has no BDE)'}])
        self.assertFalse(self.requests_for(booking).exists())
        with override_settings(COMMUNICATIONS_FALLBACK_SENDER_NAME='Eduport Plus Team',
                               COMMUNICATIONS_FALLBACK_SENDER_PHONE='+91 80000 00000'):
            self.assertEqual(self.ask(self.admin, booking).status_code, 201)

    def test_a_bde_asks_for_their_own_leads_only(self):
        nobodys, others = self.live(owned=False, at=MORNING), self.others_booking()
        for booking in (nobodys, others):
            with self.subTest(owner=booking.lead.owner_bde_id):
                self.assert_refused(self.ask(self.bde, booking), 404, 'NOT_FOUND')
                self.assert_refused(self.preview(self.bde, booking), 404, 'NOT_FOUND')
                self.assertFalse(self.requests_for(booking).exists())
        self.assertEqual(self.ask(self.bde, self.live()).status_code, 201)

    def test_nobody_else_may_ask_or_see_it(self):
        booking = self.ready(self.live(), now=timezone.now())  # taught by self.tutor
        for user in (self.tutor, account('mentor_maya', role='MENTOR'), account('tl_tara', role='SALES_TL')):
            with self.subTest(role=user.role):
                self.assertEqual(self.ask(user, booking).status_code, 403)
                self.assertEqual(self.preview(user, booking).status_code, 403)
        self.revoke('BDE', 'send_lead_communications')
        self.assertEqual(self.ask(self.bde, booking).status_code, 403)
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
        self.assertEqual(data['actions'], {'request_confirmation': False, 'record_confirmation': False})
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
