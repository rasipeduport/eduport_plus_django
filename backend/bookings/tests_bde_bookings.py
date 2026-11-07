"""
A BDE's Demo Bookings and Diagnostic Bookings lists (GET /api/bde/bookings/<type>/):
only the caller's own leads' bookings of that type, filtered as the Admin's
list is, each row written out field by field -- the tutor's name but never
their Meet link, and never who cancelled a booking or why.
"""
from datetime import time

from django.test import TestCase
from rest_framework.test import APIClient

from .models import BookingStatus, BookingType
from .tests_enquiries import account, booking, complete, indian_date, lead

DEMO, DIAGNOSTIC = BookingType.DEMO, BookingType.DIAGNOSTIC
LIST = '/api/bde/bookings/{}/'
ROW_FIELDS = {'id', 'booking_type', 'date', 'time', 'starts_at', 'status', 'activity_state', 'started_at', 'booked_at',
              'tutor', 'parent_confirmation', 'redemo', 'enquiry'}


class BdeBookingListTests(TestCase):
    def setUp(self):
        self.bde = account('bde_a')
        self.other_bde = account('bde_b')
        self.tutor = account('tutor_t', role='TUTOR')
        self.client = APIClient()
        self.client.force_authenticate(self.bde)
        self.riya = lead(self.bde, 'Riya', phone='501000001')
        self.arjun = lead(self.bde, 'Arjun', phone='501000002', parent='Meera Menon')

    def get(self, booking_type='demo', **params):
        return self.client.get(LIST.format(booking_type), params)

    def ids(self, response):
        self.assertEqual(response.status_code, 200, response.content)
        return [row['id'] for row in response.json()['results']]

    def test_each_list_is_the_bdes_own_bookings_of_its_type_soonest_first(self):
        later = booking(self.riya, 3, DEMO)
        sooner = booking(self.arjun, 1, DEMO)
        diagnostic = booking(self.riya, 2, DIAGNOSTIC)
        booking(lead(self.other_bde, 'Sara', phone='502000000'), 1, DEMO, at=time(9, 30))
        booking(lead(None, 'Nobody', phone='503000000'), 1, DEMO, at=time(10, 30))

        response = self.get('demo')
        self.assertEqual(self.ids(response), [str(sooner.id), str(later.id)])
        self.assertEqual(response.json()['count'], 2)
        self.assertEqual(response.json()['timezone'], 'Asia/Kolkata')
        self.assertEqual(self.ids(self.get('diagnostic')), [str(diagnostic.id)])

    def test_the_filters_are_the_admin_lists_less_tutors_slots_and_reports(self):
        upcoming = booking(self.riya, 2, DEMO)
        past = booking(self.arjun, -2, DEMO)
        cancelled = booking(self.arjun, 4, DEMO, status=BookingStatus.CANCELLED)

        self.assertEqual(self.ids(self.get(when='upcoming')), [str(upcoming.id), str(cancelled.id)])
        self.assertEqual(self.ids(self.get(when='past')), [str(past.id)])
        self.assertEqual(self.ids(self.get(status='cancelled')), [str(cancelled.id)])
        day = indian_date().isoformat()
        self.assertEqual(self.ids(self.get(**{'from': day, 'to': day})), [])
        self.assertEqual(set(self.ids(self.get(q='Meera'))), {str(past.id), str(cancelled.id)})
        self.assertEqual(self.ids(self.get(q='501000001')), [str(upcoming.id)])
        # The Admin list's tutor filter is not the BDE's: it is not read.
        self.assertEqual(len(self.ids(self.get(tutor=str(self.tutor.id)))), 3)

        response = self.get(status='LOST', when='later')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['error'], 'INVALID_INPUT')
        self.assertEqual(sorted(response.json()['fields']), ['status', 'when'])

    def test_a_row_names_the_tutor_and_carries_nothing_more(self):
        taught = complete(booking(self.riya, -1, DEMO, started_by=self.tutor))
        type(taught).objects.filter(pk=taught.pk).update(tutor_meet_link='https://meet.google.com/abc-defg-hij')
        cancelled = booking(self.arjun, 2, DEMO, status=BookingStatus.CANCELLED)
        type(cancelled).objects.filter(pk=cancelled.pk).update(cancel_reason='Parent asked', cancelled_by=self.other_bde)

        response = self.get()
        rows = {row['id']: row for row in response.json()['results']}
        for row in rows.values():
            self.assertEqual(set(row), ROW_FIELDS)
        done = rows[str(taught.id)]
        self.assertEqual((done['status'], done['activity_state']), ('COMPLETED', 'COMPLETED'))
        self.assertEqual(done['tutor'], {'full_name': 'Tutor T'})
        self.assertEqual(done['enquiry'],
                         {'id': str(self.riya.id), 'parent_name': 'Asha Nair', 'student_name': 'Riya', 'grade': 'Class 8'})
        self.assertIsNone(rows[str(cancelled.id)]['tutor'])
        self.assertIs(done['redemo'], False)
        # The parent's answer, for a BDE who may see the lead's communication (the BDE role group carries it).
        self.assertEqual(done['parent_confirmation'], taught.parent_confirmation)
        body = response.content.decode()
        self.assertNotIn('meet.google.com', body)
        self.assertNotIn('Parent asked', body)
        self.assertNotIn(str(self.other_bde.id), body)

    def test_it_is_paged(self):
        made = [booking(self.riya, day, DEMO) for day in (1, 2, 3)]
        response = self.get(page=2, page_size=2)
        self.assertEqual(self.ids(response), [str(made[2].id)])
        self.assertEqual((response.json()['count'], response.json()['page'], response.json()['page_size']), (3, 2, 2))

    def test_an_unknown_type_is_not_found(self):
        self.assertEqual(self.get('trial').status_code, 404)


class OtherCallerTests(TestCase):
    """Only an active BDE reaches the lists; a superuser holds the permission (D1) but is told it is not a BDE."""

    def test_every_other_caller_is_refused(self):
        booking(lead(account('bde_a'), 'Riya'), 1, DEMO)
        superuser = account('root', role='ADMIN', is_superuser=True, is_staff=True)
        client = APIClient()
        client.force_authenticate(superuser)
        response = client.get(LIST.format('demo'))
        self.assertEqual((response.status_code, response.json()['error']), (403, 'NOT_A_BDE'))
        for role in ('ADMIN', 'MENTOR', 'TUTOR', 'SALES_TL'):
            with self.subTest(role=role):
                client.force_authenticate(account(role.lower(), role))
                self.assertEqual(client.get(LIST.format('demo')).status_code, 403)
        client.force_authenticate(None)
        self.assertIn(client.get(LIST.format('demo')).status_code, (401, 403))
