"""
What the Tutor Earnings pages read -- the overview of every tutor, one tutor's
earnings (an administrator's view, or the tutor's own), their ledger, the
classes not counted yet and the earnings an administrator should review.
Every function here only reads: a page never writes an earning, a payment or
anything else (earnings.ledger writes earnings).

Amounts are rupees as text with two decimals ("27625.00"); units likewise
("46.50"). A period is one month (the first day of it) or every month (None):
earnings count in their entry's month -- an earning's is its class's
scheduled end, in India time -- and payments in their payment date's. What a
tutor is owed is always everything earned less everything paid, whatever the
period.
"""
from collections import defaultdict
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db.models import Count, Exists, F, OuterRef, Q, Sum
from django.utils import timezone

from bookings.models import CONDUCTED, BookingStatus, DemoBooking, DiagnosticBooking
from sessions.models import Session, SessionStatusChoices

from .eligibility import activated_at, eligible_bookings, eligible_sessions, is_eligible
from .models import (
    CURRENCY,
    UNIT_OF,
    ClassType,
    EarningEntry,
    EarningReview,
    EarningsSyncRun,
    EntryKind,
    TutorEarningsPricing,
    TutorPayment,
)
from .rates import RateBook, pricing
from .values import india_today, month_of

User = get_user_model()

ZERO = Decimal('0.00')
BOOKING_MODELS = ((ClassType.DIAGNOSTIC, DiagnosticBooking), (ClassType.DEMO, DemoBooking))


# ------------------------------------------------------------------- values

def money(value):
    return f'{Decimal(value or 0):.2f}'


def iso(moment):
    return moment.isoformat() if moment else None


def name_of(user):
    return (user.full_name or user.email) if user else None


def person(user):
    return {'id': str(user.pk), 'name': name_of(user)} if user else None


def month_key(month):
    return month.strftime('%Y-%m')


def next_month(month):
    return date(month.year + (month.month == 12), month.month % 12 + 1, 1)


def months_since_activation():
    """'YYYY-MM' of every month from the activation's to this one, newest first."""
    since = activated_at()
    if since is None:
        return []
    month, last, found = month_of(since), india_today().replace(day=1), []
    while month <= last:
        found.append(month_key(month))
        month = next_month(month)
    return found[::-1]


def status_block(admin=True):
    """
    Activation, pricing and the last sync run: what every earnings page shows
    at the top. A tutor reads when, not who started pricing or how the sync went.
    """
    started = pricing()
    run = EarningsSyncRun.objects.first()
    block = {
        'currency': CURRENCY,
        'activated_at': iso(activated_at()),
        'pricing': {'started_at': iso(started.started_at)} if started else None,
        'last_sync': {'started_at': iso(run.started_at), 'finished_at': iso(run.finished_at)} if run else None,
        'months': months_since_activation(),
    }
    if admin and started:
        block['pricing']['started_by'] = person(started.started_by)
    if admin and run:
        block['last_sync'].update(status=run.status, earned_count=run.earned_count, waiting_count=run.waiting_count)
    return block


def _period(entries, payments, month):
    if month is None:
        return entries, payments
    return entries.filter(month=month), payments.filter(paid_on__gte=month, paid_on__lt=next_month(month))


def _live_earnings(entries):
    """The earnings of ``entries`` that have not been reversed: the classes that count."""
    return entries.filter(kind=EntryKind.EARNING, reversal__isnull=True)


# ----------------------------------------------------------------- counting

def class_counts(entries, by=('tutor_id',)):
    """{key: {type: (classes, units)}} of the unreversed earnings of ``entries``, keyed by ``by``."""
    found = defaultdict(lambda: defaultdict(lambda: (0, ZERO)))
    rows = _live_earnings(entries).values(*by, 'class_type').annotate(classes=Count('id'), units=Sum('units'))
    for row in rows:
        key = tuple(row[name] for name in by)
        found[key if len(by) > 1 else key[0]][row['class_type']] = (row['classes'], row['units'] or ZERO)
    return found


def counts_block(counts):
    """The class counts of one tutor (or everyone) as served: diagnostic, demo, sessions, session hours, classes."""
    diagnostic = counts.get(ClassType.DIAGNOSTIC, (0, ZERO))[0]
    demo = counts.get(ClassType.DEMO, (0, ZERO))[0]
    sessions, hours = counts.get(ClassType.SESSION, (0, ZERO))
    return {
        'diagnostic': diagnostic, 'demo': demo, 'sessions': sessions, 'session_hours': money(hours),
        'classes': diagnostic + demo + sessions,
    }


def _sum_by(queryset, key, field='amount'):
    return {row[key]: row['total'] or ZERO for row in queryset.values(key).annotate(total=Sum(field))}


def balance_state(owed, earned_all, paid_all):
    if owed > 0:
        return 'pending'
    if owed < 0:
        return 'overpaid'
    return 'paid' if (earned_all or paid_all) else 'none'


# ----------------------------------------------------------------- overview

def tutor_accounts():
    """Every active tutor, and anyone with earnings or payments -- a deactivated tutor, or one who is a tutor no more."""
    ids = set(EarningEntry.objects.values_list('tutor_id', flat=True).distinct())
    ids |= set(TutorPayment.objects.values_list('tutor_id', flat=True).distinct())
    return User.objects.filter(Q(role='TUTOR', is_active=True) | Q(pk__in=ids)).order_by('full_name', 'email')


def overview(month=None, search='', balance='', rate='', now=None):
    """Every tutor's earnings for the period, what each is owed, and the totals (the Admin overview)."""
    now = now or timezone.now()
    entries, payments = EarningEntry.objects.all(), TutorPayment.objects.filter(voided_at__isnull=True)
    period_entries, period_payments = _period(entries, payments, month)
    earned_all, paid_all = _sum_by(entries, 'tutor_id'), _sum_by(payments, 'tutor_id')
    earned, paid = _sum_by(period_entries, 'tutor_id'), _sum_by(period_payments, 'tutor_id')
    counts = class_counts(period_entries)
    own_rates = RateBook.load().tutors_with_own_rates(now)

    rows = []
    for tutor in tutor_accounts():
        owed = earned_all.get(tutor.pk, ZERO) - paid_all.get(tutor.pk, ZERO)
        rows.append({
            'id': str(tutor.pk),
            'name': name_of(tutor),
            'email': tutor.email,
            'active': tutor.is_active and tutor.role == 'TUTOR',
            **counts_block(counts.get(tutor.pk, {})),
            'earned': money(earned.get(tutor.pk)),
            'paid': money(paid.get(tutor.pk)),
            'outstanding': money(owed),
            'balance_state': balance_state(owed, earned_all.get(tutor.pk), paid_all.get(tutor.pk)),
            'own_rates': tutor.pk in own_rates,
        })
    owed_all = [Decimal(row['outstanding']) for row in rows]
    totals_counts = defaultdict(lambda: (0, ZERO))
    for per_tutor in counts.values():
        for class_type, (classes, units) in per_tutor.items():
            totals_counts[class_type] = (totals_counts[class_type][0] + classes, totals_counts[class_type][1] + units)
    totals = {
        'earned': money(sum(earned.values(), ZERO)),
        'paid': money(sum(paid.values(), ZERO)),
        'pending': money(sum((owed for owed in owed_all if owed > 0), ZERO)),
        'overpaid': money(-sum((owed for owed in owed_all if owed < 0), ZERO)),
        'tutors': len(rows),
        'tutors_with_balance': sum(1 for owed in owed_all if owed > 0),
        'payments': period_payments.count(),
        **counts_block(totals_counts),
    }

    term = (search or '').strip().lower()
    if term:
        rows = [row for row in rows if term in (row['name'] or '').lower() or term in (row['email'] or '').lower()]
    if balance in ('pending', 'paid', 'overpaid', 'none'):
        rows = [row for row in rows if row['balance_state'] == balance]
    if rate in ('tutor', 'global'):
        rows = [row for row in rows if row['own_rates'] == (rate == 'tutor')]
    rows.sort(key=lambda row: (-Decimal(row['outstanding']), (row['name'] or '').lower()))
    return {
        **status_block(),
        'period': {'month': month_key(month) if month else None},
        'totals': totals,
        'not_counted': not_counted_counts(now),
        'review_count': len(review_items()),
        'tutors': rows,
    }


# ------------------------------------------------------------- one tutor

def rate_row(version):
    return {
        'id': str(version.id),
        'class_type': version.class_type,
        'unit': UNIT_OF[ClassType(version.class_type)],
        'amount': money(version.amount) if version.amount is not None else None,
        'tutor_id': str(version.tutor_id) if version.tutor_id else None,
        'effective_from': iso(version.effective_from),
        'initial': version.initial,
        'reason': version.reason,
        'created_at': iso(version.created_at),
        'created_by': person(version.created_by),
    }


def payment_row(payment, admin):
    row = {
        'id': str(payment.id),
        'amount': money(payment.amount),
        'currency': payment.currency,
        'paid_on': payment.paid_on.isoformat(),
        'method': payment.method,
        'method_label': payment.get_method_display(),
        'reference': payment.reference,
        'notes': payment.notes,
        'recorded_at': iso(payment.recorded_at),
        'voided': payment.voided_at is not None,
        'voided_at': iso(payment.voided_at),
        'void_reason': payment.void_reason or None,
    }
    if admin:
        row['recorded_by'] = person(payment.recorded_by)
        row['voided_by'] = person(payment.voided_by)
    return row


def entry_row(entry, admin):
    reversal = getattr(entry, 'reversal', None)
    row = {
        'id': str(entry.id),
        'kind': entry.kind,
        'class_type': entry.class_type,
        'source_id': str(entry.source_id) if entry.source_id else None,
        'class_start': iso(entry.class_start),
        'class_end': iso(entry.class_end),
        'month': month_key(entry.month),
        'units': money(entry.units) if entry.units is not None else None,
        'unit': UNIT_OF[ClassType(entry.class_type)] if entry.class_type else None,
        'rate': money(entry.rate) if entry.rate is not None else None,
        'amount': money(entry.amount),
        'details': entry.details or {},
        'reason': entry.reason or None,
        'created_at': iso(entry.created_at),
        'reverses_id': str(entry.reverses_id) if entry.reverses_id else None,
        'reversed': reversal is not None,
        'reversal': {
            'id': str(reversal.id), 'created_at': iso(reversal.created_at), 'reason': reversal.reason,
            **({'created_by': person(reversal.created_by)} if admin else {}),
        } if reversal is not None else None,
    }
    if admin:
        row['rate_source'] = entry.rate_source
        row['created_by'] = person(entry.created_by)
    return row


def _breakdown(period_entries, admin):
    """Per class type: classes, units, amount, and a line per rate (and, for an administrator, per rate source)."""
    by = ('class_type', 'rate', 'rate_source') if admin else ('class_type', 'rate')
    lines = defaultdict(list)
    for row in (_live_earnings(period_entries).values(*by)
                .annotate(classes=Count('id'), units=Sum('units'), amount=Sum('amount'))
                .order_by('class_type', 'rate')):
        line = {'rate': money(row['rate']), 'classes': row['classes'], 'units': money(row['units']),
                'amount': money(row['amount'])}
        if admin:
            line['rate_source'] = row['rate_source']
        lines[row['class_type']].append(line)
    out = []
    for class_type in ClassType.values:
        found = lines.get(class_type, [])
        out.append({
            'class_type': class_type,
            'unit': UNIT_OF[ClassType(class_type)],
            'classes': sum(line['classes'] for line in found),
            'units': money(sum((Decimal(line['units']) for line in found), ZERO)),
            'amount': money(sum((Decimal(line['amount']) for line in found), ZERO)),
            'lines': found,
        })
    return out


def _months(entries):
    """Every month with entries -- newest first -- with what was earned and the classes that count."""
    earned = _sum_by(entries, 'month')
    counts = class_counts(entries, by=('month',))
    return [{'month': month_key(month), 'earned': money(earned[month]), **counts_block(counts.get(month, {}))}
            for month in sorted(earned, reverse=True)]


def _rates_for(tutor, book, now, admin):
    out = []
    for class_type in ClassType.values:
        applied, source = book.resolve(tutor.pk, class_type, now)
        overall, _source = book.resolve(None, class_type, now)
        row = {
            'class_type': class_type,
            'unit': UNIT_OF[ClassType(class_type)],
            'amount': money(applied.amount) if applied else None,
        }
        if admin:
            row.update(source=source, global_amount=money(overall.amount) if overall else None,
                       effective_from=iso(applied.effective_from) if applied else None)
        out.append(row)
    return out


def tutor_earnings(tutor, month=None, admin=True, now=None):
    """
    One tutor's earnings for the period: what they earned and were paid, what
    they are owed, the breakdown by class type and by month, their rates, the
    classes not counted yet and every payment. An administrator also reads
    where each rate came from, the rate history and what needs review; the
    tutor reads their own figures only.
    """
    now = now or timezone.now()
    entries = EarningEntry.objects.filter(tutor=tutor)
    payments = TutorPayment.objects.filter(tutor=tutor).select_related('recorded_by', 'voided_by')
    live_payments = payments.filter(voided_at__isnull=True)
    period_entries, period_payments = _period(entries, live_payments, month)
    period_voided = _period(entries, payments.filter(voided_at__isnull=False), month)[1]
    earned_all = entries.aggregate(total=Sum('amount'))['total'] or ZERO
    paid_all = live_payments.aggregate(total=Sum('amount'))['total'] or ZERO
    earned = period_entries.aggregate(total=Sum('amount'))['total'] or ZERO
    counted = _live_earnings(period_entries).aggregate(total=Sum('amount'))['total'] or ZERO
    owed = earned_all - paid_all
    last = period_payments.order_by('-paid_on', '-recorded_at').first()
    book = RateBook.load()
    data = {
        **status_block(admin),
        'period': {'month': month_key(month) if month else None},
        'tutor': {'id': str(tutor.pk), 'name': name_of(tutor), 'email': tutor.email,
                  'active': tutor.is_active and tutor.role == 'TUTOR', 'is_tutor': tutor.role == 'TUTOR'},
        'summary': {
            'earned': money(earned),
            'paid': money(period_payments.aggregate(total=Sum('amount'))['total']),
            'outstanding': money(owed),
            'balance_state': balance_state(owed, earned_all, paid_all),
            'earned_all_time': money(earned_all),
            'paid_all_time': money(paid_all),
            # The period's, like 'paid'.
            'payments': period_payments.count(),
            'voided_payments': period_voided.count(),
            'last_paid_on': last.paid_on.isoformat() if last else None,
            **counts_block(class_counts(period_entries).get(tutor.pk, {})),
        },
        'breakdown': _breakdown(period_entries, admin),
        # Reversals of adjustments and adjustments themselves; a reversed earning and its reversal cancel out.
        'adjustments': money(earned - counted),
        'months_breakdown': _months(entries),
        'rates': _rates_for(tutor, book, now, admin),
        'not_counted': not_counted(tutor, now),
        'payments': [payment_row(payment, admin) for payment in payments],
    }
    if admin:
        data['own_rates'] = tutor.pk in book.tutors_with_own_rates(now)
        data['rate_history'] = {
            'tutor': [rate_row(version) for version in book.history(tutor.pk)],
            'global': [rate_row(version) for version in book.history(None)],
        }
        data['review'] = review_items(tutor_id=tutor.pk)
    return data


def entries_page(tutor, month=None, class_type=None):
    """``tutor``'s ledger, newest first: every earning, reversal and adjustment (a queryset to page)."""
    entries = (EarningEntry.objects.filter(tutor=tutor)
               .select_related('created_by', 'reversal', 'reversal__created_by')
               .order_by('-month', '-class_end', '-created_at'))
    if month is not None:
        entries = entries.filter(month=month)
    if class_type in ClassType.values:
        entries = entries.filter(class_type=class_type)
    return entries


# --------------------------------------------------------- not counted yet

def _waiting_reason():
    return 'BEING_ADDED' if TutorEarningsPricing.objects.exists() else 'WAITING_FOR_RATES'


def _not_earned(class_type):
    return ~Exists(EarningEntry.objects.filter(kind=EntryKind.EARNING, class_type=class_type, source_id=OuterRef('pk')))


def _pending_queries(now, tutor_id=None):
    """(reason, class_type, queryset) of every class of ``tutor_id`` (or anyone) not counted yet that may still count."""
    since = activated_at()
    if since is None:
        return []
    mine = {'tutor_id': tutor_id} if tutor_id else {}
    assigned = {'assigned_tutor_id': tutor_id} if tutor_id else {}
    queries = [
        # Started and ended: the tutor's notes are due (whenever they come in, they count).
        ('NOTES_DUE', ClassType.SESSION, Session.objects.filter(
            started_at__isnull=False, completed_at__isnull=True, end_time__lte=now, end_time__gte=since,
            tutor__isnull=False, **mine,
        ).exclude(status__in=[SessionStatusChoices.CANCELLED, SessionStatusChoices.NOT_CONDUCTED])),
        ('WAITING', ClassType.SESSION,
         eligible_sessions(Session.objects.filter(end_time__lte=now, **mine)).filter(_not_earned(ClassType.SESSION))),
    ]
    for class_type, model in BOOKING_MODELS:
        started = model.objects.filter(started_at__isnull=False, started_by=F('assigned_tutor'),
                                        slot__ends_at__gte=since, **assigned)
        queries += [
            # Started and its slot over, but its report is not in yet.
            ('REPORT_DUE', class_type, started.filter(status=BookingStatus.BOOKED, slot__ends_at__lte=now)),
            # Report in before the slot ended: it counts once the slot has ended.
            ('SLOT_NOT_ENDED', class_type, started.filter(status__in=CONDUCTED, slot__ends_at__gt=now,
                                                          completed_by=F('assigned_tutor'))),
            ('WAITING', class_type, eligible_bookings(model, model.objects.filter(**assigned), now=now)
             .filter(_not_earned(class_type))),
        ]
    return queries


def not_counted(tutor, now=None):
    """The classes of ``tutor`` not counted yet that may still count, oldest first."""
    now = now or timezone.now()
    waiting = _waiting_reason()
    items = []
    for reason, class_type, queryset in _pending_queries(now, tutor.pk):
        reason = waiting if reason == 'WAITING' else reason
        if class_type == ClassType.SESSION:
            for session in queryset.select_related('student'):
                items.append({
                    'class_type': class_type, 'source_id': str(session.pk), 'reason': reason,
                    'class_start': iso(session.start_time), 'class_end': iso(session.end_time),
                    'title': session.title, 'student_name': session.student.full_name,
                    'student_id': str(session.student_id),
                })
        else:
            for booking in queryset.select_related('slot', 'lead'):
                items.append({
                    'class_type': class_type, 'source_id': str(booking.pk), 'reason': reason,
                    'class_start': iso(booking.slot.starts_at), 'class_end': iso(booking.slot.ends_at),
                    'title': None, 'student_name': booking.lead.student_name,
                    'is_redemo': getattr(booking, 'redemo_for_id', None) is not None,
                })
    return sorted(items, key=lambda item: item['class_end'])


def not_counted_counts(now=None):
    """How many classes, across every tutor, are not counted yet for each reason."""
    now = now or timezone.now()
    waiting = _waiting_reason()
    counts = {'NOTES_DUE': 0, 'REPORT_DUE': 0, 'SLOT_NOT_ENDED': 0, waiting: 0}
    for reason, _class_type, queryset in _pending_queries(now):
        counts[waiting if reason == 'WAITING' else reason] += queryset.count()
    return counts


# ----------------------------------------------------------------- review

def seen(item):
    """The change a review item shows -- its problem and the class as it reads now -- as an EarningReview keeps it."""
    return {'problem': item['problem'], 'current': item['current']}


def review_items(tutor_id=None):
    """
    The earnings whose class has changed since it was earned -- no longer
    counting, now another tutor's, scheduled differently, or gone -- unless
    an administrator kept the earning as earned while its class reads as it
    does now. The sync never touches an earning: an administrator reverses
    it or keeps it as earned (earnings.corrections); an adjustment alone
    leaves it here.
    """
    earnings = _live_earnings(EarningEntry.objects.all()).select_related('tutor')
    reviews = EarningReview.objects.all()
    if tutor_id is not None:
        earnings = earnings.filter(tutor_id=tutor_id)
        reviews = reviews.filter(entry__tutor_id=tutor_id)
    kept = defaultdict(list)
    for review in reviews.values('entry_id', 'seen'):
        kept[review['entry_id']].append(review['seen'])
    still = {
        ClassType.SESSION: eligible_sessions(Session.objects.filter(
            pk=OuterRef('source_id'), tutor=OuterRef('tutor'), start_time=OuterRef('class_start'),
            end_time=OuterRef('class_end'),
        )),
    }
    for class_type, model in BOOKING_MODELS:
        still[class_type] = eligible_bookings(model, model.objects.filter(
            pk=OuterRef('source_id'), assigned_tutor=OuterRef('tutor'), slot__starts_at=OuterRef('class_start'),
            slot__ends_at=OuterRef('class_end'),
        ))
    items = []
    for class_type, matching in still.items():
        for entry in earnings.filter(class_type=class_type).filter(~Exists(matching)):
            problem = _review_problem(entry)
            if seen(problem) in kept[entry.pk]:
                continue
            items.append({**problem, 'entry': entry_row(entry, admin=True), 'tutor': person(entry.tutor)})
    return sorted(items, key=lambda item: item['entry']['class_end'] or '')


def review_item(entry):
    """``entry``'s review item -- an earning that needs review and is not kept as earned -- else None."""
    return next((item for item in review_items(tutor_id=entry.tutor_id) if item['entry']['id'] == str(entry.pk)), None)


def review_row(review):
    """A "Keep as earned": the change it kept, why, and who kept it when."""
    return {'id': str(review.id), 'entry_id': str(review.entry_id), **review.seen, 'reason': review.reason,
            'created_at': iso(review.created_at), 'created_by': person(review.created_by)}


def _review_problem(entry):
    """
    What changed in ``entry``'s class: the problem, and the class as it reads
    now (``current``: its tutor, times, and whether it counts for that tutor
    as it stands -- a status that still counts changes nothing), with its
    tutor now (``current_tutor``, for display only).
    """
    if entry.class_type == ClassType.SESSION:
        source = Session.objects.select_related('tutor').filter(pk=entry.source_id).first()
        tutor = source.tutor if source else None
        times = (source.start_time, source.end_time) if source else None
        counts = is_eligible(source) if source else False
    else:
        model = DiagnosticBooking if entry.class_type == ClassType.DIAGNOSTIC else DemoBooking
        source = model.objects.select_related('slot', 'assigned_tutor').filter(pk=entry.source_id).first()
        tutor = source.assigned_tutor if source else None
        times = (source.slot.starts_at, source.slot.ends_at) if source else None
        counts = eligible_bookings(model, model.objects.filter(pk=source.pk)).exists() if source else False
    if source is None:
        return {'problem': 'SOURCE_MISSING', 'current': None, 'current_tutor': None}
    tutor_id = tutor.pk if tutor else None
    current = {'tutor_id': str(tutor_id) if tutor_id else None, 'class_start': iso(times[0]), 'class_end': iso(times[1]),
               'eligible': counts}
    if tutor_id != entry.tutor_id:
        problem = 'TUTOR_CHANGED'
    elif times != (entry.class_start, entry.class_end):
        problem = 'TIMES_CHANGED'
    else:
        problem = 'NO_LONGER_ELIGIBLE'
    return {'problem': problem, 'current': current, 'current_tutor': person(tutor)}
