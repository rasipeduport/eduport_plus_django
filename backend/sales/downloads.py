"""
A syllabus's PDF as the Sales API hands it over (sales.pdf), as the report
PDFs do (reports.downloads):

    GET  /api/sales/syllabi/<id>/pdf/                       what it offers: its published revision,
                                                            or its draft before the first publication
    GET  /api/sales/syllabi/<id>/revisions/<number>/pdf/    one revision, a draft or a published one
    POST /api/sales/syllabi/pdf-preview/                    content not yet saved (the editor's preview)

Each prices the packages at the pricing in effect now; with none yet the
answer is 409 NO_PRICING. ``?disposition=inline`` shows it in the browser (a
preview); otherwise it downloads. The PDF is rendered for each request and
never stored, and leaves only as a private answer: Cache-Control private,
no-store, and no content sniffing. Its file name --
"Grade-6-CBSE-New-Syllabus-Plan-and-Price-r1.pdf" -- holds ASCII letters,
digits and hyphens only. Rendering costs real CPU, so each account may ask for
SYLLABUS_PDF_THROTTLE_RATE of them (30 a minute unless set).
"""
import re
import unicodedata

from django.http import HttpResponse
from rest_framework import status
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle

from .models import Structure
from .pdf import syllabus_pdf
from .pricing import active_pricing


class SyllabusPdfThrottle(UserRateThrottle):
    scope = 'syllabus_pdf'


class SyllabusPdfView:
    """
    Mixed into the APIViews that answer a syllabus PDF: their rate limit, and
    refusals as JSON whatever the client accepts -- one asking only for
    application/pdf still learns why it got none, rather than 406.
    """
    throttle_classes = [SyllabusPdfThrottle]

    def perform_content_negotiation(self, request, force=False):
        return super().perform_content_negotiation(request, force=True)


def pdf_response(request, content, suffix=''):
    """``content`` (a syllabus's) as its PDF, priced as now: inline when the request asks, else a download."""
    pricing = active_pricing()
    if pricing is None:
        return Response(
            {'error': 'NO_PRICING', 'message': 'Set up the global pricing first: the PDF prices every package.'},
            status=status.HTTP_409_CONFLICT,
        )
    inline = request.query_params.get('disposition') == 'inline'
    response = HttpResponse(syllabus_pdf(content, pricing), content_type='application/pdf')
    response['Content-Disposition'] = f'{"inline" if inline else "attachment"}; filename="{pdf_filename(content, suffix)}"'
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


def pdf_filename(content, suffix=''):
    """
    'Grade-6-CBSE-New-Syllabus-Plan-and-Price-r1.pdf', 'Grade-7-CBSE-Bridge-Course-r1.pdf' --
    the syllabus version only when the title does not already say it ('Grade 7 CBSE (Old Syllabus)').
    """
    kind = 'Bridge-Course' if content['structure'] == Structure.BRIDGE_COURSE else 'Plan-and-Price'
    title, version = _ascii_words(content['title']), _ascii_words(content['syllabus_version'])
    if version and f'-{version.lower()}-' in f'-{title.lower()}-':
        version = ''
    words = '-'.join(part for part in (title, version) if part)
    return f'{words or "Syllabus"}-{kind}{suffix}.pdf'


def _ascii_words(text):
    """``text``'s words in ASCII letters and digits, joined by hyphens: 'Grade 7 (Old Syllabus)' is 'Grade-7-Old-Syllabus'."""
    ascii_text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode()
    return '-'.join(re.findall(r'[A-Za-z0-9]+', ascii_text))[:80].strip('-')
