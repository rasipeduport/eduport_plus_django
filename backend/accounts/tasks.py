"""
Scheduled housekeeping for the database session store.

Expired sessions are not deleted when they expire -- Django only ignores them
-- so `clearsessions` must run periodically or the table grows without bound.
Scheduled daily by Celery beat (settings.CELERY_BEAT_SCHEDULE).
"""
import logging

from celery import shared_task
from django.core.management import call_command

logger = logging.getLogger(__name__)


@shared_task(name='accounts.tasks.clear_expired_sessions')
def clear_expired_sessions():
    call_command('clearsessions')
    logger.info('Expired sessions cleared.')
