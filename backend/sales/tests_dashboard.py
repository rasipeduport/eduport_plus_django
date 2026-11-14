"""The administrators' Sales Dashboard: every figure read from the sale, purchase and payment records, as the Finance tab reads them.

Stripe transport is mocked throughout; no request leaves the test process.
"""
from datetime import timedelta

from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from bookings.models import Lead
from . import tests_student_finance as finance_helpers
from .payment_models import Sale
from .tests_quotes import QuoteTestCase

Finance = finance_helpers.StudentFinanceTests


@override_settings(STRIPE_SECRET_KEY='sk_test_unit_only', STRIPE_WEBHOOK_SECRET='whsec_unit_only', STRIPE_LIVE_MODE=False,
                   LEARN_INVITATION_KEYS=['MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA='])
class SalesDashboardTests(QuoteTestCase, APITestCase):
    """The initial-sale fixtures (Bridge Course, 10 classes, AED 500, sold by self.bde), enrolled and given to self.mentor."""
    setUp = Finance.setUp
    new_lead = Finance.new_lead
    url = Finance.url
    start = Finance.start
    stripe_transport = Finance.stripe_transport
    event = Finance.event
    webhook = Finance.webhook
    link_for = Finance.link_for
    transport = Finance.transport
    paid = Finance.paid
    enrolled = Finance.enrolled
    as_user = Finance.as_user
    purchase = Finance.purchase
    receipt = Finance.receipt
    finance = Finance.finance

    def dashboard(self, client=None, **dates):
        params = {key: value.isoformat() if hasattr(value, 'isoformat') else value for key, value in dates.items()}
        return (client or self.as_user(self.admin)).get('/api/sales/dashboard/', params)

    def today(self):
        return {'from': timezone.localdate(), 'to': timezone.localdate()}

    def test_only_an_administrator_reads_the_sales_dashboard(self):
        self.enrolled()
        self.assertEqual(self.dashboard().status_code, 200)
        # The BDE who sold it, the student's mentor and an anonymous caller hold no financial oversight.
        for client in (self.client, self.as_user(), APIClient()):
            with self.subTest(client=client):
                self.assertIn(self.dashboard(client).status_code, (401, 403))

    def test_its_figures_add_up_to_the_students_finance_tab(self):
        self.enrolled()
        additional = self.purchase(collection_mode='PARTIAL').json()['sale']['id']
        self.assertEqual(self.receipt(additional).status_code, 201)
        data = self.dashboard(**self.today()).json()
        finance = self.finance().json()['summary']
        summary = data['summary']
        self.assertEqual((summary['sales_value'], summary['collected'], summary['outstanding']),
                         (finance['total_amount'], finance['paid_amount'], finance['pending_amount']))
        self.assertEqual({key: summary[key] for key in ('sales_count', 'enrollments', 'additional_purchases', 'payments',
                                                         'collected', 'refunded', 'outstanding_purchases', 'enrolled_leads')},
                         {'sales_count': 2, 'enrollments': 1, 'additional_purchases': 1, 'payments': 2, 'collected': '700',
                          'refunded': '0', 'outstanding_purchases': 1, 'enrolled_leads': 1})
        self.assertEqual(summary['leads'], Lead.objects.count())

        self.assertEqual(data['mix'], {
            'kinds': [{'kind': 'INITIAL', 'count': 1, 'value': '500'}, {'kind': 'ADDITIONAL', 'count': 1, 'value': '500'}],
            'plans': [{'plan': 'FULL', 'count': 1, 'value': '500'}, {'plan': 'PARTIAL', 'count': 1, 'value': '500'},
                      {'plan': 'AUTOPAY', 'count': 0, 'value': '0'}]})
        types = {row['type']: (row['count'], row['amount']) for row in data['collections']['types']}
        self.assertEqual((types['INITIAL'], types['ADDITIONAL'], types['BALANCE']), ((1, '500'), (1, '200'), (0, '0')))
        methods = {row['method']: (row['count'], row['amount']) for row in data['collections']['methods']}
        self.assertEqual((methods['STRIPE'], methods['TRANSFER']), ((1, '500'), (1, '200')))

        # The additional purchase is the one balance left, as its Finance tab row says.
        [row] = data['outstanding']['rows']
        self.assertEqual((row['sale_id'], row['kind'], row['payment_status'], row['package_amount'], row['paid_amount'],
                          row['outstanding_amount'], row['student']['id']),
                         (additional, 'ADDITIONAL', 'PARTIALLY_PAID', '500', '200', '300', str(self.student.pk)))
        by_status = {row['status']: (row['count'], row['amount']) for row in data['outstanding']['by_status']}
        self.assertEqual(by_status, {'PARTIALLY_PAID': (1, '300'), 'UNPAID': (0, '0'), 'LINK_PENDING': (0, '0'), 'AUTOPAY': (0, '0')})

        # The BDE is credited with the first sale; the mentor's additional purchase is no BDE's.
        bde = next(row for row in data['bdes'] if row['id'] == str(self.bde.pk))
        self.assertEqual({key: bde[key] for key in ('enrolled_leads', 'enrollments', 'sales_value', 'collected')},
                         {'enrolled_leads': 1, 'enrollments': 1, 'sales_value': '500', 'collected': '500'})
        funnel = {stage['stage']: stage['count'] for stage in data['funnel']}
        self.assertEqual((funnel['SALE_STARTED'], funnel['ENROLLED']), (1, 1))
        self.assertGreaterEqual(funnel['QUOTED'], 1)

        self.assertEqual(data['trend']['unit'], 'day')
        [bucket] = data['trend']['buckets']
        self.assertEqual((bucket['sales_count'], bucket['sales_value'], bucket['payments'], bucket['collected']), (2, '1000', 2, '700'))
        newest, oldest = data['recent_payments']
        self.assertEqual((newest['payment_type'], newest['method'], newest['amount'], newest['student']['student_code']),
                         ('ADDITIONAL', 'TRANSFER', '200', self.student.student_code))
        self.assertEqual((oldest['payment_type'], oldest['method_label']), ('INITIAL', 'Stripe'))
        self.assertEqual(data['pending']['links'], {'count': 0, 'amount': '0', 'before_enrollment': 0})

    def test_a_span_counts_only_its_own_dates_while_balances_stay_as_they_stand(self):
        self.enrolled(mode='PARTIAL', classes='6')
        yesterday = timezone.localdate() - timedelta(days=1)
        data = self.dashboard(**{'from': yesterday - timedelta(days=6), 'to': yesterday}).json()
        summary = data['summary']
        self.assertEqual((summary['sales_count'], summary['sales_value'], summary['collected'], summary['leads']), (0, '0', '0', 0))
        self.assertEqual((summary['outstanding'], summary['outstanding_purchases']), ('200', 1))
        self.assertEqual(len(data['trend']['buckets']), 7)
        self.assertTrue(all(bucket['collected'] == '0' for bucket in data['trend']['buckets']))
        # Today's span holds the sale itself, partly paid.
        self.assertEqual(self.dashboard(**self.today()).json()['outstanding']['rows'][0]['payment_status'], 'PARTIALLY_PAID')

    def test_long_spans_are_drawn_week_by_week_then_month_by_month_each_bucket_cut_to_the_span(self):
        weeks = self.dashboard(**{'from': '2026-01-07', 'to': '2026-03-31'}).json()['trend']
        self.assertEqual((weeks['unit'], weeks['buckets'][0]['from'], weeks['buckets'][0]['to'], weeks['buckets'][-1]['to']),
                         ('week', '2026-01-07', '2026-01-11', '2026-03-31'))
        months = self.dashboard(**{'from': '2025-12-15', 'to': '2026-11-14'}).json()['trend']
        self.assertEqual([(bucket['from'], bucket['to']) for bucket in months['buckets']][:2],
                         [('2025-12-15', '2025-12-31'), ('2026-01-01', '2026-01-31')])
        self.assertEqual((months['unit'], len(months['buckets']), months['buckets'][-1]['to']), ('month', 12, '2026-11-14'))

    def test_bad_dates_are_refused_naming_them(self):
        for dates, fields in (({'from': '2026-13-01', 'to': '2026-11-01'}, ['from']), ({'from': '2026-11-01'}, ['to']),
                              ({'from': '2025-01-01', 'to': '2026-11-01'}, ['to'])):
            with self.subTest(dates=dates):
                response = self.dashboard(**dates)
                self.assertEqual((response.status_code, response.json()['error'], response.json()['fields']), (400, 'INVALID_INPUT', fields))
        self.assertEqual(Sale.objects.count(), 0)
