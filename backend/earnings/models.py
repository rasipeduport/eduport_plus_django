"""
Tutor Earnings: what each tutor earned for the classes they taught, and what
they were paid -- in Indian rupees only, to the paisa.

- TutorEarningsActivation: when Tutor Earnings was activated. Only a class
  scheduled to end at or after it can count (earnings.eligibility).
- TutorEarningsPricing: when an administrator started pricing, with the
  initial rates (earnings.rates). Nothing is priced before it.
- EarningsRate: every rate there has been, global or one tutor's, per class
  type. A rate is never edited: a change is a new version, in effect for the
  classes ending from then on.
- EarningEntry: the ledger. An earning per counted class, written by the sync
  (earnings.ledger) and never twice; reversals and adjustments by an
  administrator, each with its reason. Rows are only ever added.
- EarningReview: an administrator's "Keep as earned" on an earning whose class
  changed after it earned, with the reason.
- TutorPayment: a payment an administrator made to a tutor outside Eduport
  Plus and recorded here. Never edited or deleted; voided, with a reason.
- EarningsSyncRun: each run of the sync, for when it last ran and what it did.

The database holds the rules that matter for money (migration 0002): the
checks below, one earning per class, and triggers that refuse any change to
the ledger, the reviews, the rates and the pricing, and any change to a
payment but its voiding.
"""
import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

# Tutor Earnings is in Indian rupees, whatever Sales and Finance use.
CURRENCY = 'INR'
# Up to ₹9,99,99,99,999.99 an amount; ₹9,99,99,999.99 a rate; 9999.99 units.
MONEY = {'max_digits': 12, 'decimal_places': 2}
RATE = {'max_digits': 10, 'decimal_places': 2}
UNITS = {'max_digits': 6, 'decimal_places': 2}

# Text that is more than blanks.
NOT_BLANK = r'\S'


class ClassType(models.TextChoices):
    DIAGNOSTIC = 'DIAGNOSTIC', 'Diagnostic'
    DEMO = 'DEMO', 'Demo'
    SESSION = 'SESSION', 'Normal Session'


class RateUnit(models.TextChoices):
    CLASS = 'CLASS', 'per class'
    HOUR = 'HOUR', 'per class hour'


# Diagnostic and Demo bookings are paid by the class (each a 60-minute slot);
# a normal session by its booked hours.
UNIT_OF = {
    ClassType.DIAGNOSTIC: RateUnit.CLASS,
    ClassType.DEMO: RateUnit.CLASS,
    ClassType.SESSION: RateUnit.HOUR,
}


class RateSource(models.TextChoices):
    GLOBAL = 'GLOBAL', 'Global rate'
    TUTOR = 'TUTOR', 'Tutor rate'


class EntryKind(models.TextChoices):
    EARNING = 'EARNING', 'Earning'
    REVERSAL = 'REVERSAL', 'Reversal'
    ADJUSTMENT = 'ADJUSTMENT', 'Adjustment'


class PaymentMethod(models.TextChoices):
    ACCOUNT_TRANSFER = 'ACCOUNT_TRANSFER', 'Account Transfer'
    UPI = 'UPI', 'UPI'


class SyncStatus(models.TextChoices):
    SUCCEEDED = 'SUCCEEDED', 'Succeeded'
    # Activated but not yet priced: eligible classes are counted, nothing is written.
    WAITING_FOR_PRICING = 'WAITING_FOR_PRICING', 'Waiting for pricing'
    FAILED = 'FAILED', 'Failed'


class SyncTrigger(models.TextChoices):
    SCHEDULE = 'SCHEDULE', 'Schedule'
    COMMAND = 'COMMAND', 'Command'


class TutorEarningsActivation(models.Model):
    """
    When Tutor Earnings was activated here: a single row, recorded by
    migration 0001 when it is applied, by the server's clock. No setting or
    date is configured by hand. Only a class scheduled to end at or after
    this moment can count (earnings.eligibility), so nothing that ended
    before it is ever backfilled. Read only, including in the admin. With no
    row, Tutor Earnings is not active and nothing counts.
    """

    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    activated_at = models.DateTimeField()

    class Meta:
        db_table = 'tutor_earnings_activation'
        constraints = [
            models.CheckConstraint(condition=Q(id=1), name='tutor_earnings_activation_single_row'),
        ]

    def __str__(self):
        return f'Tutor Earnings active since {self.activated_at.isoformat()}'


class TutorEarningsPricing(models.Model):
    """
    When an administrator started pricing, saving the initial rates (which
    price every eligible class from the activation on). One row, written once.
    """

    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    started_at = models.DateTimeField()
    started_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')

    class Meta:
        db_table = 'tutor_earnings_pricing'
        constraints = [
            models.CheckConstraint(condition=Q(id=1), name='tutor_earnings_pricing_single_row'),
        ]

    def __str__(self):
        return f'Tutor Earnings priced since {self.started_at.isoformat()}'


class EarningsRate(models.Model):
    """
    One version of a rate: the global rate of a class type (no tutor), or one
    tutor's own rate for it -- which, with no amount, sends that tutor back to
    the global rate. In effect for the classes scheduled to end at or after
    ``effective_from`` until the next version of the same rate. The initial
    rates take effect from the activation; every later one when it was saved.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    class_type = models.CharField(max_length=20, choices=ClassType.choices)
    tutor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name='earnings_rates',
    )
    amount = models.DecimalField(**RATE, null=True, blank=True)
    currency = models.CharField(max_length=3, default=CURRENCY)
    effective_from = models.DateTimeField()
    initial = models.BooleanField(default=False)
    reason = models.TextField()
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'tutor_earnings_rates'
        ordering = ['class_type', '-effective_from']
        constraints = [
            models.CheckConstraint(condition=Q(class_type__in=ClassType.values),
                                   name='tutor_earnings_rates_known_class_type'),
            models.CheckConstraint(condition=Q(currency=CURRENCY), name='tutor_earnings_rates_inr'),
            models.CheckConstraint(condition=Q(amount__isnull=True) | Q(amount__gt=0),
                                   name='tutor_earnings_rates_positive_amount'),
            models.CheckConstraint(condition=Q(tutor__isnull=False) | Q(amount__isnull=False),
                                   name='tutor_earnings_rates_global_has_amount'),
            models.CheckConstraint(condition=Q(reason__regex=NOT_BLANK), name='tutor_earnings_rates_reason'),
            models.UniqueConstraint(fields=['class_type', 'effective_from'], condition=Q(tutor__isnull=True),
                                    name='tutor_earnings_rates_one_global_version'),
            models.UniqueConstraint(fields=['class_type', 'tutor', 'effective_from'], condition=Q(tutor__isnull=False),
                                    name='tutor_earnings_rates_one_tutor_version'),
        ]

    def __str__(self):
        whose = f'tutor {self.tutor_id}' if self.tutor_id else 'global'
        return f'{self.get_class_type_display()} {whose}: {self.amount} from {self.effective_from.isoformat()}'


class EarningsSyncRun(models.Model):
    """One run of the earnings sync (earnings.ledger.reconcile) and what it did."""

    started_at = models.DateTimeField()
    finished_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=30, choices=SyncStatus.choices)
    trigger = models.CharField(max_length=20, choices=SyncTrigger.choices, default=SyncTrigger.SCHEDULE)
    # Earnings written, eligible classes waiting for pricing, and eligible
    # classes that could not be priced (no rate in effect, or no booked length).
    earned_count = models.PositiveIntegerField(default=0)
    waiting_count = models.PositiveIntegerField(default=0)
    skipped_count = models.PositiveIntegerField(default=0)
    error = models.TextField(blank=True, default='')

    class Meta:
        db_table = 'tutor_earnings_sync_runs'
        ordering = ['-started_at']

    def __str__(self):
        return f'Earnings sync {self.started_at.isoformat()} ({self.status})'


class EarningEntry(models.Model):
    """
    One line of the ledger, never changed or removed once written.

    EARNING: one counted class (``class_type`` and ``source_id``: the session
    or booking), priced when the sync wrote it -- its units, the rate in effect
    at its scheduled end and where that rate came from -- with what made it
    count in ``details``. At most one per class, ever: a reversed earning is
    never written again.
    REVERSAL: an administrator's reversal of an earning or an adjustment, for
    its whole amount (a deduction's reversal gives it back), with the reason;
    it counts in the same month.
    ADJUSTMENT: an administrator's addition or deduction, with the reason, in
    the month chosen, for a class or none.
    ``month`` is the first day of the month it counts in: an earning's is its
    class's scheduled end, in India time.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    kind = models.CharField(max_length=20, choices=EntryKind.choices)
    tutor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='earning_entries')
    amount = models.DecimalField(**MONEY)
    currency = models.CharField(max_length=3, default=CURRENCY)
    class_type = models.CharField(max_length=20, choices=ClassType.choices, null=True, blank=True)
    source_id = models.UUIDField(null=True, blank=True)
    class_start = models.DateTimeField(null=True, blank=True)
    class_end = models.DateTimeField(null=True, blank=True)
    month = models.DateField()
    units = models.DecimalField(**UNITS, null=True, blank=True)
    rate = models.DecimalField(**RATE, null=True, blank=True)
    rate_source = models.CharField(max_length=10, choices=RateSource.choices, null=True, blank=True)
    rate_version = models.ForeignKey(
        EarningsRate, on_delete=models.PROTECT, null=True, blank=True, related_name='entries',
    )
    details = models.JSONField(default=dict, blank=True)
    reverses = models.OneToOneField(
        'self', on_delete=models.PROTECT, null=True, blank=True, related_name='reversal',
    )
    reason = models.TextField(blank=True, default='')
    # Who wrote it: an administrator's reversal or adjustment; none for an earning (the sync).
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name='+',
    )
    created_at = models.DateTimeField(default=timezone.now)
    sync_run = models.ForeignKey(
        EarningsSyncRun, on_delete=models.PROTECT, null=True, blank=True, related_name='entries',
    )

    class Meta:
        db_table = 'tutor_earning_entries'
        ordering = ['-month', '-class_end', '-created_at']
        constraints = [
            models.CheckConstraint(condition=Q(kind__in=EntryKind.values), name='tutor_earning_entries_known_kind'),
            models.CheckConstraint(condition=Q(currency=CURRENCY), name='tutor_earning_entries_inr'),
            models.CheckConstraint(condition=Q(class_type__isnull=True) | Q(class_type__in=ClassType.values),
                                   name='tutor_earning_entries_known_class_type'),
            models.CheckConstraint(condition=Q(rate_source__isnull=True) | Q(rate_source__in=RateSource.values),
                                   name='tutor_earning_entries_known_rate_source'),
            models.CheckConstraint(condition=Q(month__day=1), name='tutor_earning_entries_month_first_day'),
            # A class is named by its type and its id together, or not at all.
            models.CheckConstraint(
                condition=Q(class_type__isnull=True, source_id__isnull=True)
                | Q(class_type__isnull=False, source_id__isnull=False),
                name='tutor_earning_entries_class_named_whole',
            ),
            # What each kind of line carries. (A comparison with a NULL column
            # lets a check pass, so each one says NOT NULL as well.)
            models.CheckConstraint(
                condition=(
                    Q(kind=EntryKind.EARNING, amount__gt=0, class_type__isnull=False, source_id__isnull=False,
                      class_start__isnull=False, class_end__isnull=False, units__isnull=False, units__gt=0,
                      rate__isnull=False, rate__gt=0, rate_source__isnull=False, rate_version__isnull=False,
                      reverses__isnull=True, created_by__isnull=True, reason='')
                    | (
                        Q(kind=EntryKind.REVERSAL, reverses__isnull=False, created_by__isnull=False,
                          reason__regex=NOT_BLANK)
                        & ~Q(amount=0)
                    )
                    | (
                        Q(kind=EntryKind.ADJUSTMENT, reverses__isnull=True, created_by__isnull=False,
                          reason__regex=NOT_BLANK, units__isnull=True, rate__isnull=True, rate_source__isnull=True,
                          rate_version__isnull=True)
                        & ~Q(amount=0)
                    )
                ),
                name='tutor_earning_entries_kind_shape',
            ),
            # Every class counts once: one earning per class, ever.
            models.UniqueConstraint(fields=['class_type', 'source_id'], condition=Q(kind=EntryKind.EARNING),
                                    name='tutor_earning_entries_one_earning_per_class'),
        ]
        indexes = [
            models.Index(fields=['tutor', 'month'], name='tutor_earning_entries_month'),
            models.Index(fields=['class_type', 'source_id'], name='tutor_earning_entries_source'),
        ]

    def __str__(self):
        return f'{self.get_kind_display()} {self.amount} {self.currency} for {self.tutor_id} ({self.month:%Y-%m})'


class EarningReview(models.Model):
    """
    An administrator's "Keep as earned" on an earning that needs review -- its
    class changed after it earned (earnings.summaries.review_items) -- with the
    reason. ``seen`` is the change kept: the problem and the class as it then
    read. The earning leaves the review list while its class reads that way,
    and comes back if the class changes again. Never edited or removed.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    entry = models.ForeignKey(EarningEntry, on_delete=models.PROTECT, related_name='reviews')
    seen = models.JSONField()
    reason = models.TextField()
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'tutor_earning_reviews'
        ordering = ['-created_at']
        constraints = [
            models.CheckConstraint(condition=Q(reason__regex=NOT_BLANK), name='tutor_earning_reviews_reason'),
            # A change is kept once.
            models.UniqueConstraint(fields=['entry', 'seen'], name='tutor_earning_reviews_one_per_change'),
        ]

    def __str__(self):
        return f'Kept as earned: {self.entry_id} ({self.created_at:%Y-%m-%d})'


class TutorPayment(models.Model):
    """
    A payment an administrator made to a tutor outside Eduport Plus -- by
    account transfer or UPI -- and recorded here: never edited or deleted, and
    voided (no longer counting as paid) only with a reason. ``request_id`` is
    the recording dialog's own key, so a repeated request never records it
    twice; ``reference_key`` is the reference with only its letters and
    digits, upper-cased, and no two payments still counting share one.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    request_id = models.UUIDField(unique=True)
    tutor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='earnings_payments')
    amount = models.DecimalField(**MONEY)
    currency = models.CharField(max_length=3, default=CURRENCY)
    paid_on = models.DateField()
    method = models.CharField(max_length=20, choices=PaymentMethod.choices)
    reference = models.CharField(max_length=100)
    reference_key = models.CharField(max_length=100)
    notes = models.TextField(blank=True, default='')
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    recorded_at = models.DateTimeField(default=timezone.now)
    voided_at = models.DateTimeField(null=True, blank=True)
    voided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name='+',
    )
    void_reason = models.TextField(blank=True, default='')

    class Meta:
        db_table = 'tutor_earnings_payments'
        ordering = ['-paid_on', '-recorded_at']
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name='tutor_earnings_payments_positive_amount'),
            models.CheckConstraint(condition=Q(currency=CURRENCY), name='tutor_earnings_payments_inr'),
            models.CheckConstraint(condition=Q(method__in=PaymentMethod.values),
                                   name='tutor_earnings_payments_known_method'),
            models.CheckConstraint(condition=Q(reference__regex=NOT_BLANK), name='tutor_earnings_payments_reference'),
            models.CheckConstraint(condition=Q(reference_key__regex=r'^[A-Z0-9]+$'),
                                   name='tutor_earnings_payments_reference_key'),
            models.CheckConstraint(
                condition=Q(voided_at__isnull=True, voided_by__isnull=True, void_reason='')
                | Q(voided_at__isnull=False, voided_by__isnull=False, void_reason__regex=NOT_BLANK),
                name='tutor_earnings_payments_void_whole',
            ),
            models.UniqueConstraint(fields=['reference_key'], condition=Q(voided_at__isnull=True),
                                    name='tutor_earnings_payments_one_live_reference'),
        ]
        indexes = [models.Index(fields=['tutor', 'paid_on'], name='tutor_payments_paid_on')]

    def __str__(self):
        state = ' (voided)' if self.voided_at else ''
        return f'{self.amount} {self.currency} to {self.tutor_id} on {self.paid_on}{state}'
