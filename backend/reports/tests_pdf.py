"""
The report PDFs (reports.pdf, design F.2, F.3): each type prints every field
where its sample does; a report the size of the samples keeps their page
count, two pages and one; the longest report P6 allows loses no text and
stays on the page, running onto further pages instead; the tutor's text is
printed, never run; nothing but the bundled assets can be loaded; and each
version prints exactly as it was saved.

Pages are read from WeasyPrint's layout -- the text boxes it places on each
page -- which is what the PDF is written from.
"""
import re
from unittest import mock

from django.test import SimpleTestCase
from weasyprint import HTML
from weasyprint.formatting_structure import boxes
from weasyprint.urls import FatalURLFetchingError

from bookings.models import BookingType

from .models import (
    DEMO_FIELD_CHARS,
    ITEM_CHARS,
    MAX_ITEMS,
    SUGGESTED_PLAN_CHARS,
    TEACHER_REMARKS_CHARS,
    DemoReport,
    DiagnosticReport,
    PerformanceLevel,
)
from .pdf import ASSETS, _AssetFetcher, asset_path, render_document, revision_document, revision_pdf
from .services import clean_fields
from .tests_services import ReportServiceTestCase, demo_input, diagnostic_input

DIAGNOSTIC = BookingType.DIAGNOSTIC
DEMO = BookingType.DEMO

SNAPSHOTS = {'student_name_snapshot': 'Riya Menon', 'grade_snapshot': '8', 'tutor_name_snapshot': 'Tutor Anu'}

# As long as the two samples' content.
DIAGNOSTIC_SAMPLE = {
    'score': 5, 'max_score': 10, 'performance_level': 'AVERAGE',
    'strength_areas': [
        'Addition and subtraction', 'Multiples', 'Number patterns', 'Decimal addition and subtraction',
        'Identifying shapes', 'Even and odd numbers', 'Unit conversion',
    ],
    'skills_to_strengthen': ['Division', 'Multiplication', 'Factors', 'Perimeter'],
    'teacher_remarks': (
        'The student has a good idea of addition, subtraction, multiples, number patterns, even and odd numbers '
        'and unit conversion. Needs good support with multiplication, division, factors and perimeter. Fractions '
        'are new to the student. Small careless mistakes should be corrected by doing more problems.'
    ),
    'suggested_plan': 'The student is at Foundation level, so the preferable plan is:\n30 Days Foundation Plan',
}
DEMO_SAMPLE = {
    'assessment_review': (
        'The student scored 5 out of 12 in the assessment. He shows a good basic understanding of core ideas, but '
        'lapses in concentration led to avoidable mistakes. He also needs some basics in solving equations.'
    ),
    'class_observation_review': (
        'The student was attentive and participative throughout, responded well to questions and engaged actively '
        'with the material. A few short lapses in focus were noted, but his grasp of foundational concepts was strong.'
    ),
    'suggested_strategy': (
        'The student participates well; reinforce focus with short, timed practice sets and immediate error review '
        'to strengthen retention.'
    ),
}

# One word with no place to break it, as long as a list item may be.
UNBROKEN = 'W' * ITEM_CHARS


def saved(booking_type, snapshots=None, **fields):
    """A revision's content, as P6 would save ``fields``: they pass its validation first."""
    model, defaults = (DiagnosticReport, diagnostic_input) if booking_type == DIAGNOSTIC else (DemoReport, demo_input)
    return {**clean_fields(model, defaults(**fields)), **SNAPSHOTS, **(snapshots or {})}


def filled(sentence, size):
    """``sentence`` repeated to exactly ``size`` characters."""
    return (sentence * (size // len(sentence) + 1))[:size - 1] + '.'


def longest(booking_type):
    """
    Every field at its cap in ordinary sentences, with long names and one
    unbroken word: the most a real report holds. (A field of nothing but
    unbroken words runs longer still; it too stays on the page, see
    test_a_word_too_long_for_its_line_wraps_inside_the_page.)
    """
    snapshots = {
        'student_name_snapshot': 'Mohammed Abdul Rahman Thekkekara Puthenveettil Al Mansoori',
        'grade_snapshot': '10',
        'tutor_name_snapshot': 'Sreelakshmi Chandrasekharan Kizhakkemadham',
    }
    if booking_type == DEMO:
        return saved(
            DEMO, snapshots,
            assessment_review=filled('Scored 9 out of 12; strong on equations, slower on two-step problems. ', DEMO_FIELD_CHARS),
            class_observation_review=filled('Attentive throughout, explained her reasoning aloud. ', DEMO_FIELD_CHARS),
            suggested_strategy=f'{UNBROKEN} ' + filled(
                'Short timed practice sets with immediate error review. ', DEMO_FIELD_CHARS - ITEM_CHARS - 1,
            ),
        )
    items = [UNBROKEN] + [
        filled(f'{n}. Solves multi-step word problems on ratios, explaining each step and checking the answer. ', ITEM_CHARS)
        for n in range(2, MAX_ITEMS + 1)
    ]
    return saved(
        DIAGNOSTIC, snapshots, score=999, max_score=1000, performance_level='BELOW_AVERAGE',
        strength_areas=items, skills_to_strengthen=items[::-1],
        teacher_remarks=filled('Works carefully and asks for help when a method is unclear.\n', TEACHER_REMARKS_CHARS),
        suggested_plan=filled('Two sessions a week on number sense, and a short timed quiz each Friday. ', SUGGESTED_PLAN_CHARS),
    )


def laid_out(page):
    """The text and images placed on ``page``, in document order."""
    return [
        box for box in page._page_box.descendants()
        if (isinstance(box, boxes.TextBox) and box.text.strip()) or isinstance(box, boxes.ReplacedBox)
    ]


def page_text(page):
    return ' '.join(box.text for box in laid_out(page) if isinstance(box, boxes.TextBox))


def squeezed(text):
    """``text`` without its whitespace, so a line wrapped anywhere still matches."""
    return ''.join(text.split())


def all_text(document):
    return squeezed(''.join(page_text(page) for page in document.pages))


class PdfTestCase(SimpleTestCase):
    def assertInOrder(self, text, parts):
        at = -1
        for part in parts:
            found = text.find(part, at + 1)
            self.assertGreater(found, at, f'{part!r} is missing or out of order in {text!r}')
            at = found

    def assertAllPrinted(self, document, content):
        """Every value of ``content`` -- each list item on its own -- is in ``document``, whole."""
        text = all_text(document)
        for field, value in content.items():
            for part in value if isinstance(value, list) else [str(value)]:
                with self.subTest(field=field):
                    self.assertIn(squeezed(part), text)

    def assertOnThePage(self, document):
        """No text or image runs past a page's margins, and none overlaps another."""
        for number, page in enumerate(document.pages, 1):
            page_box = page._page_box
            left, top = page_box.content_box_x(), page_box.content_box_y()
            right, bottom = left + page_box.width, top + page_box.height
            placed = [
                (box, box.content_box_x(), box.content_box_y(), box.width, box.height) for box in laid_out(page)
            ]
            for box, x, y, width, height in placed:
                with self.subTest(page=number, text=getattr(box, 'text', 'image')[:30]):
                    self.assertGreaterEqual(x, left - 0.5)
                    self.assertGreaterEqual(y, top - 0.5)
                    self.assertLessEqual(x + width, right + 0.5)
                    self.assertLessEqual(y + height, bottom + 0.5)
            for i, (a, ax, ay, aw, ah) in enumerate(placed):
                for b, bx, by, bw, bh in placed[i + 1:]:
                    overlaps = ax < bx + bw - 0.5 and bx < ax + aw - 0.5 and ay < by + bh - 0.5 and by < ay + ah - 0.5
                    self.assertFalse(overlaps, f'page {number}: {getattr(a, "text", "image")!r} overlaps '
                                               f'{getattr(b, "text", "image")!r}')

    def assertNoPageEndsOnAHeading(self, document):
        for number, page in enumerate(document.pages, 1):
            last = [box for box in laid_out(page) if isinstance(box, boxes.TextBox)][-1]
            self.assertNotIn(last.element_tag, ('h1', 'h2', 'h3'), f'page {number} ends on {last.text!r}')


class PdfContentTests(PdfTestCase):
    def test_the_diagnostic_prints_each_field_where_its_sample_does(self):
        document = render_document(DIAGNOSTIC, saved(DIAGNOSTIC, **DIAGNOSTIC_SAMPLE))

        self.assertEqual(len(document.pages), 2)
        first, second = (page_text(page) for page in document.pages)
        self.assertInOrder(first, [
            'Academic', 'Report',
            'Student Name', ':', 'Riya Menon', 'Grade', ':', '8', 'Subject', ':', 'Mathematics',
            'Assessment Type', ':', 'Diagnostic Test', 'Tutor Name', ':', 'Tutor Anu',
            'Summary', 'Score: 5/10', 'Performance Level: Average',
            'Strength Areas:', *DIAGNOSTIC_SAMPLE['strength_areas'],
        ])
        # Page two starts where the sample's does.
        self.assertTrue(second.startswith('Skills to Strengthen:'), second)
        self.assertInOrder(second, [
            'Skills to Strengthen:', *DIAGNOSTIC_SAMPLE['skills_to_strengthen'],
            'Teacher’s Remarks', 'The student has a good idea', 'Suggested Plan', '30 Days Foundation Plan',
        ])
        self.assertAllPrinted(document, {field: DIAGNOSTIC_SAMPLE[field] for field in (
            'strength_areas', 'skills_to_strengthen', 'teacher_remarks', 'suggested_plan',
        )})

    def test_the_demo_prints_each_field_on_one_page(self):
        document = render_document(DEMO, saved(DEMO, **DEMO_SAMPLE))

        self.assertEqual(len(document.pages), 1)
        text = page_text(document.pages[0])
        self.assertInOrder(text, [
            'Demo', 'Report',
            'Student Name', ':', 'Riya Menon', 'Grade', ':', '8', 'Subject', ':', 'Mathematics',
            'Tutor Name', ':', 'Tutor Anu',
            'Assessment Review', 'The student scored 5 out of 12',
            'Class Observation Review', 'The student was attentive',
            'Suggested Strategy', 'The student participates well',
        ])
        self.assertNotIn('Assessment Type', text)
        self.assertAllPrinted(document, DEMO_SAMPLE)

    def test_each_performance_level_prints_its_label(self):
        for level, label in PerformanceLevel.choices:
            with self.subTest(level=level):
                document = render_document(DIAGNOSTIC, saved(DIAGNOSTIC, performance_level=level))
                self.assertIn(f'Performance Level: {label}', page_text(document.pages[0]))

    def test_the_tutors_line_breaks_are_kept(self):
        document = render_document(DIAGNOSTIC, saved(
            DIAGNOSTIC, suggested_plan='The preferable plan is:\n30 Days Foundation Plan',
        ))
        lines = {box.text: box.content_box_y() for box in laid_out(document.pages[-1]) if isinstance(box, boxes.TextBox)}
        self.assertLess(lines['The preferable plan is:'], lines['30 Days Foundation Plan'])

    def test_the_pdf_carries_the_bundled_fonts_and_the_logo(self):
        pdf = render_document(DIAGNOSTIC, saved(DIAGNOSTIC)).write_pdf(uncompressed_pdf=True)

        self.assertTrue(pdf.startswith(b'%PDF-'))
        fonts = {name.decode() for name in re.findall(rb'/BaseFont\s*/[A-Z]{6}\+([A-Za-z-]+)', pdf)}
        self.assertEqual(fonts, {'Carlito', 'Carlito-Bold', 'Arimo-Bold'})
        self.assertIn(b'/Subtype /Image', pdf)


class PdfLengthTests(PdfTestCase):
    def test_reports_the_size_of_the_samples_keep_their_page_counts(self):
        self.assertEqual(len(render_document(DIAGNOSTIC, saved(DIAGNOSTIC, **DIAGNOSTIC_SAMPLE)).pages), 2)
        self.assertEqual(len(render_document(DEMO, saved(DEMO, **DEMO_SAMPLE)).pages), 1)

    def test_the_longest_reports_lose_no_text_and_run_onto_further_pages(self):
        # Measured with the bundled fonts: five pages and two. More would mean the layout grew.
        for booking_type, most_pages in ((DIAGNOSTIC, 5), (DEMO, 2)):
            with self.subTest(booking_type=booking_type):
                content = longest(booking_type)
                document = render_document(booking_type, content)

                self.assertGreater(len(document.pages), 1)
                self.assertLessEqual(len(document.pages), most_pages)
                # The score and level print as "Score: 999/1000" and a label, checked above.
                self.assertAllPrinted(document, {
                    field: value for field, value in content.items()
                    if field not in ('score', 'max_score', 'performance_level')
                })
                self.assertOnThePage(document)
                self.assertNoPageEndsOnAHeading(document)

    def test_a_word_too_long_for_its_line_wraps_inside_the_page(self):
        document = render_document(DIAGNOSTIC, saved(
            DIAGNOSTIC, {'student_name_snapshot': UNBROKEN}, strength_areas=[UNBROKEN],
            teacher_remarks=UNBROKEN * 3, suggested_plan=UNBROKEN,
        ))
        self.assertIn(squeezed(UNBROKEN * 3), all_text(document))
        self.assertOnThePage(document)

    def test_no_page_ends_on_a_heading_wherever_the_breaks_fall(self):
        # Text of every length moves the page break through the headings that follow it. Without
        # the keep-with-next rule, a Demo review of 400 to 600 characters leaves "Suggested
        # Strategy" alone at the foot of page one, and the longest Diagnostic (above) strands
        # "Teacher's Remarks".
        for size in range(100, TEACHER_REMARKS_CHARS + 1, 150):
            with self.subTest(remarks=size):
                document = render_document(DIAGNOSTIC, saved(
                    DIAGNOSTIC, **{**DIAGNOSTIC_SAMPLE, 'teacher_remarks': filled('Checks each step. ', size)},
                ))
                self.assertNoPageEndsOnAHeading(document)
                self.assertOnThePage(document)
        for size in range(100, DEMO_FIELD_CHARS + 1, 100):
            with self.subTest(assessment_review=size):
                document = render_document(DEMO, saved(DEMO, **{
                    **DEMO_SAMPLE, 'assessment_review': filled('Scored well. ', size),
                    'class_observation_review': filled('Attentive. ', DEMO_FIELD_CHARS),
                }))
                self.assertNoPageEndsOnAHeading(document)
                self.assertOnThePage(document)


class PdfSafetyTests(PdfTestCase):
    def test_the_tutors_text_is_printed_never_run(self):
        markup = '<b>Bold</b> <img src="http://example.com/x.png"> {{ score }} &amp; <script>alert(1)</script>'
        content = saved(
            DIAGNOSTIC, {'student_name_snapshot': '<i>Riya</i>'},
            strength_areas=[markup[:ITEM_CHARS]], teacher_remarks=markup, suggested_plan=markup,
        )
        # No URL in the tutor's text is ever fetched.
        with mock.patch('weasyprint.urls.URLFetcher.open', side_effect=AssertionError('fetched')):
            document = render_document(DIAGNOSTIC, content)

        text = all_text(document)
        self.assertIn(squeezed(markup), text)
        self.assertIn('<i>Riya</i>', text)
        images = [box for page in document.pages for box in laid_out(page) if isinstance(box, boxes.ReplacedBox)]
        self.assertEqual(len(images), 1)  # The logo.

    def test_only_the_bundled_assets_can_be_loaded(self):
        for name in ('logo.png', 'report.css', 'fonts/Carlito-Regular.ttf'):
            with self.subTest(allowed=name):
                self.assertEqual(asset_path((ASSETS / name).as_uri()), ASSETS / name)
        refused = (
            'http://example.com/logo.png',
            'https://example.com/report.css',
            'data:image/png;base64,iVBORw0KGgo=',
            'ftp://example.com/logo.png',
            'file:///etc/passwd',
            (ASSETS / '..' / 'models.py').as_uri(),
            ASSETS.as_uri(),
            (ASSETS / 'missing.png').as_uri(),
            f'file://example.com{ASSETS / "logo.png"}',
        )
        for url in refused:
            with self.subTest(refused=url):
                with self.assertRaises(ValueError):
                    asset_path(url)

    def test_any_other_url_stops_the_rendering(self):
        for src in ('http://example.com/x.png', '../models.py', 'file:///etc/hostname'):
            with self.subTest(src=src):
                html = HTML(string=f'<img src="{src}">', base_url=ASSETS.as_uri() + '/', url_fetcher=_AssetFetcher())
                with self.assertRaises(FatalURLFetchingError):
                    html.render()


class RevisionPdfTests(ReportServiceTestCase):
    def test_each_version_prints_exactly_as_it_was_saved(self):
        report = self.submit(self.diagnostic, teacher_remarks='First thoughts on the test.')
        self.tutor.full_name = 'Anu Mathew'
        self.tutor.save(update_fields=['full_name'])
        self.edit(self.diagnostic, 1, teacher_remarks='Second thoughts after marking again.')
        first, second = report.revisions.order_by('version')

        old = all_text(revision_document(first))
        self.assertIn(squeezed('First thoughts on the test.'), old)
        self.assertIn('TutorAnu', old)
        self.assertNotIn('Secondthoughts', old)
        self.assertNotIn('AnuMathew', old)

        new = all_text(revision_document(second))
        self.assertIn(squeezed('Second thoughts after marking again.'), new)
        self.assertIn('AnuMathew', new)
        self.assertNotIn('Firstthoughts', new)

    def test_a_revision_is_written_with_its_own_reports_template(self):
        self.submit(self.diagnostic)
        self.submit(self.demo)
        for booking, title, pages in ((self.diagnostic, 'AcademicReport', 2), (self.demo, 'DemoReport', 1)):
            with self.subTest(booking_type=booking.booking_type):
                revision = booking.report.revisions.get()
                document = revision_document(revision)
                self.assertEqual(len(document.pages), pages)
                self.assertTrue(all_text(document).startswith(title))
                self.assertTrue(revision_pdf(revision).startswith(b'%PDF-'))
