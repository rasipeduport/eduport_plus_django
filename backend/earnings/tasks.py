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


@shared_task(name='earnings.tasks.check_demo_conversion')
def check_demo_conversion(lead_id):
    """
    A lead's Demo conversion check, asked for when its Demo's slot ends
    (earnings.hooks): the Demo was reported before the slot ended, so it
    counts only now. Never asks again -- the sync is the backup -- and, like
    the sync, never retries.
    """
    from .hooks import check_conversion
    result = check_conversion(lead_id, schedule=False)
    return {'checked': result is not None, 'converted': bool(result and result.conversion)}
