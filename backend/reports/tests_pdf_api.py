"""
The report PDF downloads (reports.downloads, through reports.tutor_views and
reports.management_views; design F.3): the assigned tutor and the Admin
download a report as last saved or at any version, each printed from that
version's own revision; nobody else reaches one, and no changed booking id,
type or version number reaches another report; a download is a private PDF
attachment with a safe file name; refusals are JSON whatever the client
accepts; no PDF is stored, and WeasyPrint's temporary font copies are gone when
the download returns; and each account's rate limit holds.

Which revision a download printed is read from the renderer's call
(reports.downloads.revision_pdf); what a revision prints is tests_pdf's.
"""
import uuid
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from django.core.cache import cache
from django.test import override_settings
from django.utils import timezone

from bookings.booking_service import create_booking
from bookings.models import BookingType
from bookings.scheduling import indian_today
from bookings.tests_booking import EVENING, account, request

from . import downloads
from .downloads import ReportPdfThrottle, pdf_filename
from .pdf import ASSETS, revision_document
from .tests_admin_api import AdminReportApiTestCase
from .tests_pdf import all_text
from .tests_services import report_input
from .tests_tutor_api import PRIVATE_VALUES, path_type, report_url

PDF_HEADERS = {'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff'}


def pdf_url(booking, version=None, admin=False):
    """The tutor's (or with ``admin`` the Admin's) download of ``booking``'s report: current, or at ``version``."""
    base = '/api/bookings/' if admin else '/api/tutor/bookings/'
    tail = 'pdf/' if version is None else f'revisions/{version}/pdf/'
    return f'{base}{path_type(booking)}/{booking.id}/report/{tail}'


class PdfApiTestCase(AdminReportApiTestCase):
    def setUp(self):
        super().setUp()
        cache.clear()  # the download rate limit counts here

    def tearDown(self):
        cache.clear()
        super().tearDown()

    def sign_in(self, admin):
        """As the Admin when ``admin``, else as the assigned tutor."""
        (self.as_admin if admin else self.as_tutor)()

    def download(self, url, **extra):
        """GET ``url``, and the revision the answer printed (None if nothing was printed)."""
        with mock.patch.object(downloads, 'revision_pdf', wraps=downloads.revision_pdf) as printed:
            response = self.client.get(url, **extra)
        return response, (printed.call_args.args[0] if printed.called else None)

    def assertPdf(self, response, filename):
        self.assertEqual(response.status_code, 200, getattr(response, 'content', b'')[:200])
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertTrue(response.content.startswith(b'%PDF-'))
        self.assertEqual(response['Content-Disposition'], f'attachment; filename="{filename}"')
        for header, value in PDF_HEADERS.items():
            self.assertEqual(response[header], value)

    def assertRefused(self, response, status, error=None):
        self.assertEqual(response.status_code, status, getattr(response, 'content', b'')[:200])
        self.assertEqual(response['Content-Type'], 'application/json')
        if error:
            self.assertEqual(response.json()['error'], error)

    def name(self, booking, suffix=''):
        kind = 'Diagnostic' if booking.booking_type == BookingType.DIAGNOSTIC else 'Demo'
        return f'{kind}-Report-Riya-{booking.slot.local_date:%Y-%m-%d}{suffix}.pdf'

    @contextmanager
    def recording_writes(self):
        """Every file the block writes, as (path, bytes) pairs; storing any file fails the test."""
        written = []
        write_bytes = Path.write_bytes

        def recorded(path, data):
            written.append((path, data))
            return write_bytes(path, data)

        with mock.patch('django.core.files.storage.FileSystemStorage.save', side_effect=AssertionError('stored')), \
                mock.patch.object(Path, 'write_bytes', recorded):
            yield written

    def assertOnlyFontCopies(self, written, renders):
        # WeasyPrint's Fontconfig reads fonts from files, so each render copies the three bundled ones into a
        # temporary folder: those copies are the only thing it writes, and they are gone when it returns.
        fonts = {path.read_bytes() for path in (ASSETS / 'fonts').glob('*.ttf')}
        self.assertEqual(len(written), 3 * renders)
        for path, data in written:
            self.assertIn(data, fonts)
            self.assertFalse(path.parent.exists(), f'{path.parent} was left behind')


class ReportPdfDownloadTests(PdfApiTestCase):
    def test_the_tutor_and_the_admin_download_each_report_as_last_saved(self):
        for booking in (self.diagnostic, self.demo):
            with self.subTest(booking_type=booking.booking_type):
                self.as_tutor()
                self.submit(booking)
                field = 'teacher_remarks' if booking.booking_type == BookingType.DIAGNOSTIC else 'suggested_strategy'
                self.edit(booking, 1, **{field: 'Revised after the session.'})
                report = type(booking).objects.get(pk=booking.pk).report

                for who, admin in (('tutor', False), ('admin', True)):
                    with self.subTest(caller=who):
                        self.sign_in(admin)
                        response, revision = self.download(pdf_url(booking, admin=admin))
                        self.assertPdf(response, self.name(booking))
                        self.assertEqual((revision.report_id, revision.version), (report.id, 2))
                        self.assertEqual(revision.content[field], 'Revised after the session.')

    def test_each_version_downloads_as_it_was_saved(self):
        self.submit(self.diagnostic, teacher_remarks='First thoughts.')
        self.edit(self.diagnostic, 1, teacher_remarks='Second thoughts.')
        self.edit(self.diagnostic, 2, teacher_remarks='Third thoughts.')
        said = {1: 'First thoughts.', 2: 'Second thoughts.', 3: 'Third thoughts.'}

        for admin in (False, True):
            self.sign_in(admin)
            for version, remarks in said.items():
                with self.subTest(admin=admin, version=version):
                    response, revision = self.download(pdf_url(self.diagnostic, version, admin=admin))
                    self.assertPdf(response, self.name(self.diagnostic, f'-v{version}'))
                    self.assertEqual(revision.version, version)
                    self.assertIn(remarks.replace(' ', ''), all_text(revision_document(revision)))
                    for other in set(said.values()) - {remarks}:
                        self.assertNotIn(other.replace(' ', ''), all_text(revision_document(revision)))
            # The current route prints the latest version, and names none.
            response, revision = self.download(pdf_url(self.diagnostic, admin=admin))
            self.assertPdf(response, self.name(self.diagnostic))
            self.assertEqual(revision.version, 3)

    def test_a_version_the_report_does_not_have_is_404_no_version(self):
        self.submit(self.demo)
        for admin in (False, True):
            self.sign_in(admin)
            for version in (0, 2, 99, 10 ** 20):
                with self.subTest(admin=admin, version=version):
                    response, revision = self.download(pdf_url(self.demo, version, admin=admin))
                    self.assertRefused(response, 404, 'NO_VERSION')
                    self.assertIsNone(revision)
            # Not a version at all: no route.
            for tail in ('revisions/-1/pdf/', 'revisions/one/pdf/', 'revisions/1.0/pdf/'):
                with self.subTest(admin=admin, tail=tail):
                    path = pdf_url(self.demo, admin=admin).replace('pdf/', tail)
                    self.assertEqual(self.client.get(path).status_code, 404)

    def test_no_report_and_no_booking_are_told_apart(self):
        for admin in (False, True):
            self.sign_in(admin)
            for url in (pdf_url(self.demo, admin=admin), pdf_url(self.demo, 1, admin=admin)):
                with self.subTest(admin=admin, url=url):
                    self.assertRefused(self.client.get(url), 404, 'NO_REPORT')
            missing = SimpleNamespace(id=uuid.uuid4(), booking_type=BookingType.DEMO)
            for url in (pdf_url(missing, admin=admin), pdf_url(missing, 1, admin=admin)):
                with self.subTest(admin=admin, url=url):
                    self.assertRefused(self.client.get(url), 404, 'NOT_FOUND')
            base = '/api/bookings/' if admin else '/api/tutor/bookings/'
            self.assertEqual(self.client.get(f'{base}webinar/{self.demo.id}/report/pdf/').status_code, 404)

    def test_a_pdf_names_the_student_never_the_parent(self):
        self.submit(self.diagnostic)
        _response, revision = self.download(pdf_url(self.diagnostic))
        text = all_text(revision_document(revision))
        self.assertIn('Riya', text)
        for value in PRIVATE_VALUES:
            self.assertNotIn(value, text)


class ReportPdfAccessTests(PdfApiTestCase):
    def setUp(self):
        super().setUp()
        self.as_tutor()
        for booking in (self.diagnostic, self.demo):
            self.assertEqual(self.submit(booking).status_code, 201)

    def callers(self):
        return {
            'another tutor': self.other_tutor,
            'admin': self.admin,
            'mentor': account('mentor_one', role='MENTOR'),
            'bde': account('bde_one', role='BDE'),
            'sales_tl': account('sales_tl_one', role='SALES_TL'),
            'superuser': account('root', role='ADMIN', is_superuser=True, is_staff=True),
            'anonymous': None,
        }

    def test_only_the_assigned_tutor_downloads_on_the_tutor_routes(self):
        # Another tutor and a superuser hold the reading permission but are not assigned: as if no booking.
        expected = {'another tutor': 404, 'superuser': 404}
        for name, caller in self.callers().items():
            self.client.force_authenticate(caller)
            for booking in (self.diagnostic, self.demo):
                for version in (None, 1):
                    with self.subTest(caller=name, booking_type=booking.booking_type, version=version):
                        response, revision = self.download(pdf_url(booking, version))
                        status = expected.get(name, 403)
                        self.assertRefused(response, status, 'NOT_FOUND' if status == 404 else None)
                        self.assertIsNone(revision)
        self.as_tutor()
        self.assertPdf(self.download(pdf_url(self.demo))[0], self.name(self.demo))

    def test_only_those_who_see_every_booking_download_on_the_admin_routes(self):
        callers = {**self.callers(), 'the assigned tutor': self.tutor}
        for name, caller in callers.items():
            self.client.force_authenticate(caller)
            for version in (None, 1):
                with self.subTest(caller=name, version=version):
                    response, revision = self.download(pdf_url(self.diagnostic, version, admin=True))
                    if name in ('admin', 'superuser'):
                        self.assertPdf(response, self.name(self.diagnostic, '' if version is None else '-v1'))
                    else:
                        self.assertRefused(response, 403)
                        self.assertIsNone(revision)

    def test_changing_the_booking_id_type_or_version_never_reaches_another_report(self):
        # Anu's Demo report has two versions; Binu has a Demo of his own, with one.
        self.edit(self.demo, 1, suggested_strategy='A new plan.')
        yesterday = indian_today() - timedelta(days=1)
        then = timezone.now() - timedelta(days=3)
        binus = self.assigned(
            create_booking(request(student='Ali', phone='0507654321', day=yesterday, at=EVENING), now=then)[0],
            then, tutor=self.other_tutor,
        )
        self.client.force_authenticate(self.other_tutor)
        self.assertEqual(self.submit(binus).status_code, 201)

        # Anu's booking, under any version: as if it did not exist.
        for version in (None, 1, 2):
            with self.subTest(version=version):
                response, revision = self.download(pdf_url(self.demo, version))
                self.assertRefused(response, 404, 'NOT_FOUND')
                self.assertIsNone(revision)
        # Binu's own booking at Anu's version number: his report has no version 2.
        response, revision = self.download(pdf_url(binus, 2))
        self.assertRefused(response, 404, 'NO_VERSION')
        self.assertIsNone(revision)
        # His own version 1 is his own report.
        response, revision = self.download(pdf_url(binus, 1))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(revision.report_id, type(binus).objects.get(pk=binus.pk).report.id)

        # A booking's id under the other type's path names no booking, for the tutor and the Admin alike.
        for caller, admin in ((self.tutor, False), (self.admin, True)):
            self.client.force_authenticate(caller)
            for booking, other_type in ((self.demo, 'diagnostic'), (self.diagnostic, 'demo')):
                with self.subTest(admin=admin, booking_type=booking.booking_type):
                    url = pdf_url(booking, admin=admin).replace(f'/{path_type(booking)}/', f'/{other_type}/')
                    self.assertRefused(self.client.get(url), 404, 'NOT_FOUND')


class ReportPdfResponseTests(PdfApiTestCase):
    def test_the_file_name_keeps_ascii_words_only(self):
        booking = SimpleNamespace(
            get_booking_type_display=lambda: 'Diagnostic', slot=SimpleNamespace(local_date=indian_today()),
        )
        day = f'{indian_today():%Y-%m-%d}'
        names = {
            'Riya Menon': 'Riya-Menon',
            '  Ríya   Ménon  ': 'Riya-Menon',
            'O\'Brien "Jr" <b>x</b>\r\n; filename=evil.exe': 'O-Brien-Jr-b-x-b-filename-evil-exe',
            'محمد': 'Student',
            '': 'Student',
            'A' * 100: 'A' * 60,
        }
        for student, expected in names.items():
            with self.subTest(student=student):
                revision = SimpleNamespace(content={'student_name_snapshot': student}, version=3)
                self.assertEqual(pdf_filename(booking, revision), f'Diagnostic-Report-{expected}-{day}.pdf')
                self.assertEqual(pdf_filename(booking, revision, numbered=True), f'Diagnostic-Report-{expected}-{day}-v3.pdf')

    def test_a_client_asking_only_for_a_pdf_still_reads_a_refusal(self):
        for admin in (False, True):
            self.sign_in(admin)
            with self.subTest(admin=admin):
                self.assertRefused(self.client.get(pdf_url(self.demo, admin=admin), HTTP_ACCEPT='application/pdf'), 404, 'NO_REPORT')
        self.as_tutor()
        self.submit(self.demo)
        for admin in (False, True):
            self.sign_in(admin)
            with self.subTest(admin=admin):
                response, _revision = self.download(pdf_url(self.demo, admin=admin), HTTP_ACCEPT='application/pdf')
                self.assertPdf(response, self.name(self.demo))

    def test_downloads_are_read_only(self):
        self.submit(self.demo)
        for admin in (False, True):
            self.sign_in(admin)
            for version in (None, 1):
                for method in ('post', 'put', 'patch', 'delete'):
                    with self.subTest(admin=admin, version=version, method=method):
                        response = getattr(self.client, method)(pdf_url(self.demo, version, admin=admin), {}, format='json')
                        self.assertEqual(response.status_code, 405)
        self.assertEqual(type(self.demo).objects.get(pk=self.demo.pk).report.version, 1)

    def test_no_pdf_is_stored_and_the_font_copies_are_gone_at_once(self):
        self.submit(self.diagnostic)
        with self.recording_writes() as written:
            for admin in (False, True):
                self.sign_in(admin)
                for version in (None, 1):
                    with self.subTest(admin=admin, version=version):
                        written.clear()
                        response, _revision = self.download(pdf_url(self.diagnostic, version, admin=admin))
                        self.assertEqual(response.status_code, 200)
                        self.assertOnlyFontCopies(written, renders=1)

    def test_each_account_downloads_at_most_its_rate(self):
        self.submit(self.demo)
        with mock.patch.object(ReportPdfThrottle, 'THROTTLE_RATES', {'report_pdf': '2/min'}):
            for _ in range(2):
                self.assertEqual(self.client.get(pdf_url(self.demo)).status_code, 200)
            response, revision = self.download(pdf_url(self.demo, 1))
            self.assertEqual(response.status_code, 429)
            self.assertIsNone(revision)  # refused before anything is rendered
            # Another account has a count of its own.
            self.as_admin()
            self.assertEqual(self.client.get(pdf_url(self.demo, admin=True)).status_code, 200)


@override_settings(CORS_ALLOWED_ORIGINS=['http://localhost:3000'])
class ReportPdfCorsTests(PdfApiTestCase):
    """The Hub, on another origin, may read a PDF's file name; no other origin gets anything it did not before."""

    def test_the_hub_reads_the_file_name_and_other_origins_get_no_cors_headers(self):
        self.submit(self.demo)
        for name, response in (
            ('download', self.client.get(pdf_url(self.demo), HTTP_ORIGIN='http://localhost:3000')),
            ('preview', self.client.post(report_url(self.demo, 'preview/'), {'version': 1, **report_input(self.demo)},
                                         format='json', HTTP_ORIGIN='http://localhost:3000')),
        ):
            with self.subTest(name):
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response['Access-Control-Allow-Origin'], 'http://localhost:3000')
                self.assertEqual(response['Access-Control-Allow-Credentials'], 'true')
                self.assertEqual(response['Access-Control-Expose-Headers'], 'Content-Disposition')
                self.assertRegex(response['Content-Disposition'], r'^(attachment|inline); filename="Demo-Report-Riya-')

        other = self.client.get(pdf_url(self.demo), HTTP_ORIGIN='https://elsewhere.example')
        self.assertEqual(other.status_code, 200)  # CORS is the browser's rule: it withholds the answer from that page
        for header in ('Access-Control-Allow-Origin', 'Access-Control-Allow-Credentials', 'Access-Control-Expose-Headers'):
            self.assertFalse(other.has_header(header), header)

        # A refusal reaches the Hub's script too, so it can say why.
        refused = self.client.get(pdf_url(self.demo, 9), HTTP_ORIGIN='http://localhost:3000')
        self.assertEqual((refused.status_code, refused.json()['error']), (404, 'NO_VERSION'))
        self.assertEqual(refused['Access-Control-Allow-Origin'], 'http://localhost:3000')
