"""Idempotent academic enrollment from a verified initial tuition allocation."""
import re

from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone

from invitations.models import Invitation
from students.models import Student
from .payment_models import SalesSequence
from .payments import audit, received, refusal


def next_number(name):
    # Also serializes first-row creation; row locks alone cannot lock an absent counter.
    with connection.cursor() as cursor:
        cursor.execute('SELECT pg_advisory_xact_lock(hashtext(%s), hashtext(%s))', ['eduport-sales-sequence', name])
    sequence, _ = SalesSequence.objects.get_or_create(name=name)
    sequence = SalesSequence.objects.select_for_update().get(pk=name)
    floor = 0
    if name == 'EDP':
        codes = list(Student.objects.filter(student_code__iregex=r'^EDP[0-9]+$').values_list('student_code', flat=True))
        codes += list(Invitation.objects.filter(extra_data__student_code__iregex=r'^EDP[0-9]+$').values_list('extra_data__student_code', flat=True))
        floor = max([settings.SALES_EDP_MIN_NUMBER, *[int(re.fullmatch(r'EDP([0-9]+)', code, re.I)[1]) for code in codes]])
    sequence.value = max(sequence.value, floor) + 1
    sequence.save(update_fields=['value'])
    return sequence.value


def enroll(sale, purchase, actor, request=None):
    if sale.student_id:
        return sale.student
    paid = received(sale)
    if paid['classes'] <= 0:
        raise refusal('TUITION_REQUIRED', 'Only verified tuition can enroll a student.')
    from invitations.credentials import new_account, create_invitation
    from .account_models import StudentAccount
    lead = sale.enquiry
    # The student account owns the child's identity (locked once money arrived).
    student_account = StudentAccount.objects.select_for_update().get(pk=sale.account_id)
    code = f'EDP{next_number("EDP"):05d}'
    account, password = new_account(code, student_account.student_name, actor)
    from bookings.models import DemoBooking, BookingStatus
    demo = (DemoBooking.objects.filter(lead=lead, assigned_tutor__isnull=False)
            .exclude(status__in=[BookingStatus.CANCELLED, BookingStatus.RESCHEDULED])
            .select_related('assigned_tutor').order_by('-slot__starts_at', '-created_at').first())
    student = Student.objects.create(
        profile=account, student_code=code, full_name=student_account.student_name,
        mobile_number=lead.phone_key, country=lead.country, school_name=lead.school_name,
        grade=lead.grade, syllabus=purchase.quote.revision.board, timezone=lead.student_timezone or None,
        admission_date=timezone.localdate(), total_class_quota=paid['classes'], quota_source='PAYMENTS',
        tutor=demo.assigned_tutor if demo else None, meet_link=demo.tutor_meet_link if demo else None,
    )
    # The account keeps its SA reference and gains the Student/EDP ID; it is
    # linked first so the sale's student always equals its account's student.
    student_account.student = student
    student_account.save(update_fields=['student'])
    sale.student = student
    sale.enrolled_at = timezone.now()
    sale.save(update_fields=['student', 'enrolled_at'])
    purchase.student = student
    purchase.save(update_fields=['student'])
    create_invitation(student, account, password, actor,
                      extra_data={'source': 'INITIAL_SALE', 'enquiry_id': str(lead.pk), 'sale_id': str(sale.pk)})
    audit('student.enrolled', sale, actor, request, student_code=student.student_code,
          quote=str(purchase.quote_id), purchased_classes=str(purchase.classes), paid_classes=str(paid['classes']))
    # Same Customer after enrollment; its labels gain the EDP ID (legacy ones only metadata).
    from .payment_models import StripeCustomer
    from .customers import sync_labels
    rows = list(StripeCustomer.objects.filter(account_id=sale.account_id, customer_id__isnull=False).values_list('pk', flat=True))
    StripeCustomer.objects.filter(pk__in=rows).update(student_metadata_synced=False)
    transaction.on_commit(lambda: [sync_labels(row) for row in rows])
    return student
