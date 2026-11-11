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
    lead = sale.enquiry
    code = f'EDP{next_number("EDP"):05d}'
    account, password = new_account(code, lead.student_name, actor)
    from bookings.models import DemoBooking, BookingStatus
    demo = (DemoBooking.objects.filter(lead=lead, assigned_tutor__isnull=False)
            .exclude(status__in=[BookingStatus.CANCELLED, BookingStatus.RESCHEDULED])
            .select_related('assigned_tutor').order_by('-slot__starts_at', '-created_at').first())
    student = Student.objects.create(
        profile=account, student_code=code, full_name=lead.student_name,
        mobile_number=lead.phone_key, country=lead.country, school_name=lead.school_name,
        grade=lead.grade, syllabus=purchase.quote.revision.board, timezone=lead.student_timezone or None,
        admission_date=timezone.localdate(), total_class_quota=paid['classes'], quota_source='PAYMENTS',
        tutor=demo.assigned_tutor if demo else None, meet_link=demo.tutor_meet_link if demo else None,
    )
    sale.student = student
    sale.enrolled_at = timezone.now()
    sale.save(update_fields=['student', 'enrolled_at'])
    purchase.student = student
    purchase.save(update_fields=['student'])
    create_invitation(student, account, password, actor,
                      extra_data={'source': 'INITIAL_SALE', 'enquiry_id': str(lead.pk), 'sale_id': str(sale.pk)})
    audit('student.enrolled', sale, actor, request, student_code=student.student_code,
          quote=str(purchase.quote_id), purchased_classes=str(purchase.classes), paid_classes=str(paid['classes']))
    # Keep the existing Stripe customer mapping after academic enrollment.
    from .stripe_gateway import sync_customer_metadata
    transaction.on_commit(lambda: sync_customer_metadata(lead.pk))
    return student
