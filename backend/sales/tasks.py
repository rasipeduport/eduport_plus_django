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


@shared_task
def recover_missed_stripe_events():
    # Events the webhook never delivered, processed by its own handler (event_backfill).
    from communications.tasks import single_run
    from .event_backfill import run
    from .payments import stripe_configured
    if not stripe_configured():
        return {'skipped': 'Stripe is not configured'}
    with single_run('recover_missed_stripe_events') as only_run:
        if not only_run:
            return {'skipped': 'another run is in progress'}
        return run()
