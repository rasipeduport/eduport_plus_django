"""
Quotes (sales.quotes, /api/sales/quotes/): a BDE quotes a parent from the
catalogue on sale -- a whole course, a Chapter Plan's chapters, a Bridge
Course whole or by the day -- and the quote keeps what it was issued with:
the revision and pricing version, the chapters by id, the rates, packages and
figures, exactly, rounded half up only at each single-payment price. Nothing
published or priced later changes it or its PDF; the database refuses any
change but its status, and any package or chapter added after the quote was
issued (sales.0005) -- checked here with real commits. A cancelled quote's PDF
is still drawn, as it was quoted, marked CANCELLED. A BDE sees their own
quotes; an administrator every one, and cancels; no one else any.
"""
import dataclasses
import uuid
from datetime import timedelta
from decimal import Decimal as D
from unittest import mock

from django.db import DatabaseError, connection, transaction
from django.template.loader import render_to_string
from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from activity.models import ActivityLog
from bookings.models import Lead

from . import pricing as pricing_module, quotes, services
from .models import PricingVersion, Quote, QuoteChapter, QuoteLine, QuoteStatus, Syllabus, SyllabusChapter, SyllabusRevision
from .pdf import TEMPLATE, pdf_context, quote_pdf, render_document
from .pricing import SELECTED_DAYS_TITLE
from .services import SalesError
from .tests_lifecycle import account, chapter_wise_payload, editable, valid
from .tests_selection import BridgeCourseFixture

QUOTES = '/api/sales/quotes/'


def lead_of(owner, name, phone):
    return Lead.objects.create(
        parent_name=f'{name} Parent', phone_dial_code='+971', phone_number=phone, phone_key=f'+971{phone}',
        student_name=name, student_name_key=name.lower(), school_name='Quote School', grade='Class 7', syllabus='CBSE',
        owner_bde=owner, owner_assigned_at=timezone.now(),
    )


class QuoteTestCase(BridgeCourseFixture):
    """
    On sale: Grade 6 (chapter-wise, sold as Regular, Revision, Regular +
    Revision and a Chapter Plan) and Grade 7 (a ten-day Bridge Course, DAYS).
    Pricing v1: AED 45 standard, 35 offer, 5% off Regular and Bridge Course
    paid at once.
    """

    def make_world(self):
        self.admin = account('quote_admin')
        self.bde = account('quote_bde', 'BDE')
        self.other_bde = account('quote_other_bde', 'BDE')
        self.grade6 = services.create_syllabus(self.admin, valid(chapter_wise_payload(
            plan_types=['REGULAR', 'REVISION', 'REGULAR_REVISION', 'CHAPTER_PLAN'])))
        draft = SyllabusRevision.objects.get(syllabus=self.grade6)
        services.publish(self.admin, self.grade6.pk, draft.number, draft.updated_at)
        self.chapters = self.day_ids(self.grade6)
        self.bridge = self.make_bridge_course()
        self.days = self.day_ids(self.bridge)
        self.price(offer='35')

    def price(self, offer='35', plan_types=('REGULAR', 'BRIDGE_COURSE')):
        return services.create_pricing_version(self.admin, {
            'currency': 'AED', 'standard_fee': D('45'), 'offer_fee': D(offer), 'single_payment_percent': D('5'),
            'single_payment_plan_types': list(plan_types), 'note': '',
        })

    def quote(self, plan_type, syllabus=None, chapter_ids=(), actor=None, revision=1, lead=None):
        return quotes.create_quote(actor or self.bde, {
            'syllabus': (syllabus or self.grade6).pk, 'revision': revision, 'plan_type': plan_type,
            'chapter_ids': list(chapter_ids), 'lead': lead.pk if lead else None,
        })

    def figures(self, quote):
        quote = Quote.objects.get(pk=quote.pk)
        return {
            'classes': quote.classes, 'total_fee': quote.total_fee, 'saving': quote.single_payment_saving,
            'payable': quote.payable_amount, 'full_course': quote.full_course,
            'lines': [(line.title, line.classes, line.fee_per_class, line.total, line.single_payment_price,
                       line.single_payment_saving) for line in quote.lines.all()],
        }


class QuoteSnapshotTests(QuoteTestCase, TestCase):
    def setUp(self):
        self.make_world()

    def test_a_whole_course_keeps_its_rates_packages_and_figures(self):
        regular = self.quote('REGULAR')
        self.assertEqual((regular.number, regular.reference, regular.status), (1, 'Q-000001', QuoteStatus.ISSUED))
        self.assertEqual((regular.revision.number, regular.pricing_version.version, regular.created_by), (1, 1, self.bde))
        self.assertEqual((regular.currency, regular.standard_fee, regular.offer_fee, regular.single_payment_percent),
                         ('AED', D('45'), D('35'), D('5')))
        # 38 classes at AED 35 are 1,330; less 5% is 1,263.50, a half, rounded up: 1,264 payable at once, saving 66.
        self.assertEqual(self.figures(regular), {
            'classes': D('38'), 'total_fee': D('1330'), 'saving': D('66'), 'payable': D('1264'), 'full_course': True,
            'lines': [('Regular Course Package', D('38'), D('35'), D('1330'), D('1264'), D('66'))],
        })
        # Every chapter, by id, with the Regular classes it counted.
        self.assertEqual([(str(row.chapter_id), row.classes) for row in regular.chapters.order_by('chapter__position')][:2],
                         [(self.chapters[0], D('4')), (self.chapters[1], D('5'))])
        self.assertEqual(regular.chapters.count(), 10)
        # Revision alone: no privilege for it in v1.
        self.assertEqual(self.figures(self.quote('REVISION'))['lines'],
                         [('Revision Course (Exam Oriented) Package', D('19'), D('35'), D('665'), None, None)])

    def test_regular_and_revision_is_two_packages_each_rounded_on_its_own(self):
        both = self.quote('REGULAR_REVISION')
        self.assertEqual(self.figures(both), {
            'classes': D('57'), 'total_fee': D('1995'), 'saving': D('66'), 'payable': D('1929'), 'full_course': True,
            'lines': [('Regular Course Package', D('38'), D('35'), D('1330'), D('1264'), D('66')),
                      ('Revision Course (Exam Oriented) Package', D('19'), D('35'), D('665'), None, None)],
        })
        # Each chapter counted with both columns: Patterns In Mathematics is 4 Regular + 2 Revision.
        self.assertEqual(both.chapters.get(chapter_id=self.chapters[0]).classes, D('6'))

    def test_a_chapter_plan_is_the_chosen_chapters_regular_classes(self):
        plan = self.quote('CHAPTER_PLAN', chapter_ids=[self.chapters[2], self.chapters[0]])
        self.assertEqual(self.figures(plan), {
            'classes': D('8'), 'total_fee': D('280'), 'saving': D('0'), 'payable': D('280'), 'full_course': False,
            'lines': [('Chapter Plan Package', D('8'), D('35'), D('280'), None, None)],
        })
        self.assertEqual(sorted(str(pk) for pk in plan.chapters.values_list('chapter_id', flat=True)),
                         sorted([self.chapters[0], self.chapters[2]]))

    def test_a_bridge_course_by_the_day_or_whole(self):
        days = self.quote('BRIDGE_COURSE', self.bridge, chapter_ids=[self.days[3], self.days[1]])
        # 1.5 + 2 classes, AED 122.50; less 5% is 116.375 -> 116, saving 6.50.
        self.assertEqual(self.figures(days), {
            'classes': D('3.5'), 'total_fee': D('122.5'), 'saving': D('6.5'), 'payable': D('116'), 'full_course': False,
            'lines': [(SELECTED_DAYS_TITLE, D('3.5'), D('35'), D('122.5'), D('116'), D('6.5'))],
        })
        whole = {'classes': D('10'), 'total_fee': D('350'), 'saving': D('17'), 'payable': D('333'), 'full_course': True,
                 'lines': [('Bridge Course Package', D('10'), D('35'), D('350'), D('333'), D('17'))]}
        # No days named, or every day: the whole course, as its own package.
        self.assertEqual(self.figures(self.quote('BRIDGE_COURSE', self.bridge)), whole)
        every = self.quote('BRIDGE_COURSE', self.bridge, chapter_ids=list(reversed(self.days)))
        self.assertEqual(self.figures(every), whole)
        self.assertEqual(every.chapters.count(), 10)

    def test_amounts_stay_exact_to_the_fil(self):
        self.price(offer='35.25')
        quote = self.quote('BRIDGE_COURSE', self.bridge, chapter_ids=[self.days[1]])
        # 1.5 classes at AED 35.25 are 52.875; less 5% is 50.23125 -> 50, saving 2.875.
        self.assertEqual(self.figures(quote)['lines'], [(SELECTED_DAYS_TITLE, D('1.5'), D('35.25'), D('52.875'), D('50'), D('2.875'))])
        self.assertEqual((quote.pricing_version.version, quote.payable_amount), (2, D('50')))

    def test_numbers_follow_one_another(self):
        numbers = [self.quote('REGULAR').number for _ in range(3)]
        self.assertEqual(numbers, [1, 2, 3])
        self.assertEqual(Quote.objects.get(number=3).reference, 'Q-000003')

    def test_what_cannot_be_quoted(self):
        def refused(*args, **kwargs):
            with self.assertRaises(SalesError) as raised:
                self.quote(*args, **kwargs)
            return raised.exception.code, raised.exception.message
        self.assertEqual(refused('BRIDGE_COURSE')[0], 'VALIDATION_ERROR')                      # Grade 6 is not one
        self.assertEqual(refused('REGULAR', self.bridge)[1], 'Grade 7 CBSE is not sold as Regular.')
        self.assertEqual(refused('REGULAR', chapter_ids=[self.chapters[0]])[1],
                         'Regular is the whole course: choose no chapters.')
        self.assertEqual(refused('CHAPTER_PLAN'), ('INVALID_SELECTION', 'Choose at least one chapter.'))
        self.assertEqual(refused('CHAPTER_PLAN', chapter_ids=[self.chapters[0]] * 2)[0], 'INVALID_SELECTION')
        self.assertEqual(refused('CHAPTER_PLAN', chapter_ids=[self.days[0]])[1], 'Choose chapters of revision 1 of this syllabus.')
        self.assertEqual(refused('BRIDGE_COURSE', self.bridge, chapter_ids=[self.days[5]]),
                         ('INVALID_SELECTION', 'The days chosen have no classes.'))
        self.assertEqual(refused('REGULAR', revision=2)[0], 'NOT_FOUND')
        draft = self.make_bridge_course(publish=False, title='Grade 8 CBSE')
        self.assertEqual(refused('BRIDGE_COURSE', draft)[0], 'NOT_FOUND')
        services.deactivate(self.admin, self.bridge.pk)
        self.assertEqual(refused('BRIDGE_COURSE', self.bridge)[0], 'NOT_FOUND')
        self.assertFalse(Quote.objects.exists())

    def test_a_quote_answers_an_enquiry_of_its_own(self):
        own, theirs = lead_of(self.bde, 'Riya', '509100001'), lead_of(self.other_bde, 'Arjun', '509100002')
        self.assertEqual(self.quote('REGULAR', lead=own).lead, own)
        with self.assertRaises(SalesError) as raised:
            self.quote('REGULAR', lead=theirs)
        self.assertEqual(raised.exception.extra['fields'], {'lead': ['Choose one of your own enquiries.']})
        # An administrator, who may read every lead, quotes for any.
        self.assertEqual(self.quote('REGULAR', lead=theirs, actor=self.admin).lead, theirs)

    def test_quoting_copies_nothing_of_the_catalogue(self):
        before = (Syllabus.objects.count(), SyllabusRevision.objects.count(), SyllabusChapter.objects.count(),
                  PricingVersion.objects.count())
        self.quote('REGULAR_REVISION')
        self.quote('BRIDGE_COURSE', self.bridge, chapter_ids=self.days[:3])
        self.assertEqual((Syllabus.objects.count(), SyllabusRevision.objects.count(), SyllabusChapter.objects.count(),
                          PricingVersion.objects.count()), before)
        self.assertEqual(QuoteChapter.objects.count(), 13)
        self.assertEqual(list(ActivityLog.objects.filter(action='quote.create').values_list('entity_label', flat=True)
                              .order_by('created_at')), ['Q-000001', 'Q-000002'])


class QuotePinningTests(QuoteTestCase, TestCase):
    """A quote says what it said, whatever is published or priced -- or however pricing works -- later."""

    def setUp(self):
        self.make_world()
        self.quoted = self.quote('BRIDGE_COURSE', self.bridge, chapter_ids=[self.days[1], self.days[3]])

    def pdf(self, quote):
        return quote_pdf(*quotes.quote_pdf_parts(Quote.objects.get(pk=quote.pk)))

    def test_a_new_revision_and_a_new_pricing_leave_it_and_its_pdf_as_they_were(self):
        data, pdf = quotes.quote_data(Quote.objects.get(pk=self.quoted.pk)), self.pdf(self.quoted)
        # The Admin edits the days (day 2 now 3 classes, renamed) and publishes revision 2; then prices go up.
        draft = services.start_draft(self.admin, self.bridge.pk)
        content = editable(draft)
        content['chapters'][1] = {**content['chapters'][1], 'name': 'Renamed day', 'bridge_classes': '3'}
        services.save_draft(self.admin, self.bridge.pk, valid(content), draft.updated_at)
        draft = SyllabusRevision.objects.get(syllabus=self.bridge, number=2)
        services.publish(self.admin, self.bridge.pk, 2, draft.updated_at)
        self.price(offer='40', plan_types=['BRIDGE_COURSE', 'REGULAR', 'REVISION'])
        self.assertEqual(quotes.quote_data(Quote.objects.get(pk=self.quoted.pk)), data)
        self.assertEqual(self.pdf(self.quoted), pdf)
        self.assertEqual([chapter['name'] for chapter in data['chapters']], ['Day 2 topic', 'Day 4 topic'])
        # Revision 1 is no longer what is sold: a new quote from it is refused, from revision 2 it is priced anew.
        with self.assertRaises(SalesError) as raised:
            self.quote('BRIDGE_COURSE', self.bridge, chapter_ids=[self.days[1]])
        self.assertEqual(raised.exception.code, 'REVISION_CHANGED')
        newer = self.quote('BRIDGE_COURSE', self.bridge, chapter_ids=[self.day_ids(self.bridge, 2)[1]], revision=2)
        self.assertEqual((newer.classes, newer.total_fee, newer.pricing_version.version), (D('3'), D('120'), 2))

    def test_the_pdf_is_drawn_from_the_quote_never_priced_again(self):
        pdf = self.pdf(self.quoted)
        # Were the pricing to work differently tomorrow (another rounding rule, say), an issued quote is not priced again.
        with mock.patch.object(pricing_module, 'packages', side_effect=AssertionError('priced again')), \
                mock.patch.object(pricing_module, 'single_payment_price', side_effect=AssertionError('priced again')):
            self.assertEqual(self.pdf(self.quoted), pdf)

    def test_the_pdf_shows_what_was_quoted_and_its_reference(self):
        content, rates, cards, selected, reference = quotes.quote_pdf_parts(self.quoted)
        context = pdf_context(content, rates, selected=selected, cards=cards, quote=reference)
        self.assertEqual([row['position'] for page in context['chapter_pages'] for row in page['rows']], [2, 4])
        self.assertEqual((context['totals']['bridge'], context['fees']['offer']), ('3.5', '35 AED/Class'))
        self.assertEqual([(p['title'], p['classes_label'], p['total'], p['single_payment']) for p in context['packages']],
                         [(SELECTED_DAYS_TITLE, '3.5 Classes', 'AED 122.50', {'price': 'AED 116', 'saving': 'AED 6.50'})])
        html = render_to_string(TEMPLATE, context)
        self.assertIn(f'<p class="quote-ref">Quote Q-000001 · {reference["date"]}</p>', html)
        self.assertIn('Save <b>AED 6.50</b> Instantly', html)
        self.assertTrue(self.pdf(self.quoted).startswith(b'%PDF'))
        # A whole course prints every chapter; the syllabus PDF itself has no quote line.
        whole = quotes.quote_pdf_parts(self.quote('REGULAR'))
        self.assertIsNone(whole[3])
        self.assertNotIn('quote-ref', render_to_string(TEMPLATE, pdf_context(content, PricingVersion.objects.get(version=1))))


class QuoteHistoryTests(QuoteTestCase, TestCase):
    """The database's own guard (sales.0004), behind the services'."""

    def setUp(self):
        self.make_world()
        self.quoted = self.quote('REGULAR_REVISION')

    def assertRefused(self, write):
        with self.assertRaises(DatabaseError):
            with transaction.atomic():
                write()

    def test_its_figures_lines_and_chapters_never_change(self):
        quote = Quote.objects.filter(pk=self.quoted.pk)
        self.assertRefused(lambda: quote.update(total_fee=D('1')))
        self.assertRefused(lambda: quote.update(payable_amount=D('1'), single_payment_saving=D('1994')))
        self.assertRefused(lambda: quote.update(created_at=timezone.now() - timedelta(days=1)))
        self.assertRefused(lambda: quote.delete())
        self.assertRefused(lambda: QuoteLine.objects.filter(quote=self.quoted).update(total=D('1')))
        self.assertRefused(lambda: QuoteLine.objects.filter(quote=self.quoted).delete())
        self.assertRefused(lambda: QuoteChapter.objects.filter(quote=self.quoted).update(classes=D('9')))
        self.assertRefused(lambda: QuoteChapter.objects.filter(quote=self.quoted).delete())

    def test_only_its_status_moves_and_a_cancelled_quote_is_final(self):
        quotes.cancel_quote(self.admin, self.quoted.pk, 'Parent chose another plan')
        cancelled = Quote.objects.get(pk=self.quoted.pk)
        self.assertEqual((cancelled.status, cancelled.cancelled_by, cancelled.cancel_reason),
                         (QuoteStatus.CANCELLED, self.admin, 'Parent chose another plan'))
        quote = Quote.objects.filter(pk=self.quoted.pk)
        self.assertRefused(lambda: quote.update(status=QuoteStatus.ISSUED, cancelled_at=None, cancelled_by=None, cancel_reason=''))
        self.assertRefused(lambda: quote.update(cancel_reason='Another reason'))
        with self.assertRaises(SalesError) as raised:
            quotes.cancel_quote(self.admin, self.quoted.pk, 'Again')
        self.assertEqual(raised.exception.code, 'ALREADY_CANCELLED')

    def checked_now(self):
        """Run the checks a commit would (the test's transaction never commits), then defer them again."""
        with connection.cursor() as cursor:
            try:
                cursor.execute('SET CONSTRAINTS ALL IMMEDIATE')
            finally:
                cursor.execute('SET CONSTRAINTS ALL DEFERRED')

    def test_a_quote_adds_up_to_its_packages_and_chapters(self):
        def at_commit(write):
            with self.assertRaises(DatabaseError):
                with transaction.atomic():
                    write()
                    self.checked_now()
        line = self.quoted.lines.first()
        # Another package, or another chapter, added afterwards: refused at commit.
        at_commit(lambda: QuoteLine.objects.create(
            quote=self.quoted, position=3, plan_type='REGULAR', title='Extra', classes=D('1'), fee_per_class=D('35'), total=D('35')))
        at_commit(lambda: QuoteChapter.objects.create(
            quote=self.quoted, chapter=SyllabusChapter.objects.filter(revision__syllabus=self.bridge).first(), classes=D('1')))
        # The service's own quotes add up.
        with transaction.atomic():
            self.quote('BRIDGE_COURSE', self.bridge, chapter_ids=self.days[:4])
            self.checked_now()
        self.assertEqual(line.title, 'Regular Course Package')


class QuoteApiTests(QuoteTestCase, APITestCase):
    def setUp(self):
        self.make_world()

    def as_user(self, user):
        self.client.force_authenticate(user)
        return self.client

    def create(self, user, **body):
        payload = {'syllabus': str(self.bridge.pk), 'revision': 1, 'plan_type': 'BRIDGE_COURSE', **body}
        return self.as_user(user).post(QUOTES, payload, format='json')

    def test_a_bde_quotes_and_sees_their_own(self):
        response = self.create(self.bde, chapter_ids=[self.days[1], self.days[3]])
        self.assertEqual(response.status_code, 201, response.content)
        data = response.json()
        self.assertEqual((data['reference'], data['status'], data['plan_type'], data['full_course'], data['revision'],
                          data['pricing_version'], data['created_by']['id']),
                         ('Q-000001', 'ISSUED', 'BRIDGE_COURSE', False, 1, 1, str(self.bde.pk)))
        self.assertEqual((data['classes'], data['total_fee'], data['single_payment_saving'], data['payable_amount'], data['currency']),
                         ('3.5', '122.5', '6.5', '116', 'AED'))
        self.assertEqual(data['lines'], [{'plan_type': 'BRIDGE_COURSE', 'title': SELECTED_DAYS_TITLE, 'classes': '3.5',
                                          'fee_per_class': '35', 'total': '122.5', 'single_payment': {'price': '116', 'saving': '6.5'}}])
        self.assertEqual([(row['position'], row['name'], row['classes']) for row in data['chapters']],
                         [(2, 'Day 2 topic', '1.5'), (4, 'Day 4 topic', '2')])
        pdf = self.client.get(f'{QUOTES}{data["id"]}/pdf/?disposition=inline')
        self.assertEqual((pdf.status_code, pdf['Content-Type']), (200, 'application/pdf'))
        self.assertEqual(pdf['Content-Disposition'], 'inline; filename="Q-000001-Grade-7-CBSE-Bridge-Course.pdf"')
        self.assertEqual(pdf['Cache-Control'], 'private, no-store')
        self.assertEqual(self.client.get(f'{QUOTES}{data["id"]}/pdf/').content, pdf.content)
        self.assertEqual([row['reference'] for row in self.client.get(QUOTES).json()['results']], ['Q-000001'])

    def test_one_bde_never_reaches_anothers_quotes(self):
        mine = self.create(self.bde).json()
        self.create(self.other_bde)
        other = self.as_user(self.other_bde)
        self.assertEqual([row['reference'] for row in other.get(QUOTES).json()['results']], ['Q-000002'])
        for url in (f'{QUOTES}{mine["id"]}/', f'{QUOTES}{mine["id"]}/pdf/'):
            response = other.get(url)
            self.assertEqual((response.status_code, response.json()), (404, {'error': 'NOT_FOUND', 'message': 'No such quote.'}))
        self.assertEqual(other.post(f'{QUOTES}{mine["id"]}/cancel/', {'reason': 'Mine now'}, format='json').status_code, 403)
        self.assertEqual(self.as_user(self.bde).post(f'{QUOTES}{mine["id"]}/cancel/', {'reason': 'Never mind'}, format='json').status_code, 403)
        self.assertEqual(Quote.objects.get(pk=mine['id']).status, QuoteStatus.ISSUED)

    def test_an_administrator_sees_every_quote_and_cancels_one(self):
        first = self.create(self.bde).json()
        self.create(self.other_bde, chapter_ids=[self.days[0]])
        admin = self.as_user(self.admin)
        self.assertEqual([row['reference'] for row in admin.get(QUOTES).json()['results']], ['Q-000002', 'Q-000001'])
        self.assertEqual([row['reference'] for row in admin.get(QUOTES, {'created_by': str(self.bde.pk)}).json()['results']], ['Q-000001'])
        for q in ('Q-000001', '1', 'grade 7'):
            self.assertIn('Q-000001', [row['reference'] for row in admin.get(QUOTES, {'q': q}).json()['results']], q)
        self.assertEqual(admin.get(QUOTES, {'q': '9' * 20}).status_code, 200)
        self.assertEqual(admin.get(f'{QUOTES}{first["id"]}/').status_code, 200)
        self.assertEqual(admin.get(f'{QUOTES}{first["id"]}/pdf/').status_code, 200)
        self.assertEqual(admin.post(f'{QUOTES}{first["id"]}/cancel/', {}, format='json').json()['error'], 'VALIDATION_ERROR')
        cancelled = admin.post(f'{QUOTES}{first["id"]}/cancel/', {'reason': 'Parent chose Regular'}, format='json')
        self.assertEqual((cancelled.status_code, cancelled.json()['status'], cancelled.json()['cancel_reason']),
                         (200, 'CANCELLED', 'Parent chose Regular'))
        again = admin.post(f'{QUOTES}{first["id"]}/cancel/', {'reason': 'Again'}, format='json')
        self.assertEqual((again.status_code, again.json()['error']), (409, 'ALREADY_CANCELLED'))
        self.assertEqual([row['reference'] for row in admin.get(QUOTES, {'status': 'cancelled'}).json()['results']], ['Q-000001'])
        self.assertEqual(admin.get(QUOTES, {'status': 'NOPE'}).status_code, 400)
        self.assertEqual(admin.get(QUOTES, {'created_by': 'nobody'}).status_code, 400)
        # The BDE sees their quote cancelled, and why.
        self.assertEqual(self.as_user(self.bde).get(f'{QUOTES}{first["id"]}/').json()['cancel_reason'], 'Parent chose Regular')
        self.assertTrue(ActivityLog.objects.filter(action='quote.cancel', entity_label='Q-000001').exists())

    def test_no_other_role_and_no_one_signed_out(self):
        quote = self.create(self.bde).json()
        requests = [('get', QUOTES, None), ('post', QUOTES, {'syllabus': str(self.bridge.pk), 'revision': 1, 'plan_type': 'BRIDGE_COURSE'}),
                    ('get', f'{QUOTES}{quote["id"]}/', None), ('get', f'{QUOTES}{quote["id"]}/pdf/', None),
                    ('post', f'{QUOTES}{quote["id"]}/cancel/', {'reason': 'No'})]
        for role in ('TUTOR', 'MENTOR', 'SALES_TL', 'STUDENT'):
            client = self.as_user(account(f'quote_{role.lower()}', role))
            with self.subTest(role=role):
                self.assertEqual([getattr(client, m)(url, body, format='json').status_code for m, url, body in requests], [403] * 5)
        client = self.as_user(None)
        self.assertEqual([getattr(client, m)(url, body, format='json').status_code for m, url, body in requests], [403] * 5)
        # A superuser holds both quote permissions (D1): every quote.
        root = self.as_user(account('quote_root', 'MENTOR', is_superuser=True))
        self.assertEqual(root.get(f'{QUOTES}{quote["id"]}/').status_code, 200)
        self.assertEqual(Quote.objects.count(), 1)

    def test_refusals_keep_nothing(self):
        def answer(**body):
            response = self.create(self.bde, **body)
            return response.status_code, response.json()
        status_code, body = answer(plan_type='NOPE')
        self.assertEqual((status_code, body['error'], list(body['fields'])), (400, 'VALIDATION_ERROR', ['plan_type']))
        status_code, body = answer(plan_type='REGULAR')
        self.assertEqual((status_code, body['fields']), (400, {'plan_type': ['Grade 7 CBSE is not sold as Regular.']}))
        status_code, body = answer(chapter_ids=[self.days[0], self.days[0]])
        self.assertEqual((status_code, body['error']), (400, 'INVALID_SELECTION'))
        draft = services.start_draft(self.admin, self.bridge.pk)
        services.publish(self.admin, self.bridge.pk, draft.number, draft.updated_at)
        status_code, body = answer()
        self.assertEqual((status_code, body['error'], body['revision']), (409, 'REVISION_CHANGED', 2))
        self.assertEqual(answer(syllabus='00000000-0000-0000-0000-000000000000')[0], 404)
        self.assertFalse(Quote.objects.exists())


class QuoteWithoutPricingTests(BridgeCourseFixture, APITestCase):
    def test_no_pricing_yet(self):
        self.admin = account('quote_no_pricing_admin')
        course = self.make_bridge_course()
        self.client.force_authenticate(self.admin)
        response = self.client.post(QUOTES, {'syllabus': str(course.pk), 'revision': 1, 'plan_type': 'BRIDGE_COURSE'}, format='json')
        self.assertEqual((response.status_code, response.json()['error']), (409, 'NO_PRICING'))
        self.assertFalse(Quote.objects.exists())


class CancelledQuotePdfTests(QuoteTestCase, TestCase):
    """A cancelled quote is history too: its PDF is still drawn, as it was quoted, and says it is cancelled."""

    def setUp(self):
        self.make_world()
        self.quoted = self.quote('REGULAR_REVISION')

    def drawn(self):
        content, rates, cards, selected, reference = quotes.quote_pdf_parts(Quote.objects.get(pk=self.quoted.pk))
        context = pdf_context(content, rates, selected=selected, cards=cards, quote=reference)
        document = render_document(content, rates, selected=selected, cards=cards, quote=reference)
        pdf = quote_pdf(content, rates, cards, selected, reference)
        return context, render_to_string(TEMPLATE, context), len(document.pages), pdf

    def test_its_pdf_keeps_every_figure_and_is_marked_cancelled_on_every_page(self):
        context, html, pages, pdf = self.drawn()
        self.assertNotIn('cancelled-mark', html)
        quotes.cancel_quote(self.admin, self.quoted.pk, 'Parent chose Regular only')
        cancelled = Quote.objects.get(pk=self.quoted.pk)
        after, marked, marked_pages, marked_pdf = self.drawn()
        # What was quoted, unchanged: the chapters, the packages and the fees.
        for key in ('chapter_pages', 'totals', 'fees', 'packages', 'title', 'package_title', 'inclusions'):
            self.assertEqual(after[key], context[key], key)
        self.assertEqual(marked_pages, pages)
        # CANCELLED across every page (a fixed box, repeated on each), and the day -- never why.
        self.assertEqual(marked.count('<div class="cancelled-mark">CANCELLED</div>'), 1)
        day = quotes._day(cancelled.cancelled_at)
        self.assertIn(f'<p class="quote-cancelled">Cancelled on {day}: this quote is no longer valid.</p>', marked)
        self.assertNotIn('Parent chose Regular only', marked)
        self.assertIn('AED 1,264', marked)
        self.assertNotEqual(marked_pdf, pdf)
        # Drawn again, the same document.
        self.assertEqual(self.drawn()[3], marked_pdf)

    def test_it_downloads_under_a_cancelled_name_for_its_owner_and_administrators(self):
        quotes.cancel_quote(self.admin, self.quoted.pk, 'Parent chose Regular only')
        client = APIClient()
        for user in (self.bde, self.admin):
            client.force_authenticate(user)
            response = client.get(f'{QUOTES}{self.quoted.pk}/pdf/')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response['Content-Disposition'],
                             'attachment; filename="Q-000001-Grade-6-CBSE-New-Syllabus-Plan-and-Price-Cancelled.pdf"')
        # An ordinary syllabus PDF carries no quote, so nothing of a cancellation.
        self.assertNotIn('cancelled', render_to_string(TEMPLATE, pdf_context(
            services.content_of(self.quoted.revision), PricingVersion.objects.get(version=1))))


class QuoteIntegrityTests(QuoteTestCase, TransactionTestCase):
    """
    The database's own guard on issued quotes (sales.0004, sales.0005), tried
    with direct SQL and real commits: each setUp and each write is its own
    committed transaction, as in production. (No serialized_rollback: replaying the seeded rows would
    trip the append-only tables' own triggers; nothing here needs them, as in bookings' concurrency tests.)
    """

    def setUp(self):
        self.make_world()
        self.chosen = self.quote('BRIDGE_COURSE', self.bridge, chapter_ids=[self.days[1], self.days[3]])
        self.whole = self.quote('BRIDGE_COURSE', self.bridge)

    def assertRefused(self, statement, params):
        with self.assertRaises(DatabaseError):
            with transaction.atomic(), connection.cursor() as cursor:
                cursor.execute(statement, params)

    def add_chapter(self, quote, chapter_id, classes):
        return ('INSERT INTO sales_quote_chapters (id, quote_id, chapter_id, classes) VALUES (%s, %s, %s, %s)',
                [uuid.uuid4(), quote.pk, chapter_id, classes])

    def test_no_chapter_is_added_to_an_issued_quote_not_even_one_without_classes(self):
        # Day 6 has no classes: added to the quote of days 2 and 4 it would change none of its sums.
        self.assertRefused(*self.add_chapter(self.chosen, self.days[5], 0))
        self.assertRefused(*self.add_chapter(self.chosen, self.days[0], 1))
        self.assertEqual(sorted(str(pk) for pk in self.chosen.chapters.values_list('chapter_id', flat=True)),
                         sorted([self.days[1], self.days[3]]))
        self.assertEqual(Quote.objects.get(pk=self.chosen.pk).classes, D('3.5'))

    def test_no_package_is_added_to_an_issued_quote(self):
        self.assertRefused(
            'INSERT INTO sales_quote_lines (id, quote_id, position, plan_type, title, classes, fee_per_class, total) '
            "VALUES (%s, %s, 2, 'BRIDGE_COURSE', 'Extra', 0, 35, 0)",
            [uuid.uuid4(), self.chosen.pk],
        )
        self.assertEqual(self.chosen.lines.count(), 1)

    def test_a_chapter_is_the_quotes_own_with_the_classes_it_has(self):
        # Even while a quote is being issued: a chapter of another revision, or counted wrong, is refused.
        snapshot = quotes.quote_snapshot(self.bde, syllabus_id=self.bridge.pk, revision=1, plan_type='BRIDGE_COURSE',
                                         chapter_ids=[self.days[1]])
        for chapter_id, classes in ((self.chapters[0], D('4')), (self.days[2], D('2'))):
            with self.assertRaises(DatabaseError):
                with transaction.atomic():
                    quote = quotes.issue(snapshot)
                    QuoteChapter.objects.create(quote=quote, chapter_id=chapter_id, classes=classes)
        self.assertEqual(Quote.objects.count(), 2)

    def test_a_whole_course_covers_every_chapter(self):
        # The whole course, without day 6 (no classes): every sum still adds up, but a day is missing.
        snapshot = quotes.quote_snapshot(self.bde, syllabus_id=self.bridge.pk, revision=1, plan_type='BRIDGE_COURSE')
        short = dataclasses.replace(snapshot, chapters=[(chapter, classes) for chapter, classes in snapshot.chapters
                                                         if str(chapter.pk) != self.days[5]])
        with self.assertRaises(DatabaseError):
            quotes.issue(short)
        self.assertEqual(Quote.objects.count(), 2)
        self.assertEqual(quotes.issue(snapshot).chapters.count(), 10)

    def test_a_quote_is_cancelled_only_with_a_reason(self):
        for reason in ('', '   '):
            self.assertRefused(
                "UPDATE sales_quotes SET status = 'CANCELLED', cancelled_at = now(), cancelled_by_id = %s, cancel_reason = %s WHERE id = %s",
                [self.admin.pk, reason, self.whole.pk],
            )
        self.assertEqual(Quote.objects.get(pk=self.whole.pk).status, QuoteStatus.ISSUED)
        self.assertEqual(quotes.cancel_quote(self.admin, self.whole.pk, 'Duplicate').cancel_reason, 'Duplicate')

    def test_a_cancelled_quote_stays_cancelled_and_as_it_was(self):
        quotes.cancel_quote(self.admin, self.chosen.pk, 'Withdrawn')
        for statement in (
            "UPDATE sales_quotes SET status = 'ISSUED', cancelled_at = NULL, cancelled_by_id = NULL, cancel_reason = '' WHERE id = %s",
            "UPDATE sales_quotes SET cancel_reason = 'Another reason' WHERE id = %s",
            'UPDATE sales_quotes SET payable_amount = 1, single_payment_saving = total_fee - 1 WHERE id = %s',
            'DELETE FROM sales_quotes WHERE id = %s',
            'DELETE FROM sales_quote_chapters WHERE quote_id = %s',
        ):
            self.assertRefused(statement, [self.chosen.pk])
        quote = Quote.objects.get(pk=self.chosen.pk)
        self.assertEqual((quote.status, quote.cancel_reason, quote.payable_amount, quote.chapters.count()),
                         (QuoteStatus.CANCELLED, 'Withdrawn', D('116'), 2))
        # An issued quote's figures, likewise, whatever writes to them.
        self.assertRefused('UPDATE sales_quotes SET total_fee = 1 WHERE id = %s', [self.whole.pk])
        self.assertRefused('UPDATE sales_quotes SET issued_xact = pg_current_xact_id() WHERE id = %s', [self.whole.pk])
