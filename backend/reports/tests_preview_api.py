"""
The tutor's report preview (P8: POST .../report/preview/, through
reports.tutor_views.TutorReportPreviewView and reports.services.preview_content):
the PDF a submit or edit of the body would make, drawn by the same renderer as
every saved version -- byte for byte what the saved version then prints -- with
nothing saved: no report, no revision, no history, no activity, not one write.
Refused as a save of the same body would be, and to anyone but the booking's
assigned tutor; counted against the download rate.
"""
import re
import uuid
from types import SimpleNamespace
from unittest import mock

from django.db import connection
from django.test.utils import CaptureQueriesContext

from activity.models import ActivityLog
from bookings.booking_service import cancel_booking
from bookings.models import BookingEvent, BookingStatus, CancelReason
from bookings.tests_booking import MORNING, account

from . import downloads
from .downloads import ReportPdfThrottle
from .models import DemoReport, DemoReportRevision, DiagnosticReport, DiagnosticReportRevision
from .tests_pdf_api import PdfApiTestCase, pdf_url
from .tests_services import report_input
from .tests_tutor_api import path_type, report_url

WRITES = re.compile(r'^\s*(INSERT|UPDATE|DELETE)\b', re.IGNORECASE)
SNAPSHOTS = {'student_name_snapshot': 'Riya', 'grade_snapshot': '8', 'tutor_name_snapshot': 'Tutor Anu'}


def preview_url(booking):
    return report_url(booking, 'preview/')


def everything_saved():
    """Every report, revision, booking event and activity entry there is, counted."""
    return {model.__name__: model.objects.count() for model in (
        DiagnosticReport, DemoReport, DiagnosticReportRevision, DemoReportRevision, BookingEvent, ActivityLog,
    )}


class ReportPreviewTestCase(PdfApiTestCase):
    def preview(self, booking, body=None):
        """POST ``body`` (the booking's valid fields by default); the answer and what was drawn, as (type, content) or None."""
        with mock.patch.object(downloads, 'content_pdf', wraps=downloads.content_pdf) as drawn:
            response = self.client.post(preview_url(booking), report_input(booking) if body is None else body, format='json')
        return response, (drawn.call_args.args if drawn.called else None)

    def assertPreviewPdf(self, response, booking):
        self.assertEqual(response.status_code, 200, getattr(response, 'content', b'')[:200])
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertTrue(response.content.startswith(b'%PDF-'))
        self.assertEqual(response['Content-Disposition'], f'inline; filename="{self.name(booking, "-preview")}"')
        self.assertEqual(response['Cache-Control'], 'private, no-store')
        self.assertEqual(response['X-Content-Type-Options'], 'nosniff')


class ReportPreviewTests(ReportPreviewTestCase):
    def test_each_type_previews_as_its_saved_version_then_prints_byte_for_byte(self):
        for booking in (self.diagnostic, self.demo):
            with self.subTest(booking_type=booking.booking_type):
                preview, drawn = self.preview(booking)
                self.assertPreviewPdf(preview, booking)
                # Drawn from what a save would store: the fields as P6 cleans them and its snapshots.
                self.assertEqual(drawn, (booking.booking_type, {**report_input(booking), **SNAPSHOTS}))

                self.assertEqual(self.submit(booking).status_code, 201)
                revision = type(booking).objects.get(pk=booking.pk).report.revisions.get()
                self.assertEqual(revision.content, drawn[1])
                saved = self.client.get(pdf_url(booking))
                self.assertEqual(saved.status_code, 200)
                self.assertEqual(saved.content, preview.content, 'the preview is the saved PDF, byte for byte')

    def test_an_edit_previews_its_new_text_and_the_report_stays_as_saved(self):
        self.submit(self.demo)
        body = {'version': 1, **report_input(self.demo, suggested_strategy='A new plan.')}
        with CaptureQueriesContext(connection) as queries:
            preview, drawn = self.preview(self.demo, body)
        self.assertPreviewPdf(preview, self.demo)
        self.assertEqual(drawn[1]['suggested_strategy'], 'A new plan.')
        self.assertNotIn('version', drawn[1])
        self.assertEqual([query['sql'] for query in queries.captured_queries if WRITES.match(query['sql'])], [])
        report = DemoReport.objects.get()
        self.assertEqual((report.version, report.suggested_strategy, report.revisions.count()),
                         (1, report_input(self.demo)['suggested_strategy'], 1))

    def test_a_preview_writes_nothing_at_all(self):
        before = everything_saved()
        with CaptureQueriesContext(connection) as queries, self.recording_writes() as written:
            for booking in (self.diagnostic, self.demo):
                self.assertPreviewPdf(self.preview(booking)[0], booking)
        self.assertEqual([query['sql'] for query in queries.captured_queries if WRITES.match(query['sql'])], [])
        self.assertEqual(everything_saved(), before)
        for booking in (self.diagnostic, self.demo):
            with self.subTest(booking_type=booking.booking_type):
                self.assertEqual(type(booking).objects.get(pk=booking.pk).status, BookingStatus.BOOKED)
                self.assertRefused(self.client.get(report_url(booking)), 404, 'NO_REPORT')
        # WeasyPrint's font copies are the only files touched, and they are gone.
        self.assertOnlyFontCopies(written, renders=2)

    def test_a_body_the_api_would_refuse_is_refused_the_same_way(self):
        bad = {**report_input(self.diagnostic), 'score': 30, 'teacher_remarks': '   ', 'tutor_name_snapshot': 'Someone'}
        preview, drawn = self.preview(self.diagnostic, bad)
        self.assertRefused(preview, 400, 'VALIDATION_ERROR')
        self.assertIsNone(drawn)
        self.assertEqual(set(preview.json()['fields']), {'score', 'teacher_remarks', 'tutor_name_snapshot'})
        submitted = self.client.post(report_url(self.diagnostic), bad, format='json')
        self.assertEqual(preview.json(), submitted.json(), 'the preview says what a submit would')

        for body in (['not', 'an', 'object'], {**report_input(self.demo), 'assessment_review': 'x' * 1201}):
            with self.subTest(body=str(body)[:40]):
                self.assertRefused(self.preview(self.demo, body)[0], 400, 'VALIDATION_ERROR')
        form = self.client.post(preview_url(self.demo), report_input(self.demo))  # multipart, not JSON
        self.assertEqual(form.status_code, 415)
        self.assertEqual(everything_saved()['DemoReport'] + everything_saved()['DiagnosticReport'], 0)

    def test_a_preview_follows_the_rules_a_save_would(self):
        self.assertRefused(self.preview(self.upcoming())[0], 409, 'NOT_STARTED')
        cancelled = self.upcoming(student='Sara', at=MORNING)
        cancel_booking(cancelled, reason_code=CancelReason.PARENT_REQUEST)
        self.assertRefused(self.preview(cancelled)[0], 409, 'BOOKING_CANCELLED')
        # A completed booking previews its edits (above); a booked one its tutor has started, its first report.
        self.assertPreviewPdf(self.preview(self.diagnostic)[0], self.diagnostic)


class ReportPreviewAccessTests(ReportPreviewTestCase):
    def test_only_the_assigned_tutor_previews(self):
        callers = {
            'another tutor': (self.other_tutor, 404),
            'superuser': (account('root', role='ADMIN', is_superuser=True, is_staff=True), 404),
            'admin': (self.admin, 403),
            'mentor': (account('mentor_one', role='MENTOR'), 403),
            'bde': (account('bde_one', role='BDE'), 403),
            'sales_tl': (account('sales_tl_one', role='SALES_TL'), 403),
            'anonymous': (None, 403),
        }
        for name, (caller, status) in callers.items():
            self.client.force_authenticate(caller)
            for booking in (self.diagnostic, self.demo):
                with self.subTest(caller=name, booking_type=booking.booking_type):
                    response, drawn = self.preview(booking)
                    self.assertRefused(response, status, 'NOT_FOUND' if status == 404 else None)
                    self.assertIsNone(drawn)

        self.as_tutor()
        missing = SimpleNamespace(id=uuid.uuid4(), booking_type='DEMO')
        self.assertRefused(self.preview(missing, report_input(self.demo))[0], 404, 'NOT_FOUND')
        swapped = preview_url(self.demo).replace(f'/{path_type(self.demo)}/', '/diagnostic/')
        self.assertRefused(self.client.post(swapped, report_input(self.demo), format='json'), 404, 'NOT_FOUND')
        self.assertEqual(self.client.post(f'/api/tutor/bookings/webinar/{self.demo.id}/report/preview/', {}, format='json').status_code, 404)
        for method in ('get', 'put', 'patch', 'delete'):
            with self.subTest(method=method):
                self.assertEqual(getattr(self.client, method)(preview_url(self.demo)).status_code, 405)

    def test_previews_count_against_the_download_rate(self):
        self.submit(self.demo)
        with mock.patch.object(ReportPdfThrottle, 'THROTTLE_RATES', {'report_pdf': '2/min'}):
            self.assertEqual(self.client.get(pdf_url(self.demo)).status_code, 200)
            self.assertEqual(self.preview(self.demo, {'version': 1, **report_input(self.demo)})[0].status_code, 200)
            response, drawn = self.preview(self.demo, {'version': 1, **report_input(self.demo)})
            self.assertEqual(response.status_code, 429)
            self.assertEqual(response['Content-Type'], 'application/json')
            self.assertIsNone(drawn)
