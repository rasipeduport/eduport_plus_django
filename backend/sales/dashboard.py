"""
The administrators' Sales Dashboard (GET /api/sales/dashboard/): Eduport
Plus sales and collections at a glance. Over a span of Indian dates, what was
sold and what was received, how it was sold and collected, how far the leads
that came in converted, and each BDE's share; then, whatever the span, the
balances still outstanding, the Autopay agreements and what awaits an
administrator.

Everything is read from the sale, purchase, payment and Autopay records as
they stand -- nothing is stored or estimated here -- with the Finance tab's
own definitions (sales.student_finance), so its figures add up to the
students' Finance tabs:

- a sale is a purchase on an enrolled student's account: the first sale,
  dated when its first verified payment enrolled the student, or an additional
  purchase, dated when it was added; it is worth its agreed amount;
- a payment counts as received as payments.received_payments counts it,
  dated by its payment date (the receipt's, or the day Stripe confirmed it),
  its type as student_finance.payment_type names it;
- a purchase's balance and payment status are sale_summary's.

Refunds are shown beside what was received, never netted from it, as the
Finance tab shows them until a refund policy is approved. Students managed only
in the enrolment sheet have no sales here.
"""
from collections import Counter, defaultdict
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db.models import Exists, F, OuterRef, Q, Sum

from bookings import lead_admin
from bookings.models import Lead
from bookings.scheduling import BOOKING_TIMEZONE, BOOKING_TIMEZONE_NAME

from . import autopay, payments
from .additional_purchases import payment_status
from .autopay_models import AutopayAgreement, AutopayInstallment
from .ledger_models import Dispute, Refund, StripeReviewItem
from .models import Quote
from .payment_models import INITIAL_KINDS, Payment, PaymentMethod, PaymentStatus, Purchase, Sale, SaleKind
from .pricing import plain
from .student_finance import COUNTED_REFUNDS, payment_type

ZERO = Decimal('0')
OUTSTANDING_ROWS = 8
RECENT_ROWS = 8
# Autopay collections due within this many days are the ones coming up.
DUE_DAYS = 30
# A span of up to a month is drawn day by day, up to six months week by week, longer month by month.
DAILY_DAYS = 31
WEEKLY_DAYS = 186
FINISHED_AGREEMENTS = ('COMPLETED', 'CANCELLED')
# Installments that will not be collected: paid, cancelled with their agreement, or written off in Stripe.
CLOSED_INSTALLMENTS = ('PAID', 'CANCELLED', 'VOID', 'UNCOLLECTIBLE')
PAYMENT_TYPES = ('INITIAL', 'TOKEN', 'AUTOPAY_INITIAL', 'BALANCE', 'AUTOPAY_INSTALLMENT', 'ADDITIONAL')
OPEN_STATUSES = ('PARTIALLY_PAID', 'UNPAID', 'LINK_PENDING', 'AUTOPAY')
PLANS = ('FULL', 'PARTIAL', 'AUTOPAY')


def _indian_date(instant):
    return instant.astimezone(BOOKING_TIMEZONE).date()


def _on_dates(field, date_from, date_to):
    """``field`` (an instant) on the Indian dates ``date_from`` to ``date_to``, inclusive."""
    return Q(**{
        f'{field}__gte': datetime.combine(date_from, time.min, tzinfo=BOOKING_TIMEZONE),
        f'{field}__lt': datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=BOOKING_TIMEZONE),
    })


def _total(values):
    return sum(values, ZERO)


def _student(sale):
    student = sale.student
    if student is None:
        return None
    return {'id': str(student.pk), 'full_name': student.full_name, 'student_code': student.student_code}


def _purchases():
    """
    Every sale on an enrolled student's account -- the sales student_finance
    collects -- with its purchase, what has been received on it and where its
    payment stands, as sale_summary works them out one sale at a time.
    """
    enrolled = Sale.objects.filter(student__isnull=False)
    bought = {purchase.sale_id: purchase for purchase in
              Purchase.objects.filter(sale__in=enrolled, is_initial=True).select_related('quote__revision')}
    paid = dict(payments.received_payments(Payment.objects.filter(sale__in=enrolled))
                .values('sale_id').annotate(amount=Sum('amount')).values_list('sale_id', 'amount'))
    on_autopay = set(AutopayAgreement.objects.filter(purchase__sale__in=enrolled).values_list('purchase__sale_id', flat=True))
    link_pending = set(Payment.objects.filter(sale__in=enrolled, status=PaymentStatus.PENDING).values_list('sale_id', flat=True))
    rows = []
    for sale in enrolled.select_related('student', 'original_bde').order_by('created_at', 'id'):
        purchase = bought.get(sale.pk)
        if purchase is None:
            continue
        received = paid.get(sale.pk) or ZERO
        rows.append({
            'sale': sale, 'purchase': purchase, 'sold_on': _indian_date(sale.enrolled_at or sale.created_at),
            'plan': 'AUTOPAY' if sale.pk in on_autopay else purchase.collection_mode,
            'paid': received, 'outstanding': purchase.amount - received,
            'status': payment_status(received >= purchase.amount, sale.pk in on_autopay, sale.pk in link_pending, received),
        })
    return rows


def _received(date_from, date_to):
    """The payments received on the span's dates, each with its type."""
    rows = list(payments.received_payments(Payment.objects.filter(payment_date__gte=date_from, payment_date__lte=date_to))
                .select_related('sale'))
    installments = {row.payment_id: row for row in AutopayInstallment.objects.filter(payment__in=rows)}
    return [(row, payment_type(row, installments.get(row.pk))) for row in rows]


def _unit(date_from, date_to):
    days = (date_to - date_from).days + 1
    return 'day' if days <= DAILY_DAYS else 'week' if days <= WEEKLY_DAYS else 'month'


def _bucket(day, unit):
    """The first day of the day, week (from Monday) or month ``day`` falls in."""
    if unit == 'day':
        return day
    return day - timedelta(days=day.weekday()) if unit == 'week' else day.replace(day=1)


def _next(start, unit):
    if unit == 'day':
        return start + timedelta(days=1)
    return start + timedelta(days=7) if unit == 'week' else (start.replace(day=28) + timedelta(days=4)).replace(day=1)


def _trend(date_from, date_to, sold, received):
    """What was sold and received, day by day, week by week or month by month; each bucket cut to the span."""
    unit = _unit(date_from, date_to)
    sales, collected = defaultdict(list), defaultdict(list)
    for row in sold:
        sales[_bucket(row['sold_on'], unit)].append(row['purchase'].amount)
    for payment, _type in received:
        collected[_bucket(payment.payment_date, unit)].append(payment.amount)
    buckets, start = [], _bucket(date_from, unit)
    while start <= date_to:
        following = _next(start, unit)
        buckets.append({
            'from': max(start, date_from).isoformat(), 'to': min(following - timedelta(days=1), date_to).isoformat(),
            'sales_count': len(sales[start]), 'sales_value': plain(_total(sales[start])),
            'payments': len(collected[start]), 'collected': plain(_total(collected[start])),
        })
        start = following
    return {'unit': unit, 'buckets': buckets}


def _mix(sold):
    """The span's sales by kind (a first sale or an additional purchase) and by how each is collected."""
    def part(rows):
        return {'count': len(rows), 'value': plain(_total(row['purchase'].amount for row in rows))}
    return {
        'kinds': [{'kind': 'INITIAL', **part([row for row in sold if row['sale'].kind in INITIAL_KINDS])},
                  {'kind': 'ADDITIONAL', **part([row for row in sold if row['sale'].kind == SaleKind.ADDITIONAL])}],
        'plans': [{'plan': plan, **part([row for row in sold if row['plan'] == plan])} for plan in PLANS],
    }


def _collections(received):
    """What was received on the span's dates, by payment type and by method."""
    def part(rows):
        return {'count': len(rows), 'amount': plain(_total(payment.amount for payment, _type in rows))}
    return {
        'types': [{'type': kind, **part([row for row in received if row[1] == kind])} for kind in PAYMENT_TYPES],
        'methods': [{'method': method.value, 'label': method.label,
                     **part([row for row in received if row[0].method == method.value])} for method in PaymentMethod],
    }


def _leads(date_from, date_to):
    """
    The leads that came in on the span's dates, each with its BDE and how far
    it went: quoted, a sale started, enrolled (lead_status's ENROLLED: its sale
    enrolled a student).
    """
    return list(lead_admin.received_between(Lead.objects.all(), date_from, date_to).annotate(
        quoted=Exists(Quote.objects.filter(lead_id=OuterRef('pk'))),
        sale_started=Exists(Sale.objects.filter(enquiry_id=OuterRef('pk'))),
        enrolled=Exists(Sale.objects.filter(enquiry_id=OuterRef('pk'), student__isnull=False)),
    ).values('owner_bde_id', 'quoted', 'sale_started', 'enrolled'))


def _funnel(leads):
    return [
        {'stage': 'LEADS', 'label': 'Leads', 'count': len(leads)},
        {'stage': 'QUOTED', 'label': 'Quoted', 'count': sum(1 for lead in leads if lead['quoted'])},
        {'stage': 'SALE_STARTED', 'label': 'Sale started', 'count': sum(1 for lead in leads if lead['sale_started'])},
        {'stage': 'ENROLLED', 'label': 'Enrolled', 'count': sum(1 for lead in leads if lead['enrolled'])},
    ]


def _bdes(leads, sold, received):
    """
    Each BDE's share: the leads they own that came in on the span's dates and
    how many of those enrolled, the first sales they made that enrolled a
    student on those dates, and what was received then on any first sale of
    theirs. Additional purchases are a mentor's, so no BDE's.
    """
    people = {person['id']: person for person in lead_admin.bde_options()}
    stats = defaultdict(lambda: {'leads': 0, 'enrolled_leads': 0, 'enrollments': 0, 'sales_value': ZERO, 'collected': ZERO})
    for lead in leads:
        if lead['owner_bde_id']:
            entry = stats[str(lead['owner_bde_id'])]
            entry['leads'] += 1
            entry['enrolled_leads'] += int(lead['enrolled'])
    for row in sold:
        sale = row['sale']
        if sale.kind in INITIAL_KINDS:
            entry = stats[str(sale.original_bde_id)]
            entry['enrollments'] += 1
            entry['sales_value'] += row['purchase'].amount
    for payment, _type in received:
        if payment.sale.kind in INITIAL_KINDS:
            stats[str(payment.sale.original_bde_id)]['collected'] += payment.amount
    # A lead's owner listed nowhere else: someone since given another role, with no lead of their own any more.
    for user in get_user_model().objects.filter(pk__in=set(stats) - set(people)):
        people[str(user.pk)] = lead_admin._person(user)
    rows = []
    for person_id, person in people.items():
        entry = stats.get(person_id)
        if entry is None and not person.get('assignable'):
            continue
        entry = entry or stats.default_factory()
        rows.append({'id': person_id, 'full_name': person['full_name'], 'leads': entry['leads'],
                     'enrolled_leads': entry['enrolled_leads'], 'enrollments': entry['enrollments'],
                     'sales_value': plain(entry['sales_value']), 'collected': plain(entry['collected'])})
    rows.sort(key=lambda row: (-Decimal(row['sales_value']), -row['enrollments'], -row['leads'], row['full_name'].lower()))
    return rows


def _outstanding(rows):
    """The balances still to be received, as things stand: by payment status, and the largest first."""
    owing = sorted((row for row in rows if row['outstanding'] > 0), key=lambda row: (-row['outstanding'], row['sale'].created_at))
    return {
        'total': plain(_total(row['outstanding'] for row in owing)), 'count': len(owing),
        'by_status': [{'status': status, 'count': sum(1 for row in owing if row['status'] == status),
                       'amount': plain(_total(row['outstanding'] for row in owing if row['status'] == status))}
                      for status in OPEN_STATUSES],
        'rows': [{
            'sale_id': str(row['sale'].pk), 'kind': row['sale'].kind, 'student': _student(row['sale']),
            'reference': row['purchase'].quote.reference, 'syllabus': row['purchase'].quote.revision.title,
            'plan': row['plan'], 'sold_on': row['sold_on'].isoformat(), 'package_amount': plain(row['purchase'].amount),
            'paid_amount': plain(row['paid']), 'outstanding_amount': plain(row['outstanding']), 'payment_status': row['status'],
        } for row in owing[:OUTSTANDING_ROWS]],
    }


def _autopay(now, received):
    """Every Autopay agreement by state, what Autopay collected on the span's dates, what falls due next, and what needs attention."""
    agreements = list(AutopayAgreement.objects.select_related('purchase__sale__student', 'purchase__quote', 'created_by')
                      .order_by('created_at', 'id'))
    counts = Counter(agreement.status if agreement.status in ('ACTIVE', *FINISHED_AGREEMENTS) else 'SETTING_UP'
                     for agreement in agreements)
    attention = []
    for agreement in agreements:
        if agreement.status in FINISHED_AGREEMENTS:
            continue
        data = autopay.agreement_data(agreement)
        if data['attention_status']:
            attention.append({
                'id': data['id'], 'sale_id': str(agreement.purchase.sale_id), 'student': _student(agreement.purchase.sale),
                'reference': agreement.purchase.quote.reference, 'status': data['status'],
                'attention_status': data['attention_status'], 'next_collection_at': data['next_collection_at'],
                'remaining_amount': data['remaining_amount'],
            })
    due = AutopayInstallment.objects.filter(
        position__gt=0, due_at__gt=now, due_at__lte=now + timedelta(days=DUE_DAYS),
    ).exclude(status__in=CLOSED_INSTALLMENTS).exclude(agreement__status__in=FINISHED_AGREEMENTS)
    collected = [payment for payment, kind in received if kind == 'AUTOPAY_INSTALLMENT']
    return {
        'counts': {status: counts[status] for status in ('ACTIVE', 'SETTING_UP', 'COMPLETED', 'CANCELLED')},
        'collected': {'count': len(collected), 'amount': plain(_total(payment.amount for payment in collected))},
        'due': {'days': DUE_DAYS, 'count': due.count(), 'amount': plain(due.aggregate(n=Sum('amount'))['n'] or ZERO)},
        'attention': attention,
    }


def _pending():
    """What awaits an administrator now: unpaid links, unattributed Stripe activity and open disputes."""
    links = Payment.objects.filter(status=PaymentStatus.PENDING)
    return {
        'links': {'count': links.count(), 'amount': plain(links.aggregate(n=Sum('amount'))['n'] or ZERO),
                  'before_enrollment': links.filter(sale__student__isnull=True).count()},
        'stripe_review': StripeReviewItem.objects.filter(status='OPEN').count(),
        'disputes': Dispute.objects.filter(closed_at__isnull=True).count(),
    }


def _recent():
    """The latest payments received, whatever the span."""
    rows = list(payments.received_payments(Payment.objects.all()).select_related('sale__student', 'sale__account')
                .order_by(F('verified_at').desc(nulls_last=True), '-created_at')[:RECENT_ROWS])
    installments = {row.payment_id: row for row in AutopayInstallment.objects.filter(payment__in=rows)}
    data = []
    for row in rows:
        installment = installments.get(row.pk)
        data.append({
            'id': str(row.pk), 'sale_id': str(row.sale_id), 'student': _student(row.sale),
            'student_name': row.sale.student.full_name if row.sale.student else row.sale.account.student_name,
            'payment_type': payment_type(row, installment), 'method': row.method,
            'method_label': 'Stripe · Autopay' if installment and installment.position > 0 else row.get_method_display(),
            'amount': plain(row.amount), 'payment_date': row.payment_date.isoformat(),
            'verified_at': row.verified_at.isoformat() if row.verified_at else None,
        })
    return data


def dashboard(now, date_from, date_to):
    """The dashboard for the Indian dates ``date_from`` to ``date_to``, inclusive."""
    purchases = _purchases()
    sold = [row for row in purchases if date_from <= row['sold_on'] <= date_to]
    received = _received(date_from, date_to)
    leads = _leads(date_from, date_to)
    refunded = Refund.objects.filter(_on_dates('stripe_created_at', date_from, date_to), status__in=COUNTED_REFUNDS)
    outstanding = _outstanding(purchases)
    return {
        'timezone': BOOKING_TIMEZONE_NAME,
        'currency': 'AED',
        'range': {'from': date_from.isoformat(), 'to': date_to.isoformat()},
        'summary': {
            'sales_count': len(sold), 'sales_value': plain(_total(row['purchase'].amount for row in sold)),
            'enrollments': sum(1 for row in sold if row['sale'].kind in INITIAL_KINDS),
            'additional_purchases': sum(1 for row in sold if row['sale'].kind == SaleKind.ADDITIONAL),
            'payments': len(received), 'collected': plain(_total(payment.amount for payment, _type in received)),
            'refunded': plain(refunded.aggregate(n=Sum('amount'))['n'] or ZERO),
            'outstanding': outstanding['total'], 'outstanding_purchases': outstanding['count'],
            'leads': len(leads), 'enrolled_leads': sum(1 for lead in leads if lead['enrolled']),
            'unassigned_leads': sum(1 for lead in leads if not lead['owner_bde_id']),
        },
        'trend': _trend(date_from, date_to, sold, received),
        'mix': _mix(sold),
        'collections': _collections(received),
        'funnel': _funnel(leads),
        'bdes': _bdes(leads, sold, received),
        'outstanding': outstanding,
        'autopay': _autopay(now, received),
        'pending': _pending(),
        'recent_payments': _recent(),
    }
