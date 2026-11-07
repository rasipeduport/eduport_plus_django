"""
The administrators' Admissions Dashboard (bookings.admissions,
GET /api/admissions/dashboard/): who may read it, the span of Indian dates it
counts, and that every count is the one the list it opens would show.
"""
from datetime import datetime, time, timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from activity.models import ActivityLog

from . import admissions
from .models import BookingStatus, BookingType, Lead, ParentConfirmation
from .scheduling import BOOKING_TIMEZONE, indian_today
from .tests_enquiries import account, booking, complete, lead

DEMO, DIAGNOSTIC = BookingType.DEMO, BookingType.DIAGNOSTIC
DASHBOARD = '/api/admissions/dashboard/'


def received(of, days_ago, minutes=12 * 60):
    """``of`` as if it came in ``days_ago`` Indian days ago, ``minutes`` after that day's midnight in India."""
    day = indian_today() - timedelta(days=days_ago)
    at = datetime.combine(day, time.min, tzinfo=BOOKING_TIMEZONE) + timedelta(minutes=minutes)
    Lead.objects.filter(pk=of.pk).update(created_at=at)
    return of


class AdmissionsTestCase(TestCase):
    def setUp(self):
        self.admin = account('admin_ops', role='ADMIN')
        self.bde = account('bde_anil')
        self.tutor = account('tutor_tara', role='TUTOR')
        self.client = APIClient()
        self.client.force_authenticate(self.admin)

    def read(self, **params):
        res = self.client.get(DASHBOARD, params)
        self.assertEqual(res.status_code, 200, res.content)
        return res.json()


class AdmissionsAccessTests(AdmissionsTestCase):
    def test_only_administrators_read_it(self):
        for role in ('BDE', 'TUTOR', 'MENTOR', 'SALES_TL'):
            client = APIClient()
            client.force_authenticate(self.bde if role == 'BDE' else account(f'user_{role.lower()}', role=role))
            with self.subTest(role=role):
                self.assertEqual(client.get(DASHBOARD).status_code, 403)
        self.assertIn(APIClient().get(DASHBOARD).status_code, (401, 403))

    def test_bad_dates_are_refused_and_named(self):
        today = indian_today()
        cases = [
            ({'from': '08-11-2026', 'to': '2026-11-08'}, ['from']),
            ({'from': today.isoformat()}, ['to']),
            ({'to': today.isoformat()}, ['from']),
            ({'from': today.isoformat(), 'to': (today - timedelta(days=1)).isoformat()}, ['to']),
            ({'from': (today - timedelta(days=admissions.MAX_DAYS)).isoformat(), 'to': today.isoformat()}, ['to']),
        ]
        for params, fields in cases:
            with self.subTest(params=params):
                res = self.client.get(DASHBOARD, params)
                self.assertEqual((res.status_code, res.json()['error'], res.json()['fields']), (400, 'INVALID_INPUT', fields))


class AdmissionsLeadTests(AdmissionsTestCase):
    def test_the_last_seven_indian_days_by_default(self):
        today = indian_today()
        data = self.read()
        self.assertEqual(data['range'], {'from': (today - timedelta(days=6)).isoformat(), 'to': today.isoformat()})
        self.assertEqual(data['timezone'], 'Asia/Kolkata')

    def test_leads_that_came_in_on_the_span_and_where_each_stands(self):
        fresh = received(lead(None, 'Fresh', phone='501000001'), 0)
        booked = received(lead(self.bde, 'Booked', phone='501000002'), 1)
        booking(booked, 2, DIAGNOSTIC)
        done = received(lead(self.bde, 'Done', phone='501000003'), 3)
        complete(booking(done, -1, DEMO, started_by=self.tutor))
        missed = received(lead(None, 'Missed', phone='501000004'), 6, minutes=5)
        booking(missed, -1, DEMO, at=time(9, 0))
        dropped = received(lead(None, 'Dropped', phone='501000005'), 2)
        booking(dropped, 1, DEMO, status=BookingStatus.CANCELLED)
        # Before the span: its last minutes in India are the day before the first.
        received(lead(None, 'Earlier', phone='501000006'), 7, minutes=24 * 60 - 5)

        data = self.read()
        self.assertEqual(data['leads'], {'received': 5, 'new': 1})
        self.assertEqual([(row['stage'], row['count']) for row in data['pipeline']],
                         [('NEW', 1), ('BOOKED', 1), ('COMPLETED', 1), ('NOT_STARTED', 1), ('CANCELLED', 1)])
        self.assertEqual(sum(row['count'] for row in data['pipeline']), data['leads']['received'])

        # One day: only what came in on it.
        today = indian_today().isoformat()
        self.assertEqual(self.read(**{'from': today, 'to': today})['leads'], {'received': 1, 'new': 1})
        self.assertEqual(fresh.student_name, 'Fresh')

    def test_the_latest_leads_whatever_the_span(self):
        for number in range(8):
            received(lead(None, f'Child {number}', phone=f'50100010{number}'), 30 + number)
        rows = self.read()['recent_leads']
        self.assertEqual([row['student_name'] for row in rows], [f'Child {number}' for number in range(6)])
        self.assertIn('owner', rows[0])


class AdmissionsBookingTests(AdmissionsTestCase):
    def setUp(self):
        super().setUp()
        self.riya = lead(self.bde, 'Riya', phone='501000011')
        self.ali = lead(None, 'Ali', phone='501000012')

    def test_bookings_for_classes_on_the_span_that_hold_their_seat(self):
        booking(self.riya, 0, DEMO)
        complete(booking(self.riya, -2, DEMO, started_by=self.tutor))
        booking(self.riya, -1, DEMO, status=BookingStatus.CANCELLED)
        booking(self.ali, -3, DIAGNOSTIC)
        booking(self.ali, -30, DIAGNOSTIC)
        booking(self.ali, 5, DIAGNOSTIC)
        data = self.read()
        self.assertEqual(data['bookings']['DEMO']['total'], 2)
        self.assertEqual(data['bookings']['DIAGNOSTIC']['total'], 1)

    def test_what_awaits_an_administrator(self):
        booking(self.riya, 2, DEMO)                                  # needs a tutor, awaiting confirmation
        booking(self.ali, 3, DIAGNOSTIC)                             # needs a tutor, awaiting confirmation
        confirmed = booking(self.ali, 4, DEMO, started_by=None)
        type(confirmed).objects.filter(pk=confirmed.pk).update(
            assigned_tutor=self.tutor, tutor_assigned_at=timezone.now(),
            parent_confirmation=ParentConfirmation.CONFIRMED, parent_confirmation_at=timezone.now(),
        )
        booking(self.riya, -1, DIAGNOSTIC, started_by=self.tutor)    # started, over, no report: report due
        booking(self.riya, -2, DEMO)                                 # over, never started: not a report
        pending = self.read()['pending']
        self.assertEqual(pending['unassigned_leads'], 1)
        self.assertEqual(pending['needs_tutor'], {'DEMO': 1, 'DIAGNOSTIC': 1})
        self.assertEqual(pending['report_due'], {'DEMO': 0, 'DIAGNOSTIC': 1})
        self.assertEqual(pending['awaiting_confirmation'], {'DEMO': 1, 'DIAGNOSTIC': 1})
        self.assertEqual(pending['redemo_scheduling'], 0)

    def test_each_count_is_what_its_list_shows(self):
        booking(self.riya, 2, DEMO)
        booking(self.ali, -1, DIAGNOSTIC, started_by=self.tutor)
        pending = self.read()['pending']
        lists = {
            ('needs_tutor', 'DEMO'): ('/api/bookings/demo/', {'status': 'BOOKED', 'assigned': 'false', 'when': 'upcoming'}),
            ('report_due', 'DIAGNOSTIC'): ('/api/bookings/diagnostic/', {'report': 'due'}),
        }
        for (key, booking_type), (path, params) in lists.items():
            with self.subTest(key=key):
                self.assertEqual(self.client.get(path, params).json()['count'], pending[key][booking_type])
        self.assertEqual(self.client.get('/api/leads/', {'owner': 'unassigned'}).json()['count'], pending['unassigned_leads'])

    def test_todays_bookings_soonest_first_as_the_lists_show_them(self):
        evening = booking(self.riya, 0, DEMO)
        morning = booking(self.ali, 0, DIAGNOSTIC, at=time(9, 0))
        booking(self.ali, 0, DEMO, status=BookingStatus.CANCELLED, at=time(11, 0))
        booking(self.riya, 1, DEMO)
        today = self.read()['today_bookings']
        self.assertEqual((today['date'], today['total']), (indian_today().isoformat(), 2))
        self.assertEqual([row['id'] for row in today['rows']], [str(morning.id), str(evening.id)])
        self.assertEqual(
            {key: today['rows'][0][key] for key in ('booking_type', 'student_name', 'status', 'tutor')},
            {'booking_type': 'DIAGNOSTIC', 'student_name': 'Ali', 'status': 'BOOKED', 'tutor': None},
        )

    def test_without_every_booking_the_booking_parts_are_left_out(self):
        today = indian_today()
        data = admissions.dashboard(timezone.now(), today, today, user=self.admin)
        self.assertEqual((data['bookings'], data['today_bookings'], data['activity']), (None, None, None))
        self.assertEqual(
            data['pending'],
            {'unassigned_leads': 1, 'needs_tutor': None, 'report_due': None, 'redemo_scheduling': None,
             'awaiting_confirmation': None},
        )
        shown = admissions.dashboard(timezone.now(), today, today, user=self.admin, show_bookings=True)
        self.assertIsNone(shown['pending']['awaiting_confirmation'])
        self.assertEqual(shown['pending']['needs_tutor'], {'DEMO': 0, 'DIAGNOSTIC': 0})


class AdmissionsActivityTests(AdmissionsTestCase):
    def test_the_latest_admissions_activity_only(self):
        for action, entity in (('lead.create', 'lead'), ('student.create', 'student'), ('booking.create', 'booking'),
                               ('session.create', 'session'), ('booking_slot.close', 'booking_slot')):
            ActivityLog.objects.create(action=action, entity_type=entity, entity_id=action, actor=self.admin)
        rows = self.read()['activity']
        self.assertEqual({row['entity_type'] for row in rows}, {'lead', 'booking', 'booking_slot'})
        self.assertEqual(rows[0]['action'], 'booking_slot.close', 'newest first')
