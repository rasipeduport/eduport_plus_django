"""
A BDE's follow-ups (communications.followups, GET /api/bde/follow-ups/): only
what the BDE must do -- call a new enquiry, get the parent's confirmation,
make the 15-minute call, discuss a tutor's report, confirm a scheduled
Re-Demo -- never the system's own messages; each from its own trigger, once,
following the lead's owner now; Completed when the BDE records it, Missed when
the class starts first. The services run on the PRD clock (NOW, 27 Oct 12:00
IST, a booking on 28 Oct at 19:30); the API on the real clock.
"""
from datetime import date, datetime, timedelta

from django.contrib.auth.models import Permission
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import RoleGroup
from activity.models import ActivityLog
from bookings.booking_service import cancel_booking, record_parent_confirmation, request_redemo, schedule_redemo
from bookings.lead_intake import create_lead
from bookings.models import BookingStatus, CancelReason, Lead, LeadSource, ParentConfirmation
from bookings.ownership import assign_owner
from bookings.scheduling import BOOKING_TIMEZONE, indian_today
from bookings.tests_booking import EVENING, MORNING, NOW, account, start
from reports.services import submit_report
from reports.tests_services import report_input

from . import followups, planner
from .followups import FollowUpState, FollowUpType
from .models import CommunicationTask, FollowUp, FollowUpKind, FollowUpOutcome, FollowUpStatus, Step, TaskResolution
from .services import record_call_outcome, request_confirmation
from .tests_planning import CommunicationTestCase

URL = '/api/bde/follow-ups/'
HOUR = timedelta(hours=1)
# The booking CommunicationTestCase.book makes starts at 19:30 IST on 28 Oct.
STARTS = datetime(2026, 10, 28, 19, 30, tzinfo=BOOKING_TIMEZONE)


def details(student, phone):
    return {'parent_name': 'Asha Nair', 'phone_dial_code': '+971', 'phone_number': phone, 'student_name': student,
            'grade': 'Class 8'}


class FollowUpTestCase(CommunicationTestCase):
    def new_enquiry(self, student='Kiran', phone='501110001', to=None, now=NOW):
        """A lead from the website's form, nobody's, then given to ``to`` (the BDE) by an administrator."""
        lead = create_lead(details(student, phone), source=LeadSource.WEBSITE)
        assign_owner(lead.pk, (to or self.bde).pk, actor=self.admin, via='admin_leads', now=now)
        return Lead.objects.get(pk=lead.pk)

    def complete(self, booking, minutes=50):
        """``booking`` started by its tutor and reported on ``minutes`` into its slot; returns when."""
        at = booking.slot.starts_at + timedelta(minutes=minutes)
        start(booking)
        submit_report(booking, self.tutor, report_input(booking), now=at)
        return at

    def open(self, user=None, now=NOW, enquiry=None):
        return followups.open_items(user or self.bde, now, enquiry=enquiry)

    def kinds(self, items):
        return [(item.type, item.state) for item in items]

    def closed(self, lead, user=None, now=NOW):
        return [(item.type, item.state, item.outcome and item.outcome[0])
                for item in followups.closed_items(user or self.bde, now, lead.pk)]


class TriggerTests(FollowUpTestCase):
    def test_a_new_enquiry_given_by_an_administrator_gets_one_call_due_within_three_hours(self):
        lead = self.new_enquiry()
        [call] = FollowUp.objects.filter(lead=lead)
        self.assertEqual((call.kind, call.status, call.due_at), (FollowUpKind.NEW_ENQUIRY_CALL, FollowUpStatus.OPEN,
                                                                 NOW + 3 * HOUR))
        self.assertEqual(self.kinds(self.open()), [(FollowUpType.NEW_ENQUIRY_CALL, FollowUpState.DUE_TODAY)])
        self.assertEqual(self.kinds(self.open(now=NOW + 4 * HOUR)),
                         [(FollowUpType.NEW_ENQUIRY_CALL, FollowUpState.OVERDUE)])
        # Given again -- to the same BDE, or handled twice -- it is still one call.
        assign_owner(lead.pk, self.bde.pk, actor=self.admin, via='admin_leads', now=NOW)
        followups.enquiry_assigned(lead, NOW)
        self.assertEqual(FollowUp.objects.filter(lead=lead).count(), 1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            FollowUp.objects.create(lead=lead, kind=FollowUpKind.NEW_ENQUIRY_CALL, due_at=NOW)

    def test_no_call_for_an_enquiry_with_a_booking_or_one_the_bde_added_or_booked_through_their_link(self):
        booked = self.book()  # through the BDE's link: the booking has its own follow-ups
        own = create_lead(details('Walk-in', '501110002'), source=LeadSource.WALK_IN, created_by=self.bde,
                          owner=self.bde)
        other = self.book(owned=False)
        assign_owner(other.lead_id, self.bde.pk, actor=self.admin, via='admin_leads', now=NOW)
        self.assertFalse(FollowUp.objects.filter(lead__in=[booked.lead_id, own.pk, other.lead_id]).exists())

    def test_a_submitted_report_gets_one_discussion_due_within_a_day_and_an_edit_adds_none(self):
        booking = self.ready(self.book())
        at = self.complete(booking)
        [discussion] = FollowUp.objects.filter(demo_booking=booking)
        self.assertEqual((discussion.kind, discussion.lead_id, discussion.due_at),
                         (FollowUpKind.REPORT_DISCUSSION, booking.lead_id, at + timedelta(days=1)))
        followups.report_submitted(booking, at + HOUR)
        self.assertEqual(FollowUp.objects.filter(demo_booking=booking).count(), 1)

    def test_the_systems_own_steps_are_never_follow_ups(self):
        booking = self.book()
        # Every step open, the acknowledgement and the confirmed message included: a day before, only the
        # confirmation is not yet due, and none of the others is the BDE's to do.
        self.assertTrue(all(task.status == 'OPEN' for task in booking.communication_tasks.all()))
        self.assertEqual(self.open(), [])
        # From 12 hours before: the parent's confirmation, once -- never the messages around it.
        self.assertEqual(self.kinds(self.open(now=STARTS - 12 * HOUR)),
                         [(FollowUpType.PARENT_CONFIRMATION, FollowUpState.DUE_TODAY)])


class ConfirmationTests(FollowUpTestCase):
    def test_from_twelve_hours_before_until_the_parent_answers(self):
        booking = self.ready(self.book())
        due = STARTS - 12 * HOUR
        self.assertEqual(self.open(now=due - timedelta(seconds=1)), [])
        [item] = self.open(now=due)
        self.assertEqual((item.type, item.id, item.due_at, item.request), (FollowUpType.PARENT_CONFIRMATION, booking.id,
                                                                           STARTS, None))
        self.assertEqual(item.actions, {'record_outcome': False, 'request_confirmation': True, 'record_answer': True,
                                        'complete': False})
        # Asked: the request is shown, and asking again is not offered.
        request_confirmation(booking, actor=self.bde, owner_bde=self.bde, now=due + HOUR)
        [item] = self.open(now=due + HOUR)
        self.assertEqual((item.request.status, item.actions['request_confirmation']), ('PENDING', False))
        # Answered: Completed, recorded by the BDE.
        record_parent_confirmation(booking, ParentConfirmation.CONFIRMED, actor=self.bde, owner_bde=self.bde,
                                   now=due + 2 * HOUR)
        self.assertEqual(self.open(now=due + 2 * HOUR), [])
        self.assertIn((FollowUpType.PARENT_CONFIRMATION, FollowUpState.COMPLETED, ParentConfirmation.CONFIRMED),
                      self.closed(booking.lead, now=due + 2 * HOUR))

    def test_not_confirmed_completes_it_with_the_booking_cancelled(self):
        booking = self.book()
        record_parent_confirmation(booking, ParentConfirmation.NOT_CONFIRMED, reason_code='NO_RESPONSE',
                                   confirm_cancellation=True, actor=self.bde, owner_bde=self.bde, now=STARTS - 6 * HOUR)
        self.assertEqual(self.open(now=STARTS - 6 * HOUR), [])
        [item] = [item for item in followups.closed_items(self.bde, STARTS, booking.lead_id)
                  if item.type == FollowUpType.PARENT_CONFIRMATION]
        row = followups.row(item, STARTS, self.bde)
        self.assertEqual((row['state'], row['outcome'], row['by_you'], row['booking']['status']),
                         ('COMPLETED', {'code': 'NOT_CONFIRMED', 'label': 'Parent did not confirm (booking cancelled)'},
                          True, BookingStatus.CANCELLED))

    def test_missed_when_the_class_starts_unanswered_and_gone_when_cancelled(self):
        missed, cancelled = self.book(), self.book(at=MORNING)
        cancel_booking(cancelled, reason_code=CancelReason.PARENT_REQUEST, actor=self.admin, now=NOW)
        self.assertEqual(self.kinds(self.open(now=STARTS - HOUR)), [(FollowUpType.PARENT_CONFIRMATION,
                                                                     FollowUpState.DUE_TODAY)])
        self.assertEqual(self.open(now=STARTS), [])
        self.assertEqual(self.closed(missed.lead, now=STARTS)[0][:2],
                         (FollowUpType.PARENT_CONFIRMATION, FollowUpState.MISSED))
        self.assertNotIn(FollowUpType.PARENT_CONFIRMATION,
                         [kind for kind, *_ in self.closed(cancelled.lead, now=STARTS)])

    def test_a_redemo_is_followed_up_once_scheduled_never_while_only_requested(self):
        after = datetime(2026, 10, 29, 12, 0, tzinfo=BOOKING_TIMEZONE)
        demo = self.ready(self.book())
        self.complete(demo)
        redemo = request_redemo(type(demo).objects.get(pk=demo.pk), 'The parent wants a slower pace.',
                                actor=self.bde, owner_bde=self.bde, now=after)
        self.assertNotIn(FollowUpType.REDEMO_CONFIRMATION, [item.type for item in self.open(now=after)])
        other_tutor = account('tutor_neel', role='TUTOR', tutor_meet_link='https://meet.google.com/xyz-abcd-efg')
        booking = schedule_redemo(redemo, other_tutor, date(2026, 10, 31), EVENING, actor=self.admin, now=after)
        [item] = [item for item in self.open(now=after) if item.type == FollowUpType.REDEMO_CONFIRMATION]
        self.assertEqual((item.id, item.due_at, item.state),
                         (booking.id, booking.slot.starts_at, FollowUpState.PENDING))
        self.assertEqual(item.actions['record_answer'], True)
        self.assertIs(followups.row(item, after, self.bde)['booking']['redemo'], True)
        record_parent_confirmation(booking, ParentConfirmation.CONFIRMED, actor=self.bde, owner_bde=self.bde, now=after)
        self.assertNotIn(FollowUpType.REDEMO_CONFIRMATION, [item.type for item in self.open(now=after)])


class CallTests(FollowUpTestCase):
    def test_from_fifteen_minutes_before_until_the_start_then_missed(self):
        booking = self.book()
        record_parent_confirmation(booking, ParentConfirmation.CONFIRMED, actor=self.bde, owner_bde=self.bde, now=NOW)
        self.assertEqual(self.open(now=STARTS - timedelta(minutes=16)), [])
        [item] = self.open(now=STARTS - timedelta(minutes=15))
        self.assertEqual((item.type, item.state, item.opens_at, item.due_at), (
            FollowUpType.PRE_ACTIVITY_CALL, FollowUpState.DUE_TODAY, STARTS - timedelta(minutes=15), STARTS))
        # At the start it leaves the list, whether or not the sweep has run, and is Missed.
        self.assertEqual(self.open(now=STARTS), [])
        planner.close_expired(STARTS + timedelta(minutes=3))
        self.assertIn((FollowUpType.PRE_ACTIVITY_CALL, FollowUpState.MISSED, None),
                      self.closed(booking.lead, now=STARTS))

    def test_completed_with_the_outcome_the_bde_recorded(self):
        booking = self.book()
        call = booking.communication_tasks.get(step=Step.PRE_ACTIVITY_CALL)
        record_call_outcome(call, TaskResolution.CALLED, actor=self.bde, owner_bde=self.bde,
                            now=STARTS - timedelta(minutes=5))
        later = self.open(now=STARTS - timedelta(minutes=4))
        self.assertNotIn(FollowUpType.PRE_ACTIVITY_CALL, [item.type for item in later])
        planner.close_expired(STARTS)
        self.assertIn((FollowUpType.PRE_ACTIVITY_CALL, FollowUpState.COMPLETED, 'CALLED'),
                      self.closed(booking.lead, now=STARTS))

    def test_gone_once_its_tutor_starts_the_class_early(self):
        booking = self.ready(self.book())
        record_parent_confirmation(booking, ParentConfirmation.CONFIRMED, actor=self.bde, owner_bde=self.bde, now=NOW)
        self.assertEqual(len(self.open(now=STARTS - timedelta(minutes=5))), 1)
        start(booking, minutes=-4)
        self.assertEqual(self.open(now=STARTS - timedelta(minutes=3)), [])


class CompletionTests(FollowUpTestCase):
    def test_a_new_enquirys_call_completes_with_its_outcome_once(self):
        lead = self.new_enquiry()
        call = FollowUp.objects.get(lead=lead)
        with self.assertRaises(followups.InvalidFollowUpOutcome):
            followups.complete(call, FollowUpOutcome.DISCUSSED, actor=self.bde, owner_bde=self.bde, now=NOW)
        followups.complete(call, FollowUpOutcome.SPOKE, actor=self.bde, owner_bde=self.bde, now=NOW + HOUR)
        call.refresh_from_db()
        self.assertEqual((call.status, call.outcome, call.resolved_at, call.resolved_by),
                         (FollowUpStatus.DONE, FollowUpOutcome.SPOKE, NOW + HOUR, self.bde))
        self.assertEqual(self.open(), [])
        self.assertEqual(self.closed(lead), [(FollowUpType.NEW_ENQUIRY_CALL, FollowUpState.COMPLETED, 'SPOKE')])
        with self.assertRaises(followups.FollowUpDone):
            followups.complete(call, FollowUpOutcome.MESSAGED, actor=self.bde, owner_bde=self.bde)
        with self.assertRaises(followups.FollowUpNotFound):
            followups.complete(call, FollowUpOutcome.MESSAGED, actor=self.other_bde, owner_bde=self.other_bde)
        entry = ActivityLog.objects.get(action='follow_up.complete')
        self.assertEqual(entry.context, {'kind': 'NEW_ENQUIRY_CALL', 'outcome': 'SPOKE', 'lead_id': str(lead.pk),
                                         'booking_id': None})

    def test_a_reports_discussion_needs_the_reports(self):
        booking = self.ready(self.book())
        at = self.complete(booking)
        [item] = [item for item in self.open(now=at) if item.type == FollowUpType.REPORT_DISCUSSION]
        self.assertEqual((item.booking.pk, item.actions['complete']), (booking.pk, True))
        RoleGroup.objects.get(role='BDE').group.permissions.remove(
            Permission.objects.get(codename='view_own_lead_reports'))
        self.bde = type(self.bde).objects.get(pk=self.bde.pk)
        self.assertNotIn(FollowUpType.REPORT_DISCUSSION, [item.type for item in self.open(now=at)])


class OwnershipTests(FollowUpTestCase):
    def test_every_follow_up_goes_with_the_lead_and_the_bde_before_sees_none(self):
        lead = self.new_enquiry(now=NOW)
        booking = self.book()
        moment = STARTS - 12 * HOUR
        self.assertEqual(len(self.open(now=moment)), 2)
        assign_owner(lead.pk, self.other_bde.pk, actor=self.admin, via='admin_leads', now=moment)
        assign_owner(booking.lead_id, self.other_bde.pk, actor=self.admin, via='admin_leads', now=moment)
        self.assertEqual(self.open(now=moment), [])
        self.assertEqual(followups.closed_items(self.bde, moment, lead.pk), [])
        mine = self.open(user=self.other_bde, now=moment)
        self.assertEqual(sorted(item.type for item in mine),
                         [FollowUpType.NEW_ENQUIRY_CALL, FollowUpType.PARENT_CONFIRMATION])
        # The call still open is due as soon from its new owner's start as it was from the first.
        [call] = [item for item in mine if item.type == FollowUpType.NEW_ENQUIRY_CALL]
        self.assertEqual(call.due_at, moment + 3 * HOUR)
        # The communication steps went too (planner.lead_owner_changed).
        self.assertEqual(set(CommunicationTask.objects.filter(demo_booking=booking, status='OPEN')
                             .values_list('owner', flat=True)), {self.other_bde.pk})


class DueTests(FollowUpTestCase):
    def test_counted_in_indian_days_soonest_first(self):
        now = datetime(2026, 11, 9, 10, 0, tzinfo=BOOKING_TIMEZONE)
        overdue = self.new_enquiry('Asha', '501110010', now=now - 5 * HOUR)
        today = self.new_enquiry('Bina', '501110011', now=now)
        upcoming = self.new_enquiry('Chitra', '501110012', now=now + 13 * HOUR)  # due at 02:00 tomorrow
        items = self.open(now=now)
        self.assertEqual([item.lead.pk for item in items], [overdue.pk, today.pk, upcoming.pk])
        self.assertEqual([item.state for item in items],
                         [FollowUpState.OVERDUE, FollowUpState.DUE_TODAY, FollowUpState.PENDING])
        self.assertEqual(followups.summary(items), {'total': 3, 'overdue': 1, 'today': 1, 'upcoming': 1})
        self.assertEqual([item.lead.pk for item in followups.filtered(items, due='upcoming')], [upcoming.pk])
        self.assertEqual(followups.filtered(items, follow_up_type=FollowUpType.PRE_ACTIVITY_CALL), [])


class ApiTests(FollowUpTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(self.bde)

    def test_a_row_carries_what_is_due_for_which_booking_and_whose_it_is(self):
        lead = self.new_enquiry(now=timezone.now())
        response = self.client.get(URL)
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        self.assertEqual((data['summary']['total'], data['summary']['overdue'], data['count']), (1, 0, 1))
        [row] = data['results']
        self.assertEqual(set(row), {'id', 'type', 'type_label', 'state', 'state_label', 'due_at', 'opens_at',
                                    'closed_at', 'outcome', 'by_you', 'request', 'booking', 'enquiry', 'actions'})
        self.assertEqual((row['type'], row['type_label'], row['booking']),
                         ('NEW_ENQUIRY_CALL', 'Call new enquiry', None))
        self.assertEqual(set(row['enquiry']),
                         {'id', 'parent_name', 'student_name', 'grade', 'phone', 'phone_dial_code', 'phone_number'})
        self.assertEqual(row['actions'], {'record_outcome': True, 'request_confirmation': False, 'record_answer': False,
                                          'complete': False})

        # Completed: answered as it now stands, gone from the open list, in the enquiry's history.
        done = self.client.post(f'{URL}{row["id"]}/complete/', {'outcome': 'not_interested'}, format='json')
        self.assertEqual(done.status_code, 200, done.content)
        self.assertEqual((done.json()['state'], done.json()['outcome']['code'], done.json()['by_you']),
                         ('COMPLETED', 'NOT_INTERESTED', True))
        self.assertEqual(self.client.get(URL).json()['count'], 0)
        history = self.client.get(URL, {'state': 'closed', 'enquiry': str(lead.pk)}).json()
        self.assertEqual(([r['id'] for r in history['results']], 'summary' in history), ([row['id']], False))
        again = self.client.post(f'{URL}{row["id"]}/complete/', {'outcome': 'SPOKE'}, format='json')
        self.assertEqual((again.status_code, again.json()['error']), (409, 'FOLLOW_UP_DONE'))

    def test_completing_is_for_the_owner_with_an_outcome_its_kind_allows(self):
        lead = self.new_enquiry(now=timezone.now())
        call = FollowUp.objects.get(lead=lead)
        bad = self.client.post(f'{URL}{call.pk}/complete/', {'outcome': 'DISCUSSED'}, format='json')
        self.assertEqual((bad.status_code, bad.json()['error']), (400, 'INVALID_OUTCOME'))
        other = APIClient()
        other.force_authenticate(self.other_bde)
        for path in (f'{URL}{call.pk}/complete/', f'{URL}00000000-0000-4000-8000-000000000000/complete/'):
            response = other.post(path, {'outcome': 'SPOKE'}, format='json')
            self.assertEqual((response.status_code, response.json()['error']), (404, 'NOT_FOUND'))
        RoleGroup.objects.get(role='BDE').group.permissions.remove(
            Permission.objects.get(codename='send_lead_communications'))
        self.assertEqual(self.client.post(f'{URL}{call.pk}/complete/', {'outcome': 'SPOKE'}, format='json').status_code,
                         403)
        self.assertEqual(FollowUp.objects.get(pk=call.pk).status, FollowUpStatus.OPEN)

    def test_the_call_outcome_is_recorded_on_the_bookings_communication(self):
        booking = self.book(day=indian_today() + timedelta(days=2), now=timezone.now())
        now = timezone.now()
        url = f'/api/communications/bookings/demo/{booking.pk}/call-outcome/'
        CommunicationTask.objects.filter(demo_booking=booking, step=Step.PRE_ACTIVITY_CALL).update(
            active_from=now + HOUR, due_at=now + 2 * HOUR)
        early = self.client.post(url, {'outcome': 'CALLED'}, format='json')
        self.assertEqual((early.status_code, early.json()['error']), (409, 'CALL_NOT_OPEN_YET'))
        CommunicationTask.objects.filter(demo_booking=booking, step=Step.PRE_ACTIVITY_CALL).update(
            active_from=now - HOUR, due_at=now + HOUR)
        self.assertEqual(self.client.post(url, {'outcome': 'MAYBE'}, format='json').json()['error'], 'INVALID_OUTCOME')
        response = self.client.post(url, {'outcome': 'no_answer'}, format='json')
        self.assertEqual(response.status_code, 201, response.content)
        call = self.by_step(response.json()['tasks'])['PRE_ACTIVITY_CALL']
        self.assertEqual((call['status'], call['resolution']), ('DONE', 'NO_ANSWER'))
        other = APIClient()
        other.force_authenticate(self.other_bde)
        self.assertEqual(other.post(url, {'outcome': 'CALLED'}, format='json').status_code, 404)
        CommunicationTask.objects.filter(demo_booking=booking, step=Step.PRE_ACTIVITY_CALL).update(due_at=now - HOUR)
        late = self.client.post(url, {'outcome': 'CALLED'}, format='json')
        self.assertEqual((late.status_code, late.json()['error']), (409, 'CALL_CLOSED'))

    @staticmethod
    def by_step(rows):
        return {row['step']: row for row in rows}

    def test_filters_are_checked_and_every_other_caller_is_refused(self):
        response = self.client.get(URL, {'due': 'soon', 'type': 'NOPE', 'enquiry': 'x', 'state': 'gone'})
        self.assertEqual((response.status_code, sorted(response.json()['fields'])),
                         (400, ['due', 'enquiry', 'state', 'type']))
        # History is one enquiry's, and has no due date to filter by.
        response = self.client.get(URL, {'state': 'closed', 'due': 'today'})
        self.assertEqual(sorted(response.json()['fields']), ['due', 'enquiry'])
        client = APIClient()
        client.force_authenticate(account('root', role='ADMIN', is_superuser=True, is_staff=True))
        self.assertEqual(client.get(URL).json()['error'], 'NOT_A_BDE')
        self.assertEqual(client.post(f'{URL}00000000-0000-4000-8000-000000000000/complete/').json()['error'],
                         'NOT_A_BDE')
        for role in ('MENTOR', 'TUTOR', 'SALES_TL'):
            with self.subTest(role=role):
                client.force_authenticate(account(role.lower(), role))
                self.assertEqual(client.get(URL).status_code, 403)
                self.assertEqual(client.post(f'{URL}00000000-0000-4000-8000-000000000000/complete/').status_code, 403)
        client.force_authenticate(self.admin)
        self.assertEqual(client.get(URL).status_code, 403)
