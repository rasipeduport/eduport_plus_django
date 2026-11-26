"""Additional hours with deferred payment (sales.additional_hours).

The hours reach the quota at once and exactly once; payments are recorded
against them in parts, never touch the quota, and stay apart from the regular
plan ledger. Stripe is never called: every plan payment here is a direct receipt.
"""
import io
import tempfile
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal as D
from threading import Barrier

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import CommandError, call_command
from django.db import DatabaseError, close_old_connections, transaction
from django.test import TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from activity.models import ActivityLog
from sessions.models import Session
from students import quota_sync
from students.models import Student
from students.services import serialize_student
from . import additional_hours, dashboard, payments, quotes, services, student_finance
from . import tests_payments as payment_helpers
from .allocation_models import AdditionalHoursAllocation, AdditionalHoursPayment
from .payment_models import Payment, Purchase
from .tests_lifecycle import account as user_account
from .tests_quotes import QuoteTestCase, lead_of

PNG = b'\x89PNG\r\n\x1a\n' + b'0' * 20
SETTINGS = dict(STRIPE_SECRET_KEY='sk_test_unit_only', STRIPE_WEBHOOK_SECRET='whsec_unit_only', STRIPE_LIVE_MODE=False,
                LEARN_INVITATION_KEYS=['MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA='])


def receipt():
    return SimpleUploadedFile('receipt.png', PNG, content_type='image/png')


def in_days(days):
    return (timezone.localdate() + timedelta(days=days)).isoformat()


@override_settings(**SETTINGS)
class AdditionalHoursTests(QuoteTestCase, APITestCase):
    """Bridge Course plans (10 classes, AED 500), enrolled by a BDE's direct receipt and given to self.mentor."""
    payment_setup = payment_helpers.InitialPaymentTests.setUp
    new_lead = payment_helpers.InitialPaymentTests.new_lead
    payload = payment_helpers.InitialPaymentTests.payload

    def setUp(self):
        self.payment_setup()
        self.mentor = user_account('hours_mentor', 'MENTOR')
        self.other_mentor = user_account('hours_other_mentor', 'MENTOR')
        self.tutor = user_account('hours_tutor', 'TUTOR')

    def as_user(self, user):
        client = APIClient()
        client.force_authenticate(user)
        return client

    def enroll(self, mode='FULL', classes='10', amount='500', reference=''):
        lead = self.new_lead(collection_mode=mode)
        client = self.as_user(self.bde)
        self.assertEqual(client.post(f'/api/sales/enquiries/{lead.pk}/sale/', {'kind': 'NEW'}, format='json').status_code, 201)
        response = client.post(f'/api/sales/enquiries/{lead.pk}/sale/payments/', self.payload(
            collection_mode=mode, classes=classes, amount=amount, transaction_reference=reference), format='multipart')
        self.assertEqual(response.status_code, 201, response.content)
        student = Student.objects.get(sales__enquiry=lead)
        Student.objects.filter(pk=student.pk).update(mentor=self.mentor)
        student.refresh_from_db()
        return student

    def plan(self, student):
        return Purchase.objects.filter(student=student).order_by('created_at').first()

    def add(self, student, user=None, **extra):
        body = {'request_id': str(uuid.uuid4()), 'purchase': str(self.plan(student).pk), 'hours': '3', 'amount': '150',
                'due_date': in_days(14), 'reason': 'Extra practice before the final exams.', **extra}
        return self.as_user(user or self.admin).post(f'/api/sales/students/{student.pk}/additional-hours/', body, format='json')

    def added(self, student, **extra):
        response = self.add(student, **extra)
        self.assertEqual(response.status_code, 201, response.content)
        return response.json()

    def pay(self, allocation_id, user=None, **extra):
        body = {'request_id': str(uuid.uuid4()), 'amount': '50', 'method': 'TRANSFER', 'payment_date': in_days(0),
                'received_confirmed': True, 'proof': receipt(), **extra}
        return self.as_user(user or self.mentor).post(f'/api/sales/additional-hours/{allocation_id}/payments/', body,
                                                      format='multipart')

    def quota(self, student):
        return Student.objects.get(pk=student.pk).total_class_quota

    def codes(self, response):
        return [problem['code'] for problem in response.json().get('problems', [])]

    # --- adding hours --------------------------------------------------------

    def test_hours_reach_the_quota_at_once_and_the_payment_stays_pending(self):
        student = self.enroll()
        self.assertEqual(self.quota(student), D(10))
        allocation = self.added(student, chapter=str(self.days[0]))
        self.assertEqual(self.quota(student), D(13))
        self.assertEqual((allocation['hours'], allocation['amount'], allocation['status'], allocation['outstanding_amount'],
                          allocation['quota_before'], allocation['quota_after'], allocation['hours_status']),
                         ('3', '150', 'PENDING', '150', '10', '13', 'ACTIVE'))
        self.assertEqual(allocation['chapter']['id'], str(self.days[0]))
        self.assertEqual(allocation['plan']['purchase_id'], str(self.plan(student).pk))
        self.assertTrue(allocation['reference'].startswith('AH-'))
        self.assertEqual(allocation['payments'], [])
        log = ActivityLog.objects.get(action='additional_hours.create')
        self.assertEqual(log.changes, {'total_class_quota': {'old': '10', 'new': '13'}})
        # The profile shows the hours as part of the quota, with their payment still owed.
        self.assertEqual(serialize_student(Student.objects.get(pk=student.pk))['additional_hours'],
                         {'active_hours': '3', 'payment_pending_hours': '3'})
        # Booking reads the same quota: the hours can be booked now.
        self.assertEqual(additional_hours.reconciliation(Student.objects.get(pk=student.pk))['reconciles'], True)

    def test_a_repeated_request_never_credits_twice(self):
        student = self.enroll()
        body = {'request_id': str(uuid.uuid4())}
        first = self.add(student, **body)
        again = self.add(student, **body)
        self.assertEqual((first.status_code, again.status_code), (201, 200))
        self.assertEqual(first.json()['id'], again.json()['id'])
        self.assertEqual(self.quota(student), D(13))
        conflict = self.add(student, hours='4', **body)
        self.assertEqual((conflict.status_code, conflict.json()['error']), (409, 'IDEMPOTENCY_CONFLICT'))
        self.assertEqual(AdditionalHoursAllocation.objects.count(), 1)

    def test_the_plan_chapter_hours_and_due_date_are_checked(self):
        student, other = self.enroll(), self.enroll()
        refused = self.add(student, purchase=str(self.plan(other).pk))
        self.assertEqual((refused.status_code, refused.json()['error']), (409, 'PLAN_NOT_STUDENTS'))
        refused = self.add(student, chapter=str(self.chapters[0]))  # A Grade 6 chapter: not this plan's.
        self.assertEqual((refused.status_code, refused.json()['error']), (409, 'CHAPTER_NOT_IN_PLAN'))
        refused = self.add(student, due_date=in_days(-1))
        self.assertEqual((refused.status_code, refused.json()['error']), (400, 'DUE_DATE_PAST'))
        for hours in ('1.25', '0', '0.4', '50.5', '1.3'):
            with self.subTest(hours=hours):
                self.assertEqual(self.add(student, hours=hours).status_code, 400)
        self.assertEqual(self.add(student, reason='   ').status_code, 400)
        self.assertEqual(self.add(student, amount='0').status_code, 400)
        self.assertEqual(self.add(student, amount='10.5').status_code, 400)
        self.assertEqual(self.quota(student), D(10))
        self.assertEqual(self.added(student, hours='0.5')['hours'], '0.5')

    def test_the_same_hours_again_within_a_week_need_confirmation(self):
        student = self.enroll()
        chapter = str(self.days[1])
        self.added(student, chapter=chapter)
        twice = self.add(student, chapter=chapter)
        self.assertEqual((twice.status_code, twice.json()['error']), (409, 'POSSIBLE_DUPLICATE'))
        self.assertEqual(self.quota(student), D(13))
        self.added(student, chapter=chapter, confirm_duplicate=True)
        self.assertEqual(self.quota(student), D(16))

    # --- eligibility ---------------------------------------------------------

    def test_unpaid_plan_classes_block_additional_hours(self):
        student = self.enroll(mode='PARTIAL', classes='6', amount='300')
        refused = self.add(student)
        self.assertEqual((refused.status_code, refused.json()['error']), (409, 'PLAN_CLASSES_UNPAID'))
        unpaid = next(problem for problem in refused.json()['problems'] if problem['code'] == 'PLAN_CLASSES_UNPAID')
        self.assertEqual((unpaid['plans'][0]['unpaid_classes'], unpaid['plans'][0]['outstanding_amount']), ('4', '200'))
        self.assertEqual((self.quota(student), AdditionalHoursAllocation.objects.count()), (D(6), 0))
        eligibility = self.as_user(self.admin).get(f'/api/sales/students/{student.pk}/additional-hours/eligibility/').json()
        self.assertFalse(eligibility['eligible'])
        self.assertEqual([plan['unpaid_classes'] for plan in eligibility['plans']], ['4'])
        self.assertEqual(len(eligibility['plans'][0]['chapters']), 10)

    def test_paid_but_uncredited_classes_block_additional_hours_on_every_plan(self):
        student = self.enroll(mode='PARTIAL', classes='6', amount='300')
        sale = self.plan(student).sale
        # The mentor collects the plan's balance: received, but the existing rules credit no class for it.
        balance = self.as_user(self.mentor).post(f'/api/sales/purchases/{sale.pk}/payments/', {
            'request_id': str(uuid.uuid4()), 'method': 'TRANSFER', 'classes': '4', 'amount': '200', 'received_confirmed': True,
            'payment_date': in_days(0), 'proof': receipt()}, format='multipart')
        self.assertEqual(balance.status_code, 201, balance.content)
        refused = self.add(student)
        self.assertEqual((refused.status_code, refused.json()['error']), (409, 'PAID_CLASSES_NOT_CREDITED'))
        self.assertNotIn('PLAN_CLASSES_UNPAID', self.codes(refused))
        problem = refused.json()['problems'][0]
        self.assertIn('4 paid classes (4 hrs)', problem['message'])
        self.assertEqual([(row['classes'], row['amount'], row['payment_type']) for row in problem['payments']],
                         [('4', '200', 'BALANCE')])
        self.assertEqual(self.quota(student), D(6))

    def test_any_plan_of_the_student_blocks_whichever_plan_is_chosen(self):
        student = self.enroll()
        # The mentor adds a further purchase, unpaid: hours against the first plan are refused too.
        additional = self.as_user(self.mentor).post(f'/api/sales/students/{student.pk}/purchases/', {
            'syllabus': str(self.bridge.pk), 'revision': 1, 'plan_type': 'BRIDGE_COURSE', 'collection_mode': 'FULL',
            'request_id': str(uuid.uuid4())}, format='json')
        self.assertEqual(additional.status_code, 201, additional.content)
        refused = self.add(student, purchase=str(self.plan(student).pk))
        self.assertEqual((refused.status_code, refused.json()['error']), (409, 'PLAN_CLASSES_UNPAID'))
        # Paid, its classes are money only under the existing rules: still refused, now as uncredited.
        sale_id = additional.json()['sale']['id']
        paid = self.as_user(self.mentor).post(f'/api/sales/purchases/{sale_id}/payments/', {
            'request_id': str(uuid.uuid4()), 'method': 'TRANSFER', 'classes': '10', 'amount': '500', 'received_confirmed': True,
            'payment_date': in_days(0), 'proof': receipt()}, format='multipart')
        self.assertEqual(paid.status_code, 201, paid.content)
        refused = self.add(student, purchase=str(self.plan(student).pk))
        self.assertEqual((refused.status_code, refused.json()['error']), (409, 'PAID_CLASSES_NOT_CREDITED'))

    def test_an_open_payment_link_blocks_additional_hours(self):
        student = self.enroll(mode='PARTIAL', classes='6', amount='300')
        purchase = self.plan(student)
        Payment.objects.create(id=uuid.uuid4(), request_id=uuid.uuid4(), sale=purchase.sale, purchase=purchase, purpose='TUITION',
                               method='STRIPE', collection_mode='PARTIAL', amount=D(200), classes=D(4), recorded_by=self.mentor)
        self.assertIn('PAYMENT_IN_PROGRESS', self.codes(self.add(student)))

    def test_a_quota_that_does_not_add_up_blocks_additional_hours(self):
        student = self.enroll()
        Student.objects.filter(pk=student.pk).update(total_class_quota=D(12))
        refused = self.add(student)
        self.assertEqual((refused.status_code, refused.json()['error']), (409, 'QUOTA_MISMATCH'))
        self.assertEqual(refused.json()['problems'][0]['quota']['expected_quota'], '10')
        out = io.StringIO()
        call_command('check_class_quota', stdout=out)
        self.assertIn(f'MISMATCH {student.student_code}: quota 12 hrs, expected 10 hrs', out.getvalue())
        with self.assertRaises(CommandError):
            call_command('check_class_quota', '--strict', stdout=io.StringIO())

    def test_sheet_managed_and_expired_students_are_refused(self):
        sheet = Student.objects.create(profile=user_account('sheet_parent', 'STUDENT'), student_code='EDP09001',
                                       full_name='Sheet Child', total_class_quota=D(20), mentor=self.mentor)
        refused = self.as_user(self.admin).post(f'/api/sales/students/{sheet.pk}/additional-hours/', {
            'request_id': str(uuid.uuid4()), 'purchase': str(uuid.uuid4()), 'hours': '2', 'amount': '100',
            'due_date': in_days(3), 'reason': 'Sheet student.'}, format='json')
        self.assertEqual((refused.status_code, refused.json()['error']), (409, 'NOT_ELIGIBLE'))
        self.assertEqual(Student.objects.get(pk=sheet.pk).total_class_quota, D(20))
        expired = self.enroll()
        Student.objects.filter(pk=expired.pk).update(status='EXPIRED')
        refused = self.add(expired)
        self.assertEqual((refused.status_code, refused.json()['error']), (409, 'NOT_ELIGIBLE'))

    # --- payments ------------------------------------------------------------

    def test_partial_and_multiple_payments_settle_the_hours_without_touching_the_quota(self):
        student = self.enroll()
        allocation = self.added(student)
        first = self.pay(allocation['id'])
        self.assertEqual(first.status_code, 201, first.content)
        self.assertEqual((first.json()['allocation']['status'], first.json()['allocation']['outstanding_amount']),
                         ('PARTIALLY_PAID', '100'))
        second = self.pay(allocation['id'], user=self.admin, amount='100', method='AJAS_UAE')
        state = second.json()['allocation']
        self.assertEqual((state['status'], state['paid_amount'], state['outstanding_amount'], state['last_payment_date']),
                         ('PAID', '150', '0', in_days(0)))
        self.assertEqual([row['recorded_by']['name'] for row in state['payments']], ['Hours_Mentor', 'Quote_Admin'])
        self.assertEqual(self.quota(student), D(13))
        refused = self.pay(allocation['id'])
        self.assertEqual((refused.status_code, refused.json()['error']), (409, 'ALLOCATION_PAID'))
        self.assertEqual(self.quota(student), D(13))
        self.assertEqual(ActivityLog.objects.filter(action='additional_hours.payment_record').count(), 2)

    def test_a_payment_is_never_more_than_is_due_and_needs_its_receipt(self):
        student = self.enroll()
        allocation = self.added(student)
        refused = self.pay(allocation['id'], amount='151')
        self.assertEqual((refused.status_code, refused.json()['error'], refused.json()['outstanding']),
                         (409, 'EXCEEDS_OUTSTANDING', '150'))
        self.assertEqual(self.pay(allocation['id'], received_confirmed=False).json()['error'], 'RECEIPT_NOT_CONFIRMED')
        body = {'request_id': str(uuid.uuid4()), 'amount': '50', 'method': 'TRANSFER', 'received_confirmed': True}
        self.assertEqual(self.as_user(self.mentor).post(f'/api/sales/additional-hours/{allocation["id"]}/payments/', body,
                                                        format='multipart').json()['error'], 'PROOF_REQUIRED')
        self.assertEqual(self.pay(allocation['id'], payment_date=in_days(1)).status_code, 400)
        self.assertEqual(self.pay(allocation['id'], method='STRIPE').status_code, 400)
        refused = self.pay(allocation['id'], proof=SimpleUploadedFile('receipt.html', b'<html></html>'))
        self.assertEqual(refused.json()['error'], 'INVALID_PROOF')
        self.assertFalse(AdditionalHoursPayment.objects.exists())
        key = str(uuid.uuid4())
        once, again = self.pay(allocation['id'], request_id=key), self.pay(allocation['id'], request_id=key)
        self.assertEqual((once.status_code, again.status_code), (201, 200))
        self.assertEqual(AdditionalHoursPayment.objects.count(), 1)
        self.assertEqual(self.pay(allocation['id'], request_id=key, amount='60').json()['error'], 'IDEMPOTENCY_CONFLICT')

    def test_a_voided_payment_reopens_the_balance_and_the_correct_one_is_recorded(self):
        student = self.enroll()
        allocation = self.added(student)
        self.assertEqual(self.pay(allocation['id'], amount='50').status_code, 201)
        wrong = self.pay(allocation['id'], amount='100', transaction_reference='UTR 7781').json()
        self.assertEqual(wrong['allocation']['status'], 'PAID')
        url = f'/api/sales/additional-hours/{allocation["id"]}/payments/{wrong["payment"]["id"]}/void/'
        self.assertEqual(self.as_user(self.mentor).post(url, {'kind': 'ERROR', 'reason': 'Wrong amount.'}).status_code, 403)
        voided = self.as_user(self.admin).post(url, {'kind': 'ERROR', 'reason': 'Receipt shows AED 70.'}, format='json')
        self.assertEqual(voided.status_code, 200, voided.content)
        state = voided.json()
        self.assertEqual((state['status'], state['paid_amount'], state['outstanding_amount']), ('PARTIALLY_PAID', '50', '100'))
        struck = next(row for row in state['payments'] if row['id'] == wrong['payment']['id'])
        self.assertEqual((struck['voided'], struck['void']['kind'], struck['void']['reason']), (True, 'ERROR', 'Receipt shows AED 70.'))
        # The voided payment's reference is free again for the corrected one.
        corrected = self.pay(allocation['id'], amount='70', transaction_reference='UTR-7781')
        self.assertEqual(corrected.status_code, 201, corrected.content)
        self.assertEqual(corrected.json()['allocation']['outstanding_amount'], '30')
        again = self.as_user(self.admin).post(url, {'kind': 'ERROR', 'reason': 'Again.'}, format='json')
        self.assertEqual(again.json()['error'], 'ALREADY_VOIDED')
        self.assertEqual(self.quota(student), D(13))
        log = ActivityLog.objects.get(action='additional_hours.payment_void')
        self.assertEqual(log.changes, {'outstanding': {'old': '0', 'new': '100'}})

    def test_references_are_never_counted_twice(self):
        student = self.enroll(reference='UTR-ENROL-1')
        other = self.enroll()
        allocation = self.added(student)
        second = self.added(student, hours='2', amount='100')
        foreign = self.added(other)
        self.assertEqual(self.pay(allocation['id'], transaction_reference='utr 555').status_code, 201)
        # The same receipt on the same hours: never.
        self.assertEqual(self.pay(allocation['id'], transaction_reference='UTR-555', amount='20').json()['error'],
                         'DUPLICATE_REFERENCE')
        # On another student's hours: never.
        self.assertEqual(self.pay(foreign['id'], transaction_reference='UTR555').json()['error'], 'DUPLICATE_REFERENCE')
        # On the same student's other hours: one transfer may have paid both, once confirmed.
        self.assertEqual(self.pay(second['id'], transaction_reference='UTR555').json()['error'], 'POSSIBLE_DUPLICATE')
        self.assertEqual(self.pay(second['id'], transaction_reference='UTR555', confirm_duplicate=True).status_code, 201)
        # The tuition payment's reference, and the same amount on the same day: confirmed only.
        self.assertEqual(self.pay(allocation['id'], transaction_reference='utr-enrol-1', amount='10').json()['error'],
                         'POSSIBLE_DUPLICATE')
        self.assertEqual(self.pay(allocation['id'], amount='50').json()['error'], 'POSSIBLE_DUPLICATE')
        self.assertEqual(self.pay(allocation['id'], amount='50', confirm_duplicate=True).status_code, 201)

    # --- managing ------------------------------------------------------------

    def test_due_date_and_amount_change_with_a_reason_never_below_what_is_paid(self):
        student = self.enroll()
        allocation = self.added(student)
        url = f'/api/sales/additional-hours/{allocation["id"]}/'
        admin = self.as_user(self.admin)
        self.assertEqual(self.as_user(self.mentor).patch(url, {'due_date': in_days(20), 'change_reason': 'x'}, format='json').status_code, 403)
        self.assertEqual(admin.patch(url, {'due_date': in_days(20)}, format='json').status_code, 400)
        moved = admin.patch(url, {'due_date': in_days(20), 'change_reason': 'Parent asked for a week.'}, format='json')
        self.assertEqual((moved.status_code, moved.json()['due_date']), (200, in_days(20)))
        self.assertEqual(admin.patch(url, {'due_date': in_days(-2), 'change_reason': 'x'}, format='json').json()['error'], 'DUE_DATE_PAST')
        self.assertEqual(admin.patch(url, {'due_date': in_days(20), 'change_reason': 'x'}, format='json').json()['error'], 'NO_CHANGE')
        self.assertEqual(self.pay(allocation['id'], amount='100').status_code, 201)
        refused = admin.patch(url, {'amount': '90', 'change_reason': 'Discount agreed.'}, format='json')
        self.assertEqual((refused.json()['error'], refused.json()['paid_amount']), ('AMOUNT_BELOW_PAID', '100'))
        lowered = admin.patch(url, {'amount': '100', 'change_reason': 'Discount agreed.'}, format='json').json()
        self.assertEqual((lowered['amount'], lowered['status']), ('100', 'PAID'))
        raised = admin.patch(url, {'amount': '180', 'change_reason': 'Price was entered too low.'}, format='json').json()
        self.assertEqual((raised['status'], raised['outstanding_amount']), ('PARTIALLY_PAID', '80'))
        log = ActivityLog.objects.filter(action='additional_hours.update').order_by('created_at').first()
        self.assertEqual((log.changes, log.context['reason']),
                         ({'due_date': {'old': in_days(14), 'new': in_days(20)}}, 'Parent asked for a week.'))
        self.assertEqual(self.quota(student), D(13))

    def test_overdue_is_worked_out_from_the_due_date(self):
        student = self.enroll()
        allocation = self.added(student, due_date=in_days(0))
        self.assertFalse(allocation['overdue'])
        # Past its due date (set directly: the API only takes today or later).
        AdditionalHoursAllocation.objects.filter(pk=allocation['id']).update(due_date=timezone.localdate() - timedelta(days=2))
        state = self.as_user(self.mentor).get(f'/api/sales/additional-hours/{allocation["id"]}/').json()
        self.assertEqual((state['status'], state['overdue'], state['days_overdue']), ('PENDING', True, 2))
        self.assertEqual(self.as_user(self.admin).get('/api/sales/additional-hours/?overdue=true').json()['count'], 1)
        self.pay(allocation['id'], amount='150')
        state = self.as_user(self.mentor).get(f'/api/sales/additional-hours/{allocation["id"]}/').json()
        self.assertEqual((state['status'], state['overdue']), ('PAID', False))
        self.assertEqual(self.as_user(self.admin).get('/api/sales/additional-hours/?overdue=true').json()['count'], 0)

    def test_waiving_keeps_the_hours_and_closes_the_allocation(self):
        student = self.enroll()
        allocation = self.added(student)
        paid = self.pay(allocation['id']).json()['payment']
        url = f'/api/sales/additional-hours/{allocation["id"]}/'
        admin = self.as_user(self.admin)
        self.assertEqual(self.as_user(self.mentor).post(url + 'waive/', {'reason': 'x'}).status_code, 403)
        waived = admin.post(url + 'waive/', {'reason': 'Goodwill after a missed class.'}, format='json').json()
        self.assertEqual((waived['status'], waived['paid_amount'], waived['waived_amount'], waived['outstanding_amount'],
                          waived['hours_status']), ('WAIVED', '50', '100', '0', 'ACTIVE'))
        self.assertEqual(self.quota(student), D(13))
        self.assertEqual(self.pay(allocation['id']).json()['error'], 'ALLOCATION_CLOSED')
        self.assertEqual(admin.post(url + f'payments/{paid["id"]}/void/', {'kind': 'REFUNDED', 'reason': 'x'},
                                    format='json').json()['error'], 'ALLOCATION_CLOSED')
        self.assertEqual(admin.patch(url, {'due_date': in_days(30), 'change_reason': 'x'}, format='json').json()['error'],
                         'ALLOCATION_CLOSED')
        self.assertEqual(admin.post(url + 'withdraw/', {'reason': 'x'}, format='json').json()['error'], 'ALLOCATION_CLOSED')
        settled = self.added(student, hours='1', amount='50')
        self.pay(settled['id'], amount='50', transaction_reference='UTR-SETTLED')
        self.assertEqual(admin.post(f'/api/sales/additional-hours/{settled["id"]}/waive/', {'reason': 'x'}, format='json')
                         .json()['error'], 'ALLOCATION_PAID')

    def test_only_unused_hours_without_payments_can_be_withdrawn(self):
        student = self.enroll()
        allocation = self.added(student)
        url = f'/api/sales/additional-hours/{allocation["id"]}/'
        admin = self.as_user(self.admin)
        paid = self.pay(allocation['id']).json()['payment']
        self.assertEqual(admin.post(url + 'withdraw/', {'reason': 'Given by mistake.'}, format='json').json()['error'], 'HAS_PAYMENTS')
        admin.post(url + f'payments/{paid["id"]}/void/', {'kind': 'REFUNDED', 'reason': 'Money returned.'}, format='json')
        # Eleven of the thirteen hours booked: the three cannot all come back.
        start = timezone.now() + timedelta(days=2)
        session = Session.objects.create(student=student, start_time=start, end_time=start + timedelta(hours=11), title='Booked')
        refused = admin.post(url + 'withdraw/', {'reason': 'Given by mistake.'}, format='json').json()
        self.assertEqual((refused['error'], refused['unused_hours'], refused['hours']), ('HOURS_IN_USE', '2', '3'))
        session.delete()
        withdrawn = admin.post(url + 'withdraw/', {'reason': 'Given by mistake.'}, format='json').json()
        self.assertEqual((withdrawn['status'], withdrawn['hours_status'], withdrawn['outstanding_amount']),
                         ('CANCELLED', 'WITHDRAWN', '0'))
        self.assertEqual(self.quota(student), D(10))
        self.assertTrue(additional_hours.reconciliation(Student.objects.get(pk=student.pk))['reconciles'])
        self.assertEqual(self.pay(allocation['id']).json()['error'], 'ALLOCATION_CLOSED')
        self.assertNotIn('additional_hours', serialize_student(Student.objects.get(pk=student.pk)))

    # --- who may do what -----------------------------------------------------

    def test_only_administrators_add_and_manage_mentors_read_and_record_for_their_own_students(self):
        student = self.enroll()
        allocation = self.added(student)
        url = f'/api/sales/students/{student.pk}/additional-hours/'
        # A mentor can never add hours, nor read the form's eligibility.
        self.assertEqual(self.add(student, user=self.mentor).status_code, 403)
        self.assertEqual(self.as_user(self.mentor).get(url + 'eligibility/').status_code, 403)
        for user in (self.tutor, self.bde):
            with self.subTest(role=user.role):
                self.assertEqual(self.as_user(user).get(url).status_code, 403)
                self.assertEqual(self.add(student, user=user).status_code, 403)
                self.assertEqual(self.pay(allocation['id'], user=user).status_code, 403)
                self.assertEqual(self.as_user(user).get('/api/sales/additional-hours/').status_code, 403)
        self.assertIn(APIClient().get(url).status_code, (401, 403))
        # Their own student's hours: read and pay. Another mentor's student does not exist for them.
        overview = self.as_user(self.mentor).get(url).json()
        self.assertEqual((overview['can_create'], overview['allocations'][0]['can_manage'],
                          overview['allocations'][0]['can_record_payment']), (False, False, True))
        self.assertEqual(self.as_user(self.other_mentor).get(url).status_code, 404)
        self.assertEqual(self.as_user(self.other_mentor).get(f'/api/sales/additional-hours/{allocation["id"]}/').status_code, 404)
        self.assertEqual(self.pay(allocation['id'], user=self.other_mentor).status_code, 404)
        paid = self.pay(allocation['id']).json()['payment']
        self.assertEqual(self.as_user(self.mentor).get(paid['proof_url']).status_code, 200)
        self.assertEqual(self.as_user(self.other_mentor).get(paid['proof_url']).status_code, 404)
        # The list across students is the administrator's whole, a mentor's own only.
        self.assertEqual(self.as_user(self.mentor).get('/api/sales/additional-hours/').json()['count'], 1)
        self.assertEqual(self.as_user(self.other_mentor).get('/api/sales/additional-hours/').json()['count'], 0)
        self.assertTrue(self.as_user(self.admin).get(url).json()['can_create'])

    def test_the_pending_list_filters_and_totals(self):
        first, second = self.enroll(), self.enroll()
        Student.objects.filter(pk=second.pk).update(mentor=self.other_mentor)
        pending = self.added(first)
        partial = self.added(first, hours='2', amount='100')
        settled = self.added(second, hours='1', amount='40')
        self.pay(partial['id'], amount='30')
        self.pay(settled['id'], user=self.admin, amount='40')
        admin = self.as_user(self.admin)

        def references(query=''):
            return [row['reference'] for row in admin.get(f'/api/sales/additional-hours/{query}').json()['results']]
        self.assertEqual(len(references()), 3)
        self.assertEqual(references('?status=PENDING'), [pending['reference']])
        self.assertEqual(references('?status=PARTIALLY_PAID'), [partial['reference']])
        self.assertEqual(references('?status=PAID'), [settled['reference']])
        self.assertEqual(sorted(references('?status=OPEN')), sorted([pending['reference'], partial['reference']]))
        self.assertEqual(len(references(f'?mentor={self.other_mentor.pk}')), 1)
        self.assertEqual(len(references(f'?student={first.pk}')), 2)
        totals = admin.get('/api/sales/additional-hours/').json()['summary']
        self.assertEqual((totals['hours_added'], totals['amount'], totals['received'], totals['outstanding'],
                          totals['payment_pending_hours']), ('6', '290', '70', '220', '5'))
        self.assertEqual(admin.get('/api/sales/additional-hours/?status=NOPE').status_code, 400)

    # --- kept apart from the plan ledger ------------------------------------

    def test_hours_and_their_payments_stay_out_of_every_regular_figure(self):
        student = self.enroll()
        now = timezone.now()
        span = (timezone.localdate() - timedelta(days=7), timezone.localdate())
        before = student_finance.finance(self.admin, student.pk)
        board_before = dashboard.dashboard(now, *span)
        history_before = student_finance.payment_history(self.admin, student.pk).count()
        allocation = self.added(student)
        self.pay(allocation['id'], amount='100')
        after = student_finance.finance(self.admin, student.pk)
        # Only the class quota moves (by the hours); every plan and money figure stays as it was.
        self.assertEqual({**after['summary'], 'class_quota': None}, {**before['summary'], 'class_quota': None})
        self.assertEqual((before['summary']['class_quota'], after['summary']['class_quota']), ('10', '13'))
        self.assertEqual((after['purchases'], after['blockers'], after['autopay']),
                         (before['purchases'], before['blockers'], before['autopay']))
        self.assertEqual(dashboard.dashboard(now, *span), board_before)
        self.assertEqual(student_finance.payment_history(self.admin, student.pk).count(), history_before)
        self.assertEqual(Payment.objects.filter(sale__student=student).count(), 1)
        # The hourly enrolment-sheet sync never reads a payment-managed student, so it can never reset them.
        self.assertNotIn(student.student_code.upper(), quota_sync._students_by_code())

    # --- the database's own rules -------------------------------------------

    def test_history_is_kept_by_the_database(self):
        student = self.enroll()
        allocation = AdditionalHoursAllocation.objects.get(pk=self.added(student)['id'])
        payment = AdditionalHoursPayment.objects.get(pk=self.pay(allocation.pk).json()['payment']['id'])
        changes = (
            lambda: AdditionalHoursAllocation.objects.filter(pk=allocation.pk).update(hours=D(5)),
            lambda: AdditionalHoursAllocation.objects.filter(pk=allocation.pk).update(reason='Rewritten.'),
            lambda: AdditionalHoursAllocation.objects.filter(pk=allocation.pk).update(amount=D(10)),  # Below the 50 paid.
            lambda: AdditionalHoursAllocation.objects.filter(pk=allocation.pk).delete(),
            lambda: AdditionalHoursPayment.objects.filter(pk=payment.pk).update(amount=D(10)),
            lambda: AdditionalHoursPayment.objects.filter(pk=payment.pk).delete(),
        )
        for change in changes:
            with self.subTest(change=change), self.assertRaises(DatabaseError), transaction.atomic():
                change()
        other = self.enroll()
        with self.assertRaises(DatabaseError), transaction.atomic():
            # Another student's plan.
            AdditionalHoursAllocation.objects.create(
                reference='AH-999999', request_id=uuid.uuid4(), student=student, purchase=self.plan(other), hours=D(1),
                amount=D(10), due_date=timezone.localdate(), reason='x', quota_before=D(13), created_by=self.admin)


@override_settings(**SETTINGS)
class AdditionalHoursCommitTests(QuoteTestCase, TransactionTestCase):
    """What the database checks at commit, and requests racing each other. A superuser acts: a flush drops role grants."""

    def setUp(self):
        self.make_world()
        self.boss = user_account('hours_boss', 'ADMIN', is_superuser=True)
        services.create_pricing_version(self.admin, {'currency': 'AED', 'standard_fee': D(60), 'offer_fee': D(50),
                                                    'single_payment_percent': D(0), 'single_payment_plan_types': [], 'note': ''})
        self.tmp = tempfile.TemporaryDirectory()
        self.storage = override_settings(MEDIA_ROOT=self.tmp.name)
        self.storage.enable(); self.addCleanup(self.storage.disable); self.addCleanup(self.tmp.cleanup)
        lead = lead_of(self.bde, 'Commit Child', '506000001')
        lead.parent_email = 'commit-parent@hours.test'; lead.save(update_fields=['parent_email'])
        quotes.create_quote(self.bde, {'collection_mode': 'FULL', 'syllabus': self.bridge.pk, 'revision': 1,
                                       'plan_type': 'BRIDGE_COURSE', 'lead': lead.pk})
        payments.start_sale(self.boss, lead.pk, {'kind': 'NEW'})
        payments.collect(self.boss, lead.pk, {
            'request_id': uuid.uuid4(), 'purpose': 'TUITION', 'method': 'TRANSFER', 'classes': D(10), 'amount': D(500),
            'collection_mode': 'FULL', 'payment_date': timezone.localdate(), 'received_confirmed': True, 'proof': receipt()})
        self.student = Student.objects.get()
        self.purchase = Purchase.objects.get(student=self.student)

    def data(self, **extra):
        return {'request_id': uuid.uuid4(), 'purchase': self.purchase.pk, 'hours': D(3), 'amount': D(150),
                'due_date': timezone.localdate() + timedelta(days=7), 'reason': 'Racing.', 'confirm_duplicate': True, **extra}

    def payment(self, amount):
        return {'request_id': uuid.uuid4(), 'amount': D(amount), 'method': 'TRANSFER', 'payment_date': timezone.localdate(),
                'received_confirmed': True, 'proof': receipt(), 'transaction_reference': '', 'confirm_duplicate': True}

    def parallel(self, *calls):
        barrier = Barrier(len(calls))

        def run(call):
            close_old_connections()
            try:
                barrier.wait(timeout=15)
                return call()
            except services.SalesError as exc:
                return exc.code
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=len(calls)) as pool:
            return list(pool.map(run, calls))

    def test_hours_reach_the_quota_exactly_once_or_not_at_all(self):
        common = dict(student=self.student, purchase=self.purchase, amount=D(10), due_date=timezone.localdate(),
                      reason='x', created_by=self.boss)
        # An allocation whose hours never reached the quota does not commit...
        with self.assertRaises(DatabaseError), transaction.atomic():
            AdditionalHoursAllocation.objects.create(reference='AH-900001', request_id=uuid.uuid4(), hours=D(2),
                                                     quota_before=D(10), **common)
        # ...nor one credited twice.
        with self.assertRaises(DatabaseError), transaction.atomic():
            Student.objects.filter(pk=self.student.pk).update(total_class_quota=D(14))
            AdditionalHoursAllocation.objects.create(reference='AH-900002', request_id=uuid.uuid4(), hours=D(2),
                                                     quota_before=D(10), **common)
        self.assertEqual((Student.objects.get().total_class_quota, AdditionalHoursAllocation.objects.count()), (D(10), 0))
        allocation, _created = additional_hours.create(self.boss, self.student.pk, self.data())
        # Withdrawn hours must leave the quota exactly once too.
        with self.assertRaises(DatabaseError), transaction.atomic():
            AdditionalHoursAllocation.objects.filter(pk=allocation.pk).update(
                withdrawn_at=timezone.now(), withdrawn_by=self.boss, withdraw_reason='x', withdrawn_quota_before=D(13))
        self.assertEqual(Student.objects.get().total_class_quota, D(13))

    def test_payments_never_add_up_to_more_than_the_amount(self):
        allocation, _created = additional_hours.create(self.boss, self.student.pk, self.data())
        with self.assertRaises(DatabaseError), transaction.atomic():
            for _ in range(2):
                AdditionalHoursPayment.objects.create(
                    request_id=uuid.uuid4(), allocation=allocation, amount=D(100), method='TRANSFER',
                    payment_date=timezone.localdate(), received_confirmed=True, proof='additional-hours-proofs/x.png',
                    recorded_by=self.boss)
        self.assertFalse(AdditionalHoursPayment.objects.exists())

    def test_simultaneous_payments_cannot_overpay(self):
        allocation, _created = additional_hours.create(self.boss, self.student.pk, self.data())
        results = self.parallel(lambda: additional_hours.record_payment(self.boss, allocation.pk, self.payment(100))[0].pk,
                                lambda: additional_hours.record_payment(self.boss, allocation.pk, self.payment(100))[0].pk)
        self.assertEqual(sorted(str(value) for value in results if value == 'EXCEEDS_OUTSTANDING'), ['EXCEEDS_OUTSTANDING'], results)
        self.assertEqual(additional_hours.paid_amount(allocation), D(100))
        self.assertEqual(Student.objects.get().total_class_quota, D(13))

    def test_simultaneous_allocations_both_reach_the_quota(self):
        results = self.parallel(lambda: additional_hours.create(self.boss, self.student.pk, self.data())[0].pk,
                                lambda: additional_hours.create(self.boss, self.student.pk, self.data(hours=D(2)))[0].pk)
        self.assertEqual(len(set(results)), 2, results)
        self.assertEqual(Student.objects.get().total_class_quota, D(15))
        self.assertTrue(additional_hours.reconciliation(Student.objects.get())['reconciles'])
