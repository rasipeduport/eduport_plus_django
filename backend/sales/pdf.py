"""
A syllabus's customer-facing "Plan & Price" PDF, drawn from its content -- a
revision's, or a draft not yet saved (a preview) -- and a pricing version, in
the design of the Eduport Plus reference PDFs: the chapter table, fifteen rows
a page under the syllabus's title (the Bridge Course's by day), then the
packages page with the per-class fees, a card per package the syllabus
offers (sales.pricing.card_plan_types) and the inclusions.

Every page is one sheet with the logo: a sheet whose content would run onto
another page -- a long title or long chapter names on a full page, two
single-payment boxes -- is drawn again with fewer rows a page, or the packages
page tightened, until each fits (render_document).

As the report PDFs (reports.pdf), it is rendered for each request and never
stored, and everything it loads -- the stylesheet, the Manrope fonts, the
logo, the icons -- comes from pdf_assets through _AssetFetcher, which stops
the rendering at any other URL. Django's autoescaping keeps the Admin's text
as text. WeasyPrint copies the fonts into a temporary folder for Fontconfig;
syllabus_pdf removes it as soon as the PDF is written.
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

from .models import PlanType, Structure
from .pricing import chapter_totals, packages, plain
from .wording import package_title_of, subtitle_of

ASSETS = (Path(__file__).parent / 'pdf_assets').resolve()
TEMPLATE = 'sales/pdf/syllabus.html'
# Rows of the chapter table per page, as the references print them -- fewer, down to the
# minimum, when the rows or the title are long enough to run the page over.
ROWS_PER_PAGE = 15
MIN_ROWS_PER_PAGE = 5


def syllabus_pdf(content, pricing):
    """The PDF of ``content`` (a syllabus's), its packages priced by ``pricing``."""
    font_config = FontConfiguration()
    try:
        return render_document(content, pricing, font_config).write_pdf()
    finally:
        _remove_font_copies(font_config)


def render_document(content, pricing, font_config=None):
    """
    ``content`` laid out in pages, before it is written as a PDF: each sheet on
    a page of its own. A chapter sheet that runs over is drawn again with one
    row a page fewer; a packages sheet that runs over, tightened (``compact``).
    """
    rows_per_page, compact = ROWS_PER_PAGE, False
    while True:
        html = render_to_string(TEMPLATE, pdf_context(content, pricing, rows_per_page=rows_per_page, compact=compact))
        document = HTML(string=html, base_url=ASSETS.as_uri() + '/', url_fetcher=_AssetFetcher()).render(
            font_config=font_config,
        )
        spilled = spilled_sheets(document)
        if any(name.startswith('chapters-') for name in spilled) and rows_per_page > MIN_ROWS_PER_PAGE:
            rows_per_page -= 1
        elif 'packages' in spilled and not compact:
            compact = True
        else:
            return document


def spilled_sheets(document):
    """
    The sheets (``chapters-<n>``, ``packages``) whose end is not on the page
    they start on: the template marks each sheet's start and end with an id.
    A sheet carried onto another page (box-decoration-break: clone) repeats its
    id there, so a sheet starts on the first page that has it.
    """
    starts, ends = {}, {}
    for index, page in enumerate(document.pages):
        for anchor in page.anchors:
            if anchor.startswith('sheet-'):
                name = anchor.removeprefix('sheet-')
                if name.endswith('-end'):
                    ends.setdefault(name.removesuffix('-end'), index)
                else:
                    starts.setdefault(name, index)
    return {name for name, page in starts.items() if ends.get(name) != page}


def pdf_context(content, pricing, rows_per_page=ROWS_PER_PAGE, compact=False):
    """What the template prints: the content as the PDF words it, every amount in ``pricing``'s currency."""
    chapters = content['chapters']
    currency = pricing.currency
    rows = [
        {
            'position': position,
            'name': chapter['name'],
            'regular': classes(chapter.get('regular_classes')),
            'revision': classes(chapter.get('revision_classes')),
            'bridge': classes(chapter.get('bridge_classes')),
        }
        for position, chapter in enumerate(chapters, start=1)
    ]
    pages = [rows[start:start + rows_per_page] for start in range(0, len(rows), rows_per_page)]
    totals = chapter_totals(chapters)
    return {
        'title': content['title'],
        'subtitle': subtitle_of(content),
        'package_title': package_title_of(content),
        'compact': compact,
        'bridge': content['structure'] == Structure.BRIDGE_COURSE,
        'chapter_pages': [{'rows': page, 'last': index == len(pages) - 1} for index, page in enumerate(pages)],
        'totals': {column: classes(total) for column, total in totals.items()},
        'fees': {
            'standard': f'{money(pricing.standard_fee)} {currency}/Class',
            'offer': f'{money(pricing.offer_fee)} {currency}/Class',
            'has_offer': pricing.offer_fee < pricing.standard_fee,
        },
        'packages': [
            {
                'title': package.title,
                'classes_label': classes_label(package.classes),
                'classes': classes(package.classes),
                'fee_per_class': amount(package.fee_per_class, currency),
                'total': amount(package.total, currency),
                # The Revision card lists no class count, its total in bold, as the references do.
                'shows_class_count': package.plan_type != PlanType.REVISION,
                'single_payment': {
                    'price': amount(package.single_payment[0], currency),
                    'saving': amount(package.single_payment[1], currency),
                } if package.single_payment else None,
            }
            for package in packages(content['plan_types'], chapters, pricing)
        ],
        'inclusions': content['inclusions'],
    }


def classes(value):
    """A number of classes as printed: 4, 1.5 -- or nothing."""
    return plain(value) if value is not None else ''


def classes_label(value):
    return f'{classes(value)} Class' if value == 1 else f'{classes(value)} Classes'


def money(value):
    """An exact amount with thousands separators and whole cents: 1,330 -- 1,067.50 -- 687.375 keeps its every fil."""
    whole, _dot, fraction = plain(value).partition('.')
    return f'{int(whole):,}' + (f'.{fraction.ljust(2, "0")}' if fraction else '')


def amount(value, currency):
    return f'{currency} {money(value)}'


def _remove_font_copies(font_config):
    """Delete the temporary folder WeasyPrint copied the fonts into (as reports.pdf does)."""
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
    raise ValueError(f'Not a syllabus PDF asset: {url}')


class _AssetFetcher(URLFetcher):
    """Hands WeasyPrint the files in pdf_assets and nothing else: any other URL stops the rendering."""

    def __init__(self):
        super().__init__(fail_on_errors=True)

    def fetch(self, url, headers=None):
        path = asset_path(url)
        content_type = mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
        return URLFetcherResponse(url, body=path.read_bytes(), headers={'Content-Type': content_type})
