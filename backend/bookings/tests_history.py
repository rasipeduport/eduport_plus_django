"""
History (bookings.timeline): each booking change as an entry -- when, what,
who (staff by name and role, the parent, or the system), what changed and
why -- for administrators (any student), the lead's BDE (their own leads,
staff names and reason codes included, the parent's answers and report edits
behind their permissions) and the tutor teaching a booking (it, the bookings
it replaced, and for a Re-Demo the Demos it repeats -- never a request made on
their own booking). Read from the append-only booking history, never kept.
"""
import json
from datetime import timedelta

from django.contrib.auth.models import Permission
from django.db import DatabaseError, transaction

from accounts.models import RoleGroup

from reports.services import edit_report
from reports.tests_services import demo_input

from .booking_service import (
    cancel_booking,
    close_redemo,
    record_parent_confirmation,
    request_redemo,
    reschedule_booking,
    schedule_redemo,
)
from .models import BookingEvent, CancelReason, NotConfirmedReason, ParentConfirmation, RedemoCloseReason, RescheduleReason
from .scheduling import booking_window
from .tests_booking import EVENING, MORNING, account
from .tests_redemos import MEET, REASON, REMARKS, RedemoApiTestCase, complete


def kinds(entries):
    return [entry['kind'] for entry in entries]


class HistoryTestCase(RedemoApiTestCase):
    """
    The Demo, taught by Tutor Orla, sent for a Re-Demo by its BDE; the
    Re-Demo booked by the Admin with Tutor Neel, cancelled (parent asked),
    booked again and moved (tutor unavailable): the student's whole story.
    """

    def setUp(self):
        super().setUp()
        self.redemo = request_redemo(self.demo, REASON, actor=self.bde)
        days = booking_window('DEMO')
        self.first = schedule_redemo(self.redemo, self.tutor, days[1], EVENING, actor=self.admin, remarks=REMARKS)
        cancel_booking(self.first, reason_code=CancelReason.PARENT_REQUEST, actor=self.admin)
        second = schedule_redemo(self.redemo, self.tutor, days[2], EVENING, actor=self.admin)
        self.moved = reschedule_booking(second, days[3], MORNING, reason_code=RescheduleReason.TUTOR_UNAVAILABLE,
                                        actor=self.admin).booking
        self.second = second

    def admin_history(self, booking):
        return self.as_user(self.admin).get(f'/api/bookings/demo/{booking.pk}/history/', {'scope': 'student'})

    def assert_private(self, data):
        """Never the parent's name or number, a Meet link, staff's own words or any report text."""
        text = json.dumps(data, default=str)
        report = self.demo.report
        for hidden in ('Asha Nair', self.lead.phone_number, MEET, REASON, REMARKS,
                       report.assessment_review, report.class_observation_review, report.suggested_strategy):
            self.assertNotIn(hidden, text)


class AdminHistoryTests(HistoryTestCase):
    def test_the_students_whole_history_with_who_and_why(self):
        res = self.admin_history(self.moved)
        self.assertEqual(res.status_code, 200, res.data)
        data = res.data
        self.assertEqual(data['chain_ids'], [str(self.second.pk), str(self.moved.pk)])
        self.assertEqual(len(data['bookings']), 4)
        entries = data['entries']
        self.assertEqual(kinds(entries)[:5], ['CREATED', 'TUTOR_ASSIGNED', 'STARTED', 'COMPLETED', 'REDEMO_REQUESTED'])
        self.assertEqual((entries[0]['by'], entries[0]['actor'], entries[0]['details']['via']),
                         ('PARENT', None, 'public_booking'))
        requested = entries[4]
        self.assertEqual((requested['by'], requested['actor']['full_name'], requested['actor']['role_label'],
                          requested['details']['to_status']), ('STAFF', 'Bde Anil', 'BDE', 'REDEMO_REQUIRED'))
        cancelled = next(entry for entry in entries if entry['kind'] == 'CANCELLED')
        self.assertEqual((cancelled['actor']['full_name'], cancelled['details']['reason']),
                         ('Admin Ops', {'code': 'PARENT_REQUEST', 'label': 'Parent asked to cancel'}))
        moved = next(entry for entry in entries if entry['kind'] == 'RESCHEDULED')
        self.assertEqual((moved['details']['reason']['label'], moved['details']['old_slot']['time'],
                          moved['details']['new_slot']['time']), ('Tutor unavailable', '19:30', '10:00'))
        assigned = [entry for entry in entries if entry['kind'] == 'TUTOR_ASSIGNED' and entry['booking']['redemo']]
        self.assertEqual(assigned[0]['details']['new_tutor'], {'full_name': 'Tutor Neel'})
        self.assert_private(data)
        # The booking's own timeline is as it was.
        own = self.as_user(self.admin).get(f'/api/bookings/demo/{self.moved.pk}/history/').data
        self.assertEqual(set(own), {'booking_id', 'timezone', 'chain', 'events'})
        res = self.as_user(self.admin).get(f'/api/bookings/demo/{self.moved.pk}/history/', {'scope': 'all'})
        self.assertEqual((res.status_code, res.data['fields']), (400, ['scope']))
        for user in (self.bde, self.tutor):
            res = self.as_user(user).get(f'/api/bookings/demo/{self.moved.pk}/history/', {'scope': 'student'})
            self.assertEqual(res.status_code, 403)

    def test_a_closed_request_says_why(self):
        # Nothing may be booked for a request that closes: its last attempt is cancelled first.
        cancel_booking(self.moved, reason_code=CancelReason.PARENT_REQUEST, actor=self.admin)
        close_redemo(self.redemo, RedemoCloseReason.PARENT_DECLINED, actor=self.bde, owner_bde=self.bde)
        entries = self.admin_history(self.demo).data['entries']
        closed = entries[-1]
        self.assertEqual((closed['kind'], closed['actor']['full_name'], closed['details']['reason']['label']),
                         ('REDEMO_CLOSED', 'Bde Anil', 'Parent declined'))
        # Still append-only: the database refuses to rewrite or delete an event.
        event = BookingEvent.objects.filter(kind='REDEMO_CLOSED').get()
        with self.assertRaises(DatabaseError):
            with transaction.atomic():
                BookingEvent.objects.filter(pk=event.pk).update(kind='CREATED')
        with self.assertRaises(DatabaseError):
            with transaction.atomic():
                BookingEvent.objects.filter(pk=event.pk).delete()
        self.assertEqual(BookingEvent.objects.get(pk=event.pk).kind, 'REDEMO_CLOSED')


class BdeHistoryTests(HistoryTestCase):
    def history(self, user=None):
        return self.as_user(user or self.bde).get(f'/api/bde/enquiries/{self.lead.pk}/history/')

    def test_their_own_leads_history_with_staff_names_and_reason_codes(self):
        res = self.history()
        self.assertEqual(res.status_code, 200, res.data)
        entries = res.data['entries']
        cancelled = next(entry for entry in entries if entry['kind'] == 'CANCELLED')
        self.assertEqual((cancelled['actor']['full_name'], cancelled['actor']['role'], cancelled['details']['reason']['code']),
                         ('Admin Ops', 'ADMIN', 'PARENT_REQUEST'))
        self.assertEqual(res.data['chain_ids'], [])
        self.assertEqual(len(res.data['bookings']), 4)
        # Ids an administrator's screens link by are left out.
        self.assertTrue(all('redemo_request_id' not in entry['details'] for entry in entries))
        self.assert_private(res.data)
        self.assertEqual(self.history(self.other_bde).status_code, 404)
        self.assertEqual(self.history(self.admin).status_code, 403)
        # The activity feed stays as it was: by you or not, never who or why.
        feed = self.as_user(self.bde).get('/api/bde/activity/').data['results']
        row = next(row for row in feed if row['kind'] == 'CANCELLED')
        self.assertEqual((row['by_you'], row['detail']), (False, {}))

    def test_the_parents_answers_follow_the_communications_permission(self):
        # Not Confirmed: the answer, and the cancellation it makes, whose reason is the answer too.
        record_parent_confirmation(self.moved, ParentConfirmation.NOT_CONFIRMED, reason_code=NotConfirmedReason.NO_RESPONSE,
                                   confirm_cancellation=True, actor=self.bde)
        entries = self.history().data['entries']
        self.assertIn('PARENT_NOT_CONFIRMED', kinds(entries))
        cancelled = [entry for entry in entries if entry['kind'] == 'CANCELLED']
        self.assertEqual(cancelled[-1]['details']['reason']['code'], 'NOT_CONFIRMED')
        group = RoleGroup.objects.select_related('group').get(role='BDE').group
        group.permissions.remove(Permission.objects.get(codename='view_own_lead_communications'))
        entries = self.history().data['entries']
        self.assertNotIn('PARENT_NOT_CONFIRMED', kinds(entries))
        cancelled = [entry for entry in entries if entry['kind'] == 'CANCELLED']
        # The cancellation stays, without the answer it would give away; the parent's request to cancel keeps its reason.
        self.assertNotIn('reason', cancelled[-1]['details'])
        self.assertEqual(cancelled[0]['details']['reason']['code'], 'PARENT_REQUEST')
        self.assertNotIn('Parent did not confirm', json.dumps(entries))

    def test_report_edits_follow_the_reports_permission(self):
        edit_report(self.demo, self.original_tutor, demo_input(assessment_review='Sharper now.'), self.demo.report.version)
        self.assertIn('REPORT_EDITED', kinds(self.history().data['entries']))
        group = RoleGroup.objects.select_related('group').get(role='BDE').group
        group.permissions.remove(Permission.objects.get(codename='view_own_lead_reports'))
        self.assertNotIn('REPORT_EDITED', kinds(self.history().data['entries']))


class TutorHistoryTests(HistoryTestCase):
    def history(self, booking, user):
        return self.as_user(user).get(f'/api/tutor/bookings/demo/{booking.pk}/history/')

    def setUp(self):
        super().setUp()
        self.lead.refresh_from_db()

    def test_the_redemo_tutor_reads_their_booking_its_moves_and_the_demo_it_repeats(self):
        res = self.history(self.moved, self.tutor)
        self.assertEqual(res.status_code, 200, res.data)
        booking_ids = {entry['booking']['id'] for entry in res.data['entries']}
        self.assertEqual(booking_ids, {str(self.demo.pk), str(self.second.pk), str(self.moved.pk)})
        # The request the Demo was sent for is part of this Re-Demo's story; the cancelled attempt is not theirs.
        self.assertIn('REDEMO_REQUESTED', kinds(res.data['entries']))
        self.assertNotIn(str(self.first.pk), booking_ids)
        moved = next(entry for entry in res.data['entries'] if entry['kind'] == 'RESCHEDULED')
        self.assertEqual((moved['actor']['full_name'], moved['details']['reason']['code']),
                         ('Admin Ops', 'TUTOR_UNAVAILABLE'))
        self.assertEqual(res.data['chain_ids'], sorted([str(self.second.pk), str(self.moved.pk)]))
        self.assert_private(res.data)
        # Who asked for the Re-Demo and who scheduled it is never named to its tutor: staff, unnamed.
        requested = next(entry for entry in res.data['entries'] if entry['kind'] == 'REDEMO_REQUESTED')
        scheduled = next(entry for entry in res.data['entries']
                         if entry['kind'] == 'CREATED' and entry['details'].get('via') == 'redemo')
        assigned = next(entry for entry in res.data['entries']
                        if entry['kind'] == 'TUTOR_ASSIGNED' and entry['details'].get('via') == 'redemo')
        for entry in (requested, scheduled, assigned):
            self.assertEqual((entry['by'], entry['actor']), ('STAFF', None))
        self.assertNotIn('Bde Anil', json.dumps(res.data))

    def test_the_tutor_never_reads_the_parents_answers(self):
        record_parent_confirmation(self.moved, ParentConfirmation.CONFIRMED, actor=self.bde)
        res = self.history(self.moved, self.tutor)
        self.assertNotIn('PARENT_CONFIRMED', kinds(res.data['entries']))
        record_parent_confirmation(self.moved, ParentConfirmation.NOT_CONFIRMED, reason_code=NotConfirmedReason.NO_RESPONSE,
                                   confirm_cancellation=True, actor=self.bde)
        entries = self.history(self.moved, self.tutor).data['entries']
        self.assertNotIn('PARENT_NOT_CONFIRMED', kinds(entries))
        self.assertNotIn('reason', [entry for entry in entries if entry['kind'] == 'CANCELLED'][-1]['details'])

    def test_a_redemo_of_a_redemo_hides_each_request_from_the_tutor_whose_booking_it_was_made_on(self):
        taught = complete(self.moved, self.tutor)
        second = request_redemo(taught, 'Once more.', actor=self.admin)
        later = schedule_redemo(second, account('tutor_tara', role='TUTOR'), booking_window('DEMO')[4], EVENING,
                                actor=self.admin)
        # The Re-Demo's own tutor: the request made on their booking is not theirs.
        own = self.history(taught, self.tutor).data['entries']
        self.assertNotIn('REDEMO_REQUESTED', [entry['kind'] for entry in own if entry['booking']['id'] == str(taught.pk)])
        # The next Re-Demo's tutor reads both requests -- each repeats a Demo they teach again -- naming nobody.
        res = self.history(later, later.assigned_tutor)
        requested = [entry for entry in res.data['entries'] if entry['kind'] == 'REDEMO_REQUESTED']
        self.assertEqual({entry['booking']['id'] for entry in requested}, {str(self.demo.pk), str(taught.pk)})
        self.assertTrue(all(entry['actor'] is None for entry in requested))
        self.assert_private(res.data)

    def test_the_original_tutor_never_sees_the_request_made_on_their_demo(self):
        res = self.history(self.demo, self.original_tutor)
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(kinds(res.data['entries']), ['CREATED', 'TUTOR_ASSIGNED', 'STARTED', 'COMPLETED'])
        self.assertEqual([booking['status'] for booking in res.data['bookings']], ['COMPLETED'])
        self.assertEqual(self.history(self.moved, self.original_tutor).status_code, 404)
        self.assertEqual(self.history(self.demo, account('tutor_zed', role='TUTOR')).status_code, 404)
