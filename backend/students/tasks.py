"""
Background jobs for the students app.

Thin by design: the work lives in ``students.quota_sync`` so that the Celery
beat schedule and ``manage.py sync_student_quotas`` run exactly the same code.
"""
import logging

from celery import shared_task

from .quota_sync import sync_student_quotas_from_sheet

logger = logging.getLogger(__name__)


@shared_task(name='students.tasks.sync_student_quotas')
def sync_student_quotas():
    """
    Scheduled enrolment-sheet quota sync (see ``settings.CELERY_BEAT_SCHEDULE``).

    Deliberately does not retry. ``sync_student_quotas_from_sheet`` already
    treats an unreadable sheet as "change nothing", and the schedule fires
    again shortly, so a retry storm against the Google API would buy nothing.
    The returned dict carries ``failed``/``error`` for anything watching task
    results.
    """
    report = sync_student_quotas_from_sheet()
    if report.failed:
        logger.error("Scheduled quota sync failed: %s", report.error)
    return report.as_dict()
