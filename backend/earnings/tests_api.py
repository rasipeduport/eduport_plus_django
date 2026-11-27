"""
The Tutor Earnings API (earnings.views): administrators read every tutor's
earnings and act on rates, payments and the ledger; a tutor reads their own
earnings only -- always the signed-in account's; mentors, BDEs and students get
nothing. Every GET only reads.
"""
import uuid
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from sessions.models import Session

from . import ledger
from .models import EarningEntry, EntryKind, TutorPayment
from .tests_ledger import LedgerWorld
from .values import india_today

User = get_user_model()


class EarningsApiWorld(LedgerWorld):
    def setUp(self):
        super().setUp()
        self.price(tutors=[{'tutor': str(self.tutor.pk), 'rates': {'SESSION': '450'}}])
        self.session = self.completed(timedelta(days=2), hours=1.5)  # ₹675 to the tutor (their own rate)
        self.other_session = self.completed(timedelta(days=1), tutor=self.other_tutor)  # ₹400 to the other tutor
        ledger.reconcile()
        self.earning = EarningEntry.objects.get(source_id=self.session.pk)

    def call(self, user, method, name, *args, data=None, params=None):
        self.client.force_authenticate(user=user)
        url = reverse(f'earnings:{name}', args=args)
        if method == 'get':
            return self.client.get(url, params or {})
        return self.client.post(url, data or {}, format='json')

    def payment(self, **changes):
        return {'request_id': str(uuid.uuid4()), 'amount': '100.00', 'paid_on': india_today().isoformat(),
                'method': 'UPI', 'reference': f'UPI {uuid.uuid4().hex[:12]}', **changes}


class PermissionTests(EarningsApiWorld):
    def admin_calls(self):
        tutor = str(self.tutor.pk)
        return [
            ('get', 'overview', (), None),
            ('get', 'rates', (), None),
            ('post', 'rates', (), {'rates': {'SESSION': '410'}, 'reason': 'Revision'}),
            ('post', 'rates-initial', (), {'confirm': True}),
            ('get', 'review', (), None),
            ('get', 'tutor', (tutor,), None),
            ('get', 'tutor-entries', (tutor,), None),
            ('post', 'tutor-rates', (tutor,), {'rates': {'DEMO': '320'}, 'reason': 'Senior'}),
            ('post', 'tutor-payments', (tutor,), self.payment()),
            ('post', 'tutor-adjustments', (tutor,), {'amount': '10', 'reason': 'Prep'}),
            ('post', 'payment-void', (str(uuid.uuid4()),), {'reason': 'Mistake'}),
            ('post', 'entry-reverse', (str(self.earning.pk),), {'reason': 'Mistake'}),
            ('post', 'entry-keep', (str(self.earning.pk),), {'reason': 'Ran as paid'}),
        ]

    def tutor_calls(self):
        return [('get', 'me', (), None), ('get', 'me-entries', (), None)]

    def test_mentors_bdes_students_and_strangers_get_nothing(self):
        for user in (self.mentor, self.other_mentor, self.bde, self.student_user, None):
            for method, name, args, data in self.admin_calls() + self.tutor_calls():
                with self.subTest(user=getattr(user, 'role', 'anonymous'), call=name, method=method):
                    res = self.call(user, method, name, *args, data=data)
                    self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(EarningEntry.objects.count(), 2)
        self.assertFalse(TutorPayment.objects.exists())

    def test_a_tutor_reads_their_own_earnings_and_nothing_of_the_administrators(self):
        for method, name, args, data in self.admin_calls():
            with self.subTest(call=name, method=method):
                self.assertEqual(self.call(self.tutor, method, name, *args, data=data).status_code,
                                 status.HTTP_403_FORBIDDEN)
        for method, name, args, data in self.tutor_calls():
            with self.subTest(call=name):
                self.assertEqual(self.call(self.tutor, method, name, *args, data=data).status_code, status.HTTP_200_OK)

    def test_an_administrator_has_no_my_earnings(self):
        for method, name, args, data in self.tutor_calls():
            self.assertEqual(self.call(self.admin, method, name, *args).status_code, status.HTTP_403_FORBIDDEN)
        for method, name, args, data in self.admin_calls():
            with self.subTest(call=name, method=method):
                self.assertNotEqual(self.call(self.admin, method, name, *args, data=data).status_code,
                                    status.HTTP_403_FORBIDDEN)


class TutorScopeTests(EarningsApiWorld):
    def test_my_earnings_are_always_the_signed_in_tutors(self):
        for tutor, earned in ((self.tutor, '675.00'), (self.other_tutor, '400.00')):
            with self.subTest(tutor=tutor.email):
                other = self.other_tutor if tutor == self.tutor else self.tutor
                res = self.call(tutor, 'get', 'me', params={'tutor': str(other.pk), 'tutor_id': str(other.pk)})
                self.assertEqual(res.status_code, status.HTTP_200_OK)
                self.assertEqual((res.data['tutor']['id'], res.data['summary']['earned']), (str(tutor.pk), earned))
                rows = self.call(tutor, 'get', 'me-entries', params={'tutor': str(other.pk)}).data['results']
                self.assertEqual({row['source_id'] for row in rows},
                                 {str(self.session.pk if tutor == self.tutor else self.other_session.pk)})

    def test_a_tutor_reads_no_administrators_detail(self):
        TutorPayment.objects.create(request_id=uuid.uuid4(), tutor=self.tutor, amount=100, paid_on=india_today(),
                                    method='UPI', reference='UPI 1', reference_key='UPI1', recorded_by=self.admin,
                                    voided_at=timezone.now(), voided_by=self.admin, void_reason='Typed twice')
        data = self.call(self.tutor, 'get', 'me').data
        for hidden in ('rate_history', 'review', 'own_rates'):
            self.assertNotIn(hidden, data)
        # When pricing started and the sync last ran -- not who started it, or how the sync went.
        self.assertEqual((set(data['pricing']), set(data['last_sync'])), ({'started_at'}, {'started_at', 'finished_at'}))
        self.assertNotIn('rate_source', data['breakdown'][2]['lines'][0])
        self.assertEqual(data['breakdown'][2]['lines'][0]['rate'], '450.00')
        self.assertEqual(set(data['rates'][0]), {'class_type', 'unit', 'amount'})
        voided = data['payments'][0]
        self.assertNotIn('recorded_by', voided)
        self.assertEqual((voided['voided'], voided['void_reason']), (True, 'Typed twice'))
        entry = self.call(self.tutor, 'get', 'me-entries').data['results'][0]
        self.assertNotIn('rate_source', entry)
        self.assertNotIn('created_by', entry)


class ReadOnlyTests(EarningsApiWorld):
    def test_no_page_read_writes_anything(self):
        # A class that counts and has not been synced yet: reading never earns it.
        self.completed(timedelta(hours=5))
        before = EarningEntry.objects.count()
        reads = [(self.admin, 'overview', ()), (self.admin, 'rates', ()), (self.admin, 'review', ()),
                 (self.admin, 'tutor', (str(self.tutor.pk),)), (self.admin, 'tutor-entries', (str(self.tutor.pk),)),
                 (self.tutor, 'me', ()), (self.tutor, 'me-entries', ())]
        for user, name, args in reads:
            with self.subTest(name=name), CaptureQueriesContext(connection) as captured:
                self.assertEqual(self.call(user, 'get', name, *args).status_code, status.HTTP_200_OK)
            writes = [q['sql'] for q in captured.captured_queries
                      if q['sql'].lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE'))]
            self.assertEqual(writes, [])
        self.assertEqual(EarningEntry.objects.count(), before)


class OverviewTests(EarningsApiWorld):
    def test_the_overview_has_every_tutor_their_counts_and_balances(self):
        data = self.call(self.admin, 'get', 'overview').data
        self.assertEqual(data['currency'], 'INR')
        totals = data['totals']
        self.assertEqual((totals['earned'], totals['paid'], totals['pending']), ('1075.00', '0.00', '1075.00'))
        self.assertEqual((totals['sessions'], totals['session_hours'], totals['classes']), (2, '2.50', 2))
        first, second = data['tutors']
        self.assertEqual((first['id'], first['outstanding'], first['own_rates']), (str(self.tutor.pk), '675.00', True))
        self.assertEqual((first['sessions'], first['session_hours'], first['balance_state']), (1, '1.50', 'pending'))
        self.assertEqual((second['id'], second['own_rates']), (str(self.other_tutor.pk), False))
        self.assertEqual(data['pricing']['started_by']['name'], 'Lc Admin')
        self.assertEqual(data['last_sync']['status'], 'SUCCEEDED')

    def test_filters_and_months(self):
        rows = self.call(self.admin, 'get', 'overview', params={'search': 'two'}).data['tutors']
        self.assertEqual([row['id'] for row in rows], [str(self.other_tutor.pk)])
        self.assertEqual(self.call(self.admin, 'get', 'overview', params={'balance': 'paid'}).data['tutors'], [])
        rows = self.call(self.admin, 'get', 'overview', params={'rate': 'tutor'}).data['tutors']
        self.assertEqual([row['id'] for row in rows], [str(self.tutor.pk)])
        for month in ('soon', '9999-12', '0-01', '99999999999999999999-01', '2026-13'):
            with self.subTest(month=month):
                res = self.call(self.admin, 'get', 'overview', params={'month': month})
                self.assertEqual((res.status_code, res.data['code']), (status.HTTP_400_BAD_REQUEST, 'INVALID_INPUT'))
        old = self.call(self.admin, 'get', 'overview', params={'month': '2020-01'}).data
        self.assertEqual(old['totals']['earned'], '0.00')
        self.assertEqual(old['totals']['pending'], '1075.00')


class TutorDetailTests(EarningsApiWorld):
    def test_one_tutors_earnings_rates_history_and_what_is_not_counted_yet(self):
        notes_due = self.make(-timedelta(hours=6), started=True)
        data = self.call(self.admin, 'get', 'tutor', str(self.tutor.pk)).data
        self.assertEqual(data['summary']['earned'], '675.00')
        session = data['breakdown'][2]
        self.assertEqual((session['class_type'], session['classes'], session['units'], session['amount']),
                         ('SESSION', 1, '1.50', '675.00'))
        self.assertEqual(session['lines'], [{'rate': '450.00', 'classes': 1, 'units': '1.50', 'amount': '675.00',
                                              'rate_source': 'TUTOR'}])
        rates = {row['class_type']: row for row in data['rates']}
        self.assertEqual((rates['SESSION']['amount'], rates['SESSION']['source'], rates['SESSION']['global_amount']),
                         ('450.00', 'TUTOR', '400.00'))
        self.assertEqual(rates['DEMO']['source'], 'GLOBAL')
        self.assertEqual((len(data['rate_history']['tutor']), len(data['rate_history']['global'])), (1, 4))
        self.assertEqual([(item['reason'], item['source_id']) for item in data['not_counted']],
                         [('NOTES_DUE', str(notes_due.pk))])
        self.assertEqual(data['months_breakdown'][0]['earned'], '675.00')

    def test_only_tutors_have_earnings_pages(self):
        for missing in (uuid.uuid4(), self.mentor.pk):
            res = self.call(self.admin, 'get', 'tutor', str(missing))
            self.assertEqual((res.status_code, res.data['code']), (status.HTTP_404_NOT_FOUND, 'TUTOR_NOT_FOUND'))

    def test_a_page_past_the_last_is_empty(self):
        for page in ('2', '99999999999999999999'):
            with self.subTest(page=page):
                res = self.call(self.admin, 'get', 'tutor-entries', str(self.tutor.pk), params={'page': page})
                self.assertEqual((res.status_code, res.data['count'], res.data['results']), (status.HTTP_200_OK, 1, []))
        self.assertEqual(len(self.call(self.tutor, 'get', 'me-entries', params={'page': '1'}).data['results']), 1)

    def test_a_former_tutor_keeps_their_page_but_has_no_rates_to_change(self):
        self.assertTrue(self.call(self.admin, 'get', 'tutor', str(self.tutor.pk)).data['tutor']['is_tutor'])
        User.objects.filter(pk=self.other_tutor.pk).update(role='MENTOR')
        data = self.call(self.admin, 'get', 'tutor', str(self.other_tutor.pk)).data
        self.assertEqual((data['tutor']['is_tutor'], data['tutor']['active'], data['summary']['outstanding']),
                         (False, False, '400.00'))
        res = self.call(self.admin, 'post', 'tutor-rates', str(self.other_tutor.pk),
                        data={'rates': {'DEMO': '320'}, 'reason': 'Senior'})
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_the_paid_figures_are_the_periods(self):
        paid = self.call(self.admin, 'post', 'tutor-payments', str(self.tutor.pk), data=self.payment(amount='100')).data
        self.call(self.admin, 'post', 'payment-void', paid['payment']['id'], data={'reason': 'Typed twice'})
        self.call(self.admin, 'post', 'tutor-payments', str(self.tutor.pk), data=self.payment(amount='50'))
        today = india_today()
        for month, expected in ((None, ('50.00', 1, 1, today.isoformat())),
                                (today.strftime('%Y-%m'), ('50.00', 1, 1, today.isoformat())),
                                ('2020-01', ('0.00', 0, 0, None))):
            with self.subTest(month=month):
                summary = self.call(self.admin, 'get', 'tutor', str(self.tutor.pk),
                                    params={'month': month} if month else None).data['summary']
                self.assertEqual((summary['paid'], summary['payments'], summary['voided_payments'], summary['last_paid_on']),
                                 expected)
                self.assertEqual((summary['paid_all_time'], summary['outstanding']), ('50.00', '625.00'))


class ActionTests(EarningsApiWorld):
    def test_payments_are_recorded_once_per_request_and_voided_with_a_reason(self):
        data = self.payment(amount='675')
        res = self.call(self.admin, 'post', 'tutor-payments', str(self.tutor.pk), data=data)
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.data)
        self.assertEqual((res.data['payment']['amount'], res.data['outstanding']), ('675.00', '0.00'))
        again = self.call(self.admin, 'post', 'tutor-payments', str(self.tutor.pk), data=data)
        self.assertEqual((again.status_code, again.data['created']), (status.HTTP_200_OK, False))
        over = self.call(self.admin, 'post', 'tutor-payments', str(self.tutor.pk), data=self.payment())
        self.assertEqual((over.status_code, over.data['code']), (status.HTTP_409_CONFLICT, 'NOTHING_OUTSTANDING'))
        void = self.call(self.admin, 'post', 'payment-void', res.data['payment']['id'], data={'reason': 'Wrong tutor'})
        self.assertEqual(void.status_code, status.HTTP_200_OK, void.data)
        self.assertEqual((void.data['payment']['voided'], void.data['outstanding']), (True, '675.00'))

    def test_reversals_adjustments_and_rate_changes(self):
        res = self.call(self.admin, 'post', 'entry-reverse', str(self.earning.pk), data={'reason': 'Wrong class'})
        self.assertEqual((res.status_code, res.data['entry']['kind'], res.data['entry']['amount']),
                         (status.HTTP_201_CREATED, 'REVERSAL', '-675.00'))
        res = self.call(self.admin, 'post', 'tutor-adjustments', str(self.tutor.pk),
                        data={'amount': '675', 'reason': 'Re-paid at the right class', 'entry': str(self.earning.pk)})
        self.assertEqual((res.status_code, res.data['entry']['kind']), (status.HTTP_201_CREATED, 'ADJUSTMENT'))
        entries = self.call(self.admin, 'get', 'tutor-entries', str(self.tutor.pk)).data
        self.assertEqual(entries['count'], 3)
        reversed_row = next(row for row in entries['results'] if row['kind'] == EntryKind.EARNING)
        self.assertTrue(reversed_row['reversed'])
        self.assertEqual(reversed_row['reversal']['reason'], 'Wrong class')
        res = self.call(self.admin, 'post', 'rates', data={'rates': {'SESSION': '410'}, 'reason': 'Revision'})
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
        self.assertEqual(next(row for row in res.data['rates'] if row['class_type'] == 'SESSION')['amount'], '410.00')
        res = self.call(self.admin, 'post', 'tutor-rates', str(self.tutor.pk),
                        data={'rates': {'SESSION': None}, 'reason': 'Back to global'})
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
        self.assertFalse(res.data['own_rates'])
        res = self.call(self.admin, 'post', 'rates-initial', data={'confirm': True, 'global': {
            'DIAGNOSTIC': '1', 'DEMO': '1', 'SESSION': '1', 'DEMO_CONVERSION': '1'}})
        self.assertEqual((res.status_code, res.data['code']), (status.HTTP_409_CONFLICT, 'PRICING_STARTED'))

    def test_an_earning_in_review_is_kept_as_earned_with_its_reason(self):
        res = self.call(self.admin, 'post', 'entry-keep', str(self.earning.pk), data={'reason': 'Ran as paid', 'seen': {}})
        self.assertEqual((res.status_code, res.data['code']), (status.HTTP_409_CONFLICT, 'NOT_IN_REVIEW'))
        Session.objects.filter(pk=self.session.pk).update(end_time=self.session.end_time + timedelta(minutes=30))
        [item] = self.call(self.admin, 'get', 'review').data['items']
        self.assertEqual(self.call(self.admin, 'get', 'overview').data['review_count'], 1)
        seen = {'problem': item['problem'], 'current': item['current']}
        res = self.call(self.admin, 'post', 'entry-keep', str(self.earning.pk), data={'reason': 'The class ran 2 hours'})
        self.assertEqual((res.status_code, res.data['code']), (status.HTTP_400_BAD_REQUEST, 'INVALID_INPUT'))
        res = self.call(self.admin, 'post', 'entry-keep', str(self.earning.pk),
                        data={'reason': 'The class ran 2 hours', 'seen': seen})
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.data)
        kept = res.data['review']
        self.assertEqual((kept['entry_id'], kept['problem'], kept['reason'], kept['created_by']['name']),
                         (str(self.earning.pk), 'TIMES_CHANGED', 'The class ran 2 hours', 'Lc Admin'))
        self.assertEqual(self.call(self.admin, 'get', 'review').data['items'], [])
        self.assertEqual(self.call(self.admin, 'get', 'overview').data['review_count'], 0)
        self.assertEqual(self.call(self.admin, 'get', 'tutor', str(self.tutor.pk)).data['review'], [])


class TutorIdTests(EarningsApiWorld):
    """Each tutor's permanent Tutor ID (accounts.tutor_codes) on the Admin's pages and the tutor's own."""

    def test_the_overview_shows_and_finds_each_tutors_id(self):
        codes = {self.tutor.tutor_code, self.other_tutor.tutor_code}
        self.assertEqual(codes, {'EPT0001', 'EPT0002'})
        rows = self.call(self.admin, 'get', 'overview').data['tutors']
        self.assertEqual({row['id']: row['tutor_code'] for row in rows},
                         {str(self.tutor.pk): self.tutor.tutor_code, str(self.other_tutor.pk): self.other_tutor.tutor_code})
        found = self.call(self.admin, 'get', 'overview', params={'search': self.other_tutor.tutor_code.lower()})
        self.assertEqual([row['id'] for row in found.data['tutors']], [str(self.other_tutor.pk)])

    def test_the_tutor_page_and_my_earnings_carry_it(self):
        self.assertEqual(self.call(self.admin, 'get', 'tutor', str(self.tutor.pk)).data['tutor']['tutor_code'],
                         self.tutor.tutor_code)
        mine = self.call(self.tutor, 'get', 'me').data['tutor']
        self.assertEqual((mine['id'], mine['tutor_code']), (str(self.tutor.pk), self.tutor.tutor_code))

    def test_a_former_tutor_is_listed_with_the_id_they_keep(self):
        code = self.other_tutor.tutor_code
        self.other_tutor.role = 'MENTOR'
        self.other_tutor.save(update_fields=['role'])
        row = next(row for row in self.call(self.admin, 'get', 'overview').data['tutors']
                   if row['id'] == str(self.other_tutor.pk))
        self.assertEqual((row['tutor_code'], row['active']), (code, False))
