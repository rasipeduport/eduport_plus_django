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
    # Retries Customer label pushes (student name, guardian contact, EDP ID).
    from .customers import sync_pending
    sync_pending()
