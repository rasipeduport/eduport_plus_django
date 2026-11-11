"""One shared, purchase-based Autopay lifecycle; initial BDE setup is its first caller."""
import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone


class AutopayAgreement(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    purchase = models.OneToOneField('sales.Purchase', on_delete=models.PROTECT, related_name='autopay')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='created_autopay_agreements')
    creator_role = models.CharField(max_length=20)
    source = models.CharField(max_length=30, default='BDE_INITIAL')
    billing_timezone = models.CharField(max_length=64)
    terms_url = models.URLField(max_length=2048)
    consent_text = models.TextField()
    schedule_digest = models.CharField(max_length=64)
    status = models.CharField(max_length=30, default='WAITING_INITIAL')
    setup_status = models.CharField(max_length=30, default='PENDING')
    setup_message = models.CharField(max_length=255, blank=True)
    stripe_customer_id = models.CharField(max_length=255, blank=True)
    stripe_payment_method_id = models.CharField(max_length=255, blank=True)
    card_brand = models.CharField(max_length=30, blank=True)
    card_last4 = models.CharField(max_length=4, blank=True)
    livemode = models.BooleanField(default=False)
    initial_paid_at = models.DateTimeField(null=True, blank=True)
    consent_verified_at = models.DateTimeField(null=True, blank=True)
    ready_at = models.DateTimeField(null=True, blank=True)
    # Existing agreements stay on their original engine until explicitly migrated.
    collection_engine = models.CharField(max_length=20, default='LEGACY_PI', choices=[('LEGACY_PI', 'Historical PaymentIntents'), ('STRIPE_BILLING', 'Stripe Billing')])
    stripe_subscription_id = models.CharField(max_length=255, null=True, blank=True, unique=True)
    stripe_schedule_id = models.CharField(max_length=255, null=True, blank=True, unique=True)
    stripe_product_id = models.CharField(max_length=255, blank=True)
    stripe_subscription_status = models.CharField(max_length=30, blank=True)
    stripe_schedule_status = models.CharField(max_length=30, blank=True)
    billing_status = models.CharField(max_length=30, default='NOT_PROVISIONED')
    billing_message = models.CharField(max_length=255, blank=True)
    billing_issue_scope = models.CharField(max_length=20, blank=True)
    billing_request = models.JSONField(default=dict, blank=True)
    provisioning_started_at = models.DateTimeField(null=True, blank=True)
    provisioning_generation = models.PositiveIntegerField(default=0)
    provisioning_key_started_at = models.DateTimeField(null=True, blank=True)
    provisioning_rejection_verified = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now, editable=False)


class AutopayInstallment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    agreement = models.ForeignKey(AutopayAgreement, on_delete=models.PROTECT, related_name='installments')
    # Position zero is the initial, on-session tuition payment.
    position = models.PositiveIntegerField()
    classes = models.DecimalField(max_digits=9, decimal_places=1)
    amount = models.DecimalField(max_digits=15, decimal_places=0)
    due_at = models.DateTimeField(null=True, blank=True)
    payment = models.OneToOneField('sales.Payment', on_delete=models.PROTECT, null=True, blank=True, related_name='autopay_installment')
    status = models.CharField(max_length=30, default='SCHEDULED')
    paid_at = models.DateTimeField(null=True, blank=True)
    stripe_invoice_id = models.CharField(max_length=255, null=True, blank=True, unique=True)
    stripe_invoice_status = models.CharField(max_length=30, blank=True)
    stripe_invoice_number = models.CharField(max_length=255, blank=True)
    stripe_invoice_url = models.URLField(max_length=2048, blank=True)
    stripe_next_payment_attempt = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['position']
        constraints = [
            models.UniqueConstraint(fields=['agreement', 'position'], name='autopay_position_once'),
            models.UniqueConstraint(fields=['agreement', 'due_at'], name='autopay_due_once'),
            models.CheckConstraint(condition=Q(classes__gt=0, amount__gt=0), name='autopay_positive_allocation'),
            models.CheckConstraint(condition=Q(position=0, due_at__isnull=True) | Q(position__gt=0, due_at__isnull=False), name='autopay_initial_or_dated'),
        ]


class AutopayAttempt(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    installment = models.ForeignKey(AutopayInstallment, on_delete=models.PROTECT, related_name='attempts')
    number = models.PositiveIntegerField()
    status = models.CharField(max_length=30, default='SUBMITTING')
    stripe_payment_intent_id = models.CharField(max_length=255, blank=True, db_index=True)
    stripe_checkout_id = models.CharField(max_length=255, null=True, blank=True, unique=True)
    checkout_url = models.URLField(max_length=2048, blank=True)
    error_code = models.CharField(max_length=100, blank=True)
    provider_attempt_key = models.CharField(max_length=255, null=True, blank=True, unique=True)
    stripe_invoice_payment_id = models.CharField(max_length=255, blank=True)
    stripe_charge_id = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['number']
        constraints = [models.UniqueConstraint(fields=['installment', 'number'], name='autopay_attempt_number_once')]
