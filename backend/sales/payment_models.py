"""Initial admission ledger. Quotes remain immutable; payments survive enrollment."""
import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone


class SaleKind(models.TextChoices):
    NEW = 'NEW', 'New Sale'
    TOKEN = 'TOKEN', 'Token Sale'


class CollectionMode(models.TextChoices):
    FULL = 'FULL', 'Full payment'
    PARTIAL = 'PARTIAL', 'Partial payment'


class PaymentMethod(models.TextChoices):
    STRIPE = 'STRIPE', 'Stripe'
    TRANSFER = 'TRANSFER', 'Account Transfer'
    AJAS_UAE = 'AJAS_UAE', 'AJAS – CEO UAE Account'
    AJAS_INDIA = 'AJAS_INDIA', 'AJAS – CEO Indian Account'


class PaymentStatus(models.TextChoices):
    PENDING = 'PENDING', 'Pending'
    SUCCEEDED = 'SUCCEEDED', 'Received'
    FAILED = 'FAILED', 'Failed'
    EXPIRED = 'EXPIRED', 'Expired'


class SalesSequence(models.Model):
    name = models.CharField(max_length=20, primary_key=True)
    value = models.PositiveBigIntegerField(default=0)


class Sale(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    enquiry = models.OneToOneField('bookings.Lead', on_delete=models.PROTECT, related_name='initial_sale')
    original_bde = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='originated_sales')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='created_sales')
    kind = models.CharField(max_length=5, choices=SaleKind.choices)
    original_quote = models.ForeignKey('sales.Quote', on_delete=models.PROTECT, null=True, blank=True, related_name='original_sales')
    student = models.OneToOneField('students.Student', on_delete=models.PROTECT, null=True, blank=True, related_name='initial_sale')
    reservation_reference = models.CharField(max_length=30, unique=True, null=True, blank=True)
    expected_start_date = models.DateField(null=True, blank=True)
    parent_email = models.EmailField(blank=True)
    enrolled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(kind='NEW') | Q(kind='TOKEN', expected_start_date__isnull=False, reservation_reference__isnull=False), name='sales_token_has_date_reference'),
            models.CheckConstraint(condition=Q(student__isnull=True, enrolled_at__isnull=True) | Q(student__isnull=False, enrolled_at__isnull=False), name='sales_enrollment_fields_together'),
        ]


class Purchase(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    sale = models.ForeignKey(Sale, on_delete=models.PROTECT, related_name='purchases')
    is_initial = models.BooleanField(default=True)
    quote = models.OneToOneField('sales.Quote', on_delete=models.PROTECT, related_name='purchase')
    student = models.ForeignKey('students.Student', on_delete=models.PROTECT, null=True, blank=True, related_name='purchases')
    collection_mode = models.CharField(max_length=7, choices=CollectionMode.choices)
    classes = models.DecimalField(max_digits=9, decimal_places=1)
    # Whole AED, rounded once from the quote, never from current pricing.
    amount = models.DecimalField(max_digits=15, decimal_places=0)
    currency = models.CharField(max_length=3, default='AED')
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(classes__gt=0, amount__gt=0, currency='AED'), name='sales_purchase_positive_aed'),
            models.CheckConstraint(condition=Q(collection_mode__in=CollectionMode.values), name='sales_purchase_collection_mode'),
            models.UniqueConstraint(fields=['sale'], condition=Q(is_initial=True), name='sales_one_initial_purchase'),
        ]


class StripeCustomer(models.Model):
    enquiry = models.OneToOneField('bookings.Lead', on_delete=models.PROTECT, primary_key=True, related_name='stripe_customer')
    customer_id = models.CharField(max_length=255, unique=True, null=True, blank=True)
    livemode = models.BooleanField(default=False)
    student_metadata_synced = models.BooleanField(default=False)
    creation_request = models.JSONField(default=dict, blank=True)
    creation_started_at = models.DateTimeField(null=True, blank=True)


def proof_path(instance, filename):
    return f'payment-proofs/{instance.id}/{uuid.uuid4().hex}{instance.proof_extension}'


class Payment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    request_id = models.UUIDField(unique=True)
    sale = models.ForeignKey(Sale, on_delete=models.PROTECT, related_name='payments')
    purchase = models.ForeignKey(Purchase, on_delete=models.PROTECT, null=True, blank=True, related_name='payments')
    purpose = models.CharField(max_length=7, choices=[('TOKEN', 'Token'), ('TUITION', 'Tuition')])
    method = models.CharField(max_length=10, choices=PaymentMethod.choices)
    collection_mode = models.CharField(max_length=7, choices=CollectionMode.choices)
    amount = models.DecimalField(max_digits=15, decimal_places=0)
    currency = models.CharField(max_length=3, default='AED')
    classes = models.DecimalField(max_digits=9, decimal_places=1, default=0)
    status = models.CharField(max_length=10, choices=PaymentStatus.choices, default=PaymentStatus.PENDING)
    payment_date = models.DateField(default=timezone.localdate)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='recorded_payments')
    collection_scope = models.CharField(max_length=20, default='INITIAL', choices=[('INITIAL', 'Initial/legacy collection'), ('BILLING_INSTALLMENT', 'Stripe Billing installment')])
    transaction_reference = models.CharField(max_length=255, blank=True)
    received_confirmed = models.BooleanField(default=False)
    proof = models.FileField(upload_to=proof_path, max_length=512, blank=True)
    proof_name = models.CharField(max_length=255, blank=True)
    proof_content_type = models.CharField(max_length=100, blank=True)
    proof_extension = models.CharField(max_length=10, blank=True)
    stripe_checkout_id = models.CharField(max_length=255, null=True, blank=True, unique=True)
    stripe_payment_intent = models.CharField(max_length=255, null=True, blank=True, unique=True)
    stripe_customer_id = models.CharField(max_length=255, blank=True)
    payment_url = models.URLField(max_length=2048, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ['created_at', 'id']
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0, currency='AED', classes__gte=0), name='sales_payment_positive_aed'),
            models.CheckConstraint(condition=Q(status__in=PaymentStatus.values), name='sales_payment_known_status'),
            models.CheckConstraint(condition=Q(method__in=PaymentMethod.values), name='sales_payment_known_method'),
            models.CheckConstraint(condition=Q(collection_mode__in=CollectionMode.values), name='sales_payment_collection_mode'),
            models.CheckConstraint(condition=Q(purpose='TOKEN', classes=0, amount=100, purchase__isnull=True) | Q(purpose='TUITION', classes__gt=0, purchase__isnull=False), name='sales_payment_allocation_shape'),
            models.UniqueConstraint(fields=['sale'], condition=Q(status='PENDING', collection_scope='INITIAL'), name='sales_one_pending_initial'),
            models.CheckConstraint(condition=Q(collection_scope='INITIAL') | Q(collection_scope='BILLING_INSTALLMENT', purpose='TUITION', purchase__isnull=False), name='sales_payment_collection_scope'),
            models.UniqueConstraint(fields=['sale'], condition=Q(purpose='TOKEN', status='SUCCEEDED'), name='sales_one_received_token'),
        ]


class StripeEvent(models.Model):
    event_id = models.CharField(max_length=255, primary_key=True)
    event_type = models.CharField(max_length=100)
    object_id = models.CharField(max_length=255, blank=True)
    outcome = models.CharField(max_length=20, default='RECEIVED')
    error = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)


class StripeCheckoutOperation(models.Model):
    """Durable initial Checkout request; never a recurring collection engine."""
    id = models.UUIDField(primary_key=True, editable=False)
    payment = models.ForeignKey(Payment, on_delete=models.PROTECT, related_name='checkout_operations')
    livemode = models.BooleanField()
    idempotency_key = models.CharField(max_length=255, unique=True)
    # Customer is resolved from the durable enquiry mapping before dispatch.
    request = models.JSONField()
    status = models.CharField(max_length=30, default='PREPARED')
    message = models.CharField(max_length=255, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    stripe_checkout_id = models.CharField(max_length=255, null=True, blank=True, unique=True)
    checkout_url = models.URLField(max_length=2048, blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
