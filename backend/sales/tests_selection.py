"""
A Bridge Course bought by the day (sales.pricing, sales.pdf,
sales.services.bridge_selection, the selection endpoints): the days chosen
are rows of one published revision, priced at the global offer fee per class
with exact decimals and half classes, the single-payment privilege on their
total as on the whole course's, and drawn under their own day numbers in the
course's order. Choosing every day is the whole course, exactly as before.
Nothing is written, copied or changed.
"""
from decimal import Decimal as D

from django.template.loader import render_to_string
from django.test import SimpleTestCase, TestCase
from rest_framework.test import APITestCase

from activity.models import ActivityLog

from . import services
from .models import PlanType, PricingVersion, Syllabus, SyllabusChapter, SyllabusRevision
from .pdf import TEMPLATE, pdf_context, render_document, spilled_sheets
from .pricing import SELECTED_DAYS_TITLE, packages, plan_classes
from .reference_syllabi import REFERENCE_SYLLABI
from .serializers import SyllabusContentSerializer
from .services import SalesError
from .tests_lifecycle import account, chapter_wise_payload, valid

BRIDGE = PlanType.BRIDGE_COURSE
SYLLABI = '/api/sales/syllabi/'
# Ten days of a Bridge Course: whole, half and no classes (day 6), 10 classes in all.
DAYS = ['1', '1.5', '0.5', '2', '1', '0', '1', '1', '1', '1']


def pricing(**fields):
    return PricingVersion(**{
        'version': 3, 'currency': 'AED', 'standard_fee': D('45'), 'offer_fee': D('35'),
        'single_payment_percent': D('5'), 'single_payment_plan_types': ['REGULAR'], **fields,
    })


def days(counts=DAYS):
    """Bridge Course rows as the PDF reads them, with ids as a revision's chapters have."""
    return [{'id': f'day-{n}', 'name': f'Day {n} topic', 'regular_classes': None, 'revision_classes': None,
             'bridge_classes': D(count)} for n, count in enumerate(counts, start=1)]


def reference_bridge():
    """The Grade 7 Bridge Course reference (30 days of one class), its rows with ids."""
    serializer = SyllabusContentSerializer(data=REFERENCE_SYLLABI[8])
    assert serializer.is_valid(), serializer.errors
    content = dict(serializer.validated_data)
    content['chapters'] = [{**chapter, 'id': f'day-{n}'} for n, chapter in enumerate(content['chapters'], start=1)]
    return content


class SelectedDaysPricingTests(SimpleTestCase):
    def test_the_whole_course_is_every_day_and_a_choice_only_its_days(self):
        rows = days()
        self.assertEqual(plan_classes(BRIDGE, rows), D('10'))
        self.assertEqual(plan_classes(BRIDGE, rows, ['day-2', 'day-3']), D('2'))
        # The order of the choice changes nothing; nor do ids not among the rows; none chosen sells nothing.
        self.assertEqual(plan_classes(BRIDGE, rows, ['day-4', 'day-1']), plan_classes(BRIDGE, rows, ['day-1', 'day-4']))
        self.assertEqual(plan_classes(BRIDGE, rows, ['day-1', 'elsewhere']), D('1'))
        self.assertEqual(plan_classes(BRIDGE, rows, []), D('0'))

    def test_the_selected_days_package_at_the_offer_fee_with_exact_decimals(self):
        [card] = packages([BRIDGE], days(), pricing(), selected=['day-2', 'day-3', 'day-9'])
        self.assertEqual((card.title, card.classes, card.fee_per_class, card.total, card.single_payment),
                         (SELECTED_DAYS_TITLE, D('3'), D('35'), D('105'), None))
        # A half class at a fee with fils: 1.5 x 35.25 = 52.875, kept to the fil.
        [card] = packages([BRIDGE], days(), pricing(offer_fee=D('35.25')), selected=['day-2'])
        self.assertEqual((card.classes, card.total), (D('1.5'), D('52.875')))

    def test_the_whole_course_keeps_its_own_package(self):
        [card] = packages([BRIDGE], days(), pricing())
        self.assertEqual((card.title, card.classes, card.total), ('Bridge Course Package', D('10'), D('350')))
        # A choice reaches the Bridge Course card only: a chapter-wise syllabus's cards are as before.
        rows = [{'id': 'c1', 'regular_classes': D('4'), 'revision_classes': D('2'), 'bridge_classes': None}]
        self.assertEqual(packages(['REGULAR_REVISION'], rows, pricing(), selected=['c1']),
                         packages(['REGULAR_REVISION'], rows, pricing()))

    def test_the_single_payment_privilege_applies_to_the_days_chosen_as_to_the_whole_course(self):
        on_bridge = pricing(single_payment_plan_types=['BRIDGE_COURSE'])
        # 2 classes are AED 70; less 5% is 66.50, a half, rounded up to 67: saving 3.
        [card] = packages([BRIDGE], days(), on_bridge, selected=['day-2', 'day-3'])
        self.assertEqual(card.single_payment, (D('67'), D('3')))
        # 3 classes, AED 105, less 5% is 99.75 -> 100, saving 5; the whole course, 350 -> 332.50 -> 333.
        self.assertEqual(packages([BRIDGE], days(), on_bridge, selected=['day-1', 'day-4'])[0].single_payment,
                         (D('100'), D('5')))
        self.assertEqual(packages([BRIDGE], days(), on_bridge)[0].single_payment, (D('333'), D('17')))
        # Exact until the price: 1.5 classes at 35.25 = 52.875, less 5% is 50.23125 -> 50, saving 2.875.
        fils = pricing(offer_fee=D('35.25'), single_payment_plan_types=['BRIDGE_COURSE'])
        self.assertEqual(packages([BRIDGE], days(), fils, selected=['day-2'])[0].single_payment, (D('50'), D('2.875')))
        # Not for Bridge Course, or off: no privilege, chosen days or not.
        self.assertIsNone(packages([BRIDGE], days(), pricing(), selected=['day-2'])[0].single_payment)
        off = pricing(single_payment_percent=D('0'), single_payment_plan_types=[])
        self.assertIsNone(packages([BRIDGE], days(), off, selected=['day-2'])[0].single_payment)


class SelectedDaysPdfTests(SimpleTestCase):
    def test_only_the_days_chosen_under_their_own_numbers_in_the_course_order(self):
        content = reference_bridge()
        context = pdf_context(content, pricing(), selected=['day-12', 'day-3', 'day-7'])
        [page] = context['chapter_pages']
        self.assertEqual([(row['position'], row['name'], row['bridge']) for row in page['rows']], [
            (3, 'Division ,BODMAS,Word Problem', '1'),
            (7, 'Decimal Introduction Addition Subtraction', '1'),
            (12, 'Percentage', '1'),
        ])
        self.assertTrue(page['last'])
        self.assertEqual(context['totals']['bridge'], '3')
        self.assertEqual([(p['title'], p['classes_label'], p['classes'], p['fee_per_class'], p['total'], p['single_payment'])
                          for p in context['packages']],
                         [(SELECTED_DAYS_TITLE, '3 Classes', '3', 'AED 35', 'AED 105', None)])
        html = render_to_string(TEMPLATE, context)
        self.assertIn('<h3>Bridge Course – Selected Days Package</h3>', html)
        self.assertIn('<td>12</td><td class="name">Percentage</td><td>1</td>', html)
        self.assertIn('<td>Total No Of Classes</td><td>3</td>', html)
        # The heading and its subtitle are the course's own; the days left out are not printed.
        self.assertIn('<span>Grade 7 CBSE</span><span>Detailed Bridge Course Curriculum</span>', html)
        self.assertNotIn('Ratios', html)
        self.assertNotIn('<h3>Bridge Course Package</h3>', html)

    def test_more_than_a_page_of_days_runs_on_with_the_total_on_the_last(self):
        content = reference_bridge()
        chosen = [f'day-{n}' for n in range(5, 25)]
        context = pdf_context(content, pricing(), selected=chosen)
        self.assertEqual([[row['position'] for row in page['rows']] for page in context['chapter_pages']],
                         [list(range(5, 20)), list(range(20, 25))])
        self.assertEqual([page['last'] for page in context['chapter_pages']], [False, True])
        self.assertEqual((context['totals']['bridge'], context['packages'][0]['total']), ('20', 'AED 700'))
        document = render_document(content, pricing(), selected=chosen)
        self.assertEqual((len(document.pages), spilled_sheets(document)), (3, set()))
        # One day: its page and the packages page.
        document = render_document(content, pricing(), selected=['day-30'])
        self.assertEqual((len(document.pages), spilled_sheets(document)), (2, set()))

    def test_the_privilege_box_under_the_selected_days_package(self):
        on_bridge = pricing(single_payment_plan_types=['BRIDGE_COURSE'])
        context = pdf_context(reference_bridge(), on_bridge, selected=['day-1', 'day-2', 'day-3'])
        self.assertEqual(context['packages'][0]['single_payment'], {'price': 'AED 100', 'saving': 'AED 5'})
        html = render_to_string(TEMPLATE, context)
        self.assertIn('Save <b>AED 5</b> Instantly', html)
        self.assertIn('<td class="price">AED 100</td>', html)
        document = render_document(reference_bridge(), on_bridge, selected=['day-1', 'day-2', 'day-3'])
        self.assertEqual(spilled_sheets(document), set())

    def test_the_whole_course_pdf_is_as_before(self):
        content = reference_bridge()
        whole = pdf_context(content, pricing())
        self.assertEqual(pdf_context(content, pricing(), selected=None), whole)
        self.assertEqual([[row['position'] for row in page['rows']] for page in whole['chapter_pages']],
                         [list(range(1, 16)), list(range(16, 31))])
        self.assertEqual((whole['totals']['bridge'], whole['packages'][0]['title'], whole['packages'][0]['total']),
                         ('30', 'Bridge Course Package', 'AED 1,050'))


class BridgeCourseFixture:
    """A published ten-day Bridge Course (DAYS), its chapter ids in the course's order."""

    def make_bridge_course(self, counts=DAYS, publish=True, title='Grade 7 CBSE'):
        payload = {
            'title': title, 'grade': 7, 'board': 'CBSE', 'structure': 'BRIDGE_COURSE', 'plan_types': ['BRIDGE_COURSE'],
            'chapters': [{'name': f'Day {n} topic', 'bridge_classes': count} for n, count in enumerate(counts, start=1)],
        }
        syllabus = services.create_syllabus(self.admin, valid(payload))
        if publish:
            draft = SyllabusRevision.objects.get(syllabus=syllabus)
            services.publish(self.admin, syllabus.pk, draft.number, draft.updated_at)
        return syllabus

    def day_ids(self, syllabus, number=1):
        return [str(pk) for pk in SyllabusChapter.objects.filter(
            revision__syllabus=syllabus, revision__number=number).order_by('position').values_list('pk', flat=True)]

    def footprint(self):
        """Every row a selection could touch, as it stands."""
        return (Syllabus.objects.count(), SyllabusRevision.objects.count(), SyllabusChapter.objects.count(),
                ActivityLog.objects.count(), PricingVersion.objects.count(),
                sorted(SyllabusRevision.objects.values_list('pk', 'updated_at', 'published_at')))


class BridgeSelectionServiceTests(BridgeCourseFixture, TestCase):
    def setUp(self):
        self.admin = account('selection_admin')
        self.course = self.make_bridge_course()
        self.ids = self.day_ids(self.course)

    def refused(self, chapter_ids, number=1, syllabus=None):
        with self.assertRaises(SalesError) as raised:
            services.bridge_selection((syllabus or self.course).pk, number, chapter_ids)
        return raised.exception.code, raised.exception.message

    def test_the_days_chosen_in_the_course_order(self):
        revision, content, selected = services.bridge_selection(self.course.pk, 1, [self.ids[8], self.ids[1], self.ids[2]])
        self.assertEqual((revision.number, revision.is_draft, len(content['chapters'])), (1, False, 10))
        self.assertEqual(selected, [self.ids[1], self.ids[2], self.ids[8]])
        data = services.selection_data(revision, content, selected, pricing())
        self.assertEqual([(day['day'], day['name'], day['classes']) for day in data['days']],
                         [(2, 'Day 2 topic', '1.5'), (3, 'Day 3 topic', '0.5'), (9, 'Day 9 topic', '1')])
        self.assertEqual((data['full_course'], data['classes'], data['revision'], data['title']), (False, '3', 1, 'Grade 7 CBSE'))
        self.assertEqual(data['package'], {'plan_type': 'BRIDGE_COURSE', 'title': SELECTED_DAYS_TITLE, 'classes': '3',
                                           'fee_per_class': '35', 'total': '105', 'single_payment': None})
        self.assertEqual(data['pricing'], {'version': 3, 'currency': 'AED', 'standard_fee': '45', 'offer_fee': '35'})

    def test_every_day_chosen_is_the_whole_course_exactly_as_before(self):
        revision, content, selected = services.bridge_selection(self.course.pk, 1, list(reversed(self.ids)))
        self.assertIsNone(selected)
        self.assertEqual(content, services.content_of(revision))
        data = services.selection_data(revision, content, selected, pricing())
        whole = services.revision_data(revision, pricing())['packages'][0]
        self.assertEqual((data['full_course'], data['classes'], data['package']), (True, '10', whole))
        self.assertEqual(whole['title'], 'Bridge Course Package')
        self.assertEqual(pdf_context(content, pricing(), selected=selected), pdf_context(services.content_of(revision), pricing()))

    def test_a_choice_must_be_days_of_that_published_revision_each_once(self):
        self.assertEqual(self.refused([]), ('INVALID_SELECTION', 'Choose at least one day.'))
        self.assertEqual(self.refused([self.ids[0], self.ids[0]]), ('INVALID_SELECTION', 'Choose each day once.'))
        other = self.make_bridge_course(title='Grade 9 CBSE')
        for stranger in (self.day_ids(other)[0], '00000000-0000-0000-0000-000000000000'):
            self.assertEqual(self.refused([self.ids[0], stranger]),
                             ('INVALID_SELECTION', 'Choose days of revision 1 of this Bridge Course.'))
        # Day 6 has no classes: chosen alone, nothing is sold.
        self.assertEqual(self.refused([self.ids[5]]), ('INVALID_SELECTION', 'The days chosen have no classes.'))

    def test_only_a_published_revision_of_an_active_bridge_course(self):
        draft = self.make_bridge_course(publish=False, title='Grade 8 CBSE')
        self.assertEqual(self.refused(self.day_ids(draft), syllabus=draft)[0], 'NOT_PUBLISHED')
        chapter_wise = services.create_syllabus(self.admin, valid(chapter_wise_payload()))
        self.assertEqual(self.refused([self.ids[0]], syllabus=chapter_wise)[0], 'NOT_A_BRIDGE_COURSE')
        self.assertEqual(self.refused([self.ids[0]], number=9)[0], 'NOT_FOUND')
        services.deactivate(self.admin, self.course.pk)
        self.assertEqual(self.refused([self.ids[0]])[0], 'SYLLABUS_INACTIVE')

    def test_a_choice_stays_with_its_revision_when_a_new_one_is_published(self):
        draft = services.start_draft(self.admin, self.course.pk)
        services.publish(self.admin, self.course.pk, draft.number, draft.updated_at)
        newer = self.day_ids(self.course, 2)
        # Revision 1 is still sold from its own rows; revision 2's rows are its own -- neither takes the other's.
        self.assertEqual(services.bridge_selection(self.course.pk, 1, [self.ids[3]])[2], [self.ids[3]])
        self.assertEqual(services.bridge_selection(self.course.pk, 2, [newer[3]])[2], [newer[3]])
        self.assertEqual(self.refused([newer[3]], number=1)[0], 'INVALID_SELECTION')

    def test_choosing_writes_nothing(self):
        before = self.footprint()
        for chapter_ids in ([self.ids[1]], self.ids, []):
            try:
                selection = services.bridge_selection(self.course.pk, 1, chapter_ids)
                services.selection_data(*selection, pricing())
            except SalesError:
                pass
        self.assertEqual(self.footprint(), before)


class SelectionApiTests(BridgeCourseFixture, APITestCase):
    def setUp(self):
        self.admin = account('selection_api_admin')
        self.client.force_authenticate(self.admin)
        self.course = self.make_bridge_course()
        self.ids = self.day_ids(self.course)
        self.url = f'{SYLLABI}{self.course.pk}/revisions/1/selection/'
        services.create_pricing_version(self.admin, {
            'currency': 'AED', 'standard_fee': D('45'), 'offer_fee': D('35'), 'single_payment_percent': D('5'),
            'single_payment_plan_types': ['BRIDGE_COURSE'], 'note': '',
        })

    def post(self, url, chapter_ids, **extra):
        return self.client.post(url, {'chapter_ids': chapter_ids}, format='json', **extra)

    def test_the_days_chosen_priced_as_now(self):
        response = self.post(self.url, [self.ids[3], self.ids[1]])
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        self.assertEqual([day['day'] for day in data['days']], [2, 4])
        # 3.5 classes at AED 35 are 122.50; less 5% is 116.375 -> 116, saving 6.50.
        self.assertEqual((data['classes'], data['package']['total'], data['package']['single_payment']),
                         ('3.5', '122.5', {'price': '116', 'saving': '6.5'}))
        self.assertEqual((data['full_course'], data['package']['title']), (False, SELECTED_DAYS_TITLE))

    def test_their_pdf_and_every_day_chosen_is_the_revisions_own_pdf(self):
        response = self.post(f'{self.url}pdf/?disposition=inline', [self.ids[1], self.ids[3]])
        self.assertEqual((response.status_code, response['Content-Type']), (200, 'application/pdf'))
        self.assertEqual(response['Content-Disposition'], 'inline; filename="Grade-7-CBSE-Bridge-Course-r1-Selected-Days.pdf"')
        self.assertEqual(response['Cache-Control'], 'private, no-store')
        self.assertTrue(response.content.startswith(b'%PDF'))
        whole = self.post(f'{self.url}pdf/', self.ids)
        own = self.client.get(f'{SYLLABI}{self.course.pk}/revisions/1/pdf/')
        self.assertEqual(whole['Content-Disposition'], 'attachment; filename="Grade-7-CBSE-Bridge-Course-r1.pdf"')
        self.assertEqual(whole.content, own.content)
        self.assertTrue(self.post(self.url, self.ids).json()['full_course'])

    def test_refusals(self):
        def answer(url, body):
            response = self.client.post(url, body, format='json')
            return response.status_code, response.json()
        for url in (self.url, f'{self.url}pdf/'):
            status_code, body = answer(url, {})
            self.assertEqual((status_code, body['error'], list(body['fields'])), (400, 'VALIDATION_ERROR', ['chapter_ids']))
            self.assertEqual(answer(url, {'chapter_ids': ['day-1']})[0], 400)
            self.assertEqual(answer(url, {'chapter_ids': [self.ids[0]] * 61})[0], 400)
            status_code, body = answer(url, {'chapter_ids': []})
            self.assertEqual((status_code, body['error'], body['fields']),
                             (400, 'INVALID_SELECTION', {'chapter_ids': ['Choose at least one day.']}))
            self.assertEqual(answer(url, {'chapter_ids': [self.ids[0], self.ids[0]]})[1]['error'], 'INVALID_SELECTION')
            missing = url.replace(str(self.course.pk), '00000000-0000-0000-0000-000000000000')
            self.assertEqual(answer(missing, {'chapter_ids': [self.ids[0]]})[:1], (404,))
        draft = self.make_bridge_course(publish=False, title='Grade 8 CBSE')
        status_code, body = answer(f'{SYLLABI}{draft.pk}/revisions/1/selection/', {'chapter_ids': self.day_ids(draft)})
        self.assertEqual((status_code, body['error']), (409, 'NOT_PUBLISHED'))

    def test_administrators_only(self):
        for role in ('MENTOR', 'TUTOR', 'BDE', 'SALES_TL', 'STUDENT'):
            self.client.force_authenticate(account(f'sel_{role.lower()}', role))
            for url in (self.url, f'{self.url}pdf/'):
                with self.subTest(role=role, url=url):
                    self.assertEqual(self.post(url, [self.ids[0]]).status_code, 403)
        self.client.force_authenticate(None)
        self.assertEqual(self.post(self.url, [self.ids[0]]).status_code, 403)
        # A superuser holds every permission, whatever their role (D1).
        self.client.force_authenticate(account('sel_root', 'MENTOR', is_superuser=True))
        self.assertEqual(self.post(self.url, [self.ids[0]]).status_code, 200)

    def test_pricing_and_drawing_write_nothing(self):
        before = self.footprint()
        self.post(self.url, [self.ids[1]])
        self.post(f'{self.url}pdf/', [self.ids[1]])
        self.post(f'{self.url}pdf/', self.ids)
        self.post(self.url, [])
        self.assertEqual(self.footprint(), before)


class SelectionWithoutPricingTests(BridgeCourseFixture, APITestCase):
    def test_no_pricing_yet(self):
        self.admin = account('no_pricing_admin')
        self.client.force_authenticate(self.admin)
        course = self.make_bridge_course()
        url = f'{SYLLABI}{course.pk}/revisions/1/selection/'
        for target in (url, f'{url}pdf/'):
            response = self.client.post(target, {'chapter_ids': self.day_ids(course)[:2]}, format='json')
            self.assertEqual((response.status_code, response.json()['error']), (409, 'NO_PRICING'))
