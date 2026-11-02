"""
Report PDFs (design F.2, F.3): one saved version of a report, drawn as the
samples draw it -- the Academic Report for a Diagnostic, the Demo Report for a
Demo.

A PDF is always drawn from a revision's content: the report exactly as saved
at that version, the tutor's fields and the system snapshots alike (D7).
Revisions are append-only (reports.0002), so a version prints the same content
every time, and the current report is simply its latest revision. A preview
(P8) is drawn from the content a save would store
(reports.services.preview_content), by the same content_pdf, so it prints
exactly as the saved version will. Nothing is stored: every PDF is rendered
when it is asked for.

Each report type has a template of its own (reports/pdf/diagnostic.html and
demo.html, over one stylesheet). Everything they load -- the stylesheet, the
fonts, the logo -- comes from pdf_assets through _AssetFetcher, which stops
the rendering at any other URL, so a report never reaches the network or the
rest of the disk. Django's autoescaping keeps the tutor's text as text.

The one thing a rendering writes is WeasyPrint's: Fontconfig loads fonts from
files, so it copies the bundled fonts into a temporary folder. content_pdf
removes that folder as soon as the PDF is written.

Longer content runs onto further pages and is never clipped: a report the size
of the samples is two pages (Diagnostic) or one (Demo).
"""
import mimetypes
import shutil
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import url2pathname

from django.template.loader import render_to_string
from weasyprint import HTML
from weasyprint.text.fonts import FontConfiguration
from weasyprint.urls import URLFetcher, URLFetcherResponse

from bookings.models import BookingType

from .models import PerformanceLevel, report_model

ASSETS = (Path(__file__).parent / 'pdf_assets').resolve()

TEMPLATES = {
    BookingType.DIAGNOSTIC: 'reports/pdf/diagnostic.html',
    BookingType.DEMO: 'reports/pdf/demo.html',
}


def revision_pdf(revision):
    """The PDF of ``revision`` (a Diagnostic or Demo report revision): its report as saved at that version."""
    return content_pdf(_booking_type(revision), revision.content)


def content_pdf(booking_type, content):
    """
    The PDF of ``content`` -- a revision's, or the one a save would store (a
    preview) -- drawn by the template of ``booking_type``.
    """
    font_config = FontConfiguration()
    try:
        return render_document(booking_type, content, font_config).write_pdf()
    finally:
        _remove_font_copies(font_config)


def revision_document(revision, font_config=None):
    """``revision`` laid out in pages, before it is written as a PDF."""
    return render_document(_booking_type(revision), revision.content, font_config)


def _booking_type(revision):
    return type(revision)._meta.get_field('report').related_model.BOOKING_TYPE


def render_document(booking_type, content, font_config=None):
    """
    ``content`` -- a revision's: the tutor's fields and the three snapshots --
    laid out in pages by the template of ``booking_type``.
    """
    html = render_to_string(TEMPLATES[booking_type], report_context(booking_type, content))
    document = HTML(string=html, base_url=ASSETS.as_uri() + '/', url_fetcher=_AssetFetcher())
    return document.render(font_config=font_config)


def report_context(booking_type, content):
    """What the template prints: each tutor field as saved, the system fields as snapshotted."""
    context = {field: content[field] for field in report_model(booking_type).TUTOR_FIELDS}
    if booking_type == BookingType.DIAGNOSTIC:
        context['performance_level'] = PerformanceLevel(content['performance_level']).label
    context.update(
        student_name=content['student_name_snapshot'],
        grade=content['grade_snapshot'],
        tutor_name=content['tutor_name_snapshot'],
    )
    return context


def _remove_font_copies(font_config):
    """
    Delete the temporary folder WeasyPrint copied the fonts into. It would go
    when ``font_config`` is garbage collected, but a reference cycle can keep
    it until the next collection, so a busy worker would gather them meanwhile.
    """
    folder = getattr(font_config, '_folder', None)
    if folder:
        shutil.rmtree(folder, ignore_errors=True)


def asset_path(url):
    """The file in pdf_assets that ``url`` names. Raises ValueError for any other URL."""
    parts = urlsplit(url)
    if parts.scheme == 'file' and parts.netloc in ('', 'localhost'):
        path = Path(url2pathname(parts.path)).resolve()
        if path.is_relative_to(ASSETS) and path.is_file():
            return path
    raise ValueError(f'Not a report asset: {url}')


class _AssetFetcher(URLFetcher):
    """Hands WeasyPrint the files in pdf_assets and nothing else: any other URL stops the rendering."""

    def __init__(self):
        super().__init__(fail_on_errors=True)

    def fetch(self, url, headers=None):
        path = asset_path(url)
        content_type = mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
        return URLFetcherResponse(url, body=path.read_bytes(), headers={'Content-Type': content_type})
