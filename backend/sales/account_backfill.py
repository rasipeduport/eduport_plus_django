"""Student accounts for financial records created before student accounts existed.

``plan`` is read-only. ``apply`` (run by migration 0017) creates exactly what the
plan reports. Both take an app registry so they run against the historical
schema: before migration 0016 the Customer mapping is keyed by ``enquiry``,
afterwards by ``legacy_enquiry``.

Rules: one account per enquiry with a sale or a Stripe Customer; one guardian
per enquiry from its own parent details. Children sharing a phone or email are
reported as possible families and never linked automatically. Stripe IDs,
payments and subscriptions are not touched.
"""
import uuid
from collections import defaultdict

NAMESPACE = uuid.UUID('6f0c7a52-4b1e-4d47-9c0f-5a8e2b1d3c90')


class BackfillConflict(Exception):
    pass


def deterministic(kind, lead_id):
    return uuid.uuid5(NAMESPACE, f'{kind}:{lead_id}')


def _customer_lead_field(StripeCustomer):
    names = {field.name for field in StripeCustomer._meta.get_fields()}
    return 'legacy_enquiry' if 'legacy_enquiry' in names else 'enquiry'


def plan(apps):
    Lead = apps.get_model('bookings', 'Lead')
    Sale = apps.get_model('sales', 'Sale')
    Payment = apps.get_model('sales', 'Payment')
    StripeCustomer = apps.get_model('sales', 'StripeCustomer')
    lead_field = _customer_lead_field(StripeCustomer)
    accounts_exist = 'studentaccount' in {model._meta.model_name for model in apps.get_app_config('sales').get_models()}
    StudentAccount = apps.get_model('sales', 'StudentAccount') if accounts_exist else None

    customers = defaultdict(list)
    for row in StripeCustomer.objects.all():
        customers[getattr(row, f'{lead_field}_id')].append(row)
    sales = {sale.enquiry_id: sale for sale in Sale.objects.select_related('student')}
    lead_ids = set(sales) | {lead_id for lead_id in customers if lead_id}
    rows, problems, notices = [], [], []
    seen_students = {}
    for lead in Lead.objects.filter(pk__in=lead_ids).order_by('created_at', 'id'):
        sale = sales.get(lead.pk)
        existing = StudentAccount.objects.filter(origin_lead_id=lead.pk).first() if StudentAccount else None
        student = sale.student if sale and sale.student_id else None
        name = ' '.join((student.full_name if student else lead.student_name).split())
        if student and ' '.join(student.full_name.split()) != ' '.join(lead.student_name.split()):
            notices.append(f'Enquiry {lead.pk}: enrolled name differs from the enquiry name; the enrolled name is kept.')
        if student:
            if student.pk in seen_students:
                problems.append(f'Student {student.student_code} belongs to two enquiries ({seen_students[student.pk]} and {lead.pk}).')
            seen_students[student.pk] = lead.pk
            if StudentAccount and StudentAccount.objects.filter(student_id=student.pk).exclude(origin_lead_id=lead.pk).exists():
                problems.append(f'Student {student.student_code} already has another student account.')
        payments = list(Payment.objects.filter(sale=sale).order_by('created_at')) if sale else []
        mapped = customers.get(lead.pk, [])
        if len(mapped) > 1:
            problems.append(f'Enquiry {lead.pk} has {len(mapped)} Customer mappings.')
        for row in mapped:
            if not row.customer_id:
                notices.append(f'Enquiry {lead.pk}: Customer creation was started but never confirmed; it stays pending.')
        if sale is None:
            notices.append(f'Enquiry {lead.pk}: Stripe Customer without a sale.')
        rows.append({
            'lead': lead, 'sale': sale, 'student': student, 'student_name': name, 'existing': existing,
            'customers': mapped, 'payments': len(payments),
            'pending_payments': sum(1 for row in payments if row.status == 'PENDING'),
            'locked_at': payments[0].created_at if payments else None,
            'guardian': {'full_name': ' '.join(lead.parent_name.split()) or 'Parent',
                         'email': (lead.parent_email or (sale.parent_email if sale else '') or '').strip().lower(),
                         'phone': lead.phone_key or ''},
            'started_at': sale.created_at if sale else lead.created_at,
        })
    rows.sort(key=lambda row: (row['started_at'], str(row['lead'].pk)))
    families = defaultdict(list)
    for row in rows:
        if row['guardian']['phone']:
            families[('phone', row['guardian']['phone'])].append(row)
        if row['guardian']['email']:
            families[('email', row['guardian']['email'])].append(row)
    for (kind, _value), group in families.items():
        if len(group) > 1:
            notices.append(f'{len(group)} children share a parent {kind}: '
                           + ', '.join(row['student_name'] for row in group)
                           + '. Separate guardians are created; link the family explicitly in the Hub if it is one family.')
    return rows, problems, notices


def apply(apps, schema_editor=None):
    rows, problems, _notices = plan(apps)
    if problems:
        raise BackfillConflict('Student account backfill stopped; run backfill_student_accounts for the report: ' + '; '.join(problems))
    Sale = apps.get_model('sales', 'Sale')
    StripeCustomer = apps.get_model('sales', 'StripeCustomer')
    StudentAccount = apps.get_model('sales', 'StudentAccount')
    Guardian = apps.get_model('sales', 'Guardian')
    StudentGuardian = apps.get_model('sales', 'StudentGuardian')
    SalesSequence = apps.get_model('sales', 'SalesSequence')
    connection = schema_editor.connection if schema_editor else None
    if connection is None:
        from django.db import connection
    for row in rows:
        lead = row['lead']
        account = row['existing']
        if account is None:
            with connection.cursor() as cursor:
                cursor.execute('SELECT pg_advisory_xact_lock(hashtext(%s), hashtext(%s))', ['eduport-sales-sequence', 'STUDENT_ACCOUNT'])
            sequence, _ = SalesSequence.objects.get_or_create(name='STUDENT_ACCOUNT')
            sequence.value += 1
            sequence.save(update_fields=['value'])
            account = StudentAccount.objects.create(
                id=deterministic('account', lead.pk), reference=f'SA-{sequence.value:06d}', origin_lead_id=lead.pk,
                student_id=row['student'].pk if row['student'] else None, student_name=row['student_name'],
                identity_locked_at=row['locked_at'], created_at=row['started_at'])
            guardian = Guardian.objects.create(id=deterministic('guardian', lead.pk), **row['guardian'], created_at=row['started_at'])
            StudentGuardian.objects.create(id=deterministic('guardian-link', lead.pk), account_id=account.pk, guardian_id=guardian.pk,
                                           relationship='PARENT', is_billing_contact=True, basis='BACKFILL', linked_at=row['started_at'])
        if row['sale'] is not None:
            Sale.objects.filter(pk=row['sale'].pk, account__isnull=True).update(account_id=account.pk)
        for customer in row['customers']:
            StripeCustomer.objects.filter(pk=customer.pk, account__isnull=True).update(account_id=account.pk)


REVERSE_SQL = [
    'SET CONSTRAINTS ALL IMMEDIATE',
    'ALTER TABLE sales_sale DISABLE TRIGGER sales_initial_sale_fixed',
    'ALTER TABLE sales_stripecustomer DISABLE TRIGGER sales_customer_origin_fixed',
    'ALTER TABLE sales_studentaccount DISABLE TRIGGER sales_student_account_fixed',
    'ALTER TABLE sales_studentguardian DISABLE TRIGGER sales_student_guardian_fixed',
    'UPDATE sales_sale SET account_id = NULL WHERE account_id IS NOT NULL',
    "UPDATE sales_stripecustomer SET account_id = NULL, stripe_account_id = '' WHERE account_id IS NOT NULL",
    'DELETE FROM sales_studentguardian',
    'DELETE FROM sales_guardian',
    'DELETE FROM sales_studentaccount',
    "DELETE FROM sales_salessequence WHERE name = 'STUDENT_ACCOUNT'",
    'SET CONSTRAINTS ALL IMMEDIATE',
    'ALTER TABLE sales_sale ENABLE TRIGGER sales_initial_sale_fixed',
    'ALTER TABLE sales_stripecustomer ENABLE TRIGGER sales_customer_origin_fixed',
    'ALTER TABLE sales_studentaccount ENABLE TRIGGER sales_student_account_fixed',
    'ALTER TABLE sales_studentguardian ENABLE TRIGGER sales_student_guardian_fixed',
]


def unapply(apps, schema_editor=None):
    """Remove exactly what apply created, only while nothing newer depends on it."""
    StripeCustomer = apps.get_model('sales', 'StripeCustomer')
    StudentAccount = apps.get_model('sales', 'StudentAccount')
    StudentIdentityCorrection = apps.get_model('sales', 'StudentIdentityCorrection')
    if (StripeCustomer.objects.filter(label_format='STUDENT').exists()
            or StudentAccount.objects.exclude(guardian_links__basis='BACKFILL').exists()
            or StudentIdentityCorrection.objects.exists()):
        raise BackfillConflict('Student accounts, Customers or corrections created after the backfill exist; '
                               'the backfill cannot be reversed without losing them.')
    connection = schema_editor.connection if schema_editor else None
    if connection is None:
        from django.db import connection
    with connection.cursor() as cursor:
        for statement in REVERSE_SQL:
            cursor.execute(statement)
