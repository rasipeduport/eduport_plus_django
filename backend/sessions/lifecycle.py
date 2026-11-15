"""
Where a normal session stands as a class its tutor teaches -- started,
completed -- worked out in one place, as bookings.lifecycle does for Demo and
Diagnostic bookings.

A class starts only when someone running it says so: Start Session
(start_session, POST /api/sessions/<id>/start/) by its assigned tutor, the
student's mentor or an administrator (may_start), from START_EARLY before its
scheduled start until its scheduled end, recorded as ``started_at`` and
``started_by`` by the server's clock. Its scheduled time alone never starts
it. A start is for meeting access and activity tracking only: it never
completes the class, and whether it was started, and by whom, never matters
to the completion.

It is completed only by its assigned tutor's own notes -- the notes link
through PUT /api/sessions/, or an uploaded notes file -- submitted once its
originally scheduled end has passed, whether or not anyone started it
(tutor_notes_target): the same write sets the status to ATTENDED and records
``completed_at`` and ``completed_by``, the tutor's completion. That is the one
condition. Before the scheduled end the tutor's notes are refused
(CLASS_NOT_ENDED); a cancelled class takes none; exactly once -- later notes
change the notes, never the completion. Nothing completes a class on its own.
Notes or recordings from an administrator or a mentor never complete a class,
and nor does their Mark Attended -- that records operational attendance and
leaves the completion empty, so a class attended by staff stays told apart
from one its tutor completed, and the tutor's notes still complete it
afterwards.

What a completed class counts as is the class that was booked:
Session.duration_hours, its scheduled end minus its scheduled start. Neither
the moment it was started nor the moment its notes came in enters it, and the
schedule of a class cannot change once it has been started or attended
(sessions.views).

Every write here locks the session's row (FOR UPDATE, that row alone) and
re-reads it first, so a Start, a completion and a staff edit of the same class
queue behind each other, and a repeated or racing request sees what the first
one did.
"""
from datetime import timedelta

from django.utils import timezone

from accounts.authz import has_app_permission
from activity.utils import log_activity
from core.querysets import reaches

from .models import Session, SessionStatusChoices

# Start opens this long before the scheduled start and stays open until the scheduled end.
START_EARLY = timedelta(minutes=5)

NOT_ASSIGNED = 'SESSION_NOT_ASSIGNED'
SESSION_CANCELLED = 'SESSION_CANCELLED'
SESSION_ATTENDED = 'SESSION_ATTENDED'
START_TOO_EARLY = 'START_TOO_EARLY'
START_WINDOW_CLOSED = 'START_WINDOW_CLOSED'
CLASS_NOT_ENDED = 'CLASS_NOT_ENDED'
# Staff edits a started, past or attended class may no longer take (sessions.views).
SESSION_STARTED = 'SESSION_STARTED'
SESSION_ENDED = 'SESSION_ENDED'
SESSION_CHANGED = 'SESSION_CHANGED'


class SessionStateError(Exception):
    """A refusal with its API code, HTTP status and message; sessions.views answers it as it is."""

    def __init__(self, code, message, status=409, **extra):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.extra = extra

    def response_data(self):
        return {'error': self.message, 'code': self.code, **self.extra}


def start_opens_at(session):
    """The first moment ``session`` may be started."""
    return session.start_time - START_EARLY


def locked(session):
    """``session``'s row, re-read under FOR UPDATE (that row only: never its student's)."""
    return Session.objects.select_for_update(of=('self',)).select_related('student').get(pk=session.pk)


def may_start(session, user, request=None):
    """
    Whether ``user`` may start ``session``: its assigned tutor, or whoever
    manages the student's sessions -- an administrator, or the student's mentor
    (accounts.manage_session within their session scope). Read from the
    session's and the student's rows as they are now.
    """
    if session.tutor_id is not None and session.tutor_id == user.pk:
        return True
    return has_app_permission(user, 'accounts.manage_session', request) and reaches(
        'sessions', user, session.student, request
    )


def start_session(session, user, now=None, request=None):
    """
    Record that ``user`` has started ``session``; returns (session, changed).
    Call inside ``transaction.atomic()``. Only its assigned tutor, the
    student's mentor or an administrator (may_start, else NOT_ASSIGNED), only
    while it is scheduled (SESSION_CANCELLED, SESSION_ATTENDED), and only from
    START_EARLY before its scheduled start (START_TOO_EARLY) until its
    scheduled end (START_WINDOW_CLOSED). A class already started -- by anyone
    -- is left as it is, however often Start is sent again, and keeps who
    started it first. ``started_at`` is the server's clock read under the lock
    (``now`` pins it).
    """
    session = locked(session)
    at = now or timezone.now()
    if not may_start(session, user, request):
        raise SessionStateError(
            NOT_ASSIGNED,
            "Only the session's tutor, the student's mentor or an administrator can start it.",
            status=403,
        )
    if session.status == SessionStatusChoices.CANCELLED:
        raise SessionStateError(SESSION_CANCELLED, 'This session was cancelled, so it cannot be started.')
    if session.status == SessionStatusChoices.ATTENDED:
        raise SessionStateError(SESSION_ATTENDED, 'This session is already attended.')
    if session.started_at is not None:
        return session, False
    if at < start_opens_at(session):
        raise SessionStateError(
            START_TOO_EARLY,
            'It is too early to start this session. You can start it from 5 minutes before its scheduled time.',
            opens_at=start_opens_at(session).isoformat(),
        )
    if at >= session.end_time:
        raise SessionStateError(START_WINDOW_CLOSED, "This session's scheduled time has passed, so it can no longer be started.")
    session.started_at = at
    session.started_by = user
    session.save(update_fields=['started_at', 'started_by', 'updated_at'])
    return session, True


def log_start(session, request):
    log_activity(
        action='session.start',
        entity_type='session',
        entity_id=str(session.id),
        entity_label=session.title,
        student=session.student,
        context={
            'started_at': session.started_at.isoformat(),
            'start_time': session.start_time.isoformat(),
            'end_time': session.end_time.isoformat(),
            'duration_hours': session.duration_hours,
        },
        request=request,
    )


def completes_on_notes(session):
    """Whether its tutor's notes complete ``session``: not completed yet, not cancelled. A start is never asked for."""
    return session.completed_at is None and session.status != SessionStatusChoices.CANCELLED


def tutor_notes_target(session, tutor, now, cancelled_message):
    """
    ``session`` re-read under its lock for ``tutor``'s notes, and whether those
    notes complete it: (session, completing). Call inside
    ``transaction.atomic()``. Only its assigned tutor (NOT_ASSIGNED), never on
    a cancelled class (400, ``cancelled_message``), and -- until the class is
    completed -- only once its scheduled end has passed (CLASS_NOT_ENDED): the
    tutor's notes are the completion, so they wait for the end. Whether it was
    started, and by whom, is never read. Once completed, later notes are edits.
    """
    session = locked(session)
    if session.tutor_id is None or session.tutor_id != tutor.pk:
        raise SessionStateError(NOT_ASSIGNED, 'You can only add notes to the sessions assigned to you.', status=403)
    if session.status == SessionStatusChoices.CANCELLED:
        raise SessionStateError(SESSION_CANCELLED, cancelled_message, status=400)
    completing = completes_on_notes(session)
    if completing and now < session.end_time:
        raise SessionStateError(
            CLASS_NOT_ENDED,
            'This class has not ended yet. Submit your notes once it ends to complete it.',
            ends_at=session.end_time.isoformat(),
        )
    return session, completing


def mark_completed(session, tutor, at):
    """Complete ``session`` (its tutor's notes are in); returns the fields to save."""
    session.status = SessionStatusChoices.ATTENDED
    session.completed_at = at
    session.completed_by = tutor
    return ['status', 'completed_at', 'completed_by']


def log_completion(session, before_status, request):
    changes = {}
    if before_status != session.status:
        changes['status'] = {'old': before_status, 'new': session.status}
    log_activity(
        action='session.complete',
        entity_type='session',
        entity_id=str(session.id),
        entity_label=session.title,
        student=session.student,
        changes=changes,
        context={
            # Whether anyone started it is kept for the record only; it never decides the completion.
            'started_at': session.started_at.isoformat() if session.started_at else None,
            'completed_at': session.completed_at.isoformat(),
            'duration_hours': session.duration_hours,
        },
        request=request,
    )

