"""
Quotes: what a parent is quoted for one purchase, priced once and kept as it
was issued -- the foundation of the Sales workflow to come (the parent's
confirmation, a payment link, the payment, Sales Punching).

    quote_snapshot   checks a request against the catalogue on sale and prices it; writes nothing
    issue            saves a snapshot as the next quote, its number taken under a table lock
    create_quote     quote_snapshot, issue and the activity log: the API's way in
    cancel_quote     an administrator withdraws an issued quote
    visible_quotes   the quotes a caller may see: their own, or every one with manage_sales_quotes
    quote_data, quote_row       a quote as the API answers it
    quote_pdf_parts             what its PDF draws -- its own figures, never priced again

A quote is made from the revision a syllabus sells now (services.on_sale_revision)
and priced at the pricing in effect by the functions that price the syllabus
PDFs (sales.pricing): a whole course (Regular, Revision, Regular + Revision),
a Chapter Plan's chosen chapters, or a Bridge Course whole or by the day --
choosing every day is the whole course. It keeps its rates, packages and
figures, and the chapters it covers by id (rows of an immutable published
revision, never copied), so nothing published, priced or decided later -- a
revision, a pricing version, a rounding rule -- changes what it says. The
database holds it so (sales.0004).
"""
from dataclasses import dataclass, replace
from decimal import Decimal

from django.db import connection, transaction
from django.db.models import OuterRef, Q, Subquery
from django.utils import timezone, formats

from accounts.authz import has_app_permission
from activity.utils import log_activity
from bookings.models import Lead

from . import services
from .models import PlanType, Quote, QuoteChapter, QuoteLine, QuoteStatus, Syllabus
from .pricing import Package, active_pricing, chosen_chapters, package_total, packages, plain, plan_classes, single_payment_price
from .services import SalesError

CREATE_QUOTES = 'accounts.create_sales_quotes'
MANAGE_QUOTES = 'accounts.manage_sales_quotes'
VIEW_ALL_LEADS = 'accounts.view_all_leads'
# A Chapter Plan's card: the chapters chosen, priced per class (no single-payment privilege can name it).
CHAPTER_PLAN_TITLE = 'Chapter Plan Package'
# The plan types that sell a whole course: every chapter of the revision, none chosen.
WHOLE_COURSE_PLANS = (PlanType.REGULAR, PlanType.REVISION, PlanType.REGULAR_REVISION)
# The columns each plan type counts a chapter's classes from.
COUNTED = {
    PlanType.REGULAR: ('regular_classes',),
    PlanType.REVISION: ('revision_classes',),
    PlanType.REGULAR_REVISION: ('regular_classes', 'revision_classes'),
    PlanType.CHAPTER_PLAN: ('regular_classes',),
    PlanType.BRIDGE_COURSE: ('bridge_classes',),
}
ZERO = Decimal('0')


@dataclass(frozen=True)
class QuoteSnapshot:
    """A quote before it is issued: everything it will keep."""
    owner: object
    lead: object
    revision: object
    pricing: object
    plan_type: str
    full_course: bool
    lines: list           # sales.pricing.Package, in the order the PDF prints them
    chapters: list        # (SyllabusChapter, classes counted), in the course's order
    classes: Decimal
    total_fee: Decimal
    single_payment_saving: Decimal
    payable_amount: Decimal
    supersedes: object = None


def quote_snapshot(actor, *, syllabus_id, revision, plan_type, chapter_ids=(), lead_id=None):
    """
    ``plan_type`` of revision ``revision`` of syllabus ``syllabus_id`` --
    the revision it sells now -- priced at the pricing in effect, for
    ``actor``: the whole course, or the ``chapter_ids`` chosen (a Chapter
    Plan's chapters, a Bridge Course's days), for the enquiry ``lead_id`` if
    named (the actor's own, or any for whoever may read every lead). Writes
    nothing; a SalesError says why it cannot be quoted.
    """
    sold = services.on_sale_revision(syllabus_id, revision)
    if plan_type not in sold.plan_types:
        raise _invalid('plan_type', f'{sold.title} is not sold as {PlanType(plan_type).label}.')
    chapters = list(sold.chapters.order_by('position'))
    wanted = [str(chapter_id) for chapter_id in chapter_ids or ()]

    if plan_type in WHOLE_COURSE_PLANS:
        if wanted:
            raise _invalid('chapter_ids', f'{PlanType(plan_type).label} is the whole course: choose no chapters.')
        selected = None
    elif plan_type == PlanType.BRIDGE_COURSE:
        # No days named, or every day: the whole course, as its own package.
        selected = services.choose(chapters, wanted, plan_type, sold) if wanted else None
        if selected is not None and len(selected) == len(chapters):
            selected = None
    else:
        selected = services.choose(chapters, wanted, plan_type, sold)
    covered = chapters if selected is None else chosen_chapters(chapters, selected)

    lead = _lead(actor, lead_id) if lead_id else None
    pricing = active_pricing()
    if pricing is None:
        raise SalesError('NO_PRICING', 'Set up the global pricing first: a quote prices every package.')
    if plan_type == PlanType.CHAPTER_PLAN:
        classes = plan_classes(plan_type, chapters, selected)
        total = package_total(classes, pricing)
        lines = [Package(plan_type=plan_type, title=CHAPTER_PLAN_TITLE, classes=classes, fee_per_class=pricing.offer_fee,
                         total=total, single_payment=single_payment_price(total, pricing, plan_type))]
    else:
        lines = packages([plan_type], chapters, pricing, selected=selected if plan_type == PlanType.BRIDGE_COURSE else None)

    if sum((line.classes for line in lines), ZERO) <= 0:
        raise _invalid('plan_type', 'This plan has no classes to quote.')

    total_fee = sum((line.total for line in lines), ZERO)
    saving = sum((line.single_payment[1] for line in lines if line.single_payment), ZERO)
    return QuoteSnapshot(
        owner=actor, lead=lead, revision=sold, pricing=pricing, plan_type=plan_type,
        full_course=len(covered) == len(chapters), lines=lines,
        chapters=[(chapter, _counted(chapter, plan_type)) for chapter in covered],
        classes=sum((line.classes for line in lines), ZERO), total_fee=total_fee,
        single_payment_saving=saving, payable_amount=total_fee - saving,
    )


def issue(snapshot, quote_id=None):
    """``snapshot`` saved as the next quote -- its lines and chapters with it -- in one transaction."""
    pricing = snapshot.pricing
    with transaction.atomic():
        # One issuer at a time, so numbers only ever go up and never repeat. Reads go on.
        with connection.cursor() as cursor:
            cursor.execute(f'LOCK TABLE {Quote._meta.db_table} IN EXCLUSIVE MODE')
        last = Quote.objects.order_by('-number').values_list('number', flat=True).first() or 0
        quote = Quote.objects.create(
            **({'id': quote_id} if quote_id else {}),
            number=last + 1, created_by=snapshot.owner, lead=snapshot.lead, supersedes=snapshot.supersedes, revision=snapshot.revision,
            pricing_version=pricing, plan_type=snapshot.plan_type, full_course=snapshot.full_course,
            currency=pricing.currency, standard_fee=pricing.standard_fee, offer_fee=pricing.offer_fee,
            single_payment_percent=pricing.single_payment_percent, classes=snapshot.classes,
            total_fee=snapshot.total_fee, single_payment_saving=snapshot.single_payment_saving,
            payable_amount=snapshot.payable_amount,
        )
        QuoteLine.objects.bulk_create([
            QuoteLine(
                quote=quote, position=position, plan_type=line.plan_type, title=line.title, classes=line.classes,
                fee_per_class=line.fee_per_class, total=line.total,
                single_payment_price=line.single_payment[0] if line.single_payment else None,
                single_payment_saving=line.single_payment[1] if line.single_payment else None,
            )
            for position, line in enumerate(snapshot.lines, start=1)
        ])
        QuoteChapter.objects.bulk_create([
            QuoteChapter(quote=quote, chapter=chapter, classes=classes) for chapter, classes in snapshot.chapters
        ])
    return quote


@transaction.atomic
def create_quote(actor, data, request=None):
    """A new quote for ``actor`` from ``data`` (QuoteCreateSerializer's), issued and logged."""
    # Lock the enquiry before the syllabus and quote table, consistently with
    # any future payment writer. A stale browser cannot overwrite a newer choice.
    lead = _lead(actor, data['lead'], lock=True) if data.get('lead') else None
    previous = latest_quote(lead) if lead else None
    if lead and lead.plan_changes_locked_at:
        raise SalesError('PLAN_LOCKED', 'This enquiry is locked against plan changes. Contact an administrator.')
    if previous and previous.status == QuoteStatus.ISSUED and previous.created_by_id != actor.pk and not has_app_permission(actor, MANAGE_QUOTES, request):
        raise SalesError('PLAN_OWNER_CHANGED', 'An earlier owner issued this enquiry’s current quote. Ask an administrator to cancel it before choosing a replacement.')
    expected = str(data.get('replaces') or '')
    if expected != (str(previous.pk) if previous else ''):
        raise SalesError('PLAN_CHANGED', 'The selected plan changed meanwhile. Reload the enquiry before issuing a quote.')
    # Publishing/deactivation also lock this row. The pinned revision remains
    # on sale until this transaction has saved the quote.
    Syllabus.objects.select_for_update().filter(pk=data['syllabus']).first()
    snapshot = quote_snapshot(
        actor, syllabus_id=data['syllabus'], revision=data['revision'], plan_type=data['plan_type'],
        chapter_ids=data.get('chapter_ids') or (), lead_id=data.get('lead'),
    )
    if data.get('pricing_version') is not None and snapshot.pricing.version != data['pricing_version']:
        raise SalesError('PRICING_CHANGED', 'Pricing changed meanwhile. Reload the syllabus and review the new amount.')
    quote = issue(replace(snapshot, supersedes=previous))
    _log('quote.create', quote, request, actor, plan_type=quote.plan_type, full_course=quote.full_course,
         revision=quote.revision.number, pricing_version=quote.pricing_version.version,
         payable_amount=plain(quote.payable_amount), currency=quote.currency,
         lead=str(lead.pk) if lead else None, supersedes=str(previous.pk) if previous else None)
    return quote


def cancel_quote(actor, quote_id, reason, request=None):
    """An issued quote withdrawn by an administrator, with why; a cancelled one stays as it is (ALREADY_CANCELLED)."""
    with transaction.atomic():
        quote = Quote.objects.select_for_update().filter(pk=quote_id).first()
        if quote is None:
            raise SalesError('NOT_FOUND', 'No such quote.', 404)
        if quote.status == QuoteStatus.CANCELLED:
            raise SalesError('ALREADY_CANCELLED', 'This quote is already cancelled.')
        quote.status = QuoteStatus.CANCELLED
        quote.cancelled_at = timezone.now()
        quote.cancelled_by = actor
        quote.cancel_reason = reason
        quote.save(update_fields=['status', 'cancelled_at', 'cancelled_by', 'cancel_reason'])
    _log('quote.cancel', quote, request, actor, reason=reason)
    return quote


def visible_quotes(user, request=None):
    """The quotes ``user`` may see: every one with manage_sales_quotes, else only their own."""
    quotes = Quote.objects.select_related('created_by', 'cancelled_by', 'lead', 'revision', 'pricing_version').annotate(
        latest_for_lead=Subquery(Quote.objects.filter(lead_id=OuterRef('lead_id')).order_by('-number').values('pk')[:1]),
    )
    if has_app_permission(user, MANAGE_QUOTES, request):
        return quotes
    return quotes.filter(Q(lead__isnull=True) | Q(lead__owner_bde=user), created_by=user)


def latest_quote(lead):
    """The latest choice, including a cancellation: never revive an older quote silently."""
    return Quote.objects.filter(lead=lead).order_by('-number').first()


def enquiry_plan(actor, lead_id, request=None):
    lead = _lead(actor, lead_id)
    latest = latest_quote(lead)
    visible = visible_quotes(actor, request).filter(lead=lead)
    if latest and latest.status == QuoteStatus.ISSUED and not visible.filter(pk=latest.pk).exists():
        raise SalesError('PLAN_OWNER_CHANGED', 'An earlier owner issued this enquiry’s current quote. Ask an administrator to cancel it before choosing a replacement.')
    return {
        'lead': _lead_data(lead),
        'latest_quote': str(latest.pk) if latest else None,
        'current': quote_data(latest) if latest and latest.status == QuoteStatus.ISSUED else None,
        'locked': lead.plan_changes_locked_at is not None,
        'history': [quote_row(quote) for quote in visible.order_by('-number')],
    }


# ---------------------------------------------------------------- reading

def quote_row(quote):
    """A quote as the list shows it."""
    revision = quote.revision
    latest = getattr(quote, 'latest_for_lead', None)
    if quote.lead_id and latest is None:
        latest = latest_quote(quote.lead).pk
    current = bool(quote.lead_id and latest == quote.pk and quote.status == QuoteStatus.ISSUED)
    return {
        'id': str(quote.pk),
        'reference': quote.reference,
        'status': quote.status,
        'created_at': quote.created_at,
        'created_by': _person(quote.created_by),
        'lead': _lead_data(quote.lead),
        'syllabus': {'id': str(revision.syllabus_id), 'title': revision.title, 'grade': revision.grade,
                     'board': revision.board, 'structure': revision.structure},
        'revision': revision.number,
        'plan_type': quote.plan_type,
        'full_course': quote.full_course,
        'supersedes': str(quote.supersedes_id) if quote.supersedes_id else None,
        'is_current': current,
        'selection_status': ('CURRENT' if current else 'CANCELLED' if quote.status == QuoteStatus.CANCELLED else 'PREVIOUS') if quote.lead_id else None,
        'currency': quote.currency,
        'classes': plain(quote.classes),
        'total_fee': plain(quote.total_fee),
        'payable_amount': plain(quote.payable_amount),
    }


def quote_data(quote):
    """A quote in full: its rates, packages, the chapters it covers (names from the revision quoted) and figures."""
    row = quote_row(quote)
    covered = quote.chapters.select_related('chapter').order_by('chapter__position')
    return {
        **row,
        'syllabus': {**row['syllabus'], 'syllabus_version': quote.revision.syllabus_version},
        'pricing_version': quote.pricing_version.version,
        'standard_fee': plain(quote.standard_fee),
        'offer_fee': plain(quote.offer_fee),
        'single_payment_percent': plain(quote.single_payment_percent),
        'single_payment_saving': plain(quote.single_payment_saving),
        'lines': [
            {
                'plan_type': line.plan_type, 'title': line.title, 'classes': plain(line.classes),
                'fee_per_class': plain(line.fee_per_class), 'total': plain(line.total),
                'single_payment': {'price': plain(line.single_payment_price), 'saving': plain(line.single_payment_saving)}
                if line.single_payment_price is not None else None,
            }
            for line in quote.lines.all()
        ],
        'chapters': [
            {'id': str(row.chapter_id), 'position': row.chapter.position, 'name': row.chapter.name, 'classes': plain(row.classes),
             **{column: plain(getattr(row.chapter, column)) for column in COUNTED[quote.plan_type]}}
            for row in covered
        ],
        'cancelled_at': quote.cancelled_at,
        'cancelled_by': _person(quote.cancelled_by),
        'cancel_reason': quote.cancel_reason,
    }


@dataclass(frozen=True)
class QuoteRates:
    """The rates a quote was priced at, as the PDF's fee lines print them (sales.pdf reads these three)."""
    currency: str
    standard_fee: Decimal
    offer_fee: Decimal


def quote_pdf_parts(quote):
    """
    What a quote's PDF draws, all from the quote itself: the revision it
    quoted (its titles, inclusions and the chapters it covers -- the rest left
    out), its rates, its packages as they were priced, and its reference --
    and, once cancelled, that it is (CANCELLED on every page, and the day).
    ``(content, rates, cards, selected, reference)`` for sales.pdf.quote_pdf.
    """
    content = services.content_of(quote.revision)
    covered = {str(chapter_id) for chapter_id in quote.chapters.values_list('chapter_id', flat=True)}
    every = {str(chapter['id']) for chapter in content['chapters']}
    cards = [
        Package(plan_type=line.plan_type, title=line.title, classes=line.classes, fee_per_class=line.fee_per_class,
                total=line.total,
                single_payment=(line.single_payment_price, line.single_payment_saving)
                if line.single_payment_price is not None else None)
        for line in quote.lines.all()
    ]
    reference = {
        'reference': quote.reference,
        'date': _day(quote.created_at),
        # A cancelled quote's PDF says so on every page and when; never why (the reason is the team's, not the parent's).
        'cancelled': _day(quote.cancelled_at) if quote.status == QuoteStatus.CANCELLED else None,
    }
    rates = QuoteRates(currency=quote.currency, standard_fee=quote.standard_fee, offer_fee=quote.offer_fee)
    return content, rates, cards, (None if covered == every else sorted(covered)), reference


# ---------------------------------------------------------------- helpers

def _day(moment):
    return formats.date_format(timezone.localtime(moment), 'j F Y')


def _counted(chapter, plan_type):
    return sum((getattr(chapter, column) or ZERO for column in COUNTED[plan_type]), ZERO)


def _lead(actor, lead_id, lock=False):
    """The enquiry a quote answers: the actor's own, or any lead for whoever may read every lead."""
    rows = Lead.objects.filter(pk=lead_id)
    lead = (rows.select_for_update() if lock else rows).first()
    if lead is None or not (lead.owner_bde_id == actor.pk or has_app_permission(actor, VIEW_ALL_LEADS)):
        raise _invalid('lead', 'Choose one of your own enquiries.')
    return lead


def _invalid(field, message):
    return SalesError('VALIDATION_ERROR', message, 400, fields={field: [message]})


def _person(user):
    return {'id': str(user.pk), 'name': user.full_name or user.username} if user else None


def _lead_data(lead):
    return {'id': str(lead.pk), 'parent_name': lead.parent_name, 'student_name': lead.student_name} if lead else None


def _log(action, quote, request, actor, **context):
    log_activity(
        action=action, entity_type='quote', entity_id=quote.pk, entity_label=quote.reference,
        context=context, request=request, actor=actor,
    )
