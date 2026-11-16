"""
Syllabus PDFs (sales.pdf, sales.downloads): drawn from a syllabus's content in
the reference PDFs' layout -- fifteen chapter rows a page, then the packages
page -- priced at the pricing in effect, rendered for each request and handed
over privately.
"""
from decimal import Decimal as D

from django.template.loader import render_to_string
from django.test import SimpleTestCase

from .downloads import pdf_filename
from .models import PricingVersion
from weasyprint import HTML

from .pdf import ASSETS, TEMPLATE, _AssetFetcher, asset_path, pdf_context, render_document, spilled_sheets, syllabus_pdf
from .reference_syllabi import REFERENCE_SYLLABI
from .serializers import SyllabusContentSerializer
from .tests_api import PRICING, REFERENCE_PRICING, SYLLABI, SalesApiTestCase
from .tests_lifecycle import account, bridge_payload, chapter_wise_payload

GRADE_6, GRADE_7_NEW, GRADE_9, GRADE_7_BRIDGE = (REFERENCE_SYLLABI[0], REFERENCE_SYLLABI[2], REFERENCE_SYLLABI[6],
                                                  REFERENCE_SYLLABI[8])


def pricing(**fields):
    return PricingVersion(**{
        'version': 1, 'currency': 'AED', 'standard_fee': D('45'), 'offer_fee': D('35'),
        'single_payment_percent': D('5'), 'single_payment_plan_types': ['REGULAR'], **fields,
    })


def content(payload, **changes):
    serializer = SyllabusContentSerializer(data={**payload, **changes})
    assert serializer.is_valid(), serializer.errors
    return serializer.validated_data


class LayoutTests(SimpleTestCase):
    def test_grade_6_is_a_chapter_page_and_a_packages_page(self):
        pdf = syllabus_pdf(content(GRADE_6), pricing())
        self.assertTrue(pdf.startswith(b'%PDF'))
        self.assertEqual(len(render_document(content(GRADE_6), pricing()).pages), 2)

    def test_a_bridge_course_prints_fifteen_days_a_page(self):
        context = pdf_context(content(GRADE_7_BRIDGE), pricing())
        self.assertEqual([len(page['rows']) for page in context['chapter_pages']], [15, 15])
        self.assertEqual([page['last'] for page in context['chapter_pages']], [False, True])
        self.assertEqual(len(render_document(content(GRADE_7_BRIDGE), pricing()).pages), 3)

    def test_a_bridge_course_has_its_own_table_and_one_package(self):
        context = pdf_context(content(GRADE_7_BRIDGE), pricing())
        html = render_to_string(TEMPLATE, context)
        self.assertIn('<th class="serial">Day</th>', html)
        self.assertIn('No Of Classes', html)
        self.assertNotIn('Regular Plan', html)
        self.assertNotIn('Revision Plan', html)
        self.assertEqual(html.count('Total No Of Classes'), 1)  # on its last page only
        self.assertEqual(context['totals']['bridge'], '30')
        self.assertEqual([(p['title'], p['classes_label'], p['total'], p['shows_class_count'], p['single_payment'])
                          for p in context['packages']],
                         [('Bridge Course Package', '30 Classes', 'AED 1,050', True, None)])
        self.assertIn('Detailed Bridge Course Curriculum', html)

    def test_every_sheet_fits_its_page_even_with_a_long_title_or_long_names(self):
        # The reference's fifteen chapters and total fit one page under a one-line title...
        document = render_document(content(GRADE_7_NEW), pricing())
        self.assertEqual((len(document.pages), spilled_sheets(document)), (2, set()))
        # ...and under a title that wraps beside the logo, the last chapter and the total move to a sheet of their own.
        long_title = content(GRADE_7_NEW, title='Grade 7 CBSE Mathematics Complete Course (New Syllabus)')
        # (At a fixed fifteen rows the total row would run onto a page with no logo or title: the detector sees it.)
        fixed = HTML(string=render_to_string(TEMPLATE, pdf_context(long_title, pricing())),
                     base_url=ASSETS.as_uri() + '/', url_fetcher=_AssetFetcher()).render()
        self.assertEqual((len(fixed.pages), spilled_sheets(fixed)), (3, {'chapters-0'}))
        self.assertNotIn('sheet-chapters-1', fixed.pages[1].anchors)
        document = render_document(long_title, pricing())
        self.assertEqual((len(document.pages), spilled_sheets(document)), (3, set()))
        # Every page now starts a sheet of its own -- each chapter page with the logo and the title.
        self.assertEqual([sorted(a for a in page.anchors if a.startswith('sheet-') and not a.endswith('-end'))
                          for page in document.pages],
                         [['sheet-chapters-0'], ['sheet-chapters-1'], ['sheet-packages']])
        # Very long chapter names are moved to the next sheet, never left to run off the page.
        names = content(GRADE_7_NEW, chapters=[
            {'name': ('Introduction To Cartesian Plane, Plotting Points And Their Coordinates, Essential For '
                      'Coordinate Geometry And Graphs Of Linear Equations In Two Variables') if n % 3 == 0 else f'Chapter {n}',
             'regular_classes': '3', 'revision_classes': '2'}
            for n in range(1, 16)
        ])
        document = render_document(names, pricing())
        self.assertEqual(spilled_sheets(document), set())

    def test_two_single_payment_boxes_still_fit_the_packages_page(self):
        both = pricing(single_payment_plan_types=['REGULAR', 'REVISION'])
        self.assertEqual([p['single_payment'] is not None for p in pdf_context(content(GRADE_6), both)['packages']],
                         [True, True])
        document = render_document(content(GRADE_6), both)
        self.assertEqual((len(document.pages), spilled_sheets(document)), (2, set()))

    def test_the_single_payment_privilege_box_is_under_each_package_the_pricing_gives_it_to(self):
        # Grade 9: 79 Regular classes at AED 35 are AED 2,765; 5% off is 2,626.75, rounded to the nearest whole
        # dirham, AED 2,627 (D1), and the saving is worked out from that price: AED 138 -- as the reference PDF.
        context = pdf_context(content(GRADE_9), pricing())
        self.assertEqual([(p['title'], p['total'], p['single_payment']) for p in context['packages']], [
            ('Regular Course Package', 'AED 2,765', {'price': 'AED 2,627', 'saving': 'AED 138'}),
            ('Revision Course (Exam Oriented) Package', 'AED 1,435', None),
        ])
        html = render_to_string(TEMPLATE, context)
        regular_card = html.split('<div class="card">')[1]
        for text in ('<div class="name">Single-Payment Privilege</div>',
                     '<div class="note">Pay In One Instalment And Get A Special Price</div>',
                     'Save <b>AED 138</b> Instantly', '<td class="price">AED 2,627</td>'):
            self.assertIn(text, regular_card)
        self.assertEqual(html.count('<table class="privilege">'), 1)
        self.assertEqual(spilled_sheets(render_document(content(GRADE_9), pricing())), set())
        # None at 0%, whatever packages the version lists (as one saved before the privilege had to be on or off)...
        off = pricing(single_payment_percent=D('0'), single_payment_plan_types=['REGULAR', 'REVISION', 'BRIDGE_COURSE'])
        self.assertNotIn('Single-Payment Privilege', render_to_string(TEMPLATE, pdf_context(content(GRADE_9), off)))
        # ...and none under Regular when the privilege is for Revision only.
        cards = render_to_string(TEMPLATE, pdf_context(content(GRADE_9), pricing(single_payment_plan_types=['REVISION'])))
        self.assertEqual(['<table class="privilege">' in card for card in cards.split('<div class="card">')[1:]],
                         [False, True])

    def test_a_long_syllabus_runs_onto_more_chapter_pages(self):
        chapters = [{'name': f'Chapter {n}', 'regular_classes': '2', 'revision_classes': '1'} for n in range(1, 17)]
        self.assertEqual(len(render_document(content(GRADE_6, chapters=chapters), pricing()).pages), 3)

    def test_the_cards_follow_the_plan_types(self):
        def cards(plan_types):
            return [p['title'] for p in pdf_context(content(GRADE_6, plan_types=plan_types), pricing())['packages']]
        both = ['Regular Course Package', 'Revision Course (Exam Oriented) Package']
        self.assertEqual(cards(['REGULAR_REVISION']), both)
        self.assertEqual(cards(['REGULAR', 'CHAPTER_PLAN']), ['Regular Course Package'])
        self.assertEqual(cards(['REVISION']), ['Revision Course (Exam Oriented) Package'])
        self.assertEqual(cards(['CHAPTER_PLAN']), [])
        self.assertEqual(len(render_document(content(GRADE_6, plan_types=['CHAPTER_PLAN']), pricing()).pages), 2)

    def test_the_packages_page_reads_as_the_reference(self):
        context = pdf_context(content(GRADE_6), pricing())
        self.assertEqual(context['fees'], {'standard': '45 AED/Class', 'offer': '35 AED/Class', 'has_offer': True})
        regular, revision = context['packages']
        self.assertEqual(
            (regular['classes_label'], regular['fee_per_class'], regular['total'], regular['shows_class_count']),
            ('38 Classes', 'AED 35', 'AED 1,330', True),
        )
        self.assertEqual(regular['single_payment'], {'price': 'AED 1,264', 'saving': 'AED 66'})
        self.assertEqual((revision['total'], revision['shows_class_count'], revision['single_payment']),
                         ('AED 665', False, None))
        self.assertEqual(context['totals'], {'regular': '38', 'revision': '19', 'bridge': '0'})
        html = render_to_string(TEMPLATE, context)
        for text in ('Grade 6 CBSE', 'Detailed Chapter-Wise 1:1 Learning Plan', 'Total No Of Classes',
                     'Grade 6 CBSE – 1:1 Tuition Packages &amp; Fee Details', 'Save <b>AED 66</b> Instantly',
                     'Structured CBSE aligned learning'):
            self.assertIn(text, html)

    def test_half_classes_and_exact_amounts(self):
        chapters = [{'name': 'Real Numbers', 'regular_classes': '4', 'revision_classes': '1.5'},
                    {'name': 'Polynomials', 'regular_classes': '4', 'revision_classes': '18'}]
        context = pdf_context(content(GRADE_6, chapters=chapters), pricing(currency='INR', standard_fee=D('1500'),
                                                                            offer_fee=D('1250.25')))
        self.assertEqual(context['chapter_pages'][0]['rows'][0]['revision'], '1.5')
        revision = context['packages'][1]
        self.assertEqual((revision['classes_label'], revision['total']), ('19.5 Classes', 'INR 24,379.875'))
        self.assertEqual(context['fees']['offer'], '1,250.25 INR/Class')
        # Rounded only here: 10,002 x 0.95 = 9,501.90 -> 9,502.
        self.assertEqual(context['packages'][0]['single_payment'], {'price': 'INR 9,502', 'saving': 'INR 500'})
        # A fraction of a currency unit prints whole cents: 3.5 classes at AED 35 are AED 122.50.
        halves = pdf_context(content(GRADE_6, plan_types=['REVISION'], chapters=[
            {'name': 'Real Numbers', 'regular_classes': '4', 'revision_classes': '3.5'}]), pricing())
        self.assertEqual(halves['packages'][0]['total'], 'AED 122.50')

    def test_no_offer_shows_the_standard_fee_alone(self):
        context = pdf_context(content(GRADE_6), pricing(offer_fee=D('45')))
        self.assertFalse(context['fees']['has_offer'])
        self.assertNotIn('<s>', render_to_string(TEMPLATE, context))

    def test_the_admins_text_stays_text(self):
        html = render_to_string(TEMPLATE, pdf_context(content(GRADE_6, title='<img src=x onerror=1>'), pricing()))
        self.assertIn('&lt;img src=x onerror=1&gt;', html)
        self.assertNotIn('<img src=x', html)

    def test_the_file_name_says_the_version_once(self):
        self.assertEqual(pdf_filename(content(GRADE_6), '-r1'), 'Grade-6-CBSE-New-Syllabus-Plan-and-Price-r1.pdf')
        old = content(REFERENCE_SYLLABI[3])  # 'Grade 7 CBSE (Old Syllabus)', version 'Old Syllabus'
        self.assertEqual(pdf_filename(old), 'Grade-7-CBSE-Old-Syllabus-Plan-and-Price.pdf')
        self.assertEqual(pdf_filename(content(GRADE_7_BRIDGE), '-preview'), 'Grade-7-CBSE-Bridge-Course-preview.pdf')

    def test_only_its_own_assets_load(self):
        self.assertEqual(asset_path(asset_path.__globals__['ASSETS'].joinpath('logo.png').as_uri()).name, 'logo.png')
        for url in ('file:///etc/passwd', 'https://example.com/logo.png',
                    asset_path.__globals__['ASSETS'].joinpath('..', 'models.py').as_uri()):
            with self.subTest(url=url), self.assertRaises(ValueError):
                asset_path(url)


class PdfApiTests(SalesApiTestCase):
    def setUp(self):
        super().setUp()
        self.syllabus = self.create()

    def test_no_pdf_without_pricing(self):
        response = self.client.get(f'{SYLLABI}{self.syllabus["id"]}/pdf/', HTTP_ACCEPT='application/pdf')
        self.assertEqual((response.status_code, response.json()['error']), (409, 'NO_PRICING'))

    def test_download_preview_and_revision(self):
        self.client.post(PRICING, REFERENCE_PRICING, format='json')
        url = f'{SYLLABI}{self.syllabus["id"]}/'
        download = self.client.get(f'{url}pdf/')
        self.assertEqual(download.status_code, 200)
        self.assertEqual(download['Content-Type'], 'application/pdf')
        self.assertEqual(download['Content-Disposition'], 'attachment; filename="Grade-6-CBSE-New-Syllabus-Plan-and-Price-r1.pdf"')
        self.assertEqual((download['Cache-Control'], download['X-Content-Type-Options']), ('private, no-store', 'nosniff'))
        self.assertTrue(download.content.startswith(b'%PDF'))

        inline = self.client.get(f'{url}revisions/1/pdf/', {'disposition': 'inline'})
        self.assertTrue(inline['Content-Disposition'].startswith('inline; filename="Grade-6-CBSE-New-Syllabus-Plan-and-Price-r1'))
        self.assertEqual(self.client.get(f'{url}revisions/2/pdf/').status_code, 404)

        preview = self.client.post(f'{SYLLABI}pdf-preview/?disposition=inline', bridge_payload(), format='json')
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview['Content-Disposition'], 'inline; filename="Grade-7-CBSE-Bridge-Course-preview.pdf"')
        invalid = self.client.post(f'{SYLLABI}pdf-preview/', chapter_wise_payload(chapters=[]), format='json')
        self.assertEqual((invalid.status_code, invalid.json()['error']), (400, 'VALIDATION_ERROR'))

    def test_only_administrators(self):
        self.client.post(PRICING, REFERENCE_PRICING, format='json')
        self.client.force_authenticate(account('pdf_mentor', 'MENTOR'))
        self.assertEqual(self.client.get(f'{SYLLABI}{self.syllabus["id"]}/pdf/').status_code, 403)
        self.assertEqual(self.client.post(f'{SYLLABI}pdf-preview/', chapter_wise_payload(), format='json').status_code, 403)
