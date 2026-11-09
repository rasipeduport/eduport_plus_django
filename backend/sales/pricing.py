"""
What a syllabus's packages cost under a pricing version.

One rate applies to every plan: a package costs the version's offer fee for
each of its classes. Amounts are exact decimals -- a half class at a fee with
cents prices to the fil -- and nothing is rounded except the single-payment
price, which is rounded to the nearest whole currency unit, a half rounding
up (D1); its saving is the package's total less that rounded price.

The classes of each plan type come from the syllabus's own chapters: Regular
and Revision their columns' totals, Regular + Revision both, a Bridge Course
its days, and a Chapter Plan the Regular classes of the chapters chosen.
"""
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from django.utils import timezone

from .models import PlanType, PricingVersion

ZERO = Decimal('0')
HUNDRED = Decimal('100')

# The package each card of the packages page sells, in the order the cards appear.
PACKAGE_TITLES = {
    PlanType.REGULAR: 'Regular Course Package',
    PlanType.REVISION: 'Revision Course (Exam Oriented) Package',
    PlanType.BRIDGE_COURSE: 'Bridge Course Package',
}


def active_pricing(at=None):
    """The pricing version in effect at ``at`` (now by default): the newest effective by then, or None."""
    at = at or timezone.now()
    return PricingVersion.objects.filter(effective_from__lte=at).order_by('-effective_from', '-version').first()


def chapter_totals(chapters):
    """
    The classes of each column over ``chapters`` (rows with regular_classes,
    revision_classes and bridge_classes, each a Decimal or None).
    """
    totals = {'regular': ZERO, 'revision': ZERO, 'bridge': ZERO}
    for chapter in chapters:
        for column in totals:
            value = _get(chapter, f'{column}_classes')
            if value is not None:
                totals[column] += value
    return totals


def plan_classes(plan_type, chapters, chosen=None):
    """
    The classes ``plan_type`` sells over ``chapters``. A Chapter Plan sells the
    Regular classes of the chapters whose ids are in ``chosen``.
    """
    if plan_type == PlanType.CHAPTER_PLAN:
        chosen = {str(chapter_id) for chapter_id in (chosen or ())}
        chapters = [chapter for chapter in chapters if str(_get(chapter, 'id')) in chosen]
        return chapter_totals(chapters)['regular']
    totals = chapter_totals(chapters)
    return {
        PlanType.REGULAR: totals['regular'],
        PlanType.REVISION: totals['revision'],
        PlanType.REGULAR_REVISION: totals['regular'] + totals['revision'],
        PlanType.BRIDGE_COURSE: totals['bridge'],
    }[plan_type]


def package_total(classes, pricing):
    """``classes`` at the offer fee of ``pricing``, exactly."""
    return pricing.offer_fee * classes


def single_payment_price(total, pricing, plan_type):
    """
    ``(price, saving)`` when ``pricing`` gives ``plan_type`` the single-payment
    privilege: ``single_payment_percent`` off ``total``, worked out exactly and
    only then rounded to the nearest whole currency unit (a half rounds up),
    and the saving that leaves. None when it does not.
    """
    percent = pricing.single_payment_percent
    if not percent or plan_type not in pricing.single_payment_plan_types:
        return None
    price = (total * (HUNDRED - percent) / HUNDRED).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
    return price, total - price


@dataclass(frozen=True)
class Package:
    """One card of the packages page: what ``plan_type`` costs over a syllabus's chapters."""
    plan_type: str
    title: str
    classes: Decimal
    fee_per_class: Decimal
    total: Decimal
    single_payment: tuple | None  # (price, saving)


def card_plan_types(plan_types):
    """
    The packages the packages page shows for a syllabus offering
    ``plan_types``: Regular and Revision each when offered alone or together
    (Regular + Revision shows both cards, D6), and a Bridge Course. A Chapter
    Plan has no card yet: its chapters are the syllabus's table.
    """
    shown = set()
    if PlanType.REGULAR in plan_types or PlanType.REGULAR_REVISION in plan_types:
        shown.add(PlanType.REGULAR)
    if PlanType.REVISION in plan_types or PlanType.REGULAR_REVISION in plan_types:
        shown.add(PlanType.REVISION)
    if PlanType.BRIDGE_COURSE in plan_types:
        shown.add(PlanType.BRIDGE_COURSE)
    return [plan_type for plan_type in PACKAGE_TITLES if plan_type in shown]


def packages(plan_types, chapters, pricing):
    """The packages page's cards for a syllabus offering ``plan_types`` over ``chapters``, priced by ``pricing``."""
    cards = []
    for plan_type in card_plan_types(plan_types):
        classes = plan_classes(plan_type, chapters)
        total = package_total(classes, pricing)
        cards.append(Package(
            plan_type=plan_type,
            title=PACKAGE_TITLES[plan_type],
            classes=classes,
            fee_per_class=pricing.offer_fee,
            total=total,
            single_payment=single_payment_price(total, pricing, plan_type),
        ))
    return cards


def plain(value):
    """``value`` (a Decimal) as plain digits, without trailing zeros: 38, 1.5, 682.5 -- never 3.8E+1."""
    if value is None:
        return None
    text = format(value, 'f')
    if '.' in text:
        text = text.rstrip('0').rstrip('.')
    return text or '0'


def _get(row, field):
    return row.get(field) if isinstance(row, dict) else getattr(row, field)
