"""
The lead's owner BDE's report APIs (reports.bde_views, P9, design F.4 and
E.1): the reports on their own leads as they print, and each one's current
PDF; that nobody else reaches them -- another BDE, a lead nobody owns, any
other role -- and that no changed id or type reaches another report; and that
reading and downloading write nothing, so no send is ever recorded.
"""
import uuid
from datetime import timedelta
from types import SimpleNamespace
from unittest import mock

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from activity.models import ActivityLog
from bookings.booking_service import create_booking
from bookings.models import BookingEvent, Lead
from bookings.scheduling import indian_today
from bookings.tests_booking import EVENING, account, request

from .downloads import ReportPdfThrottle
from .models import ReportShare
from .tests_pdf_api import PdfApiTestCase, pdf_url
from .tests_preview_api import WRITES
from .tests_tutor_api import path_type, report_url


def reports_url(lead_id):
    return f'/api/bde/enquiries/{lead_id}/reports/'


def bde_pdf_url(booking, booking_type=None):
    return f'/api/bde/bookings/{booking_type or path_type(booking)}/{booking.id}/report/pdf/'


class BdeReportApiTestCase(PdfApiTestCase):
    def setUp(self):
        super().setUp()  # the tutor's Diagnostic and Demo of yesterday, both Riya's: one lead, nobody's yet
        self.bde = account('bde_anil', role='BDE')
        self.other_bde = account('bde_bina', role='BDE')
        self.lead = self.demo.lead
        self.give(self.lead, self.bde)

    def give(self, lead, bde):
        Lead.objects.filter(pk=lead.pk).update(owner_bde=bde, owner_assigned_at=timezone.now() if bde else None)

    def as_bde(self, bde=None):
        self.client.force_authenticate(bde or self.bde)

    def reported_demo(self, student, phone, owner):
        """Yesterday's Demo of a lead of its own, ``owner``'s, with a report the other tutor has submitted."""
        then = timezone.now() - timedelta(days=3)
        booking = create_booking(
            request(student=student, phone=phone, day=indian_today() - timedelta(days=1), at=EVENING), now=then,
        )[0]
        booking = self.assigned(booking, then, tutor=self.other_tutor)
        self.give(booking.lead, owner)
        self.client.force_authenticate(self.other_tutor)
        self.assertEqual(self.submit(booking).status_code, 201)
        return booking


class BdeReportReadTests(BdeReportApiTestCase):
    def test_the_owner_bde_lists_each_report_on_their_lead_as_it_prints(self):
        self.as_bde()
        none_yet = self.client.get(reports_url(self.lead.id))
        self.assertEqual(none_yet.status_code, 200, none_yet.content)
        self.assertEqual(none_yet.json(), {'results': [], 'count': 0, 'timezone': 'Asia/Kolkata'})

        self.as_tutor()
        self.submit(self.diagnostic)
        self.submit(self.demo)
        self.edit(self.demo, 1, suggested_strategy='Revised after the session.')
        self.upcoming(student='Riya')  # the same lead's next Demo: no report, so not listed
        as_printed = {str(booking.id): self.client.get(report_url(booking)).json() for booking in (self.diagnostic, self.demo)}

        self.as_bde()
        response = self.client.get(reports_url(self.lead.id))
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual((body['count'], body['timezone']), (2, 'Asia/Kolkata'))
        # Newest slot first, as the enquiry lists its bookings: yesterday's 19:30 Demo, then its 10:00 Diagnostic.
        for row, booking in zip(body['results'], (self.demo, self.diagnostic), strict=True):
            booking = type(booking).objects.select_related('slot').get(pk=booking.pk)
            with self.subTest(booking_type=booking.booking_type):
                self.assertEqual(row, {
                    'booking': {
                        'id': str(booking.id), 'booking_type': booking.booking_type,
                        'date': booking.slot.local_date.isoformat(), 'time': booking.slot.local_time.strftime('%H:%M'),
                        'starts_at': booking.slot.starts_at.isoformat(), 'status': 'COMPLETED',
                        'completed_at': booking.completed_at.isoformat(),
                    },
                    # The report as its tutor and the Admin read it, at its latest version -- nothing about sending.
                    'report': as_printed[str(booking.id)],
                })
        self.assertEqual([row['report']['version'] for row in body['results']], [2, 1])

    def test_the_owner_bde_downloads_each_report_as_last_saved(self):
        self.as_tutor()
        self.submit(self.diagnostic)
        self.submit(self.demo)
        self.edit(self.demo, 1, suggested_strategy='Revised after the session.')
        for booking, version in ((self.diagnostic, 1), (self.demo, 2)):
            with self.subTest(booking_type=booking.booking_type):
                self.as_bde()
                response, revision = self.download(bde_pdf_url(booking))
                self.assertPdf(response, self.name(booking))  # the server's file name; private, uncached, never sniffed
                report = type(booking).objects.get(pk=booking.pk).report
                self.assertEqual((revision.report_id, revision.version), (report.id, version))
                self.as_admin()
                self.assertEqual(response.content, self.client.get(pdf_url(booking, admin=True)).content,
                                 "the Admin's PDF, byte for byte")

    def test_no_report_and_no_booking_are_told_apart(self):
        self.as_bde()
        self.assertRefused(self.download(bde_pdf_url(self.demo))[0], 404, 'NO_REPORT')
        missing = SimpleNamespace(id=uuid.uuid4(), booking_type='DEMO')
        for url in (bde_pdf_url(missing), bde_pdf_url(self.demo, 'diagnostic'), bde_pdf_url(self.demo, 'webinar')):
            with self.subTest(url=url):
                # A refusal is JSON even to a client asking for a PDF only.
                response, printed = self.download(url, HTTP_ACCEPT='application/pdf')
                self.assertRefused(response, 404, 'NOT_FOUND')
                self.assertEqual(response.json()['message'], 'No such booking.')
                self.assertIsNone(printed)
        unknown = self.client.get(reports_url(uuid.uuid4()))
        self.assertRefused(unknown, 404, 'NOT_FOUND')
        self.assertEqual(unknown.json()['message'], 'No such enquiry.')


class BdeReportAccessTests(BdeReportApiTestCase):
    def setUp(self):
        super().setUp()
        self.as_tutor()
        self.submit(self.diagnostic)

    def assertNotTheirs(self, lead_id, booking):
        listed = self.client.get(reports_url(lead_id))
        self.assertRefused(listed, 404, 'NOT_FOUND')
        self.assertEqual(listed.json()['message'], 'No such enquiry.')
        response, printed = self.download(bde_pdf_url(booking))
        self.assertRefused(response, 404, 'NOT_FOUND')
        self.assertIsNone(printed)

    def test_another_bdes_lead_and_one_nobody_owns_show_nothing(self):
        with self.subTest(case='another BDE'):
            self.as_bde(self.other_bde)
            self.assertNotTheirs(self.lead.id, self.diagnostic)
        with self.subTest(case='a lead nobody owns'):
            self.give(self.lead, None)
            self.as_bde()
            self.assertNotTheirs(self.lead.id, self.diagnostic)
        # Ownership is read on every request: the lead's new owner reaches it at once, and the old one no longer.
        self.give(self.lead, self.other_bde)
        self.as_bde(self.other_bde)
        self.assertEqual(self.client.get(reports_url(self.lead.id)).json()['count'], 1)
        self.assertEqual(self.download(bde_pdf_url(self.diagnostic))[0].status_code, 200)
        self.as_bde()
        self.assertNotTheirs(self.lead.id, self.diagnostic)

    def test_changing_the_id_or_type_never_reaches_another_report(self):
        theirs = self.reported_demo('Binu', '0507654321', self.other_bde)
        self.as_bde()
        for url in (bde_pdf_url(theirs), bde_pdf_url(theirs, 'diagnostic'), bde_pdf_url(self.diagnostic, 'demo')):
            with self.subTest(url=url):
                response, printed = self.download(url)
                self.assertRefused(response, 404, 'NOT_FOUND')
                self.assertIsNone(printed)
        self.assertRefused(self.client.get(reports_url(theirs.lead_id)), 404, 'NOT_FOUND')
        # Each BDE lists the reports on their own lead only.
        mine = self.client.get(reports_url(self.lead.id)).json()['results']
        self.assertEqual([row['booking']['id'] for row in mine], [str(self.diagnostic.id)])
        self.as_bde(self.other_bde)
        others = self.client.get(reports_url(theirs.lead_id)).json()['results']
        self.assertEqual([row['booking']['id'] for row in others], [str(theirs.id)])
        self.assertNotTheirs(self.lead.id, self.diagnostic)

    def test_other_roles_are_refused_and_a_superuser_is_no_bde(self):
        callers = {
            'admin': (self.admin, None),
            'assigned tutor': (self.tutor, None),
            'mentor': (account('mentor_one', role='MENTOR'), None),
            'sales_tl': (account('sales_tl_one', role='SALES_TL'), None),
            'student': (account('student_one', role='STUDENT'), None),
            'anonymous': (None, None),
            'superuser': (account('root', role='ADMIN', is_superuser=True, is_staff=True), 'NOT_A_BDE'),
        }
        for name, (caller, error) in callers.items():
            self.client.force_authenticate(caller)
            for url in (reports_url(self.lead.id), bde_pdf_url(self.diagnostic)):
                with self.subTest(caller=name, url=url):
                    response, printed = self.download(url)
                    self.assertEqual(response.status_code, 403, response.content)
                    self.assertEqual(response.json().get('error'), error)
                    self.assertIsNone(printed)

    def test_reading_and_downloading_record_nothing(self):
        self.as_bde()
        before = (ReportShare.objects.count(), ActivityLog.objects.count(), BookingEvent.objects.count())
        with CaptureQueriesContext(connection) as queries, self.recording_writes() as written:
            listed = self.client.get(reports_url(self.lead.id))
            downloaded, _revision = self.download(bde_pdf_url(self.diagnostic))
        self.assertEqual((listed.status_code, downloaded.status_code), (200, 200))
        self.assertEqual([query['sql'] for query in queries.captured_queries if WRITES.match(query['sql'])], [])
        self.assertEqual((ReportShare.objects.count(), ActivityLog.objects.count(), BookingEvent.objects.count()), before)
        self.assertEqual(before[0], 0, 'no send is ever recorded')
        self.assertOnlyFontCopies(written, renders=1)

    def test_downloads_count_against_the_report_pdf_rate(self):
        self.as_bde()
        with mock.patch.object(ReportPdfThrottle, 'THROTTLE_RATES', {'report_pdf': '2/min'}):
            for _ in range(2):
                self.assertEqual(self.client.get(bde_pdf_url(self.diagnostic)).status_code, 200)
            response, printed = self.download(bde_pdf_url(self.diagnostic))
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response['Content-Type'], 'application/json')
        self.assertIsNone(printed)

    def test_both_routes_are_read_only(self):
        self.as_bde()
        for url in (reports_url(self.lead.id), bde_pdf_url(self.diagnostic)):
            for method in ('post', 'put', 'patch', 'delete'):
                with self.subTest(url=url, method=method):
                    self.assertEqual(getattr(self.client, method)(url, {}, format='json').status_code, 405)
        self.assertEqual(type(self.diagnostic).objects.get(pk=self.diagnostic.pk).report.version, 1)
