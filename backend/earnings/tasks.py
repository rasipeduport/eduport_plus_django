"""
Background jobs for Tutor Earnings.

Thin by design: the work lives in ``earnings.ledger`` so that the Celery beat
schedule and ``manage.py reconcile_tutor_earnings`` run exactly the same code.
"""
from celery import shared_task

from .ledger import reconcile
from .models import SyncTrigger


@shared_task(name='earnings.tasks.reconcile_tutor_earnings')
def reconcile_tutor_earnings():
    """
    The scheduled earnings sync (see ``settings.CELERY_BEAT_SCHEDULE``):
    eligible classes with no earning yet are priced and added to the ledger.
    Deliberately does not retry -- the next tick, ten minutes on, picks up
    whatever this one missed, and nothing is ever earned twice.
    """
    run = reconcile(trigger=SyncTrigger.SCHEDULE)
    if run is None:
        return {'ran': False}
    return {'ran': True, 'status': run.status, 'earned': run.earned_count, 'waiting': run.waiting_count,
            'skipped': run.skipped_count}
