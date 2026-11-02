"""
A report's PDF as the report APIs hand it over (design F.3). The tutor's
routes (reports.tutor_views), the Admin's (reports.management_views) and the
lead's owner BDE's (reports.bde_views, the current version only, P9) each find
the booking the caller may see, then answer with report_pdf_response:

    GET .../report/pdf/                       the report as last saved
    GET .../report/revisions/<version>/pdf/   the report as saved at <version>

Both print a revision row (reports.pdf), so an old version prints as it was
saved, the current one being the report's latest revision. A version is looked
up only inside the report of the booking already found for the caller, so a
changed number never reaches another report; one the report does not have is
404 NO_VERSION.

The PDF is rendered for each request and never stored, and leaves only as a
private download: Content-Disposition attachment, Cache-Control private,
no-store, and no content sniffing. Its file name -- "Diagnostic-Report-Riya-Menon-2026-10-28.pdf",
the slot's date in IST, with "-v1" added on the versions route -- holds ASCII
letters, digits and hyphens only. Rendering costs real CPU, so each account may
download REPORT_PDF_THROTTLE_RATE of them (30 a minute unless set).

The tutor's preview (P8, report_preview_response) is the PDF of a report not
yet saved, drawn by the same reports.pdf.content_pdf: the same private,
uncached answer, shown inline and named "...-preview.pdf". It counts against
the same rate.
"""
import re
import unicodedata

from django.http import HttpResponse
from rest_framework import status
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle

from .pdf import content_pdf, revision_pdf


class ReportPdfThrottle(UserRateThrottle):
    scope = 'report_pdf'


class ReportPdfView:
    """
    Mixed into the APIViews that answer a report's PDF: their rate limit, and
    refusals as JSON whatever the client accepts -- one asking only for
    application/pdf still learns why it got none, rather than 406.
    """
    throttle_classes = [ReportPdfThrottle]

    def perform_content_negotiation(self, request, force=False):
        return super().perform_content_negotiation(request, force=True)


def report_pdf_response(booking, report, version=None):
    """
    ``report`` (``booking``'s) as a PDF download: as last saved, or as saved
    at ``version`` when one is named -- else 404 NO_VERSION.
    """
    revision = report.revisions.filter(version=report.version if version is None else version).first()
    if revision is None:
        return Response(
            {'error': 'NO_VERSION', 'message': 'This report has no such version.'}, status=status.HTTP_404_NOT_FOUND,
        )
    name = pdf_filename(booking, revision, numbered=version is not None)
    return _pdf_response(revision_pdf(revision), f'attachment; filename="{name}"')


def report_preview_response(booking, content):
    """
    ``content`` -- what a save would store (reports.services.preview_content)
    -- as the PDF it would make, to look at before saving. Nothing is kept.
    """
    name = _filename(booking, content, suffix='-preview')
    return _pdf_response(content_pdf(booking.booking_type, content), f'inline; filename="{name}"')


def _pdf_response(pdf, disposition):
    response = HttpResponse(pdf, content_type='application/pdf')
    response['Content-Disposition'] = disposition
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


def pdf_filename(booking, revision, numbered=False):
    """'Diagnostic-Report-Riya-Menon-2026-10-28.pdf', or '...-v1.pdf' when ``numbered``."""
    return _filename(booking, revision.content, suffix=f'-v{revision.version}' if numbered else '')


def _filename(booking, content, suffix=''):
    student = _ascii_words(content['student_name_snapshot']) or 'Student'
    return f'{booking.get_booking_type_display()}-Report-{student}-{booking.slot.local_date:%Y-%m-%d}{suffix}.pdf'


def _ascii_words(text):
    """``text``'s words in ASCII letters and digits, joined by hyphens: 'Ríya  Menon' is 'Riya-Menon'."""
    ascii_text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode()
    return '-'.join(re.findall(r'[A-Za-z0-9]+', ascii_text))[:60].strip('-')
