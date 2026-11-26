"""
The rates Tutor Earnings pays (EarningsRate): a global rate for each class
type -- Diagnostic and Demo per class, a normal session per class hour, and a
Demo Conversion per converted Demo -- and, for any tutor, their own rate for
any type, which takes the global one's place.

The Demo Conversion rate is the TOTAL a converted Demo earns: its tutor gets
it less what the Demo earned (earnings.conversions). So no change may leave a
Demo Conversion rate below the Demo rate beside it -- the global pair, or any
tutor's pair as they resolve (their own rate, else the global one): it is
refused (INVALID_RATE). An equal rate pays no incentive.

Pricing starts once (start_pricing): an administrator saves the initial global
rates -- every class type's -- and any tutors' own, all taking effect from the
activation, so they price every eligible class since then. Nothing is priced
before it. After that every change (set_global_rates, set_tutor_rates) is a new
version in effect from the moment it is saved, for the classes ending from
then on; no version is ever edited or removed, so an earning keeps the rate it
was priced at and the history stays whole. A tutor's version with no amount
sends them back to the global rate.

RateBook answers which rate a class is paid at: its tutor's own version in
effect at the class's scheduled end, else the global one.
"""
from collections import defaultdict

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from activity.utils import log_activity

from .eligibility import activated_at
from .models import UNIT_OF, ClassType, EarningsRate, RateSource, TutorEarningsPricing
from .values import (
    MAX_RATE,
    REASON_MAX_LENGTH,
    EarningsError,
    as_uuid,
    lock_named,
    reason as clean_reason,
    rupees,
    text,
)

User = get_user_model()

NOT_ACTIVATED = 'EARNINGS_NOT_ACTIVATED'
PRICING_STARTED = 'PRICING_STARTED'
PRICING_NOT_STARTED = 'PRICING_NOT_STARTED'
NOT_CONFIRMED = 'CONFIRMATION_REQUIRED'
NO_CHANGE = 'NO_CHANGE'
UNKNOWN_TUTOR = 'TUTOR_NOT_FOUND'
INVALID_RATE = 'INVALID_RATE'

INITIAL_REASON = 'Initial rates'


class RateBook:
    """Every rate version, read once, and the rate a class is paid at."""

    def __init__(self, versions):
        self._versions = defaultdict(list)
        for version in versions:
            self._versions[(version.tutor_id, version.class_type)].append(version)
        for versions_of_rate in self._versions.values():
            versions_of_rate.sort(key=lambda version: version.effective_from)

    @classmethod
    def load(cls):
        return cls(EarningsRate.objects.select_related('created_by'))

    def adding(self, versions):
        """A RateBook of these versions and ``versions`` (not saved yet): the rates as a change would leave them."""
        return RateBook([*(version for found in self._versions.values() for version in found), *versions])

    def _in_effect(self, tutor_id, class_type, at):
        found = None
        for version in self._versions.get((tutor_id, class_type), ()):
            if version.effective_from > at:
                break
            found = version
        return found

    def resolve(self, tutor_id, class_type, at):
        """(version, RateSource) in effect for ``tutor_id``'s class of ``class_type`` ending at ``at``, or (None, None)."""
        own = self._in_effect(tutor_id, class_type, at) if tutor_id is not None else None
        if own is not None and own.amount is not None:
            return own, RateSource.TUTOR
        overall = self._in_effect(None, class_type, at)
        if overall is not None:
            return overall, RateSource.GLOBAL
        return None, None

    def own(self, tutor_id, class_type, at):
        """``tutor_id``'s own version of ``class_type``'s rate in effect at ``at`` that sets an amount, or None."""
        version = self._in_effect(tutor_id, class_type, at)
        return version if version is not None and version.amount is not None else None

    def history(self, tutor_id=None):
        """Every version of the global rates (or ``tutor_id``'s own), newest first."""
        versions = [version for (owner, _type), versions in self._versions.items() if owner == tutor_id
                    for version in versions]
        return sorted(versions, key=lambda version: (version.effective_from, version.created_at), reverse=True)

    def tutors_with_own_rates(self, at):
        """The ids of the tutors with a rate of their own in effect at ``at``."""
        return {owner for (owner, class_type) in self._versions if owner is not None
                and self.own(owner, class_type, at) is not None}


def pricing():
    """When pricing started (TutorEarningsPricing), or None."""
    return TutorEarningsPricing.objects.select_related('started_by').first()


def _inr(amount):
    return f'₹{amount:,.2f}'.removesuffix('.00')


def check_conversion_floor(book, at, tutor_ids=(), include_global=True):
    """
    Refuse (INVALID_RATE) the rates in ``book`` if, at ``at``, a Demo
    Conversion rate in effect is below the Demo rate beside it: the global
    pair (unless not ``include_global``), and each of ``tutor_ids``' pair as it
    resolves (their own rate, else the global one). With no Demo Conversion
    rate in effect there is nothing to compare.
    """
    field = f'rates.{ClassType.DEMO_CONVERSION}'
    for tutor_id in ((None,) if include_global else ()) + tuple(tutor_ids):
        conversion, _source = book.resolve(tutor_id, ClassType.DEMO_CONVERSION, at)
        demo, _source = book.resolve(tutor_id, ClassType.DEMO, at)
        if conversion is None or demo is None or conversion.amount >= demo.amount:
            continue
        rates = (f'The Demo Conversion rate ({_inr(conversion.amount)}) '
                 f'must be at least the Demo rate ({_inr(demo.amount)})')
        if tutor_id is None:
            message = f'{rates}: it is the total a converted Demo earns, the Demo included.'
        else:
            tutor = User.objects.filter(pk=tutor_id).first()
            message = f'For {(tutor.full_name or tutor.email) if tutor else "a tutor"}: {rates[0].lower()}{rates[1:]}.'
        raise EarningsError(INVALID_RATE, message, field=field)


def _touches_conversion(class_types):
    return bool({ClassType.DEMO, ClassType.DEMO_CONVERSION} & set(class_types))


def _rate(value, class_type, field):
    try:
        return rupees(value, field, maximum=MAX_RATE)
    except EarningsError as exc:
        raise EarningsError(INVALID_RATE, f'{ClassType(class_type).label}: {exc.message}', field=field) from None


def _rates(raw, field, *, every_type, allow_global):
    """
    ``raw`` ({class type: amount}) as {ClassType: Decimal or None}: every type
    when ``every_type``; None (back to the global rate) only when ``allow_global``.
    """
    if not isinstance(raw, dict):
        raise EarningsError(INVALID_RATE, 'Give the rates by class type.', field=field)
    unknown = set(raw) - set(ClassType.values)
    if unknown:
        raise EarningsError(INVALID_RATE, f'Unknown class type: {sorted(unknown)[0]}.', field=field)
    if every_type and set(raw) != set(ClassType.values):
        raise EarningsError(INVALID_RATE,
                            'Set a global rate for Diagnostic, Demo, Normal Sessions and Demo Conversion.', field=field)
    cleaned = {}
    for class_type, value in raw.items():
        if value is None and allow_global:
            cleaned[ClassType(class_type)] = None
        else:
            cleaned[ClassType(class_type)] = _rate(value, class_type, f'{field}.{class_type}')
    return cleaned


def tutor_account(tutor_id):
    """The tutor ``tutor_id`` names, else EarningsError(TUTOR_NOT_FOUND, 404)."""
    key = as_uuid(tutor_id)
    tutor = User.objects.filter(pk=key, role='TUTOR').first() if key else None
    if tutor is None:
        raise EarningsError(UNKNOWN_TUTOR, 'No such tutor.', status=404)
    return tutor


def _require_pricing():
    if pricing() is None:
        raise EarningsError(PRICING_NOT_STARTED, 'Pricing has not started yet. Set the initial rates first.', status=409)


def start_pricing(actor, data, request=None):
    """
    Start pricing with the initial rates in ``data``: ``global`` (an amount
    for every class type), optional ``tutors`` ([{tutor, rates: {type:
    amount}}]), an optional ``reason``, and ``confirm`` true. Every version
    takes effect from the activation. Once only (PRICING_STARTED), and only
    once Tutor Earnings is activated (EARNINGS_NOT_ACTIVATED). Returns the pricing row.
    """
    if data.get('confirm') is not True:
        raise EarningsError(NOT_CONFIRMED, 'Confirm the initial rates: pricing starts once and cannot be undone.',
                            field='confirm')
    overall = _rates(data.get('global'), 'global', every_type=True, allow_global=False)
    raw_tutors = data.get('tutors') or []
    if not isinstance(raw_tutors, list):
        raise EarningsError(INVALID_RATE, 'Give the tutor rates as a list.', field='tutors')
    tutors = []
    seen = set()
    for index, item in enumerate(raw_tutors):
        if not isinstance(item, dict):
            raise EarningsError(INVALID_RATE, 'Give each tutor and their rates.', field=f'tutors.{index}')
        tutor = tutor_account(item.get('tutor'))
        if tutor.pk in seen:
            raise EarningsError(INVALID_RATE, f'{tutor.full_name or tutor.email} is listed twice.', field=f'tutors.{index}')
        seen.add(tutor.pk)
        own = _rates(item.get('rates'), f'tutors.{index}.rates', every_type=False, allow_global=False)
        if own:
            tutors.append((tutor, own))
    why = text(data.get('reason'), 'reason', max_length=REASON_MAX_LENGTH, required=False, message='') or INITIAL_REASON

    with transaction.atomic():
        lock_named('rates')
        since = activated_at()
        if since is None:
            raise EarningsError(NOT_ACTIVATED, 'Tutor Earnings is not activated.', status=409)
        if TutorEarningsPricing.objects.exists():
            raise EarningsError(PRICING_STARTED, 'Pricing has already started. Change the rates instead.', status=409)
        now = timezone.now()
        versions = [EarningsRate(class_type=class_type, amount=amount, effective_from=since, initial=True,
                                 reason=why, created_by=actor, created_at=now)
                    for class_type, amount in overall.items()]
        versions += [EarningsRate(class_type=class_type, tutor=tutor, amount=amount, effective_from=since, initial=True,
                                  reason=why, created_by=actor, created_at=now)
                     for tutor, own in tutors for class_type, amount in own.items()]
        check_conversion_floor(RateBook(versions), since, [tutor.pk for tutor, _own in tutors])
        EarningsRate.objects.bulk_create(versions)
        started = TutorEarningsPricing.objects.create(started_at=now, started_by=actor)
    log_activity(
        action='earnings.start_pricing',
        entity_type='tutor_earnings',
        entity_id='rates',
        entity_label='Tutor Earnings rates',
        context={
            'effective_from': since.isoformat(),
            'global': {class_type: str(amount) for class_type, amount in overall.items()},
            'tutors': {str(tutor.pk): {class_type: str(amount) for class_type, amount in own.items()}
                       for tutor, own in tutors},
            'reason': why,
        },
        request=request,
        actor=actor,
    )
    return started


def set_global_rates(actor, data, request=None):
    """
    Change the global rate of the class types in ``data['rates']``, for
    ``data['reason']``: a new version of each rate that differs, in effect from
    now. Only once pricing has started; NO_CHANGE when nothing differs.
    Returns the new versions.
    """
    rates = _rates(data.get('rates'), 'rates', every_type=False, allow_global=False)
    why = clean_reason(data.get('reason'))
    with transaction.atomic():
        lock_named('rates')
        _require_pricing()
        now = timezone.now()
        book = RateBook.load()
        changed = []
        for class_type, amount in rates.items():
            current, _source = book.resolve(None, class_type, now)
            if current is not None and current.amount == amount:
                continue
            changed.append(EarningsRate(class_type=class_type, amount=amount, effective_from=now, reason=why,
                                        created_by=actor, created_at=now))
        if not changed:
            raise EarningsError(NO_CHANGE, 'These are the rates already in effect.')
        if _touches_conversion(version.class_type for version in changed):
            # Every tutor with a rate of their own may now pair it with a changed global one. Only current
            # tutors: a former tutor's rates can no longer be changed (tutor_account), so they must not block
            # this one; a conversion of their earlier Demo still never pays below its Demo (earnings.conversions).
            current = User.objects.filter(pk__in=book.tutors_with_own_rates(now), role='TUTOR')
            check_conversion_floor(book.adding(changed), now, sorted(current.values_list('pk', flat=True), key=str))
        EarningsRate.objects.bulk_create(changed)
    log_activity(
        action='earnings.change_rates',
        entity_type='tutor_earnings',
        entity_id='rates',
        entity_label='Global rates',
        changes={version.class_type: {'new': str(version.amount)} for version in changed},
        context={'effective_from': now.isoformat(), 'reason': why},
        request=request,
        actor=actor,
    )
    return changed


def set_tutor_rates(actor, tutor, data, request=None):
    """
    Change ``tutor``'s own rates for the class types in ``data['rates']`` --
    an amount, or None for the global rate -- for ``data['reason']``: a new
    version of each that differs, in effect from now. Only once pricing has
    started; NO_CHANGE when nothing differs. Returns the new versions.
    """
    rates = _rates(data.get('rates'), 'rates', every_type=False, allow_global=True)
    why = clean_reason(data.get('reason'))
    with transaction.atomic():
        lock_named('rates')
        _require_pricing()
        now = timezone.now()
        book = RateBook.load()
        changed = []
        for class_type, amount in rates.items():
            own = book.own(tutor.pk, class_type, now)
            if (own.amount if own is not None else None) == amount:
                continue
            changed.append(EarningsRate(class_type=class_type, tutor=tutor, amount=amount, effective_from=now,
                                        reason=why, created_by=actor, created_at=now))
        if not changed:
            raise EarningsError(NO_CHANGE, "These are the tutor's rates already in effect.")
        if _touches_conversion(version.class_type for version in changed):
            # Only this tutor's pair changes: the global one was checked when it was saved.
            check_conversion_floor(book.adding(changed), now, [tutor.pk], include_global=False)
        EarningsRate.objects.bulk_create(changed)
    log_activity(
        action='earnings.change_tutor_rates',
        entity_type='user',
        entity_id=str(tutor.pk),
        entity_label=tutor.full_name or tutor.email,
        changes={version.class_type: {'new': str(version.amount) if version.amount is not None else 'global'}
                 for version in changed},
        context={'effective_from': now.isoformat(), 'reason': why},
        request=request,
        actor=actor,
    )
    return changed


def unit_of(class_type):
    return UNIT_OF[ClassType(class_type)]
