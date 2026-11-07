"""
A BDE's activity (GET /api/bde/activity/, bookings.bde_activity): their own
leads' bookings' history only, newest first -- what happened, to which booking
and whose, and whether it was the BDE's own doing; never who else did it, nor
why a booking was cancelled, moved or not confirmed.
"""
from django.test import TestCase
from rest_framework.test import APIClient

from . import bde_activity, history
from .models import BookingEventKind, BookingSlot, Lead
from .tests_enquiries import account, booking, lead

URL = '/api/bde/activity/'


class ActivityTests(TestCase):
    def setUp(self):
        self.bde = account('bde_a')
        self.other_bde = account('bde_b')
        self.admin = account('admin_a', role='ADMIN')
        self.client = APIClient()
        self.client.force_authenticate(self.bde)
        self.riya = lead(self.bde, 'Riya', phone='501000001')

    def rows(self, response):
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()['results']

    def test_the_history_of_the_bdes_own_leads_bookings_newest_first(self):
        mine = booking(self.riya, 2)
        booked = history.record(mine, BookingEventKind.CREATED, slot_id=mine.slot_id, seat=1, via='public_booking')
        theirs = booking(lead(self.other_bde, 'Sara', phone='502000000'), 2)
        history.record(theirs, BookingEventKind.CREATED, slot_id=theirs.slot_id, seat=1, via='public_booking')
        moved_lead = lead(self.other_bde, 'Arjun', phone='501000002')
        moved = booking(moved_lead, 3)
        started = history.record(moved, BookingEventKind.STARTED, actor=self.admin)
        Lead.objects.filter(pk=moved_lead.pk).update(owner_bde=self.bde)

        rows = self.rows(self.client.get(URL))
        self.assertEqual([row['id'] for row in rows], [str(started.id), str(booked.id)])
        self.assertEqual(rows[1]['detail'], {'origin': 'public_booking'})
        self.assertEqual(rows[1]['enquiry']['student_name'], 'Riya')
        self.assertEqual([row['id'] for row in self.rows(self.client.get(URL, {'enquiry': str(moved_lead.id)}))], [str(started.id)])
        self.assertEqual(self.client.get(URL, {'enquiry': 'x'}).status_code, 400)

    def test_never_who_else_did_it_nor_why(self):
        mine = booking(self.riya, 2)
        history.record(mine, BookingEventKind.CANCELLED, actor=self.admin, reason_code='PARENT_REQUEST')
        mine_too = booking(self.riya, 4)
        new_slot = booking(lead(self.bde, 'Kavya', phone='501000003'), 5).slot
        history.record(mine_too, BookingEventKind.RESCHEDULED, actor=self.admin, reason_code='TUTOR_UNAVAILABLE',
                       old_slot_id=mine_too.slot_id, new_slot_id=new_slot.id)
        history.record(mine_too, BookingEventKind.REDEMO_REQUESTED, actor=self.bde)

        response = self.client.get(URL)
        rows = {row['kind']: row for row in self.rows(response)}
        for row in rows.values():
            self.assertEqual(set(row), {'id', 'kind', 'kind_label', 'at', 'by_you', 'detail', 'booking', 'enquiry'})
        self.assertEqual(rows['CANCELLED']['detail'], {})
        self.assertIs(rows['CANCELLED']['by_you'], False)
        self.assertIs(rows['REDEMO_REQUESTED']['by_you'], True)
        slot = BookingSlot.objects.get(pk=new_slot.id)
        self.assertEqual(rows['RESCHEDULED']['detail'],
                         {'to': {'date': slot.local_date.isoformat(), 'time': slot.local_time.strftime('%H:%M')}})
        body = response.content.decode()
        for secret in ('PARENT_REQUEST', 'TUTOR_UNAVAILABLE', str(self.admin.id), 'Admin A'):
            self.assertNotIn(secret, body)

    def test_the_parents_answers_and_report_edits_need_their_own_permissions(self):
        mine = booking(self.riya, 2)
        history.record(mine, BookingEventKind.PARENT_NOT_CONFIRMED, actor=self.bde, reason_code='NO_RESPONSE')
        history.record(mine, BookingEventKind.STARTED, actor=self.admin)
        kinds = lambda **shown: {e.kind for e in bde_activity.own_events(self.bde, **shown)}  # noqa: E731
        self.assertEqual(kinds(show_communication=True, show_reports=True), {'PARENT_NOT_CONFIRMED', 'STARTED'})
        self.assertEqual(kinds(show_communication=False, show_reports=True), {'STARTED'})

    def test_every_other_caller_is_refused(self):
        client = APIClient()
        client.force_authenticate(account('root', role='ADMIN', is_superuser=True, is_staff=True))
        self.assertEqual(client.get(URL).json()['error'], 'NOT_A_BDE')
        for role in ('MENTOR', 'TUTOR', 'SALES_TL'):
            with self.subTest(role=role):
                client.force_authenticate(account(role.lower(), role))
                self.assertEqual(client.get(URL).status_code, 403)
        client.force_authenticate(self.admin)
        self.assertEqual(client.get(URL).status_code, 403)
