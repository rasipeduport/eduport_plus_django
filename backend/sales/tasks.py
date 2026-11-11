from celery import shared_task


@shared_task
def provision_billing_subscription(agreement_id):
    from .billing import provision
    provision(agreement_id)


@shared_task
def collect_due_autopay_installments():
    from .autopay import collect_due
    collect_due()


@shared_task
def sync_stripe_student_metadata():
    from .payment_models import StripeCustomer
    from .stripe_gateway import sync_customer_metadata
    for enquiry_id in StripeCustomer.objects.filter(student_metadata_synced=False, customer_id__isnull=False, enquiry__initial_sale__student__isnull=False).values_list('enquiry_id', flat=True):
        sync_customer_metadata(enquiry_id)
