"""Additional hours with deferred payment (sales.additional_hours).

An administrator gives an enrolled student more hours of class quota at once,
for an agreed amount collected later -- by an administrator or the student's
mentor, in as many payments as it takes. The hours count from the moment the
allocation is saved; its due date is when the money should be in, never when
the hours start.

These rows are a ledger of their own. The regular plan ledger -- sale,
purchase, payment, Autopay -- is never written: an allocation only names the
purchase (and, for reference, the chapter) the hours were given against, and
its payments never change the quota. Database triggers (sales.0022) keep both
tables append-only: an allocation changes only its amount, due date and its
one closing (waived, or its hours withdrawn); a payment only by being voided,
once.
"""
import uuid
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import F, Q, Value
from django.db.models.functions import Mod
from django.db.models.lookups import Exact
from django.utils import timezone

from .payment_models import PaymentMethod

# Hours are quota hours (1 plan class = 1 hour of quota), in half hours: the shortest session is half an hour.
HOUR_STEP = Decimal('0.5')
MAX_HOURS = Decimal('50')
MAX_AMOUNT = Decimal('1000000')
REASON_MAX_LENGTH = 1000
NOTES_MAX_LENGTH = 1000
REFERENCE_MAX_LENGTH = 255
NOT_BLANK = r'\S'
# Money received directly, with its receipt: the regular ledger's own methods, without Stripe.
DIRECT_METHODS = ('TRANSFER', 'AJAS_UAE', 'AJAS_INDIA')
DIRECT_METHOD_CHOICES = [(method.value, method.label) for method in PaymentMethod if method.value in DIRECT_METHODS]
# And Stripe: paid through a Checkout link generated for the hours, recorded only by its verified webhook.
STRIPE = 'STRIPE'
METHODS = (*DIRECT_METHODS, STRIPE)
METHOD_CHOICES = [*DIRECT_METHOD_CHOICES, (STRIPE, 'Stripe')]


class VoidKind(models.TextChoices):
    ERROR = 'ERROR', 'Recorded in error'
    REFUNDED = 'REFUNDED', 'Refunded to the payer'
    REVERSED = 'REVERSED', 'Reversed or bounced'


def _half_hours(field):
    step = Value(HOUR_STEP, output_field=models.DecimalField(max_digits=2, decimal_places=1))
    return Q(**{f'{field}__gt': 0, f'{field}__lte': MAX_HOURS}) & Q(Exact(Mod(F(field), step), 0))


class AdditionalHoursAllocation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # AH-000001 onwards (sales.enrollment.next_number).
    reference = models.CharField(max_length=20, unique=True, editable=False)
    # The dialog's own key: a repeated request answers with the allocation it made, never credits twice.
    request_id = models.UUIDField(unique=True)
    student = models.ForeignKey('students.Student', on_delete=models.PROTECT, related_name='additional_hours')
    # The plan the hours were given against: one of the student's own purchases.
    purchase = models.ForeignKey('sales.Purchase', on_delete=models.PROTECT, related_name='additional_hours')
    # For reference only: the hours join the student's overall quota, whatever the chapter.
    chapter = models.ForeignKey('sales.SyllabusChapter', on_delete=models.PROTECT, null=True, blank=True,
                                related_name='additional_hours')
    hours = models.DecimalField(max_digits=5, decimal_places=1)
    amount = models.DecimalField(max_digits=15, decimal_places=0)
    currency = models.CharField(max_length=3, default='AED')
    due_date = models.DateField()
    reason = models.TextField()
    # The quota the hours were added to; after them it was quota_before + hours (checked as the row is written).
    quota_before = models.DecimalField(max_digits=9, decimal_places=1)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    # Waived: the hours stay, what is still unpaid is written off.
    waived_at = models.DateTimeField(null=True, blank=True)
    waived_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name='+')
    waive_reason = models.TextField(blank=True, default='')
    # Withdrawn: the hours leave the quota again (unused, and nothing paid that still counts).
    withdrawn_at = models.DateTimeField(null=True, blank=True)
    withdrawn_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name='+')
    withdraw_reason = models.TextField(blank=True, default='')
    withdrawn_quota_before = models.DecimalField(max_digits=9, decimal_places=1, null=True, blank=True)

    class Meta:
        db_table = 'sales_additional_hours'
        ordering = ['-created_at', '-id']
        indexes = [
            models.Index(fields=['student', '-created_at'], name='sales_additional_hours_student'),
            models.Index(fields=['due_date'], name='sales_additional_hours_due'),
        ]
        constraints = [
            models.CheckConstraint(condition=_half_hours('hours'), name='sales_additional_hours_half_hours'),
            models.CheckConstraint(condition=Q(amount__gt=0, amount__lte=MAX_AMOUNT, currency='AED'),
                                   name='sales_additional_hours_positive_aed'),
            models.CheckConstraint(condition=Q(reason__regex=NOT_BLANK), name='sales_additional_hours_reason'),
            models.CheckConstraint(condition=Q(quota_before__gte=0), name='sales_additional_hours_quota_before'),
            models.CheckConstraint(
                condition=Q(waived_at__isnull=True, waived_by__isnull=True, waive_reason='')
                | Q(waived_at__isnull=False, waived_by__isnull=False, waive_reason__regex=NOT_BLANK),
                name='sales_additional_hours_waive_whole'),
            models.CheckConstraint(
                condition=Q(withdrawn_at__isnull=True, withdrawn_by__isnull=True, withdraw_reason='',
                            withdrawn_quota_before__isnull=True)
                | Q(withdrawn_at__isnull=False, withdrawn_by__isnull=False, withdraw_reason__regex=NOT_BLANK,
                    withdrawn_quota_before__isnull=False),
                name='sales_additional_hours_withdraw_whole'),
            models.CheckConstraint(condition=Q(waived_at__isnull=True) | Q(withdrawn_at__isnull=True),
                                   name='sales_additional_hours_one_closing'),
        ]


class CheckoutStatus(models.TextChoices):
    PREPARED = 'PREPARED', 'Prepared'
    SUBMITTING = 'SUBMITTING', 'Being created at Stripe'
    UNKNOWN = 'UNKNOWN', 'Awaiting Stripe confirmation'
    OPEN = 'OPEN', 'Open'
    PAID = 'PAID', 'Paid'
    EXPIRED = 'EXPIRED', 'Expired'
    FAILED = 'FAILED', 'Failed'
    REQUIRES_REVIEW = 'REQUIRES_REVIEW', 'Needs review'


# A link still live, or one Stripe may still have created: at most one per allocation.
LIVE_CHECKOUT = ('PREPARED', 'SUBMITTING', 'UNKNOWN', 'OPEN')


class AdditionalHoursCheckout(models.Model):
    """
    One Stripe Checkout Session for part or all of what an allocation still owes
    (sales.additional_hours_stripe): its request frozen before Stripe is called,
    created with its own idempotency key, and settled only by Stripe's signed
    webhook, which records the payment. Never a reusable Payment Link.
    """
    # The generating dialog's own key: a repeated request reuses this attempt.
    id = models.UUIDField(primary_key=True, editable=False)
    allocation = models.ForeignKey(AdditionalHoursAllocation, on_delete=models.PROTECT, related_name='checkouts')
    amount = models.DecimalField(max_digits=15, decimal_places=0)
    currency = models.CharField(max_length=3, default='AED')
    status = models.CharField(max_length=20, choices=CheckoutStatus.choices, default=CheckoutStatus.PREPARED)
    livemode = models.BooleanField()
    request = models.JSONField()
    idempotency_key = models.CharField(max_length=255, unique=True)
    stripe_customer_id = models.CharField(max_length=255, blank=True, default='')
    stripe_checkout_id = models.CharField(max_length=255, unique=True, null=True, blank=True)
    checkout_url = models.URLField(max_length=2048, blank=True, default='')
    stripe_payment_intent_id = models.CharField(max_length=255, unique=True, null=True, blank=True)
    # Why it failed, or what an administrator must review.
    message = models.CharField(max_length=255, blank=True, default='')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    started_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'sales_additional_hours_checkouts'
        ordering = ['-created_at', '-id']
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0, amount__lte=MAX_AMOUNT, currency='AED'),
                                   name='sales_additional_hours_checkout_positive_aed'),
            models.CheckConstraint(condition=Q(status__in=CheckoutStatus.values), name='sales_additional_hours_checkout_status'),
            models.CheckConstraint(condition=~Q(status='PAID') | Q(stripe_checkout_id__isnull=False, stripe_payment_intent_id__isnull=False),
                                   name='sales_additional_hours_checkout_paid_evidence'),
            # One live link per allocation: two links paid together could never both fit what is owed.
            models.UniqueConstraint(fields=['allocation'], condition=Q(status__in=LIVE_CHECKOUT),
                                    name='sales_additional_hours_one_live_checkout'),
        ]


def proof_path(instance, filename):
    return f'additional-hours-proofs/{instance.allocation_id}/{uuid.uuid4().hex}{instance.proof_extension}'


class AdditionalHoursPayment(models.Model):
    """Money received against an allocation, with its receipt. Never edited or deleted: voided, once, with a reason."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    request_id = models.UUIDField(unique=True)
    allocation = models.ForeignKey(AdditionalHoursAllocation, on_delete=models.PROTECT, related_name='payments')
    amount = models.DecimalField(max_digits=15, decimal_places=0)
    currency = models.CharField(max_length=3, default='AED')
    method = models.CharField(max_length=10, choices=METHOD_CHOICES)
    payment_date = models.DateField()
    transaction_reference = models.CharField(max_length=REFERENCE_MAX_LENGTH, blank=True, default='')
    # The reference as compared: its letters and digits alone, upper-cased ('' when there is none).
    reference_key = models.CharField(max_length=REFERENCE_MAX_LENGTH, blank=True, default='')
    # A direct payment's: its recorder confirms it was received, with the receipt.
    received_confirmed = models.BooleanField(default=False)
    proof = models.FileField(upload_to=proof_path, max_length=512, blank=True)
    proof_name = models.CharField(max_length=255, blank=True)
    proof_content_type = models.CharField(max_length=100, blank=True)
    proof_extension = models.CharField(max_length=10, blank=True)
    notes = models.TextField(blank=True, default='')
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    recorded_at = models.DateTimeField(default=timezone.now, editable=False)
    voided_at = models.DateTimeField(null=True, blank=True)
    voided_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name='+')
    void_kind = models.CharField(max_length=10, blank=True, default='', choices=VoidKind.choices)
    void_reason = models.TextField(blank=True, default='')
    # A Stripe payment's: the Checkout that took it and Stripe's own references. Evidence, set once.
    checkout = models.OneToOneField(AdditionalHoursCheckout, on_delete=models.PROTECT, null=True, blank=True,
                                    related_name='payment')
    stripe_checkout_id = models.CharField(max_length=255, unique=True, null=True, blank=True)
    stripe_payment_intent_id = models.CharField(max_length=255, unique=True, null=True, blank=True)
    stripe_charge_id = models.CharField(max_length=255, blank=True, default='')
    # Who paid, as Stripe reported it (name, email, card brand/last4). Evidence only.
    payer_details = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = 'sales_additional_hours_payments'
        ordering = ['recorded_at', 'id']
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0, currency='AED'), name='sales_additional_hours_payment_positive_aed'),
            models.CheckConstraint(condition=Q(method__in=METHODS), name='sales_additional_hours_payment_known_method'),
            # A direct payment carries its receipt and its recorder's confirmation; a Stripe payment, the Checkout and
            # PaymentIntent Stripe's verified webhook named -- and no receipt.
            models.CheckConstraint(
                condition=(Q(method__in=DIRECT_METHODS, received_confirmed=True, checkout__isnull=True, stripe_checkout_id__isnull=True,
                             stripe_payment_intent_id__isnull=True) & ~Q(proof=''))
                | Q(method=STRIPE, proof='', checkout__isnull=False, stripe_checkout_id__isnull=False,
                    stripe_payment_intent_id__isnull=False),
                name='sales_additional_hours_payment_evidence'),
            models.CheckConstraint(condition=Q(reference_key='') | Q(reference_key__regex=r'^[A-Z0-9]+$'),
                                   name='sales_additional_hours_payment_reference_key'),
            models.CheckConstraint(
                condition=Q(voided_at__isnull=True, voided_by__isnull=True, void_kind='', void_reason='')
                | Q(voided_at__isnull=False, voided_by__isnull=False, void_kind__in=VoidKind.values,
                    void_reason__regex=NOT_BLANK),
                name='sales_additional_hours_payment_void_whole'),
            # The same receipt is never counted twice on one allocation.
            models.UniqueConstraint(fields=['allocation', 'reference_key'],
                                    condition=Q(voided_at__isnull=True) & ~Q(reference_key=''),
                                    name='sales_additional_hours_payment_one_live_reference'),
        ]
