"""
A BDE's follow-ups (GET /api/bde/follow-ups/, communications.followups): the
open communication steps of their own leads' bookings only -- following the
lead's owner now, not the task's recorded owner -- soonest due first, in
Indian days, each row written out field by field.
"""
from datetime import datetime, timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from bookings.models import BookingType, Lead
from bookings.scheduling import BOOKING_TIMEZONE
from bookings.tests_enquiries import account, booking, lead

from . import followups
from .models import CommunicationTask, OwnerRole, Step, TaskStatus

URL = '/api/bde/follow-ups/'
DEMO = BookingType.DEMO


def task(of, step, due_at=None, status=TaskStatus.OPEN, owner=None):
    """A communication step of booking ``of``, owned by ``owner`` (a BDE) or the Admin."""
    field = 'demo_booking' if of.booking_type == DEMO else 'diagnostic_booking'
    return CommunicationTask.objects.create(
        **{field: of}, step=step, owner_role=OwnerRole.BDE if owner else OwnerRole.ADMIN, owner=owner,
        due_at=due_at, status=status, resolved_at=timezone.now() if status != TaskStatus.OPEN else None,
    )


class FollowUpTests(TestCase):
    def setUp(self):
        self.bde = account('bde_a')
        self.other_bde = account('bde_b')
        self.client = APIClient()
        self.client.force_authenticate(self.bde)

    def ids(self, response):
        self.assertEqual(response.status_code, 200, response.content)
        return [row['id'] for row in response.json()['results']]

    def test_the_open_steps_of_the_bdes_own_leads_soonest_first_following_the_lead_owner(self):
        now = timezone.now()
        mine = booking(lead(self.bde, 'Riya', phone='501000001'), 2)
        later = task(mine, Step.PARENT_CONFIRMATION, now + timedelta(days=3), owner=self.bde)
        sooner = task(mine, Step.CONFIRMATION_REQUEST, now + timedelta(hours=1), owner=self.bde)
        task(mine, Step.ACKNOWLEDGEMENT, now - timedelta(days=1), status=TaskStatus.MISSED, owner=self.bde)
        task(booking(lead(self.other_bde, 'Sara', phone='502000000'), 2), Step.CONFIRMATION_REQUEST, now, owner=self.other_bde)
        # Given to this BDE after its steps were made: the steps still name the BDE before.
        moved_lead = lead(self.other_bde, 'Arjun', phone='501000002')
        moved = task(booking(moved_lead, 3), Step.CONFIRMATION_REQUEST, now + timedelta(hours=2), owner=self.other_bde)
        Lead.objects.filter(pk=moved_lead.pk).update(owner_bde=self.bde)

        response = self.client.get(URL)
        self.assertEqual(self.ids(response), [str(sooner.id), str(moved.id), str(later.id)])
        self.assertEqual(response.json()['summary']['total'], 3)
        self.assertEqual(self.ids(self.client.get(URL, {'enquiry': str(moved_lead.id)})), [str(moved.id)])
        self.assertEqual(self.ids(self.client.get(URL, {'step': 'parent_confirmation'})), [str(later.id)])
        other = APIClient()
        other.force_authenticate(self.other_bde)
        self.assertEqual(self.ids(other.get(URL)), [str(task.id) for task in CommunicationTask.objects.filter(
            demo_booking__lead__owner_bde=self.other_bde, status=TaskStatus.OPEN)])

    def test_due_is_counted_in_indian_days_and_the_call_is_never_overdue(self):
        now = datetime(2026, 11, 9, 10, 0, tzinfo=BOOKING_TIMEZONE)
        mine = booking(lead(self.bde, 'Riya'), 2)
        overdue = task(mine, Step.CONFIRMATION_REQUEST, now - timedelta(hours=2), owner=self.bde)
        today = task(mine, Step.PARENT_CONFIRMATION, now + timedelta(hours=13), owner=self.bde)
        tomorrow = task(mine, Step.ACKNOWLEDGEMENT, now + timedelta(hours=15), owner=self.bde)
        untimed = task(mine, Step.AFTER_ACTIVITY, None, owner=self.bde)
        call = task(mine, Step.PRE_ACTIVITY_CALL, now - timedelta(minutes=5), owner=self.bde)
        tasks = followups.own_open_tasks(self.bde)

        self.assertEqual(followups.summary(tasks, now), {'total': 5, 'overdue': 1, 'today': 2, 'upcoming': 2})
        due = lambda name: {t.id for t in followups.filtered(tasks, now, due=name)}  # noqa: E731
        self.assertEqual(due('overdue'), {overdue.id})
        self.assertEqual(due('today'), {today.id, call.id})
        self.assertEqual(due('upcoming'), {tomorrow.id, untimed.id})
        self.assertIs(followups.followup_row(call, now)['overdue'], False)
        self.assertIs(followups.followup_row(overdue, now)['overdue'], True)

    def test_a_row_carries_nothing_more_than_the_step_the_booking_and_whose_it_is(self):
        mine = booking(lead(self.bde, 'Riya'), 2)
        task(mine, Step.CONFIRMATION_REQUEST, timezone.now() + timedelta(hours=1), owner=self.bde)
        [row] = self.client.get(URL).json()['results']
        self.assertEqual(set(row), {'id', 'step', 'step_label', 'active_from', 'due_at', 'expires_at', 'overdue', 'booking', 'enquiry'})
        self.assertEqual(set(row['booking']), {'id', 'booking_type', 'date', 'time', 'starts_at', 'status', 'activity_state'})
        self.assertEqual(set(row['enquiry']),
                         {'id', 'parent_name', 'student_name', 'grade', 'phone', 'phone_dial_code', 'phone_number'})

    def test_filters_are_checked_and_every_other_caller_is_refused(self):
        response = self.client.get(URL, {'due': 'soon', 'step': 'NOPE', 'enquiry': 'x'})
        self.assertEqual((response.status_code, sorted(response.json()['fields'])), (400, ['due', 'enquiry', 'step']))
        client = APIClient()
        client.force_authenticate(account('root', role='ADMIN', is_superuser=True, is_staff=True))
        self.assertEqual(client.get(URL).json()['error'], 'NOT_A_BDE')
        for role in ('ADMIN', 'MENTOR', 'TUTOR', 'SALES_TL'):
            with self.subTest(role=role):
                client.force_authenticate(account(role.lower(), role))
                self.assertEqual(client.get(URL).status_code, 403)
