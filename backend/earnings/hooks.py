"""
Where the rest of Eduport Plus tells Tutor Earnings that a Demo conversion may
now be due -- the two moments that can complete one, whichever comes second:

- an enrollment recorded: sales.enrollment.enroll, the one step every first
  verified tuition payment takes, however it was verified (a direct receipt,
  Stripe Checkout, AutoPay);
- a Demo's report submitted: reports.services.submit_report.

Each asks for its lead's conversion check (earnings.ledger.record_conversion)
once its own transaction commits -- never inside it, so a payment or a report
never waits for an earning, nor fails because of one, nor is undone with one.
The check runs at once, in the same process. A Demo reported before its slot
ends counts only once the slot ends: the check is asked again then, by a
Celery task (check_demo_conversion). Whatever a check cannot do -- a sync
under way for too long, a database error, no broker -- is logged and left to
the 10-minute sync, which writes the same rows; nothing is ever written twice.
"""
import logging

from django.db import transaction

from . import ledger

logger = logging.getLogger(__name__)


def conversion_may_be_due(lead_id):
    """Check ``lead_id``'s Demo conversion once the current transaction commits (at once, outside one)."""
    transaction.on_commit(lambda: check_conversion(lead_id), robust=True)


def check_conversion(lead_id, schedule=True):
    """
    ``lead_id``'s conversion check (earnings.ledger.record_conversion), never
    raising: a failure is logged and left to the sync. With ``schedule``, a
    Demo reported before its slot ends is checked again when the slot ends.
    Returns the ConversionCheck, or None when the check failed.
    """
    try:
        result = ledger.record_conversion(lead_id)
    except Exception:
        logger.exception('Demo conversion check failed for lead %s; the earnings sync will add it', lead_id)
        return None
    if schedule and result.due_at is not None:
        schedule_check(lead_id, result.due_at)
    return result


def schedule_check(lead_id, at):
    """Ask Celery to check ``lead_id``'s conversion again at ``at``; without a broker, the sync does it instead."""
    from .tasks import check_demo_conversion
    try:
        check_demo_conversion.apply_async(args=[str(lead_id)], eta=at)
    except Exception:
        logger.exception('Could not schedule the Demo conversion check of lead %s; the earnings sync will add it',
                         lead_id)
