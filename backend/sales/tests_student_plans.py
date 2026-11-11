"""Student plan selection, immutable replacements, concurrent edits and the pre-payment lock."""
import dataclasses
import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal as D
from threading import Barrier

from django.db import DatabaseError, close_old_connections, connection, transaction
from django.test import TransactionTestCase
from django.utils import timezone
from rest_framework.test import APITestCase

from activity.models import ActivityLog
from bookings.models import Lead
from . import quotes, services
from .models import Quote
from .services import SalesError
from .tests_quotes import QUOTES, QuoteTestCase, lead_of


class StudentPlanTests(QuoteTestCase, APITestCase):
    def setUp(self):
        self.make_world()
        self.lead = lead_of(self.bde, 'Student Plan', '509200001')
        self.other_lead = lead_of(self.other_bde, 'Other Student', '509200002')
        self.url = f'/api/sales/enquiries/{self.lead.pk}/plan/'
        self.client.force_authenticate(self.bde)

    def create(self, **extra):
        return self.client.post(QUOTES, {
            'syllabus': str(self.grade6.pk), 'revision': 1, 'collection_mode': 'FULL', 'plan_type': 'REGULAR',
            'lead': str(self.lead.pk), 'pricing_version': 1, **extra,
        }, format='json')

    def test_empty_student_plan_uses_existing_enquiry(self):
        body = self.client.get(self.url).json()
        self.assertEqual(body['lead']['id'], str(self.lead.pk))
        self.assertEqual((body['current'], body['latest_quote'], body['history'], body['locked']), (None, None, [], False))

    def test_student_quote_and_regular_revision_components_are_saved(self):
        response = self.create(plan_type='REGULAR_REVISION')
        self.assertEqual(response.status_code, 201, response.content)
        data = response.json()
        self.assertEqual((data['lead']['id'], data['created_by']['id'], data['is_current'], data['selection_status']),
                         (str(self.lead.pk), str(self.bde.pk), True, 'CURRENT'))
        self.assertEqual((data['classes'], data['total_fee'], data['payable_amount']), ('57', '1995', '1929'))
        self.assertEqual((data['chapters'][0]['regular_classes'], data['chapters'][0]['revision_classes']), ('4', '2'))
        saved = self.client.get(self.url).json()
        self.assertEqual(saved['current'], data)
        self.assertEqual(saved['latest_quote'], data['id'])
        self.assertEqual(saved['history'][0]['id'], data['id'])
        self.assertEqual(len(self.client.get(QUOTES, {'lead': self.lead.pk}).json()['results']), 1)
        self.assertEqual(self.client.get(QUOTES, {'lead': 'bad'}).status_code, 400)

    def test_replacing_changes_current_without_rewriting_the_issued_snapshot(self):
        first = self.create().json()
        old = Quote.objects.get(pk=first['id'])
        pdf_before = quotes.quote_pdf_parts(old)
        self.price(offer='40')
        second = self.create(plan_type='REVISION', replaces=first['id'], pricing_version=2)
        self.assertEqual(second.status_code, 201, second.content)
        data = second.json()
        self.assertEqual((data['supersedes'], data['classes'], data['total_fee']), (first['id'], '19', '760'))
        old.refresh_from_db()
        self.assertEqual((old.status, old.offer_fee, old.total_fee, old.payable_amount), ('ISSUED', D('35'), D('1330'), D('1264')))
        self.assertEqual(quotes.quote_pdf_parts(old), pdf_before)
        history = self.client.get(self.url).json()
        self.assertEqual(history['current']['id'], data['id'])
        self.assertEqual([row['selection_status'] for row in history['history']], ['CURRENT', 'PREVIOUS'])
        self.assertTrue(ActivityLog.objects.filter(action='quote.create', context__supersedes=first['id']).exists())

    def test_changes_cover_chapters_bridge_modes_and_another_syllabus(self):
        current = self.create(plan_type='CHAPTER_PLAN', chapter_ids=self.chapters[:2]).json()
        self.assertEqual((current['classes'], current['total_fee']), ('9', '315'))
        response = self.create(syllabus=str(self.bridge.pk), plan_type='BRIDGE_COURSE', replaces=current['id'])
        self.assertEqual(response.status_code, 201, response.content)
        current = response.json()
        self.assertTrue(current['full_course'])
        response = self.create(syllabus=str(self.bridge.pk), plan_type='BRIDGE_COURSE', chapter_ids=self.days[1:4:2], replaces=current['id'])
        self.assertEqual(response.status_code, 201, response.content)
        current = response.json()
        self.assertEqual((current['full_course'], current['classes'], current['payable_amount']), (False, '3.5', '116'))
        response = self.create(syllabus=str(self.bridge.pk), plan_type='BRIDGE_COURSE', chapter_ids=self.days, replaces=current['id'])
        self.assertEqual((response.status_code, response.json()['full_course']), (201, True))

    def test_all_chapters_count_as_full_coverage_without_changing_the_admin_plan(self):
        response = self.create(plan_type='CHAPTER_PLAN', chapter_ids=self.chapters)
        self.assertEqual(response.status_code, 201, response.content)
        data = response.json()
        self.assertEqual((data['plan_type'], data['full_course'], data['classes'], data['payable_amount']), ('CHAPTER_PLAN', True, '38', '1330'))

    def test_cross_syllabus_and_disabled_types_are_refused(self):
        for extra in ({'plan_type': 'CHAPTER_PLAN', 'chapter_ids': self.days[:1]},
                      {'plan_type': 'REGULAR_REVISION', 'chapter_ids': self.days[:1]},
                      {'syllabus': str(self.bridge.pk), 'plan_type': 'REGULAR'}):
            with self.subTest(extra=extra):
                self.assertEqual(self.create(**extra).status_code, 400)
        self.assertFalse(Quote.objects.exists())

    def test_stale_student_revision_and_reviewed_pricing_require_reload(self):
        draft = services.start_draft(self.admin, self.grade6.pk)
        services.publish(self.admin, self.grade6.pk, draft.number, draft.updated_at)
        stale = self.create()
        self.assertEqual((stale.status_code, stale.json()['error']), (409, 'REVISION_CHANGED'))
        self.price(offer='40')
        stale = self.create(revision=2)
        self.assertEqual((stale.status_code, stale.json()['error']), (409, 'PRICING_CHANGED'))
        self.assertFalse(Quote.objects.exists())

    def test_pdf_preview_and_download_pin_the_revision_and_remain_private(self):
        url = f'/api/sales/catalogue/{self.grade6.pk}/pdf/'
        original = self.client.get(url)
        pinned = self.client.get(url, {'revision': 1, 'disposition': 'inline'})
        self.assertEqual((pinned.status_code, pinned.content), (200, original.content))
        self.assertEqual(pinned['Cache-Control'], 'private, no-store')
        self.assertEqual(self.client.get(url, {'revision': 'bad'}).status_code, 400)
        draft = services.start_draft(self.admin, self.grade6.pk)
        services.publish(self.admin, self.grade6.pk, draft.number, draft.updated_at)
        response = self.client.get(url, {'revision': 1})
        self.assertEqual((response.status_code, response.json()['error']), (409, 'REVISION_CHANGED'))
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(url, {'revision': 2}).status_code, 403)

    def test_stale_or_cross_enquiry_replacement_cannot_override_current(self):
        first = self.create().json()
        for replaces in (None, str(uuid.uuid4())):
            response = self.create(replaces=replaces)
            self.assertEqual((response.status_code, response.json()['error']), (409, 'PLAN_CHANGED'))
        second = self.create(replaces=first['id']).json()
        response = self.create(replaces=first['id'])
        self.assertEqual((response.status_code, response.json()['error']), (409, 'PLAN_CHANGED'))
        self.assertEqual(self.client.get(self.url).json()['current']['id'], second['id'])
        self.assertEqual(Quote.objects.count(), 2)

    def test_cancelled_latest_never_revives_an_older_choice(self):
        first = self.create().json()
        second = self.create(replaces=first['id']).json()
        quotes.cancel_quote(self.admin, second['id'], 'Parent reconsidered')
        data = self.client.get(self.url).json()
        self.assertIsNone(data['current'])
        self.assertEqual(data['latest_quote'], second['id'])
        self.assertEqual([row['selection_status'] for row in data['history']], ['CANCELLED', 'PREVIOUS'])
        response = self.create(replaces=second['id'])
        self.assertEqual(response.status_code, 201)

    def test_plan_lock_blocks_all_replacements_and_new_choices(self):
        first = self.create().json()
        Lead.objects.filter(pk=self.lead.pk).update(plan_changes_locked_at=timezone.now())
        for extra in ({'replaces': first['id']}, {'plan_type': 'REVISION', 'replaces': first['id']}):
            response = self.create(**extra)
            self.assertEqual((response.status_code, response.json()['error']), (409, 'PLAN_LOCKED'))
        saved = self.client.get(self.url).json()
        self.assertTrue(saved['locked'])
        self.assertEqual(saved['current']['id'], first['id'])
        self.assertEqual(Quote.objects.count(), 1)

    def test_no_other_bde_or_role_can_read_or_change_this_plan(self):
        first = self.create().json()
        self.client.force_authenticate(self.other_bde)
        self.assertEqual(self.client.get(self.url).status_code, 400)
        self.assertEqual(self.create(replaces=first['id']).status_code, 400)
        for suffix in ('', 'pdf/'):
            self.assertEqual(self.client.get(f'{QUOTES}{first["id"]}/{suffix}').status_code, 404)
        self.assertEqual(self.client.get(QUOTES, {'lead': self.lead.pk}).json()['results'], [])
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.get(self.url).json()['current']['id'], first['id'])
        self.assertEqual(self.client.get(f'{QUOTES}{first["id"]}/pdf/').status_code, 200)
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_reassignment_revokes_old_owner_access_and_requires_admin_review(self):
        first = self.create().json()
        Lead.objects.filter(pk=self.lead.pk).update(owner_bde=self.other_bde)
        self.assertEqual(self.client.get(f'{QUOTES}{first["id"]}/').status_code, 404)
        self.client.force_authenticate(self.other_bde)
        response = self.client.get(self.url)
        self.assertEqual((response.status_code, response.json()['error']), (409, 'PLAN_OWNER_CHANGED'))
        response = self.create(replaces=first['id'])
        self.assertEqual((response.status_code, response.json()['error']), (409, 'PLAN_OWNER_CHANGED'))
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.get(self.url).status_code, 200)
        cancelled = self.client.post(f'{QUOTES}{first["id"]}/cancel/', {'reason': 'Enquiry reassigned; new owner will review the plan.'}, format='json')
        self.assertEqual(cancelled.status_code, 200)
        self.client.force_authenticate(self.other_bde)
        recovered = self.client.get(self.url).json()
        self.assertIsNone(recovered['current'])
        self.assertEqual(recovered['history'], [])  # The former owner's snapshot stays private.
        response = self.create(replaces=recovered['latest_quote'])
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(self.client.get(f'{QUOTES}{first["id"]}/').status_code, 404)


class StudentPlanIntegrityTests(QuoteTestCase, TransactionTestCase):
    def setUp(self):
        self.make_world()
        self.lead = lead_of(self.bde, 'Concurrent Student', '509200003')

    def payload(self, **extra):
        return {'syllabus': self.grade6.pk, 'revision': 1, 'collection_mode': 'FULL', 'plan_type': 'REGULAR', 'lead': self.lead.pk, **extra}

    def test_two_simultaneous_choices_issue_only_one_current_quote(self):
        barrier = Barrier(2)
        def create():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return quotes.create_quote(self.bde, self.payload()).reference
            except SalesError as exc:
                return exc.code
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: create(), range(2)))
        self.assertCountEqual(results, ['Q-000001', 'PLAN_CHANGED'])
        self.assertEqual(Quote.objects.count(), 1)

    def test_database_refuses_replacement_bypass_and_clearing_the_lock(self):
        first = quotes.create_quote(self.bde, self.payload())
        snapshot = quotes.quote_snapshot(self.bde, collection_mode='FULL', syllabus_id=self.grade6.pk, revision=1, plan_type='REVISION', lead_id=self.lead.pk)
        with self.assertRaises(DatabaseError), transaction.atomic():
            quotes.issue(snapshot)  # Missing latest quote; even internal/raw writes must keep the chain.
        Lead.objects.filter(pk=self.lead.pk).update(plan_changes_locked_at=timezone.now())
        with self.assertRaises(DatabaseError), transaction.atomic():
            quotes.issue(dataclasses.replace(snapshot, supersedes=first))
        with self.assertRaises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute('UPDATE leads SET plan_changes_locked_at = NULL WHERE id = %s', [self.lead.pk])
        self.assertEqual(Quote.objects.count(), 1)
