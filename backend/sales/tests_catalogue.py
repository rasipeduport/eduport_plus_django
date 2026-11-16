"""
The catalogue on sale (/api/sales/catalogue/, accounts.view_sales_catalogue):
what BDEs -- and administrators -- quote parents from. Only active syllabuses
with a published revision, each as its newest published revision sells it,
and the pricing's rates and privilege; never a draft or its edits, a status,
a history, the pricing's past versions or notes, or who did what. It changes
nothing, and a BDE reaches nothing of the administrators' Sales Management.
"""
import json
from decimal import Decimal as D

from rest_framework.test import APITestCase

from . import services
from .models import SyllabusRevision
from .pricing import SELECTED_DAYS_TITLE
from .services import CATALOGUE_ROW_FIELDS
from .tests_lifecycle import account, chapter_wise_payload, editable, valid
from .tests_selection import BridgeCourseFixture

CATALOGUE = '/api/sales/catalogue/'
SYLLABI = '/api/sales/syllabi/'
PRICING = '/api/sales/pricing/'
DETAIL_FIELDS = {
    'id', 'revision', 'title', 'subtitle', 'package_title', 'grade', 'board', 'syllabus_version', 'structure',
    'plan_types', 'inclusions', 'chapters', 'totals', 'packages', 'pricing',
}
PRICING_FIELDS = {'version', 'currency', 'standard_fee', 'offer_fee', 'single_payment_percent', 'single_payment_plan_types'}
DRAFT_TITLE = 'Grade 6 CBSE Unpublished Edit'
NOTES = ('Internal pricing note one', 'Internal pricing note two')


class CatalogueTestCase(BridgeCourseFixture, APITestCase):
    """
    On sale: Grade 6 (chapter-wise, published, with a draft whose edits must
    not show) and Grade 7 (a published Bridge Course). Not on sale: Grade 8
    (never published) and Grade 9 (published, then deactivated). The pricing
    has two versions; the second is in effect.
    """

    def setUp(self):
        self.admin = account('catalogue_admin')  # named Catalogue_Admin
        self.bde = account('catalogue_bde', 'BDE')
        self.grade6 = services.create_syllabus(self.admin, valid(chapter_wise_payload()))
        self.publish_draft(self.grade6)
        draft = services.start_draft(self.admin, self.grade6.pk)
        services.save_draft(self.admin, self.grade6.pk, valid({**editable(draft), 'title': DRAFT_TITLE}), draft.updated_at)
        self.bridge = self.make_bridge_course()
        self.days = self.day_ids(self.bridge)
        self.unpublished = self.make_bridge_course(publish=False, title='Grade 8 CBSE')
        self.inactive = self.make_bridge_course(title='Grade 9 CBSE')
        services.deactivate(self.admin, self.inactive.pk)
        for note, plan_types in zip(NOTES, (['REGULAR'], ['REGULAR', 'BRIDGE_COURSE'])):
            services.create_pricing_version(self.admin, {
                'currency': 'AED', 'standard_fee': D('45'), 'offer_fee': D('35'), 'single_payment_percent': D('5'),
                'single_payment_plan_types': plan_types, 'note': note,
            })
        self.client.force_authenticate(self.bde)

    def publish_draft(self, syllabus):
        draft = SyllabusRevision.objects.get(syllabus=syllabus, published_at__isnull=True)
        services.publish(self.admin, syllabus.pk, draft.number, draft.updated_at)

    def selection(self, syllabus=None, revision=1, chapter_ids=None, pdf=False, **extra):
        url = f'{CATALOGUE}{(syllabus or self.bridge).pk}/selection/' + ('pdf/' if pdf else '')
        body = {'revision': revision, 'chapter_ids': self.days[:2] if chapter_ids is None else chapter_ids}
        return self.client.post(url, body, format='json', **extra)


class CatalogueFilteringTests(CatalogueTestCase):
    def test_only_active_published_syllabuses_each_as_its_published_revision(self):
        data = self.client.get(CATALOGUE).json()
        self.assertEqual((data['count'], [row['id'] for row in data['results']]), (2, [str(self.grade6.pk), str(self.bridge.pk)]))
        grade6, bridge = data['results']
        self.assertEqual(set(grade6), set(CATALOGUE_ROW_FIELDS))
        # The published revision 1, not the draft revision 2 with its new title.
        self.assertEqual((grade6['revision'], grade6['title']), (1, 'Grade 6 CBSE'))
        self.assertEqual((bridge['structure'], bridge['plan_types'], bridge['totals']['bridge'], bridge['chapter_count']),
                         ('BRIDGE_COURSE', ['BRIDGE_COURSE'], '10', 10))

    def test_filters_read_the_revision_on_sale(self):
        def ids(**params):
            return [row['id'] for row in self.client.get(CATALOGUE, params).json()['results']]
        self.assertEqual(ids(q='grade 6'), [str(self.grade6.pk)])
        self.assertEqual(ids(q='Unpublished Edit'), [])            # a draft's title finds nothing
        self.assertEqual(ids(q='grade 8'), [])                     # never published
        self.assertEqual(ids(q='grade 9'), [])                     # deactivated
        self.assertEqual(ids(structure='BRIDGE_COURSE'), [str(self.bridge.pk)])
        self.assertEqual(ids(grade='7', board='CBSE'), [str(self.bridge.pk)])
        for bad in ({'grade': '²'}, {'structure': 'NOPE'}, {'board': 'NOPE'}):
            self.assertEqual(self.client.get(CATALOGUE, bad).status_code, 400, bad)
        self.assertEqual(self.client.get(CATALOGUE, {'page_size': 1, 'page': 2}).json()['results'][0]['id'], str(self.bridge.pk))

    def test_by_grade_then_the_title_on_sale(self):
        # The order keys are each syllabus's own published revision's (not the draft's, nor another syllabus's).
        grade5 = services.create_syllabus(self.admin, valid(chapter_wise_payload(title='Grade 5 CBSE', grade=5)))
        self.publish_draft(grade5)
        keyed = services.by_grade_and_title(services.catalogue())
        self.assertEqual(list(keyed.values_list('pk', 'sold_grade', 'sold_title')), [
            (grade5.pk, 5, 'Grade 5 CBSE'), (self.grade6.pk, 6, 'Grade 6 CBSE'), (self.bridge.pk, 7, 'Grade 7 CBSE'),
        ])
        self.assertEqual([row['id'] for row in self.client.get(CATALOGUE).json()['results']],
                         [str(grade5.pk), str(self.grade6.pk), str(self.bridge.pk)])

    def test_a_syllabus_on_sale_shows_what_is_sold_and_the_rates_only(self):
        response = self.client.get(f'{CATALOGUE}{self.grade6.pk}/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(set(data), DETAIL_FIELDS)
        self.assertEqual((data['revision'], data['title'], data['subtitle'], data['package_title']),
                         (1, 'Grade 6 CBSE', 'Detailed Chapter-Wise 1:1 Learning Plan', 'Grade 6 CBSE – 1:1 Tuition Packages & Fee Details'))
        self.assertEqual(set(data['chapters'][0]), {'id', 'position', 'name', 'regular_classes', 'revision_classes', 'bridge_classes'})
        # The version in effect, its rates and privilege: no note, author, dates or earlier version.
        self.assertEqual(data['pricing'], {'version': 2, 'currency': 'AED', 'standard_fee': '45', 'offer_fee': '35',
                                           'single_payment_percent': '5', 'single_payment_plan_types': ['REGULAR', 'BRIDGE_COURSE']})
        self.assertEqual(set(data['pricing']), PRICING_FIELDS)
        self.assertEqual([(p['title'], p['total'], p['single_payment']) for p in data['packages']], [
            ('Regular Course Package', '1330', {'price': '1264', 'saving': '66'}),
            ('Revision Course (Exam Oriented) Package', '665', None),
        ])
        # Nothing of the Admin's workings anywhere in the answer.
        text = json.dumps(data)
        for secret in (DRAFT_TITLE, *NOTES, 'catalogue_admin', 'Catalogue_Admin', 'created_by', 'updated_by',
                       'published_by', 'published_at', 'history', 'status', 'similar', 'reference', 'draft'):
            self.assertNotIn(secret, text, secret)

    def test_what_is_not_on_sale_is_not_found_and_says_no_more(self):
        answers = [self.client.get(f'{CATALOGUE}{pk}/') for pk in
                   (self.unpublished.pk, self.inactive.pk, '00000000-0000-0000-0000-000000000000')]
        self.assertEqual({(answer.status_code, json.dumps(answer.json(), sort_keys=True)) for answer in answers},
                         {(404, json.dumps({'error': 'NOT_FOUND', 'message': 'No such syllabus on sale.'}, sort_keys=True))})
        for syllabus in (self.unpublished, self.inactive):
            self.assertEqual(self.client.get(f'{CATALOGUE}{syllabus.pk}/pdf/').status_code, 404)
            self.assertEqual(self.selection(syllabus=syllabus, chapter_ids=self.day_ids(syllabus)[:1]).status_code, 404)

    def test_the_catalogue_follows_publishing_and_deactivation(self):
        self.publish_draft(self.grade6)
        row = self.client.get(CATALOGUE, {'grade': '6'}).json()['results'][0]
        self.assertEqual((row['revision'], row['title']), (2, DRAFT_TITLE))
        services.deactivate(self.admin, self.grade6.pk)
        self.assertEqual(self.client.get(CATALOGUE, {'grade': '6'}).json()['count'], 0)
        self.assertEqual(self.client.get(f'{CATALOGUE}{self.grade6.pk}/').status_code, 404)


class CataloguePdfAndSelectionTests(CatalogueTestCase):
    def test_the_pdf_of_a_syllabus_on_sale_is_its_published_revisions(self):
        response = self.client.get(f'{CATALOGUE}{self.grade6.pk}/pdf/?disposition=inline')
        self.assertEqual((response.status_code, response['Content-Type']), (200, 'application/pdf'))
        self.assertEqual(response['Content-Disposition'], 'inline; filename="Grade-6-CBSE-New-Syllabus-Plan-and-Price-r1.pdf"')
        self.assertEqual(response['Cache-Control'], 'private, no-store')
        self.client.force_authenticate(self.admin)
        published = self.client.get(f'{SYLLABI}{self.grade6.pk}/revisions/1/pdf/?disposition=inline')
        self.assertEqual(response.content, published.content)

    def test_a_bridge_course_priced_by_the_days_chosen(self):
        response = self.selection(chapter_ids=[self.days[3], self.days[1]])
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        self.assertEqual(([day['day'] for day in data['days']], data['classes'], data['full_course']), ([2, 4], '3.5', False))
        # Version 2 gives Bridge Course the privilege: 122.50 less 5% is 116.375 -> 116, saving 6.50.
        self.assertEqual((data['package']['title'], data['package']['total'], data['package']['single_payment']),
                         (SELECTED_DAYS_TITLE, '122.5', {'price': '116', 'saving': '6.5'}))
        self.assertEqual(set(data['pricing']), {'version', 'currency', 'standard_fee', 'offer_fee'})
        pdf = self.selection(chapter_ids=[self.days[3], self.days[1]], pdf=True)
        self.assertEqual(pdf['Content-Disposition'], 'attachment; filename="Grade-7-CBSE-Bridge-Course-r1-Selected-Days.pdf"')
        # Every day chosen: the whole course, its own PDF byte for byte.
        whole = self.selection(chapter_ids=self.days, pdf=True)
        self.assertEqual(whole.content, self.client.get(f'{CATALOGUE}{self.bridge.pk}/pdf/').content)
        self.assertTrue(self.selection(chapter_ids=self.days).json()['full_course'])

    def test_a_choice_is_of_the_revision_on_sale(self):
        draft = services.start_draft(self.admin, self.bridge.pk)
        services.publish(self.admin, self.bridge.pk, draft.number, draft.updated_at)
        stale = self.selection(revision=1)
        self.assertEqual((stale.status_code, stale.json()['error'], stale.json()['revision']), (409, 'REVISION_CHANGED', 2))
        self.assertEqual(self.selection(revision=3).status_code, 404)
        fresh = self.day_ids(self.bridge, 2)
        self.assertEqual(self.selection(revision=2, chapter_ids=fresh[:2]).status_code, 200)
        # Revision 1's rows are not revision 2's days.
        self.assertEqual(self.selection(revision=2, chapter_ids=self.days[:2]).json()['error'], 'INVALID_SELECTION')

    def test_refusals(self):
        self.assertEqual(self.selection(syllabus=self.grade6).json()['error'], 'NOT_A_BRIDGE_COURSE')
        for body in ({'chapter_ids': self.days[:1]}, {'revision': 1}, {'revision': 0, 'chapter_ids': self.days[:1]}):
            response = self.client.post(f'{CATALOGUE}{self.bridge.pk}/selection/', body, format='json')
            self.assertEqual((response.status_code, response.json()['error']), (400, 'VALIDATION_ERROR'), body)
        self.assertEqual(self.selection(chapter_ids=[]).json()['fields'], {'chapter_ids': ['Choose at least one day.']})
        self.assertEqual(self.selection(chapter_ids=[self.days[0]] * 2).json()['error'], 'INVALID_SELECTION')


class CatalogueAccessTests(CatalogueTestCase):
    def requests(self):
        bridge = f'{CATALOGUE}{self.bridge.pk}/'
        return [
            ('get', CATALOGUE, None), ('get', bridge, None), ('get', f'{bridge}pdf/', None),
            ('post', f'{bridge}selection/', {'revision': 1, 'chapter_ids': self.days[:2]}),
            ('post', f'{bridge}selection/pdf/', {'revision': 1, 'chapter_ids': self.days[:2]}),
        ]

    def answers(self, user):
        self.client.force_authenticate(user)
        return [getattr(self.client, method)(url, body, format='json').status_code for method, url, body in self.requests()]

    def test_bdes_and_administrators_read_it(self):
        for user in (self.bde, self.admin, account('catalogue_root', 'MENTOR', is_superuser=True)):
            with self.subTest(user=user.username):
                self.assertEqual(self.answers(user), [200] * 5)

    def test_no_other_role_and_no_one_signed_out(self):
        for role in ('TUTOR', 'MENTOR', 'SALES_TL', 'STUDENT'):
            with self.subTest(role=role):
                self.assertEqual(self.answers(account(f'catalogue_{role.lower()}', role)), [403] * 5)
        self.assertEqual(self.answers(None), [403] * 5)

    def test_a_bde_reaches_nothing_of_sales_management(self):
        grade6, bridge = f'{SYLLABI}{self.grade6.pk}/', f'{SYLLABI}{self.bridge.pk}/'
        token = {'revision': 1, 'updated_at': '2026-11-09T00:00:00Z'}
        refused = [
            self.client.get(SYLLABI), self.client.post(SYLLABI, chapter_wise_payload(), format='json'),
            self.client.get(grade6), self.client.get(f'{grade6}revisions/2/'), self.client.get(f'{grade6}pdf/'),
            self.client.get(f'{grade6}revisions/2/pdf/'), self.client.post(f'{SYLLABI}pdf-preview/', chapter_wise_payload(), format='json'),
            self.client.post(f'{grade6}draft/'), self.client.put(f'{grade6}draft/', {}, format='json'),
            self.client.delete(f'{grade6}draft/', token, format='json'), self.client.post(f'{grade6}publish/', token, format='json'),
            self.client.post(f'{grade6}deactivate/'), self.client.post(f'{grade6}reactivate/'), self.client.post(f'{grade6}duplicate/'),
            self.client.post(f'{bridge}revisions/1/selection/', {'chapter_ids': self.days[:1]}, format='json'),
            self.client.post(f'{bridge}revisions/1/selection/pdf/', {'chapter_ids': self.days[:1]}, format='json'),
            # The pricing's history and changing it are the administrators' too.
            self.client.get(PRICING), self.client.post(PRICING, {}, format='json'),
        ]
        self.assertEqual([response.status_code for response in refused], [403] * len(refused))

    def test_reading_and_quoting_write_nothing(self):
        before = self.footprint()
        self.answers(self.bde)
        self.selection(chapter_ids=self.days, pdf=True)
        self.selection(chapter_ids=[])
        self.assertEqual(self.footprint(), before)
