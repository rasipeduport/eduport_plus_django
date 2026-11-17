"""Explicit acceptance audit for a known missing policy; not a regression waiver."""
import json
from datetime import timedelta
from unittest import mock
from sales.tests_authorization import AutopayAuthorizationTests
from sales import autopay
from sales.autopay_models import AutopayAgreement
from students.models import Student

class RetryPolicyAcceptance(AutopayAuthorizationTests):
    def test_confirmed_policy_initial_plus_three_retries_then_pause(self):
        self.start(); gateway, _, charges = self.transport()
        with mock.patch('sales.stripe_gateway.client', return_value=gateway):
            self.begin(); self.initial_paid(gateway)
            agreement = AutopayAgreement.objects.get()
            row = agreement.installments.get(position=1)
            for number in range(4):
                instant = row.due_at + timedelta(hours=24 * number, seconds=1)
                with mock.patch('sales.autopay.timezone.now', return_value=instant):
                    before = len(charges)
                    autopay.collect_due()
                    if len(charges) > before:
                        self.webhook(self.future_event(charges[-1][2], kind='payment_intent.payment_failed',
                            status='requires_payment_method', amount_received=0, last_payment_error={'code': 'card_declined'}))
        agreement.refresh_from_db()
        actual = {'attempts': row.attempts.count(), 'agreement_status': agreement.status,
                  'paid_class_quota': str(Student.objects.get().total_class_quota)}
        expected = {'attempts': 4, 'agreement_status': 'PAUSED', 'paid_class_quota': '2.0'}
        print('RETRY_POLICY_AUDIT ' + json.dumps({'expected': expected, 'observed': actual}))
        self.assertEqual(actual, expected, 'Confirmed retry policy has not been implemented.')
