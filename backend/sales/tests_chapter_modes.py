"""Chapter Plan modes use one revision and the existing versioned global rate."""
import copy
import dataclasses
from decimal import Decimal as D
from types import SimpleNamespace
from unittest import mock

from django.db import DatabaseError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.template.loader import render_to_string
from django.test import SimpleTestCase, TransactionTestCase
from rest_framework.test import APITestCase

from . import quotes, services
from .models import Quote, SyllabusRevision
from .pdf import TEMPLATE, pdf_context, quote_pdf
from .pricing import chapter_class_count, plan_classes
from .tests_lifecycle import chapter_wise_payload, editable, valid
from .tests_quotes import QUOTES, QuoteTestCase, lead_of


class ChapterModeApiTests(QuoteTestCase, APITestCase):
    def setUp(self):
        self.make_world()
        self.client.force_authenticate(self.bde)

    def create(self, **extra):
        return self.client.post(QUOTES, {
            'syllabus': str(self.grade6.pk), 'revision': 1, 'plan_type': 'CHAPTER_PLAN',
            'chapter_ids': self.chapters[:2], 'pricing_version': 1, **extra,
        }, format='json')

    def test_regular_default_and_explicit_regular_preserve_existing_pricing(self):
        for extra in ({}, {'class_mode': 'REGULAR'}):
            response = self.create(**extra)
            self.assertEqual(response.status_code, 201, response.content)
            data = response.json()
            self.assertEqual((data['class_mode'], data['classes'], data['total_fee'], data['payable_amount']),
                             ('REGULAR', '9', '315', '315'))
            self.assertEqual(Quote.objects.get(pk=data['id']).class_mode, 'REGULAR')

    def test_revision_counts_rate_snapshot_and_detail_are_explicit(self):
        response = self.create(class_mode='REVISION')
        self.assertEqual(response.status_code, 201, response.content)
        data = response.json()
        self.assertEqual((data['class_mode'], data['classes'], data['total_fee'], data['single_payment_saving'], data['payable_amount']),
                         ('REVISION', '4', '140', '0', '140'))
        self.assertEqual((data['pricing_version'], data['offer_fee'], data['revision']), (1, '35', 1))
        self.assertEqual([row['id'] for row in data['chapters']], self.chapters[:2])
        self.assertEqual([row['revision_classes'] for row in data['chapters']], ['2', '2'])
        self.assertTrue(all('regular_classes' not in row for row in data['chapters']))
        self.assertEqual(data['lines'][0]['fee_per_class'], '35')
        self.assertEqual(self.client.get(f'{QUOTES}{data["id"]}/').json(), data)
        self.assertEqual(self.client.get(QUOTES).json()['results'][0]['class_mode'], 'REVISION')

    def test_rate_comes_from_admin_pricing_version_and_is_never_hardcoded(self):
        self.price(offer='35.25', plan_types=['REGULAR', 'REVISION', 'BRIDGE_COURSE'])
        response = self.create(class_mode='REVISION', pricing_version=2)
        self.assertEqual(response.status_code, 201, response.content)
        data = response.json()
        self.assertEqual((data['pricing_version'], data['offer_fee'], data['classes'], data['total_fee']), (2, '35.25', '4', '141'))
        # A Chapter Plan retains its existing discount policy even when whole-course Revision has a privilege.
        self.assertEqual((data['single_payment_saving'], data['payable_amount']), ('0', '141'))

    def test_regular_quote_pdf_labels_the_regular_column(self):
        response = self.create(class_mode='REGULAR')
        quote = Quote.objects.get(pk=response.json()['id'])
        content, rates, cards, selected, reference = quotes.quote_pdf_parts(quote)
        html = render_to_string(TEMPLATE, pdf_context(content, rates, cards=cards, selected=selected, quote=reference))
        self.assertIn('Chapter Plan · Regular classes', html)
        self.assertIn('Regular Plan', html)
        self.assertNotIn('Revision Plan', html)
        pdf = self.client.get(f'{QUOTES}{quote.pk}/pdf/')
        self.assertEqual(pdf.status_code, 200)
        self.assertTrue(pdf.content.startswith(b'%PDF'))

    def test_invalid_modes_and_modes_on_other_plans_are_rejected(self):
        for mode in ('BOTH', '', 'revision', None, 1):
            response = self.create(class_mode=mode)
            self.assertEqual(response.status_code, 400, response.content)
        for plan in ('REGULAR', 'REVISION', 'REGULAR_REVISION', 'BRIDGE_COURSE'):
            response = self.create(plan_type=plan, chapter_ids=[], class_mode='REVISION',
                                   syllabus=str(self.bridge.pk) if plan == 'BRIDGE_COURSE' else str(self.grade6.pk))
            self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(Quote.objects.count(), 0)

    def test_mode_cannot_enable_a_disabled_chapter_plan(self):
        syllabus = services.create_syllabus(self.admin, valid(chapter_wise_payload(plan_types=['REGULAR', 'REVISION'])))
        draft = syllabus.revisions.get()
        services.publish(self.admin, syllabus.pk, 1, draft.updated_at)
        response = self.create(syllabus=str(syllabus.pk), chapter_ids=self.day_ids(syllabus)[:1], class_mode='REVISION')
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn('not sold as Chapter Plan', response.json()['message'])

    def test_modes_are_independent_of_standalone_plan_offerings(self):
        syllabus = services.create_syllabus(self.admin, valid(chapter_wise_payload(plan_types=['CHAPTER_PLAN'])))
        draft = syllabus.revisions.get()
        services.publish(self.admin, syllabus.pk, 1, draft.updated_at)
        response = self.create(syllabus=str(syllabus.pk), chapter_ids=self.day_ids(syllabus)[:1], class_mode='REVISION')
        self.assertEqual(response.status_code, 201, response.content)

    def test_cross_syllabus_cross_revision_duplicates_and_empty_selection_are_refused(self):
        for ids in (self.days[:1], self.chapters[:1] * 2, []):
            for mode in ('REGULAR', 'REVISION'):
                response = self.create(chapter_ids=ids, class_mode=mode)
                self.assertEqual(response.status_code, 400, response.content)
        draft = services.start_draft(self.admin, self.grade6.pk)
        services.publish(self.admin, self.grade6.pk, 2, draft.updated_at)
        response = self.create(revision=2, chapter_ids=self.chapters[:1], class_mode='REVISION')
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn('revision 2', response.json()['message'])
        response = self.create(class_mode='REVISION')
        self.assertEqual((response.status_code, response.json()['error']), (409, 'REVISION_CHANGED'))
        self.assertFalse(Quote.objects.exists())

    def test_missing_invalid_or_zero_revision_counts_cannot_issue_a_quote(self):
        # Published models prohibit missing/invalid counts. Exercise the service's
        # defensive checks too, without weakening those database constraints.
        sold = self.grade6.revisions.get(number=1)
        for invalid in (None, D('-1'), D('0.25'), D('NaN'), D('Infinity'), D('100'), D('0')):
            chapters = [copy.copy(chapter) for chapter in sold.chapters.order_by('position')]
            for chapter in chapters:
                chapter.revision_classes = invalid
            stub = SimpleNamespace(title=sold.title, number=1, structure=sold.structure, plan_types=sold.plan_types,
                                   chapters=mock.Mock(order_by=mock.Mock(return_value=chapters)))
            with mock.patch.object(quotes.services, 'on_sale_revision', return_value=stub):
                response = self.create(class_mode='REVISION')
            self.assertEqual(response.status_code, 400, response.content)
            self.assertIn('no classes' if invalid == 0 else 'Revision is unavailable', response.json()['message'])
        self.assertFalse(Quote.objects.exists())

    def test_revision_is_valid_when_selected_chapters_have_zero_regular_classes(self):
        payload = chapter_wise_payload(plan_types=['CHAPTER_PLAN'])
        payload['chapters'][0]['regular_classes'] = '0'
        payload['chapters'][0]['revision_classes'] = '1.5'
        syllabus = services.create_syllabus(self.admin, valid(payload))
        draft = syllabus.revisions.get()
        services.publish(self.admin, syllabus.pk, 1, draft.updated_at)
        response = self.create(syllabus=str(syllabus.pk), chapter_ids=self.day_ids(syllabus)[:1], class_mode='REVISION')
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual((response.json()['classes'], response.json()['total_fee']), ('1.5', '52.5'))

    def test_snapshot_pdf_and_replacement_keep_the_mode_after_republication_and_repricing(self):
        lead = lead_of(self.bde, 'Chapter Mode Student', '509300001')
        first = self.create(class_mode='REVISION', lead=str(lead.pk)).json()
        quote = Quote.objects.get(pk=first['id'])
        before = quotes.quote_data(quote)
        pdf_before = quote_pdf(*quotes.quote_pdf_parts(quote))
        content, rates, cards, selected, reference = quotes.quote_pdf_parts(quote)
        html = render_to_string(TEMPLATE, pdf_context(content, rates, cards=cards, selected=selected, quote=reference))
        self.assertIn('Chapter Plan · Revision classes', html)
        self.assertIn('Revision Plan', html)
        self.assertNotIn('Regular Plan', html)
        self.assertTrue(pdf_before.startswith(b'%PDF'))
        draft = services.start_draft(self.admin, self.grade6.pk)
        changed = editable(draft)
        changed['chapters'][0].update(name='Renamed chapter', revision_classes='8')
        services.save_draft(self.admin, self.grade6.pk, valid(changed), draft.updated_at)
        draft = SyllabusRevision.objects.get(syllabus=self.grade6, number=2)
        services.publish(self.admin, self.grade6.pk, 2, draft.updated_at)
        self.price(offer='40')
        self.assertEqual(quotes.quote_data(Quote.objects.get(pk=quote.pk)), before)
        self.assertEqual(quote_pdf(*quotes.quote_pdf_parts(Quote.objects.get(pk=quote.pk))), pdf_before)
        replacement = self.create(revision=2, pricing_version=2, class_mode='REGULAR',
                                  chapter_ids=self.day_ids(self.grade6, 2)[:2], lead=str(lead.pk), replaces=first['id'])
        self.assertEqual(replacement.status_code, 201, replacement.content)
        self.assertEqual((replacement.json()['class_mode'], replacement.json()['supersedes']), ('REGULAR', first['id']))
        quote.refresh_from_db()
        self.assertEqual(quote.class_mode, 'REVISION')
        # A pre-feature NULL mode is read as Regular without updating historical rows.
        quote.class_mode = None
        self.assertEqual(quotes.quote_row(quote)['class_mode'], 'REGULAR')


class ChapterModeIntegrityTests(QuoteTestCase, TransactionTestCase):
    def setUp(self):
        self.make_world()

    def snapshot(self):
        return quotes.quote_snapshot(self.bde, syllabus_id=self.grade6.pk, revision=1,
                                     plan_type='CHAPTER_PLAN', chapter_ids=self.chapters[:2], class_mode='REVISION')

    def test_database_uses_the_selected_column_and_keeps_the_mode_immutable(self):
        snapshot = self.snapshot()
        with self.assertRaises(DatabaseError), transaction.atomic():
            quotes.issue(dataclasses.replace(snapshot, chapters=[(chapter, chapter.regular_classes) for chapter, _ in snapshot.chapters]))
        quote = quotes.issue(snapshot)
        with self.assertRaises(DatabaseError), transaction.atomic():
            Quote.objects.filter(pk=quote.pk).update(class_mode='REGULAR')
        quote.refresh_from_db()
        self.assertEqual(quote.class_mode, 'REVISION')

    def test_database_requires_a_valid_explicit_mode_for_new_chapter_quotes(self):
        for mode in (None, 'BOTH'):
            with self.assertRaises(DatabaseError), transaction.atomic():
                quotes.issue(dataclasses.replace(self.snapshot(), class_mode=mode))
        self.assertFalse(Quote.objects.exists())


class ChapterModePricingTests(SimpleTestCase):
    def test_exact_half_counts_and_no_regular_fallback(self):
        chapters = [{'id': 'a', 'name': 'Ratios', 'regular_classes': D('4'), 'revision_classes': D('1.5')}]
        self.assertEqual(plan_classes('CHAPTER_PLAN', chapters, ['a']), D('4'))
        self.assertEqual(plan_classes('CHAPTER_PLAN', chapters, ['a'], class_mode='REVISION'), D('1.5'))
        with self.assertRaises(ValueError):
            chapter_class_count({**chapters[0], 'revision_classes': None}, 'REVISION')
        with self.assertRaises(ValueError):
            chapter_class_count(chapters[0], 'BOTH')


class ChapterModeMigrationTests(QuoteTestCase, TransactionTestCase):
    def test_rollback_cannot_remove_the_mode_of_revision_quotes(self):
        self.make_world()
        quote = quotes.issue(quotes.quote_snapshot(self.bde, syllabus_id=self.grade6.pk, revision=1,
                                                  plan_type='CHAPTER_PLAN', chapter_ids=self.chapters[:1], class_mode='REVISION'))
        with self.assertRaisesMessage(DatabaseError, 'their history must be preserved'):
            MigrationExecutor(connection).migrate([('sales', '0006_quote_replacements')])
        quote.refresh_from_db()
        self.assertEqual(quote.class_mode, 'REVISION')

    def test_existing_chapter_quotes_survive_migration_without_rewriting_their_snapshot(self):
        self.make_world()
        old_target = [('sales', '0006_quote_replacements')]
        new_target = [('sales', '0007_chapter_plan_class_mode')]
        executor = MigrationExecutor(connection)
        executor.migrate(old_target)
        try:
            apps = executor.loader.project_state(old_target).apps
            OldQuote = apps.get_model('sales', 'Quote')
            OldLine = apps.get_model('sales', 'QuoteLine')
            OldChapter = apps.get_model('sales', 'QuoteChapter')
            revision = self.grade6.revisions.get(number=1)
            price = apps.get_model('sales', 'PricingVersion').objects.get(version=1)
            with transaction.atomic():
                old = OldQuote.objects.create(
                    number=1, created_by_id=self.bde.pk, revision_id=revision.pk, pricing_version_id=price.pk,
                    plan_type='CHAPTER_PLAN', full_course=False, currency='AED', standard_fee=D('45'), offer_fee=D('35'),
                    single_payment_percent=D('5'), classes=D('9'), total_fee=D('315'), single_payment_saving=D('0'), payable_amount=D('315'),
                )
                OldLine.objects.create(quote_id=old.pk, position=1, plan_type='CHAPTER_PLAN', title='Chapter Plan Package',
                                       classes=D('9'), fee_per_class=D('35'), total=D('315'))
                for chapter in revision.chapters.order_by('position')[:2]:
                    OldChapter.objects.create(quote_id=old.pk, chapter_id=chapter.pk, classes=chapter.regular_classes)
            before = list(OldChapter.objects.filter(quote_id=old.pk).order_by('chapter_id').values_list('chapter_id', 'classes'))
            MigrationExecutor(connection).migrate(new_target)
            quote = Quote.objects.get(pk=old.pk)
            self.assertIsNone(quote.class_mode)
            self.assertEqual((quotes.quote_data(quote)['class_mode'], quote.classes, quote.total_fee), ('REGULAR', D('9'), D('315')))
            self.assertEqual(list(quote.chapters.order_by('chapter_id').values_list('chapter_id', 'classes')), before)
            with self.assertRaises(DatabaseError), transaction.atomic():
                Quote.objects.filter(pk=old.pk).update(class_mode='REGULAR')
        finally:
            MigrationExecutor(connection).migrate(new_target)
