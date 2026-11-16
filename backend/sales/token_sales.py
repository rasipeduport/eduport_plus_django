"""
Token Sale, chosen with the tuition plan in Plan Choosing.

    reserve   the enquiry's Token Sale quote and, the first time, its token reservation, in one transaction

A Token Sale is AED 100 first, then the remaining tuition in one payment by the
balance deadline the BDE chose. Its quote (collection mode TOKEN) has no
single-payment discount, and the token is credited against it exactly once: as
money received on the same sale (sales.payments.received), never a record of
its own. The token alone never enrolls; the one tuition payment that settles
the balance does (sales.payments.succeed). The sale type is fixed once a sale
exists: a New Sale never becomes a Token Sale, nor a Token Sale a New Sale.

Choosing the plan again before the balance is collected issues a replacement
Token Sale quote; the reservation, its dates and any token received stay as
they are. Nothing here forfeits a token, cancels a reservation or moves a deadline.
"""
from django.db import transaction
from django.utils import timezone

from . import payments, quotes, student_accounts
from .payment_models import Sale, SaleKind

# The tuition plan, as Plan Choosing quotes it (sales.quote_views.QuoteCreateSerializer).
PLAN_FIELDS = ('syllabus', 'revision', 'plan_type', 'class_mode', 'chapter_ids', 'replaces', 'pricing_version')


@transaction.atomic
def reserve(actor, enquiry_id, data, request=None):
    """``(quote, sale)``: the Token Sale quote issued for the plan in ``data``, and the enquiry's Token Sale."""
    lead = payments.accessible_lead(actor, enquiry_id, request, lock=True)
    sale = Sale.objects.select_for_update().filter(enquiry=lead).first()
    if sale is not None and sale.kind != SaleKind.TOKEN:
        raise payments.refusal('SALE_EXISTS', 'This enquiry already has a New Sale. The sale type cannot change once the sale has started.', 409)
    if not lead.owner_bde_id:
        raise payments.refusal('BDE_REQUIRED', 'Assign the responsible BDE before starting a sale.')
    if sale is None:
        today = timezone.localdate()
        if data.get('expected_start_date') is None or data['expected_start_date'] < today:
            raise payments.refusal('START_DATE_REQUIRED', 'Choose today or a future expected class start date.')
        if data.get('balance_due_date') is None or data['balance_due_date'] < today:
            raise payments.refusal('BALANCE_DUE_DATE_REQUIRED', 'Choose today or a later full payment deadline.')
        # The student account (its number, a sibling's family) before the quote table's lock (quotes.issue), in
        # the order a New Sale takes them: two sales starting at once then wait for each other, never deadlock.
        student_accounts.open_account(actor, lead, data, request)
    elif data.get('expected_start_date') is not None or data.get('balance_due_date') is not None:
        raise payments.refusal('RESERVATION_DATES_FIXED', 'The token reservation’s dates are fixed: only its tuition plan can be chosen again.', 409)
    plan = {key: data[key] for key in PLAN_FIELDS if key in data}
    quote = quotes.create_quote(actor, {**plan, 'lead': lead.pk, 'collection_mode': 'TOKEN'}, request=request, reserving=sale is None)
    if sale is None:
        sale = payments.open_sale(actor, lead, SaleKind.TOKEN, quote, data, request, balance_due_date=data['balance_due_date'])
    return quote, sale
