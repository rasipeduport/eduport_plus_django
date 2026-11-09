"""
The Sales Management API (sales.views): administrators only, the D4 draft
workflow over HTTP, and errors as ``{"error", "message", "fields"?}``.
"""
from rest_framework.test import APITestCase

from .tests_lifecycle import account, bridge_payload, chapter_wise_payload

SYLLABI = '/api/sales/syllabi/'
PRICING = '/api/sales/pricing/'
REFERENCE_PRICING = {
    'currency': 'aed', 'standard_fee': '45', 'offer_fee': '35', 'single_payment_percent': '5',
    'single_payment_plan_types': ['REGULAR'], 'note': 'Current offer',
}


class SalesApiTestCase(APITestCase):
    def setUp(self):
        self.admin = account('api_admin')
        self.client.force_authenticate(self.admin)

    def create(self, payload=None):
        response = self.client.post(SYLLABI, payload or chapter_wise_payload(), format='json')
        self.assertEqual(response.status_code, 201, response.content)
        return response.json()

    def token(self, detail):
        return {'revision': detail['draft']['number'], 'updated_at': detail['draft']['updated_at']}


class AccessTests(SalesApiTestCase):
    def test_only_administrators_reach_it(self):
        syllabus = self.create()
        urls = [SYLLABI, f'{SYLLABI}{syllabus["id"]}/', f'{SYLLABI}{syllabus["id"]}/revisions/1/', PRICING]
        for role in ('MENTOR', 'TUTOR', 'BDE', 'SALES_TL', 'STUDENT'):
            self.client.force_authenticate(account(f'no_{role.lower()}', role))
            for url in urls:
                with self.subTest(role=role, url=url):
                    self.assertEqual(self.client.get(url).status_code, 403)
            self.assertEqual(self.client.post(SYLLABI, chapter_wise_payload(), format='json').status_code, 403)
            self.assertEqual(self.client.post(PRICING, REFERENCE_PRICING, format='json').status_code, 403)
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(SYLLABI).status_code, 403)
        # A superuser holds every permission, whatever their role (D1).
        self.client.force_authenticate(account('root_mentor', 'MENTOR', is_superuser=True))
        self.assertEqual(self.client.get(SYLLABI).status_code, 200)
        self.assertEqual(self.client.post(PRICING, REFERENCE_PRICING, format='json').status_code, 201)


class SyllabusApiTests(SalesApiTestCase):
    def test_the_draft_workflow(self):
        created = self.create()
        url = f'{SYLLABI}{created["id"]}/'
        self.assertEqual((created['status'], created['draft']['number']), ('DRAFT', 1))

        published = self.client.post(f'{url}publish/', self.token(created), format='json')
        self.assertEqual(published.status_code, 200, published.content)
        self.assertEqual((published.json()['status'], published.json()['published']['number']), ('PUBLISHED', 1))

        started = self.client.post(f'{url}draft/')
        self.assertEqual(started.status_code, 201)
        detail = started.json()
        self.assertEqual(self.client.post(f'{url}draft/').json()['error'], 'DRAFT_EXISTS')

        edit = {**chapter_wise_payload(title='Grade 6 CBSE 2027'), 'updated_at': detail['draft']['updated_at']}
        saved = self.client.put(f'{url}draft/', edit, format='json')
        self.assertEqual(saved.status_code, 200, saved.content)
        self.assertEqual((saved.json()['published']['title'], saved.json()['draft']['title']), ('Grade 6 CBSE', 'Grade 6 CBSE 2027'))
        stale = self.client.put(f'{url}draft/', edit, format='json')
        self.assertEqual((stale.status_code, stale.json()['error']), (409, 'DRAFT_CHANGED'))

        published = self.client.post(f'{url}publish/', self.token(saved.json()), format='json').json()
        self.assertEqual([(row['number'], row['state']) for row in published['history']], [(2, 'PUBLISHED'), (1, 'SUPERSEDED')])
        first = self.client.get(f'{url}revisions/1/').json()
        self.assertEqual((first['title'], first['is_draft']), ('Grade 6 CBSE', False))
        self.assertEqual(self.client.get(f'{url}revisions/9/').status_code, 404)

        deactivated = self.client.post(f'{url}deactivate/')
        self.assertEqual(deactivated.json()['status'], 'INACTIVE')
        self.assertEqual(self.client.post(f'{url}draft/').json()['error'], 'SYLLABUS_INACTIVE')
        self.assertEqual(self.client.post(f'{url}reactivate/').json()['status'], 'PUBLISHED')

        copy = self.client.post(f'{url}duplicate/')
        self.assertEqual(copy.status_code, 201)
        self.assertEqual((copy.json()['status'], copy.json()['draft']['title']), ('DRAFT', 'Grade 6 CBSE 2027 (Copy)'))
        older = self.client.post(f'{url}duplicate/', {'revision': 1}, format='json')
        self.assertEqual(older.json()['draft']['title'], 'Grade 6 CBSE (Copy)')
        self.assertEqual(self.client.post(f'{url}duplicate/', {'revision': 7}, format='json').json()['error'], 'NO_REVISION')

    def test_discarding_a_draft(self):
        created = self.create()
        url = f'{SYLLABI}{created["id"]}/'
        refused = self.client.delete(f'{url}draft/', self.token(created), format='json')
        self.assertEqual(refused.json()['error'], 'NEVER_PUBLISHED')
        self.client.post(f'{url}publish/', self.token(created), format='json')
        detail = self.client.post(f'{url}draft/').json()
        discarded = self.client.delete(f'{url}draft/', self.token(detail), format='json')
        self.assertEqual(discarded.status_code, 200)
        self.assertIsNone(discarded.json()['draft'])

    def test_errors_name_the_field_and_the_chapter_row(self):
        payload = chapter_wise_payload()
        payload['chapters'][1]['revision_classes'] = '1.25'
        payload['chapters'][2]['revision_classes'] = '1.3'
        payload['chapters'][3]['regular_classes'] = None
        response = self.client.post(SYLLABI, {**payload, 'grade': 13}, format='json')
        self.assertEqual(response.status_code, 400)
        body = response.json()
        self.assertEqual(body['error'], 'VALIDATION_ERROR')
        self.assertIn('grade', body['fields'])
        self.assertEqual(body['fields']['chapters']['2']['revision_classes'], ['Use whole or half classes, such as 2 or 1.5.'])
        self.assertIn('revision_classes', body['fields']['chapters']['1'])

        response = self.client.post(SYLLABI, chapter_wise_payload(chapters=payload['chapters'][:1] + [
            {'name': 'No counts'}]), format='json')
        self.assertEqual(response.json()['fields']['chapters']['1'],
                         {'regular_classes': ['Enter the number of classes.'], 'revision_classes': ['Enter the number of classes.']})
        response = self.client.post(SYLLABI, chapter_wise_payload(plan_types=['BRIDGE_COURSE']), format='json')
        self.assertIn('plan_types', response.json()['fields'])
        response = self.client.post(SYLLABI, chapter_wise_payload(chapters=[]), format='json')
        self.assertIn('chapters', response.json()['fields'])

    def test_publishing_needs_classes_for_every_plan_type(self):
        payload = chapter_wise_payload()
        for chapter in payload['chapters']:
            chapter['revision_classes'] = 0
        created = self.create(payload)
        response = self.client.post(f'{SYLLABI}{created["id"]}/publish/', self.token(created), format='json')
        self.assertEqual((response.status_code, response.json()['error']), (400, 'NOT_PUBLISHABLE'))
        self.assertEqual(response.json()['problems'], ['Revision has no classes: enter its class counts.'])

        # Regular + Revision alone prints a Revision card too: it may not sell 0 Revision classes either.
        created = self.create({**payload, 'plan_types': ['REGULAR_REVISION']})
        response = self.client.post(f'{SYLLABI}{created["id"]}/publish/', self.token(created), format='json')
        self.assertEqual(response.json()['problems'], ['Regular + Revision has no Revision classes: enter its class counts.'])

    def test_the_list(self):
        grade6 = self.create()
        bridge = self.create(bridge_payload())
        self.client.post(f'{SYLLABI}{grade6["id"]}/publish/', self.token(grade6), format='json')

        listed = self.client.get(SYLLABI).json()
        self.assertEqual((listed['count'], listed['page']), (2, 1))
        rows = {row['id']: row for row in listed['results']}
        self.assertEqual(rows[grade6['id']]['status'], 'PUBLISHED')
        self.assertEqual(rows[grade6['id']]['totals'], {'regular': '38', 'revision': '19', 'bridge': None})
        self.assertEqual(rows[grade6['id']]['plan_types'], ['REGULAR', 'REVISION', 'REGULAR_REVISION'])
        self.assertEqual((rows[bridge['id']]['status'], rows[bridge['id']]['totals']['bridge']), ('DRAFT', '30'))

        def ids(**params):
            return [row['id'] for row in self.client.get(SYLLABI, params).json()['results']]
        self.assertEqual(ids(status='published'), [grade6['id']])
        self.assertEqual(ids(status='draft'), [bridge['id']])
        self.assertEqual(ids(structure='BRIDGE_COURSE'), [bridge['id']])
        self.assertEqual(ids(grade='6'), [grade6['id']])
        self.assertEqual(ids(q='grade 7'), [bridge['id']])
        self.assertEqual(ids(board='IB'), [])
        self.assertEqual(self.client.get(SYLLABI, {'status': 'gone'}).json()['error'], 'INVALID_INPUT')
        # Digits other than 0-9 ('²' passes str.isdigit) are refused, not a server error.
        for grade in ('²', '٣', '6a', '123'):
            self.assertEqual(self.client.get(SYLLABI, {'grade': grade}).status_code, 400, grade)

        # A published syllabus with a draft lists its published revision, and says it has a draft.
        self.client.post(f'{SYLLABI}{grade6["id"]}/draft/')
        row = next(r for r in self.client.get(SYLLABI).json()['results'] if r['id'] == grade6['id'])
        self.assertEqual((row['revision'], row['published_revision'], row['draft_revision']), (1, 1, 2))

    def test_unknown_syllabus(self):
        missing = f'{SYLLABI}00000000-0000-0000-0000-000000000000/'
        self.assertEqual(self.client.get(missing).status_code, 404)
        self.assertEqual(self.client.post(f'{missing}duplicate/').status_code, 404)
        self.assertEqual(self.client.post(f'{missing}deactivate/').json()['error'], 'NOT_FOUND')


class PricingApiTests(SalesApiTestCase):
    def test_a_new_version_takes_effect_and_the_history_stays(self):
        self.assertEqual(self.client.get(PRICING).json(), {'current': None, 'versions': []})
        created = self.client.post(PRICING, REFERENCE_PRICING, format='json')
        self.assertEqual(created.status_code, 201, created.content)
        current = created.json()['current']
        self.assertEqual((current['version'], current['currency'], current['offer_fee']), (1, 'AED', '35'))
        self.client.post(PRICING, {**REFERENCE_PRICING, 'offer_fee': '30'}, format='json')
        pricing = self.client.get(PRICING).json()
        self.assertEqual((pricing['current']['version'], [v['offer_fee'] for v in pricing['versions']]), (2, ['30', '35']))

        # The syllabus pages price their packages at the version in effect.
        detail = self.create()
        regular = detail['draft']['packages'][0]
        self.assertEqual((regular['title'], regular['total'], regular['single_payment']),
                         ('Regular Course Package', '1140', {'price': '1083', 'saving': '57'}))

    def test_the_single_payment_privilege_is_on_or_off(self):
        # Packages chosen at 0% would read as on while the PDFs show no privilege box: refused.
        refused = self.client.post(PRICING, {**REFERENCE_PRICING, 'single_payment_percent': '0'}, format='json')
        self.assertEqual(refused.status_code, 400, refused.content)
        self.assertEqual(list(refused.json()['fields']), ['single_payment_percent'])
        off = self.client.post(PRICING, {**REFERENCE_PRICING, 'single_payment_percent': '0', 'single_payment_plan_types': []},
                               format='json')
        self.assertEqual(off.status_code, 201, off.content)
        current = off.json()['current']
        self.assertEqual((current['single_payment_percent'], current['single_payment_plan_types']), ('0', []))
        regular = self.create()['draft']['packages'][0]
        self.assertEqual((regular['title'], regular['single_payment']), ('Regular Course Package', None))

    def test_invalid_pricing(self):
        def fields(**changes):
            return self.client.post(PRICING, {**REFERENCE_PRICING, **changes}, format='json').json()['fields']
        self.assertIn('offer_fee', fields(offer_fee='46'))
        self.assertIn('currency', fields(currency='DIRHAM'))
        self.assertIn('single_payment_plan_types', fields(single_payment_plan_types=[]))
        self.assertIn('single_payment_percent', fields(single_payment_percent='100'))
        self.assertIn('standard_fee', fields(standard_fee='0'))
        # The privilege goes on a package card the PDF prints: Regular, Revision or Bridge Course.
        self.assertIn('single_payment_plan_types', fields(single_payment_plan_types=['REGULAR_REVISION']))
        self.assertIn('single_payment_plan_types', fields(single_payment_plan_types=['CHAPTER_PLAN']))
