"""
The Hub's read of a booking's communication (communications.views and
communications.overview, Phase 3.1): everything the screens show -- the
parent's answer, the five tasks with their status and moments, the messages with
their attempts and Meta's reports, what may be done next -- and who may see
it: every booking's for the Admin, a BDE's own leads' only (404 for any other),
nobody else's at all. Bookings are made on the real clock the endpoint reads
by. Nothing is sent anywhere: the provider is the test-only fake.
"""
from datetime import timedelta

from django.contrib.auth.models import Permission
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import RoleGroup
from bookings.booking_service import create_booking, record_parent_confirmation
from bookings.models import NotConfirmedReason, ParentConfirmation
from bookings.scheduling import indian_today
from bookings.tests_booking import DEMO, DIAGNOSTIC, EVENING, MORNING, account, link, request

from . import planner
from .formatting import whatsapp_message
from .models import OUTCOME_UNKNOWN, Message, MessageStatus, Step, TaskResolution, TaskStatus
from .providers.base import SendResult, StatusUpdate
from .sending import send_message
from .services import request_confirmation
from .status_updates import apply_status_update
from .tests_planning import CommunicationTestCase
from .tests_providers import FakeProvider, use_fake_provider
from .tests_sending import SENDING

STEPS = ['ACKNOWLEDGEMENT', 'CONFIRMATION_REQUEST', 'PARENT_CONFIRMATION', 'PRE_ACTIVITY_CALL', 'AFTER_ACTIVITY']
TASK_FIELDS = {
    'id', 'step', 'step_label', 'status', 'status_label', 'resolution', 'resolution_label', 'owner_role', 'owner',
    'active_from', 'due_at', 'expires_at', 'overdue', 'resolved_at', 'resolved_by',
}
MESSAGE_FIELDS = {
    'id', 'step', 'step_label', 'status', 'status_label', 'channel', 'channel_label', 'provider', 'recipient_phone',
    'text', 'waiting_for', 'scheduled_for', 'send_before', 'queued_at', 'sent_at', 'delivered_at', 'read_at',
    'failed_at', 'cancelled_at', 'attempt_count', 'next_attempt_at', 'failure_code', 'failure_reason', 'problem',
    'cancel_reason', 'created_by', 'created_at', 'attempts', 'events',
}


def when(value):
    return value.isoformat() if value else None


class CommunicationApiTestCase(CommunicationTestCase):
    def setUp(self):
        super().setUp()
        self.api = APIClient()

    def live(self, owned=True, at=EVENING, offset=2, booking_type=DEMO):
        """A booking still to come by the real clock."""
        return self.book(booking_type=booking_type, owned=owned, day=indian_today() + timedelta(days=offset), at=at,
                         now=timezone.now())

    def read(self, user, booking, path_type=None):
        self.api.force_authenticate(user)
        return self.api.get(f'/api/communications/bookings/{path_type or booking.booking_type.lower()}/{booking.pk}/')

    def ok(self, user, booking):
        response = self.read(user, booking)
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    @staticmethod
    def by_step(rows):
        return {row['step']: row for row in rows}


class ContentTests(CommunicationApiTestCase):
    def test_everything_the_screens_show(self):
        booking = self.ready(self.live(), now=timezone.now())
        record_parent_confirmation(booking, ParentConfirmation.CONFIRMED, actor=self.bde, now=timezone.now())
        ack = booking.communication_messages.get(template__step=Step.ACKNOWLEDGEMENT)
        FakeProvider.reset(SendResult(accepted=True, status=MessageStatus.QUEUED, provider_message_id='wamid.API'))
        with use_fake_provider(), override_settings(**SENDING):
            send_message(ack.pk)
        delivered_at = timezone.now()
        apply_status_update('fake', StatusUpdate('wamid.API', MessageStatus.DELIVERED, 'delivered', delivered_at))
        booking.refresh_from_db()

        data = self.ok(self.admin, booking)
        self.assertEqual(set(data), {'booking', 'timezone', 'planned', 'redemo', 'parent_confirmation', 'tasks', 'messages',
                                     'actions'})
        # An ordinary Demo: planned, and no Re-Demo (bookings.redemos, whose parent the BDE contacts by hand).
        self.assertEqual((data['timezone'], data['planned'], data['redemo']), ('Asia/Kolkata', True, False))
        self.assertEqual(data['booking'], {
            'id': str(booking.pk), 'booking_type': 'DEMO', 'status': 'BOOKED', 'status_label': 'Booked',
            'slot': data['booking']['slot'], 'activity_state': 'UPCOMING', 'started_at': None,
            'student_name': booking.lead.student_name,
            'parent_name': 'Asha Nair', 'phone': f'+971 {booking.lead.phone_number}',
            'owner_bde': {'id': str(self.bde.pk), 'full_name': 'Bde Anil'},
            'tutor': {'id': str(self.tutor.pk), 'full_name': 'Tutor Anu'},
        })
        self.assertEqual(data['booking']['slot']['starts_at'], booking.slot.starts_at.isoformat())
        self.assertEqual(data['parent_confirmation'], {
            'status': 'CONFIRMED', 'label': 'Confirmed', 'at': when(booking.parent_confirmation_at),
            'by': {'id': str(self.bde.pk), 'full_name': 'Bde Anil'}, 'reason': None,
        })

        # Five tasks, in the workflow's order, each owned by the lead's BDE.
        self.assertEqual([task['step'] for task in data['tasks']], STEPS)
        tasks = self.by_step(data['tasks'])
        for task in data['tasks']:
            self.assertEqual(set(task), TASK_FIELDS)
            self.assertEqual((task['owner_role'], task['owner']['id']), ('BDE', str(self.bde.pk)))
        self.assertEqual((tasks['ACKNOWLEDGEMENT']['status'], tasks['ACKNOWLEDGEMENT']['resolution'],
                          tasks['ACKNOWLEDGEMENT']['resolution_label']),
                         ('DONE', 'ACCEPTED', 'Accepted by the provider (queued, not yet sent)'))
        self.assertEqual((tasks['CONFIRMATION_REQUEST']['status'], tasks['CONFIRMATION_REQUEST']['resolution']),
                         ('DONE', 'NOT_NEEDED'))
        # The 15-minute call is a task like the others: its status and its moments, nothing recorded on it.
        call = tasks['PRE_ACTIVITY_CALL']
        self.assertEqual(
            (call['status'], call['active_from'], call['due_at'], call['expires_at']),
            ('OPEN', when(booking.slot.starts_at - timedelta(minutes=15)), when(booking.slot.starts_at),
             when(booking.slot.ends_at)),
        )

        # The acknowledgement as it went: its attempt and Meta's report on it.
        messages = self.by_step(data['messages'])
        self.assertEqual(set(messages), {'ACKNOWLEDGEMENT', 'PARENT_CONFIRMATION'})
        sent = messages['ACKNOWLEDGEMENT']
        self.assertEqual(set(sent), MESSAGE_FIELDS)
        ack.refresh_from_db()
        self.assertEqual(
            (sent['status'], sent['status_label'], sent['channel'], sent['provider'], sent['recipient_phone'],
             sent['queued_at'], sent['delivered_at'], sent['problem'], sent['waiting_for'], sent['attempt_count']),
            ('DELIVERED', 'Delivered', 'WHATSAPP', 'fake', booking.lead.phone_key, when(ack.queued_at),
             delivered_at.isoformat(), None, [], 1),
        )
        # The very text the sending engine sent: WhatsApp's bold, never the template's ** markers.
        self.assertEqual(sent['text'], whatsapp_message(ack.template_version.body, ack.variables))
        self.assertIn('*Bde Anil*', sent['text'])
        self.assertNotIn('**', sent['text'])
        self.assertEqual([(a['number'], a['outcome'], a['provider'], a['error_code']) for a in sent['attempts']],
                         [(1, 'ACCEPTED', 'fake', '')])
        self.assertEqual([(e['status'], e['provider_status'], e['occurred_at']) for e in sent['events']],
                         [('DELIVERED', 'delivered', delivered_at.isoformat())])
        # The confirmed message has all it needs: ready, waiting for nothing.
        self.assertEqual((messages['PARENT_CONFIRMATION']['status'], messages['PARENT_CONFIRMATION']['waiting_for']),
                         ('PENDING', []))

    def test_a_waiting_message_says_what_it_waits_for(self):
        booking = self.live()
        messages = self.by_step(self.ok(self.admin, booking)['messages'])
        self.assertEqual(messages['ACKNOWLEDGEMENT']['waiting_for'], [])
        waiting = messages['PARENT_CONFIRMATION']
        self.assertEqual((waiting['status'], waiting['text']), ('WAITING', ''))
        self.assertEqual([item['code'] for item in waiting['waiting_for']], ['PARENT_CONFIRMED', 'TUTOR_ASSIGNED', 'MEET_LINK'])
        self.assertEqual(waiting['waiting_for'][0]['label'], 'Parent confirmation')

    def test_a_parent_who_did_not_confirm(self):
        booking = self.live()
        record_parent_confirmation(booking, ParentConfirmation.NOT_CONFIRMED, reason_code=NotConfirmedReason.NO_RESPONSE,
                                   confirm_cancellation=True, actor=self.bde, now=timezone.now())
        data = self.ok(self.admin, booking)
        self.assertEqual((data['booking']['status'], data['parent_confirmation']['status']), ('CANCELLED', 'NOT_CONFIRMED'))
        self.assertEqual(data['parent_confirmation']['reason'], {'code': 'NO_RESPONSE', 'label': 'No response'})
        tasks = self.by_step(data['tasks'])
        self.assertEqual((tasks['ACKNOWLEDGEMENT']['status'], tasks['ACKNOWLEDGEMENT']['resolution']),
                         ('CANCELLED', 'BOOKING_CANCELLED'))
        self.assertEqual(self.by_step(data['messages'])['ACKNOWLEDGEMENT']['cancel_reason'],
                         {'code': 'BOOKING_CANCELLED', 'label': 'Booking cancelled'})
        self.assertEqual(data['actions'], {'request_confirmation': False, 'record_confirmation': False})

    def test_what_went_wrong_is_flagged(self):
        booking = self.live()
        ack = booking.communication_messages.get(template__step=Step.ACKNOWLEDGEMENT)
        failed = dict(status=MessageStatus.FAILED, failed_at=timezone.now(), failure_reason='Something')
        cases = (
            ('RETRYING', dict(next_attempt_at=timezone.now(), failure_code='131000'), 'Refused for now: trying again'),
            ('REFUSED', dict(failure_code='131026', **failed), 'Refused by WhatsApp'),
            ('INVALID_RECIPIENT', dict(failure_code='INVALID_RECIPIENT', **failed), 'Not an international WhatsApp number'),
            ('OUTCOME_UNKNOWN', dict(failure_code=OUTCOME_UNKNOWN, **failed),
             'Outcome unknown: check WhatsApp before sending it again'),
            ('DELIVERY_FAILED', dict(failure_code='131026', provider='fake', provider_message_id='wamid.X', **failed),
             'Accepted, then not delivered'),
        )
        for code, changes, label in cases:
            with self.subTest(problem=code):
                Message.objects.filter(pk=ack.pk).update(
                    status=MessageStatus.PENDING, next_attempt_at=None, failed_at=None, failure_code='',
                    failure_reason='', provider='', provider_message_id='',
                )
                Message.objects.filter(pk=ack.pk).update(**changes)
                message = self.by_step(self.ok(self.admin, booking)['messages'])['ACKNOWLEDGEMENT']
                self.assertEqual(message['problem'], {'code': code, 'label': label})
        Message.objects.filter(pk=ack.pk).update(status=MessageStatus.PENDING, next_attempt_at=None, failed_at=None,
                                                 failure_code='', failure_reason='', provider='', provider_message_id='')
        self.assertIsNone(self.by_step(self.ok(self.admin, booking)['messages'])['ACKNOWLEDGEMENT']['problem'])

    def test_overdue_is_an_open_task_past_its_target(self):
        booking = self.live()
        tasks = booking.communication_tasks
        tasks.filter(step=Step.ACKNOWLEDGEMENT).update(due_at=timezone.now() - timedelta(minutes=1))
        tasks.filter(step=Step.CONFIRMATION_REQUEST).update(
            due_at=timezone.now() - timedelta(minutes=1), status=TaskStatus.DONE,
            resolution=TaskResolution.NOT_NEEDED, resolved_at=timezone.now(),
        )
        overdue = {step: task['overdue'] for step, task in self.by_step(self.ok(self.admin, booking)['tasks']).items()}
        self.assertEqual(overdue, {'ACKNOWLEDGEMENT': True, 'CONFIRMATION_REQUEST': False, 'PARENT_CONFIRMATION': False,
                                   'PRE_ACTIVITY_CALL': False, 'AFTER_ACTIVITY': False})

    def test_the_call_is_never_overdue_and_missed_at_the_start_unrecorded(self):
        booking = self.book()  # at NOW, days ago by the real clock: its start has passed, the sweep not yet run
        call = self.by_step(self.ok(self.admin, booking)['tasks'])['PRE_ACTIVITY_CALL']
        self.assertEqual((call['status'], call['overdue']), ('OPEN', False))
        planner.close_expired(timezone.now())
        data = self.ok(self.bde, booking)
        call = self.by_step(data['tasks'])['PRE_ACTIVITY_CALL']
        self.assertEqual(
            (call['status'], call['resolution'], call['resolution_label'], call['resolved_at'], call['resolved_by'],
             call['overdue']),
            ('MISSED', '', '', when(booking.slot.starts_at), None, False),
        )
        # The booking as it was: never started, which only its tutor's Start does.
        self.assertEqual((data['booking']['status'], data['booking']['started_at'], data['booking']['activity_state']),
                         ('BOOKED', None, 'NOT_STARTED'))

    def test_a_booking_made_before_communications_has_no_plan(self):
        booking = self.live()
        booking.communication_messages.all().delete()
        booking.communication_tasks.all().delete()
        data = self.ok(self.admin, booking)
        self.assertEqual((data['planned'], data['tasks'], data['messages']), (False, [], []))
        self.assertEqual(data['parent_confirmation']['status'], 'AWAITING')


class ActionTests(CommunicationApiTestCase):
    def actions(self, user, booking):
        return self.ok(user, booking)['actions']

    def test_what_may_be_done_next_follows_the_bookings_state(self):
        booking = self.live()
        for user in (self.admin, self.bde):
            with self.subTest(user=user.username):
                self.assertEqual(self.actions(user, booking), {'request_confirmation': True, 'record_confirmation': True})
        # Asked once: not again.
        request_confirmation(booking, actor=self.bde, now=timezone.now())
        self.assertFalse(self.actions(self.admin, booking)['request_confirmation'])
        # The 15-minute call is a task only: even while it is open, nothing is offered on it.
        booking.communication_tasks.filter(step=Step.PRE_ACTIVITY_CALL).update(
            active_from=timezone.now() - timedelta(minutes=1), expires_at=timezone.now() + timedelta(hours=1),
        )
        self.assertEqual(set(self.actions(self.admin, booking)), {'request_confirmation', 'record_confirmation'})

    def test_a_confirmed_parent_needs_no_request_but_may_still_be_recorded(self):
        booking = self.live()
        record_parent_confirmation(booking, ParentConfirmation.CONFIRMED, actor=self.bde, now=timezone.now())
        self.assertEqual(self.actions(self.bde, booking), {'request_confirmation': False, 'record_confirmation': True})

    def test_nothing_once_the_slot_has_started(self):
        booking = self.book()  # at NOW, days ago by the real clock
        self.assertEqual(self.actions(self.admin, booking), {'request_confirmation': False, 'record_confirmation': False})


class ScopeTests(CommunicationApiTestCase):
    def assert_no_such_booking(self, response):
        self.assertEqual(response.status_code, 404, response.content)
        self.assertEqual(response.json(), {'error': 'NOT_FOUND', 'message': 'No such booking.'})

    def test_the_admin_and_superusers_see_every_booking(self):
        root = account('root_ops', role='ADMIN', is_superuser=True)
        for booking in (self.live(), self.live(owned=False, at=MORNING), self.live(booking_type=DIAGNOSTIC)):
            for user in (self.admin, root):
                with self.subTest(booking=booking.booking_type, owned=booking.lead.owner_bde_id, user=user.username):
                    self.assertEqual(self.ok(user, booking)['booking']['id'], str(booking.pk))

    def test_a_bde_sees_their_own_leads_bookings_only(self):
        own = self.live()
        nobodys = self.live(owned=False, at=MORNING)
        token = link(self.other_bde).token
        others, _ = create_booking(request(student='Meera', phone='0507799999', ref=token,
                                           day=indian_today() + timedelta(days=3)), now=timezone.now())
        self.assertEqual(self.ok(self.bde, own)['booking']['id'], str(own.pk))
        self.assert_no_such_booking(self.read(self.bde, nobodys))
        self.assert_no_such_booking(self.read(self.bde, others))
        # Its own BDE sees it.
        self.assertEqual(self.ok(self.other_bde, others)['booking']['owner_bde']['id'], str(self.other_bde.pk))

    def test_a_booking_that_does_not_exist_or_is_of_another_type(self):
        booking = self.live()
        for user in (self.admin, self.bde):
            with self.subTest(user=user.username):
                self.api.force_authenticate(user)
                self.assert_no_such_booking(self.api.get(
                    '/api/communications/bookings/demo/00000000-0000-0000-0000-000000000000/'))
                self.assert_no_such_booking(self.read(user, booking, path_type='diagnostic'))
                self.assert_no_such_booking(self.read(user, booking, path_type='webinar'))

    def test_nobody_else_sees_any(self):
        booking = self.ready(self.live(), now=timezone.now())  # taught by self.tutor
        callers = (self.tutor, account('mentor_maya', role='MENTOR'), account('tl_tara', role='SALES_TL'))
        for user in callers:
            with self.subTest(role=user.role):
                self.assertEqual(self.read(user, booking).status_code, 403)
        self.api.force_authenticate(None)
        self.assertEqual(self.api.get(f'/api/communications/bookings/demo/{booking.pk}/').status_code, 403)

    def test_a_bde_without_the_permission_sees_none(self):
        booking = self.live()
        RoleGroup.objects.get(role='BDE').group.permissions.remove(
            Permission.objects.get(codename='view_own_lead_communications'))
        self.assertEqual(self.read(self.bde, booking).status_code, 403)


class EnquiryConfirmationTests(CommunicationApiTestCase):
    """The parent's answer beside each booking of the BDE's enquiry (the Hub's bookings table)."""

    def enquiry_bookings(self, booking):
        self.api.force_authenticate(self.bde)
        response = self.api.get(f'/api/bde/enquiries/{booking.lead_id}/')
        self.assertEqual(response.status_code, 200, response.content)
        return {row['id']: row for row in response.json()['bookings']}

    def test_each_booking_carries_the_parents_answer(self):
        booking = self.live()
        self.assertEqual(self.enquiry_bookings(booking)[str(booking.pk)]['parent_confirmation'], 'AWAITING')
        record_parent_confirmation(booking, ParentConfirmation.CONFIRMED, actor=self.bde, now=timezone.now())
        self.assertEqual(self.enquiry_bookings(booking)[str(booking.pk)]['parent_confirmation'], 'CONFIRMED')

    def test_not_without_the_permission_to_see_the_communication(self):
        booking = self.live()
        RoleGroup.objects.get(role='BDE').group.permissions.remove(
            Permission.objects.get(codename='view_own_lead_communications'))
        self.assertIsNone(self.enquiry_bookings(booking)[str(booking.pk)]['parent_confirmation'])


class HistoryTests(CommunicationApiTestCase):
    def test_the_timeline_names_why_the_parent_did_not_confirm(self):
        booking = self.live()
        record_parent_confirmation(booking, ParentConfirmation.NOT_CONFIRMED, reason_code=NotConfirmedReason.NO_RESPONSE,
                                   confirm_cancellation=True, actor=self.bde, now=timezone.now())
        self.api.force_authenticate(self.admin)
        events = self.api.get(f'/api/bookings/demo/{booking.pk}/history/').json()['events']
        not_confirmed = next(event for event in events if event['kind'] == 'PARENT_NOT_CONFIRMED')
        self.assertEqual(not_confirmed['details']['reason'], {'code': 'NO_RESPONSE', 'label': 'No response'})
