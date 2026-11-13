"""Provider-side money movements recorded against the immutable payment ledger.

Refunds and disputes never edit a Payment, never change class quota and never
change a Sale's agreed amount. Stripe objects that cannot be attributed to a
Django payment or agreement go to the review queue instead of being dropped.
"""
import uuid
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

# Stripe minor units per currency (https://docs.stripe.com/currencies).
ZERO_DECIMAL = {'bif', 'clp', 'djf', 'gnf', 'jpy', 'kmf', 'krw', 'mga', 'pyg', 'rwf', 'ugx', 'vnd', 'vuv', 'xaf', 'xof', 'xpf'}
THREE_DECIMAL = {'bhd', 'jod', 'kwd', 'omr', 'tnd'}


def from_minor(amount, currency):
    """Exact Decimal from a Stripe integer amount; never a float."""
    currency = (currency or '').lower()
    places = 0 if currency in ZERO_DECIMAL else 3 if currency in THREE_DECIMAL else 2
    return Decimal(int(amount)).scaleb(-places)


class Refund(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    payment = models.ForeignKey('sales.Payment', on_delete=models.PROTECT, related_name='refunds')
    stripe_refund_id = models.CharField(max_length=255, unique=True)
    stripe_charge_id = models.CharField(max_length=255, blank=True)
    stripe_payment_intent_id = models.CharField(max_length=255, blank=True)
    amount = models.DecimalField(max_digits=15, decimal_places=3)
    currency = models.CharField(max_length=3)
    status = models.CharField(max_length=30)
    reason = models.CharField(max_length=100, blank=True)
    failure_reason = models.CharField(max_length=100, blank=True)
    stripe_created_at = models.DateTimeField()
    # Class entitlements are never reversed automatically. A business policy
    # must be approved before any other value is allowed.
    classes_effect = models.CharField(max_length=10, default='NONE')
    recorded_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['stripe_created_at', 'id']
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name='sales_refund_positive'),
            models.CheckConstraint(condition=Q(classes_effect='NONE'), name='sales_refund_no_class_effect'),
        ]


class Dispute(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    payment = models.ForeignKey('sales.Payment', on_delete=models.PROTECT, related_name='disputes')
    stripe_dispute_id = models.CharField(max_length=255, unique=True)
    stripe_charge_id = models.CharField(max_length=255, blank=True)
    stripe_payment_intent_id = models.CharField(max_length=255, blank=True)
    amount = models.DecimalField(max_digits=15, decimal_places=3)
    currency = models.CharField(max_length=3)
    status = models.CharField(max_length=40)
    reason = models.CharField(max_length=100, blank=True)
    evidence_due_by = models.DateTimeField(null=True, blank=True)
    stripe_created_at = models.DateTimeField()
    closed_at = models.DateTimeField(null=True, blank=True)
    recorded_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['stripe_created_at', 'id']


class ReviewKind(models.TextChoices):
    INCONSISTENT = 'INCONSISTENT', 'Rejected: does not match its Django record'
    PAYMENT_LINK_PAYMENT = 'PAYMENT_LINK_PAYMENT', 'Payment through a Stripe Payment Link'
    PAYMENT_LINK_CREATED = 'PAYMENT_LINK_CREATED', 'Stripe Payment Link created or changed'
    UNMATCHED_CHECKOUT = 'UNMATCHED_CHECKOUT', 'Checkout payment not created by Django'
    UNMATCHED_INVOICE = 'UNMATCHED_INVOICE', 'Invoice paid outside a Django agreement'
    UNMATCHED_SUBSCRIPTION = 'UNMATCHED_SUBSCRIPTION', 'Subscription not created by Django'
    UNMATCHED_PAYMENT = 'UNMATCHED_PAYMENT', 'Payment not created by Django'
    UNMATCHED_REFUND = 'UNMATCHED_REFUND', 'Refund of an unknown payment'
    UNMATCHED_DISPUTE = 'UNMATCHED_DISPUTE', 'Dispute of an unknown payment'


class StripeReviewItem(models.Model):
    """Stripe activity Django could not attribute or validate. Never credited."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event = models.OneToOneField('sales.StripeEvent', on_delete=models.PROTECT, null=True, blank=True, related_name='review')
    source = models.CharField(max_length=20, default='WEBHOOK', choices=[('WEBHOOK', 'Webhook'), ('RECONCILIATION', 'Reconciliation')])
    kind = models.CharField(max_length=30, choices=ReviewKind.choices)
    object_type = models.CharField(max_length=60, blank=True)
    object_id = models.CharField(max_length=255, blank=True)
    customer_id = models.CharField(max_length=255, blank=True)
    payment_link_id = models.CharField(max_length=255, blank=True)
    amount = models.DecimalField(max_digits=15, decimal_places=3, null=True, blank=True)
    currency = models.CharField(max_length=3, blank=True)
    livemode = models.BooleanField(default=False)
    summary = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=10, default='OPEN', choices=[('OPEN', 'Open'), ('LINKED', 'Linked to a student'), ('DISMISSED', 'Dismissed')])
    # LINKED records an association for history only: it never creates a
    # Payment, credits classes or moves money between students.
    account = models.ForeignKey('sales.StudentAccount', on_delete=models.PROTECT, null=True, blank=True, related_name='review_items')
    resolution_note = models.TextField(blank=True)
    resolved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name='+')
    resolved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(fields=['kind', 'object_id'], condition=~Q(object_id=''), name='sales_review_once_per_object'),
            models.CheckConstraint(condition=Q(status='OPEN', resolved_at__isnull=True) | Q(status__in=['LINKED', 'DISMISSED'], resolved_at__isnull=False),
                                   name='sales_review_resolution_fields'),
            models.CheckConstraint(condition=~Q(status='LINKED') | Q(account__isnull=False), name='sales_review_linked_account'),
        ]
