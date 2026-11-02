"""
The Admin's report APIs (reports.management_views, design E.1, D17): reading a
booking's report and its versions; who reaches them; that nobody writes there;
and the report fields and filter on the Admin's booking list and detail.
"""
import uuid
from datetime import timedelta

from django.utils import timezone

from bookings.booking_service import cancel_booking, create_booking
from bookings.models import BookingStatus, CancelReason, DemoBooking
from bookings.scheduling import indian_today
from bookings.tests_booking import EVENING, MORNING, account, request

from .models import DemoReport
from .tests_tutor_api import TutorReportApiTestCase, path_type, report_url


def admin_url(booking, suffix=''):
    return f'/api/bookings/{path_type(booking)}/{booking.id}/report/{suffix}'


def admin_detail_url(booking):
    return f'/api/bookings/{path_type(booking)}/{booking.id}/'


class AdminReportApiTestCase(TutorReportApiTestCase):
    def setUp(self):
        super().setUp()
        self.admin = account('admin_ops', role='ADMIN')

    def as_tutor(self):
        self.client.force_authenticate(self.tutor)

    def as_admin(self):
        self.client.force_authenticate(self.admin)


class AdminReportReadTests(AdminReportApiTestCase):
    def test_the_admin_reads_each_report_and_its_versions_as_the_tutor_does(self):
        for booking in (self.diagnostic, self.demo):
            with self.subTest(booking_type=booking.booking_type):
                self.as_tutor()
                self.submit(booking)
                field = next(iter(self.client.get(report_url(booking)).json()['fields']))
                self.edit(booking, 1, **{field: 20 if field == 'score' else 'Revised after the session.'})
                tutors_report = self.client.get(report_url(booking)).json()
                tutors_history = self.client.get(report_url(booking, 'revisions/')).json()

                self.as_admin()
                report = self.client.get(admin_url(booking))
                self.assertEqual(report.status_code, 200, report.content)
                self.assertEqual(report.json(), tutors_report)
                self.assertEqual(report.json()['version'], 2)
                history = self.client.get(admin_url(booking, 'revisions/')).json()
                self.assertEqual(history, tutors_history)
                self.assertEqual([row['version'] for row in history['results']], [1, 2])

    def test_no_report_and_no_booking_are_told_apart(self):
        self.as_admin()
        for url in (admin_url(self.demo), admin_url(self.demo, 'revisions/')):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual((response.status_code, response.json()['error']), (404, 'NO_REPORT'))
        for url in (f'/api/bookings/demo/{uuid.uuid4()}/report/', f'/api/bookings/demo/{self.diagnostic.id}/report/'):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual((response.status_code, response.json()['error']), (404, 'NOT_FOUND'))
        self.assertEqual(self.client.get(f'/api/bookings/webinar/{self.demo.id}/report/').status_code, 404)


class AdminReportAccessTests(AdminReportApiTestCase):
    def setUp(self):
        super().setUp()
        self.as_tutor()
        self.submit(self.demo)

    def test_only_those_who_see_every_booking_read_its_report(self):
        callers = {
            'the assigned tutor': self.tutor,
            'mentor': account('mentor_one', role='MENTOR'),
            'bde': account('bde_one', role='BDE'),
            'sales_tl': account('sales_tl_one', role='SALES_TL'),
            'anonymous': None,
        }
        for name, caller in callers.items():
            self.client.force_authenticate(caller)
            for url in (admin_url(self.demo), admin_url(self.demo, 'revisions/')):
                with self.subTest(caller=name, url=url):
                    self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_authenticate(account('root', role='ADMIN', is_superuser=True, is_staff=True))
        self.assertEqual(self.client.get(admin_url(self.demo)).json()['version'], 1)

    def test_nobody_writes_a_report_here(self):
        self.as_admin()
        for method in ('post', 'put', 'patch', 'delete'):
            with self.subTest(method=method):
                response = getattr(self.client, method)(admin_url(self.demo), {'assessment_review': 'Admin text.'}, format='json')
                self.assertEqual(response.status_code, 405)
        report = DemoReport.objects.get()
        self.assertEqual((report.version, report.assessment_review), (1, 'Quick with mental arithmetic.'))


class AdminBookingReportFieldTests(AdminReportApiTestCase):
    def detail(self, booking):
        return self.client.get(admin_detail_url(booking)).json()

    def test_the_detail_names_the_report_and_offers_no_change_once_completed(self):
        self.as_admin()
        before = self.detail(self.demo)
        self.assertEqual(
            (before['report'], before['has_report'], before['report_version'], before['report_due']),
            (None, False, None, True),
        )
        self.as_tutor()
        submitted = self.submit(self.demo).json()['report']
        self.edit(self.demo, 1, suggested_strategy='A new plan.')
        self.as_admin()
        after = self.detail(self.demo)
        self.assertEqual((after['status'], after['has_report'], after['report_version'], after['report_due']),
                         ('COMPLETED', True, 2, False))
        self.assertEqual(after['report'], {
            'id': submitted['id'], 'version': 2, 'submitted_at': submitted['submitted_at'],
            'submitted_by': {'id': str(self.tutor.id), 'full_name': 'Tutor Anu'}, 'updated_at': after['report']['updated_at'],
        })
        self.assertGreater(after['report']['updated_at'], submitted['submitted_at'])
        self.assertEqual(after['actions'], {'cancel': False, 'no_show': False, 'reschedule': False})

    def test_the_history_names_the_completion_and_each_edit_as_the_hub_reads_them(self):
        self.as_tutor()
        report_id = self.submit(self.demo).json()['report']['id']
        self.edit(self.demo, 1, suggested_strategy='A new plan.', assessment_review='Revised.')
        self.as_admin()
        events = self.client.get(f'/api/bookings/demo/{self.demo.id}/history/').json()['events']
        completed, edited = [event for event in events if event['kind'] in ('COMPLETED', 'REPORT_EDITED')]
        self.assertEqual((completed['kind_label'], completed['actor']['full_name']), ('Completed', 'Tutor Anu'))
        self.assertEqual(completed['details'], {
            'from_status': 'BOOKED', 'to_status': 'COMPLETED', 'report_id': report_id, 'version': 1,
        })
        self.assertEqual(edited['kind_label'], 'Report edited')
        self.assertEqual(edited['details'], {
            'report_id': report_id, 'version': 2, 'changed_fields': ['assessment_review', 'suggested_strategy'],
        })
        # Field names, never what they say.
        self.assertNotIn('A new plan', str(events))

    def test_the_list_filters_by_report(self):
        upcoming = self.upcoming()
        self.as_tutor()
        self.submit(self.demo)
        self.as_admin()

        def ids(**params):
            response = self.client.get('/api/bookings/demo/', params)
            self.assertEqual(response.status_code, 200, response.content)
            return {row['id']: (row['has_report'], row['report_version'], row['report_due']) for row in response.json()['results']}

        self.assertEqual(ids(), {str(self.demo.id): (True, 1, False), str(upcoming.id): (False, None, False)})
        self.assertEqual(set(ids(report='submitted')), {str(self.demo.id)})
        self.assertEqual(set(ids(report='missing')), {str(upcoming.id)})
        self.assertEqual(set(ids(report='MISSING', status='BOOKED')), {str(upcoming.id)})
        self.assertEqual(set(ids(report='submitted', status='BOOKED')), set())
        refused = self.client.get('/api/bookings/demo/', {'report': 'maybe'})
        self.assertEqual((refused.status_code, refused.json()['error'], refused.json()['fields']), (400, 'INVALID_INPUT', ['report']))
        # The Diagnostic list keeps to its own table.
        diagnostic_rows = self.client.get('/api/bookings/diagnostic/', {'report': 'missing'}).json()['results']
        self.assertEqual([row['id'] for row in diagnostic_rows], [str(self.diagnostic.id)])
        self.assertEqual(DemoBooking.objects.get(pk=self.demo.pk).status, BookingStatus.COMPLETED)

    def test_the_list_finds_the_reports_due(self):
        # Yesterday's Demos: Riya's has no report (due), Ali's has one (not due), Sara's was a No-show
        # (cancelled: nothing is due); and one upcoming Demo, not due yet.
        then = timezone.now() - timedelta(days=3)
        yesterday = indian_today() - timedelta(days=1)
        reported = self.assigned(
            create_booking(request(student='Ali', phone='0507654321', day=yesterday, at=EVENING), now=then)[0],
            then, tutor=self.other_tutor,
        )
        cancelled = create_booking(request(student='Sara', phone='0507654322', day=yesterday, at=MORNING), now=then)[0]
        cancel_booking(cancelled, reason_code=CancelReason.NO_SHOW)
        upcoming = self.upcoming()
        self.client.force_authenticate(self.other_tutor)
        self.assertEqual(self.submit(reported).status_code, 201)
        self.as_admin()

        def ids(**params):
            response = self.client.get('/api/bookings/demo/', params)
            self.assertEqual(response.status_code, 200, response.content)
            return {row['id'] for row in response.json()['results']}

        riya = str(self.demo.id)
        self.assertEqual(ids(report='due'), {riya})
        # Exactly the rows the list itself marks report_due.
        rows = self.client.get('/api/bookings/demo/').json()['results']
        self.assertEqual(len(rows), 4)
        self.assertEqual({row['id'] for row in rows if row['report_due']}, {riya})
        # With every other filter and the search, as they were.
        self.assertEqual(ids(report='DUE', status='BOOKED'), {riya})
        self.assertEqual(ids(report='due', status='COMPLETED'), set())
        self.assertEqual(ids(report='due', when='past'), {riya})
        self.assertEqual(ids(report='due', when='upcoming'), set())
        self.assertEqual(ids(report='due', q='Riya'), {riya})
        self.assertEqual(ids(report='due', q='Ali'), set())
        self.assertEqual(ids(report='due', assigned='true', tutor=str(self.tutor.id)), {riya})
        self.assertEqual(ids(report='due', tutor=str(self.other_tutor.id)), set())
        self.assertEqual(ids(report='missing'), {riya, str(cancelled.id), str(upcoming.id)})
        self.assertEqual(ids(report='submitted'), {str(reported.id)})
        refused = self.client.get('/api/bookings/demo/', {'report': 'overdue'})
        self.assertEqual((refused.status_code, refused.json()['error'], refused.json()['fields']), (400, 'INVALID_INPUT', ['report']))
        # The Diagnostic list keeps to its own table: its booking, from yesterday and unreported, is due there.
        diagnostic = self.client.get('/api/bookings/diagnostic/', {'report': 'due'}).json()['results']
        self.assertEqual([row['id'] for row in diagnostic], [str(self.diagnostic.id)])
