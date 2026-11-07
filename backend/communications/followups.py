"""
A BDE's follow-ups (GET /api/bde/follow-ups/, communications.bde_views): the
open steps of the parent communication on their own leads' bookings
(CommunicationTask) -- asking the parent to confirm, recording their answer,
the call before the class, the messages around it -- soonest due first.

Whose follow-up a step is follows the lead's owner now, never the owner the
task recorded when it was made: a lead given to another BDE takes its
follow-ups with it, exactly as its communication goes (communications.views
scopes by the lead's owner too). Acting on a step stays where it is -- the
booking's communication, whose APIs check the permissions for each action.

Each row is written out field by field, so nothing reaches the BDE by being
added elsewhere: the step and its times, the booking it belongs to, and whose
it is -- the parent's name and number, which the BDE's own enquiry shows them.
"""
from datetime import datetime, time, timedelta

from django.db.models import Count, F, Q

from bookings.enquiries import booking_brief, enquiry_brief
from bookings.lifecycle import activity_state
from bookings.scheduling import BOOKING_TIMEZONE, indian_today

from .models import CommunicationTask, Step, TaskStatus

OVERDUE, TODAY, UPCOMING = 'overdue', 'today', 'upcoming'
DUE_FILTERS = (OVERDUE, TODAY, UPCOMING)


def own_open_tasks(bde):
    """The open communication steps of the bookings of the leads ``bde`` owns now."""
    return CommunicationTask.objects.filter(status=TaskStatus.OPEN).filter(
        Q(demo_booking__lead__owner_bde=bde) | Q(diagnostic_booking__lead__owner_bde=bde)
    )


def for_enquiry(tasks, lead_id):
    """``tasks`` of one lead's bookings."""
    return tasks.filter(Q(demo_booking__lead_id=lead_id) | Q(diagnostic_booking__lead_id=lead_id))


def _today_bounds(now):
    """Today's Indian date as the two instants that bound it -- the day the slots are booked in."""
    start = datetime.combine(indian_today(now), time.min, tzinfo=BOOKING_TIMEZONE)
    return start, start + timedelta(days=1)


def _due(now):
    """
    What each due filter means, as conditions. Overdue: still open past its
    target -- never the call before the class, a reminder only that closes at
    the class's start (communications.overview). Today: due later today, in
    Indian time. Upcoming: due on a later day, or not due yet at all (the
    after-activity message, timed once the class is completed).
    """
    start, end = _today_bounds(now)
    overdue = Q(due_at__lt=now) & ~Q(step=Step.PRE_ACTIVITY_CALL)
    today = Q(due_at__gte=now, due_at__lt=end) | (Q(step=Step.PRE_ACTIVITY_CALL, due_at__lt=now, due_at__gte=start))
    upcoming = Q(due_at__gte=end) | Q(due_at__isnull=True)
    return {OVERDUE: overdue, TODAY: today, UPCOMING: upcoming}


def summary(tasks, now):
    """How many of ``tasks`` are overdue, due today and upcoming, and how many in all."""
    due = _due(now)
    return tasks.aggregate(
        total=Count('pk'),
        overdue=Count('pk', filter=due[OVERDUE]),
        today=Count('pk', filter=due[TODAY]),
        upcoming=Count('pk', filter=due[UPCOMING]),
    )


def filtered(tasks, now, due=None, step=None):
    """``tasks`` narrowed to one due filter and one step, soonest due first (the untimed last)."""
    if due:
        tasks = tasks.filter(_due(now)[due])
    if step:
        tasks = tasks.filter(step=step)
    return tasks.select_related(
        'demo_booking__slot', 'demo_booking__lead', 'diagnostic_booking__slot', 'diagnostic_booking__lead',
    ).order_by(F('due_at').asc(nulls_last=True), 'created_at', 'id')


def _when(value):
    return value.isoformat() if value else None


def followup_row(task, now):
    """One follow-up as the BDE's list shows it."""
    booking = task.demo_booking or task.diagnostic_booking
    lead = booking.lead
    return {
        'id': str(task.id),
        'step': task.step,
        'step_label': task.get_step_display(),
        'active_from': _when(task.active_from),
        'due_at': _when(task.due_at),
        'expires_at': _when(task.expires_at),
        'overdue': task.step != Step.PRE_ACTIVITY_CALL and task.due_at is not None and task.due_at < now,
        'booking': {**booking_brief(booking), 'status': booking.status, 'activity_state': activity_state(booking, now)},
        'enquiry': {
            **enquiry_brief(lead),
            'phone': f'{lead.phone_dial_code} {lead.phone_number}',
            'phone_dial_code': lead.phone_dial_code,
            'phone_number': lead.phone_number,
        },
    }
