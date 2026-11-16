"""
A BDE's follow-ups (communications.followups, GET /api/bde/follow-ups/): a
list of reminders -- a new enquiry to call (24 hours), a parent's
confirmation (from 12 hours before), the call before a class (15 minutes
before), a tutor's report to share (24 hours), a scheduled Re-Demo to
confirm -- each gone once resolved or once its time is up, never the
system's own messages, following the lead's owner now. The services run on
the PRD clock (NOW, 27 Oct 12:00 IST, a booking on 28 Oct at 19:30); the API
on the real clock.
"""
from datetime import date, datetime, timedelta

from django.contrib.auth.models import Permission
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import RoleGroup
from bookings.booking_service import cancel_booking, record_parent_confirmation, request_redemo, schedule_redemo
from bookings.lead_intake import create_lead
from bookings.lead_status import LeadStatus, with_status
from bookings.models import BookingStatus, CancelReason, Lead, LeadSource, ParentConfirmation
from bookings.ownership import assign_owner
from bookings.scheduling import BOOKING_TIMEZONE, indian_today
from bookings.tests_booking import DIAGNOSTIC, EVENING, MORNING, NOW, account, start
from bookings.tests_enquiries import booking as booking_of
from reports.models import ReportShare
from reports.services import edit_report, record_share, submit_report
from reports.tests_services import report_input

from . import followups, planner
from .followups import FollowUpState, FollowUpType
from .models import CommunicationTask, Step, TaskResolution, TaskStatus
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

    def types(self, items):
        return [item.type for item in items]


class NewEnquiryTests(FollowUpTestCase):
    def test_an_enquiry_given_to_the_bde_is_a_reminder_for_24_hours_from_then(self):
        lead = self.new_enquiry()
        [item] = self.open()
        self.assertEqual((item.type, item.id, item.due_at, item.state),
                         (FollowUpType.NEW_ENQUIRY_CALL, lead.id, NOW + 24 * HOUR, FollowUpState.PENDING))
        # Due by 12:00 tomorrow: Due today tomorrow morning, gone once its 24 hours are up.
        self.assertEqual(self.kinds(self.open(now=NOW + 23 * HOUR)),
                         [(FollowUpType.NEW_ENQUIRY_CALL, FollowUpState.DUE_TODAY)])
        self.assertEqual(self.open(now=NOW + 24 * HOUR), [])

    def test_gone_the_moment_the_enquiry_is_no_longer_new(self):
        demo, diagnostic, cancelled = (
            self.new_enquiry(student, phone)
            for student, phone in (('Kiran', '501110001'), ('Meera', '501110002'), ('Ravi', '501110003'))
        )
        self.assertEqual(len(self.open()), 3)
        booking_of(demo, 2)
        booking_of(diagnostic, 2, booking_type=DIAGNOSTIC)
        booking_of(cancelled, 2, status=BookingStatus.CANCELLED)
        # The enquiry's own status decides: Demo booked, Diagnostic booked, or any other but New.
        statuses = dict(with_status(Lead.objects.filter(pk__in=[demo.pk, diagnostic.pk, cancelled.pk]), NOW)
                        .values_list('pk', 'lead_status'))
        self.assertEqual(statuses, {demo.pk: LeadStatus.DEMO_BOOKED, diagnostic.pk: LeadStatus.DIAGNOSTIC_BOOKED,
                                    cancelled.pk: LeadStatus.DEMO_CANCELLED})
        self.assertEqual(self.open(), [])

    def test_none_for_an_enquiry_the_bde_added_or_one_booked_through_their_link(self):
        self.book()  # through the BDE's link: never New
        create_lead(details('Walk-in', '501110003'), source=LeadSource.WALK_IN, created_by=self.bde, owner=self.bde)
        other = self.book(owned=False)
        assign_owner(other.lead_id, self.bde.pk, actor=self.admin, via='admin_leads', now=NOW)
        self.assertNotIn(FollowUpType.NEW_ENQUIRY_CALL, self.types(self.open()))

    def test_given_to_another_bde_it_moves_and_starts_24_hours_again_while_still_new(self):
        lead = self.new_enquiry(now=NOW)
        moved = NOW + 20 * HOUR
        assign_owner(lead.pk, self.other_bde.pk, actor=self.admin, via='admin_leads', now=moved)
        self.assertEqual(self.open(now=moved), [])
        [item] = self.open(user=self.other_bde, now=moved)
        self.assertEqual((item.id, item.due_at), (lead.id, moved + 24 * HOUR))
        self.assertEqual(len(self.open(user=self.other_bde, now=NOW + 30 * HOUR)), 1)
        # No longer New: given on again, it is no one's reminder.
        booking_of(lead, 2)
        assign_owner(lead.pk, self.bde.pk, actor=self.admin, via='admin_leads', now=moved + HOUR)
        self.assertEqual(self.open(now=moved + HOUR), [])


class ConfirmationTests(FollowUpTestCase):
    def test_from_twelve_hours_before_until_the_parent_answers(self):
        booking = self.ready(self.book())
        due = STARTS - 12 * HOUR
        self.assertEqual(self.open(now=due - timedelta(seconds=1)), [])
        [item] = self.open(now=due)
        self.assertEqual((item.type, item.id, item.due_at, item.request),
                         (FollowUpType.PARENT_CONFIRMATION, booking.id, STARTS, None))
        self.assertEqual(item.actions, {'record_outcome': False, 'request_confirmation': True, 'record_answer': True})
        # Asked: where the request stands is shown, and asking again is not offered.
        request_confirmation(booking, actor=self.bde, owner_bde=self.bde, now=due + HOUR)
        [item] = self.open(now=due + HOUR)
        self.assertEqual((item.request.status, item.actions['request_confirmation']), ('PENDING', False))
        # Answered: gone.
        record_parent_confirmation(booking, ParentConfirmation.CONFIRMED, actor=self.bde, owner_bde=self.bde,
                                   now=due + 2 * HOUR)
        self.assertEqual(self.open(now=due + 2 * HOUR), [])

    def test_not_confirmed_ends_it_and_cancels_the_booking_as_before(self):
        booking = self.book()
        record_parent_confirmation(booking, ParentConfirmation.NOT_CONFIRMED, reason_code='NO_RESPONSE',
                                   confirm_cancellation=True, actor=self.bde, owner_bde=self.bde, now=STARTS - 6 * HOUR)
        self.assertEqual(self.open(now=STARTS - 6 * HOUR), [])
        booking.refresh_from_db()
        self.assertEqual((booking.status, booking.cancel_reason_code),
                         (BookingStatus.CANCELLED, CancelReason.NOT_CONFIRMED))

    def test_gone_when_the_class_starts_or_the_booking_is_cancelled(self):
        self.book()
        cancelled = self.book(at=MORNING)
        cancel_booking(cancelled, reason_code=CancelReason.PARENT_REQUEST, actor=self.admin, now=NOW)
        self.assertEqual(self.kinds(self.open(now=STARTS - HOUR)),
                         [(FollowUpType.PARENT_CONFIRMATION, FollowUpState.DUE_TODAY)])
        self.assertEqual(self.open(now=STARTS), [])

    def test_a_redemo_is_a_reminder_once_scheduled_never_while_only_requested(self):
        after = datetime(2026, 10, 29, 12, 0, tzinfo=BOOKING_TIMEZONE)
        demo = self.ready(self.book())
        self.complete(demo)
        redemo = request_redemo(type(demo).objects.get(pk=demo.pk), 'The parent wants a slower pace.',
                                actor=self.bde, owner_bde=self.bde, now=after)
        self.assertNotIn(FollowUpType.REDEMO_CONFIRMATION, self.types(self.open(now=after)))
        other_tutor = account('tutor_neel', role='TUTOR', tutor_meet_link='https://meet.google.com/xyz-abcd-efg')
        booking = schedule_redemo(redemo, other_tutor, date(2026, 10, 31), EVENING, actor=self.admin, now=after)
        [item] = [item for item in self.open(now=after) if item.type == FollowUpType.REDEMO_CONFIRMATION]
        self.assertEqual((item.id, item.due_at, item.state),
                         (booking.id, booking.slot.starts_at, FollowUpState.PENDING))
        self.assertEqual(item.actions['record_answer'], True)
        self.assertIs(followups.row(item, after)['booking']['redemo'], True)
        record_parent_confirmation(booking, ParentConfirmation.CONFIRMED, actor=self.bde, owner_bde=self.bde, now=after)
        self.assertNotIn(FollowUpType.REDEMO_CONFIRMATION, self.types(self.open(now=after)))


class CallTests(FollowUpTestCase):
    def setUp(self):
        super().setUp()
        self.booking = self.ready(self.book())
        record_parent_confirmation(self.booking, ParentConfirmation.CONFIRMED, actor=self.bde, owner_bde=self.bde,
                                   now=NOW)
        self.call = self.booking.communication_tasks.get(step=Step.PRE_ACTIVITY_CALL)

    def test_from_fifteen_minutes_before_until_the_start_and_never_done_unrecorded(self):
        self.assertEqual(self.open(now=STARTS - timedelta(minutes=16)), [])
        [item] = self.open(now=STARTS - timedelta(minutes=15))
        self.assertEqual((item.type, item.state, item.opens_at, item.due_at), (
            FollowUpType.PRE_ACTIVITY_CALL, FollowUpState.DUE_TODAY, STARTS - timedelta(minutes=15), STARTS))
        # Gone at the start, whether or not the sweep has run -- and the call nobody recorded is Missed.
        self.assertEqual(self.open(now=STARTS), [])
        planner.close_expired(STARTS + timedelta(minutes=3))
        self.call.refresh_from_db()
        self.assertEqual((self.call.status, self.call.resolution), (TaskStatus.MISSED, ''))

    def test_a_recorded_outcome_ends_it_and_is_kept(self):
        record_call_outcome(self.call, TaskResolution.NO_ANSWER, actor=self.bde, owner_bde=self.bde,
                            now=STARTS - timedelta(minutes=5))
        self.assertEqual(self.open(now=STARTS - timedelta(minutes=4)), [])
        planner.close_expired(STARTS)
        self.call.refresh_from_db()
        self.assertEqual((self.call.status, self.call.resolution, self.call.resolved_by),
                         (TaskStatus.DONE, TaskResolution.NO_ANSWER, self.bde))

    def test_gone_once_its_tutor_starts_the_class_early(self):
        self.assertEqual(len(self.open(now=STARTS - timedelta(minutes=5))), 1)
        start(self.booking, minutes=-4)
        self.assertEqual(self.open(now=STARTS - timedelta(minutes=3)), [])


class ReportTests(FollowUpTestCase):
    def submitted(self, booking):
        """``booking`` reported on (as its tutor's Save stamps it, on the real clock): when its report was submitted."""
        self.complete(booking)
        return type(booking).objects.get(pk=booking.pk).report.submitted_at

    def test_a_submitted_report_is_a_reminder_for_24_hours_until_it_is_shared(self):
        booking = self.ready(self.book())
        submitted = self.submitted(booking)
        [item] = self.open(now=submitted)
        self.assertEqual((item.type, item.id, item.booking.pk, item.due_at),
                         (FollowUpType.TUTOR_REPORT, booking.report.pk, booking.pk, submitted + 24 * HOUR))
        self.assertEqual(self.open(now=submitted + 24 * HOUR), [])
        # Shared from the enquiry: gone, and an edit afterwards does not bring it back.
        record_share(type(booking).objects.get(pk=booking.pk), self.bde, now=submitted + HOUR)
        self.assertEqual(self.open(now=submitted + HOUR), [])
        edit_report(booking, self.tutor, report_input(booking, suggested_strategy='Changed.'), 1)
        self.assertEqual(self.open(now=submitted + 2 * HOUR), [])
        share = ReportShare.objects.get()
        self.assertEqual((share.demo_report_id, share.report_version, share.shared_by),
                         (booking.report.pk, 1, self.bde))

    def test_only_for_a_bde_who_may_see_the_reports(self):
        submitted = self.submitted(self.ready(self.book()))
        self.assertEqual(len(self.open(now=submitted)), 1)
        RoleGroup.objects.get(role='BDE').group.permissions.remove(
            Permission.objects.get(codename='view_own_lead_reports'))
        self.bde = type(self.bde).objects.get(pk=self.bde.pk)
        self.assertEqual(self.open(now=submitted), [])


class OwnershipTests(FollowUpTestCase):
    def test_every_reminder_goes_with_the_lead_and_the_bde_before_sees_none(self):
        lead = self.new_enquiry(now=NOW)
        booking = self.book()
        moment = STARTS - 12 * HOUR
        self.assertEqual(sorted(self.types(self.open(now=moment))),
                         [FollowUpType.NEW_ENQUIRY_CALL, FollowUpType.PARENT_CONFIRMATION])
        for lead_id in (lead.pk, booking.lead_id):
            assign_owner(lead_id, self.other_bde.pk, actor=self.admin, via='admin_leads', now=moment)
        self.assertEqual(self.open(now=moment), [])
        self.assertEqual(sorted(self.types(self.open(user=self.other_bde, now=moment))),
                         [FollowUpType.NEW_ENQUIRY_CALL, FollowUpType.PARENT_CONFIRMATION])
        self.assertEqual(set(CommunicationTask.objects.filter(demo_booking=booking, status='OPEN')
                             .values_list('owner', flat=True)), {self.other_bde.pk})


class DueTests(FollowUpTestCase):
    def test_due_today_or_pending_in_indian_days_soonest_first(self):
        now = datetime(2026, 11, 9, 10, 0, tzinfo=BOOKING_TIMEZONE)
        today = self.new_enquiry('Asha', '501110010', now=now - 20 * HOUR)  # due 14:00 today
        later = self.new_enquiry('Bina', '501110011', now=now)  # due 10:00 tomorrow
        items = self.open(now=now)
        self.assertEqual([(item.lead.pk, item.state) for item in items],
                         [(today.pk, FollowUpState.DUE_TODAY), (later.pk, FollowUpState.PENDING)])
        self.assertEqual(followups.summary(items), {'total': 2, 'today': 1, 'upcoming': 1})
        self.assertEqual([item.lead.pk for item in followups.filtered(items, due='upcoming')], [later.pk])
        self.assertEqual(followups.filtered(items, follow_up_type=FollowUpType.TUTOR_REPORT), [])


class ApiTests(FollowUpTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(self.bde)

    def test_a_row_carries_what_is_due_for_which_booking_and_whose_it_is(self):
        self.new_enquiry(now=timezone.now())
        response = self.client.get(URL)
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        self.assertEqual((set(data['summary']), data['summary']['total'], data['count']),
                         ({'total', 'today', 'upcoming'}, 1, 1))
        [row] = data['results']
        # parent_messages: a Re-Demo confirmation's messages to send by hand, null for every other reminder.
        self.assertEqual(set(row), {'id', 'type', 'type_label', 'state', 'state_label', 'due_at', 'opens_at', 'request',
                                    'booking', 'enquiry', 'actions', 'parent_messages'})
        self.assertIsNone(row['parent_messages'])
        self.assertEqual((row['type'], row['type_label'], row['booking']),
                         ('NEW_ENQUIRY_CALL', 'Call new enquiry', None))
        self.assertEqual(set(row['enquiry']),
                         {'id', 'parent_name', 'student_name', 'grade', 'phone', 'phone_dial_code', 'phone_number'})
        self.assertEqual(row['actions'],
                         {'record_outcome': False, 'request_confirmation': False, 'record_answer': False})

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
        call = {row['step']: row for row in response.json()['tasks']}['PRE_ACTIVITY_CALL']
        self.assertEqual((call['status'], call['resolution']), ('DONE', 'NO_ANSWER'))
        other = APIClient()
        other.force_authenticate(self.other_bde)
        self.assertEqual(other.post(url, {'outcome': 'CALLED'}, format='json').status_code, 404)
        CommunicationTask.objects.filter(demo_booking=booking, step=Step.PRE_ACTIVITY_CALL).update(due_at=now - HOUR)
        late = self.client.post(url, {'outcome': 'CALLED'}, format='json')
        self.assertEqual((late.status_code, late.json()['error']), (409, 'CALL_CLOSED'))

    def test_filters_are_checked_and_every_other_caller_is_refused(self):
        response = self.client.get(URL, {'due': 'invalid', 'type': 'REPORT_DISCUSSION', 'enquiry': 'x'})
        self.assertEqual((response.status_code, sorted(response.json()['fields'])), (400, ['due', 'enquiry', 'type']))
        client = APIClient()
        client.force_authenticate(account('root', role='ADMIN', is_superuser=True, is_staff=True))
        self.assertEqual(client.get(URL).json()['error'], 'NOT_A_BDE')
        for role in ('MENTOR', 'TUTOR', 'SALES_TL'):
            with self.subTest(role=role):
                client.force_authenticate(account(role.lower(), role))
                self.assertEqual(client.get(URL).status_code, 403)
        client.force_authenticate(self.admin)
        self.assertEqual(client.get(URL).status_code, 403)
