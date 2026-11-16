"""
Where a normal session stands as a class its tutor teaches -- started,
completed, not conducted -- worked out in one place, as bookings.lifecycle
does for Demo and Diagnostic bookings.

A class starts only when someone running it says so: Start Session
(start_session, POST /api/sessions/<id>/start/) by its assigned tutor, the
student's mentor or an administrator (may_start), from START_EARLY before its
scheduled start until its scheduled end, recorded as ``started_at`` and
``started_by`` by the server's clock. Its scheduled time alone never starts
it. A start never completes a class and never earns anything on its own; who
started it never matters.

A start is what opens the tutor's notes: no start, no notes. Once a class has
been started -- by anyone -- its assigned tutor's own notes (the notes link
through PUT /api/sessions/, or an uploaded notes file) complete it, at any
time after its scheduled end (CLASS_NOT_ENDED before; tutor_notes_target):
there is no deadline and nothing to approve. The same write sets the status
to ATTENDED and records ``completed_at`` and ``completed_by``, the tutor's
completion, exactly once -- later notes change the notes, never the
completion. Notes or recordings from an administrator or a mentor never
complete a class, and nor does their Mark Attended -- that records
operational attendance only.

What actually happened to a class that was not conducted is recorded by hand,
never by the clock: No-show / Not Conducted (record_outcome), by an
administrator or the student's mentor, once its scheduled end has passed and
while its tutor's notes have not completed it, for a reason in
SessionOutcomeReason. It is final: only an administrator holding
accounts.correct_session_outcome may correct its reason or revoke it, with a
note saying why (correct_outcome, revoke_outcome); every record, correction
and revocation goes to the activity log.

Where a class stands (class_state) is derived, never stored:

    UPCOMING       not started, its scheduled end still to come (a class
                   under way that nobody has started yet included)
    IN_PROGRESS    started, its scheduled end still to come
    NOTES_DUE      started, ended, its tutor's completion not in yet
    NOT_STARTED    ended with nobody having started it
    COMPLETED      completed by its tutor's notes
    NOT_CONDUCTED  No-show / Not Conducted, as recorded
    CANCELLED      by its status

What a completed class counts as is the class that was booked:
Session.duration_hours, its scheduled end minus its scheduled start. Whether
it counts towards Tutor Earnings is decided by earnings.eligibility.

Every write here locks the session's row (FOR UPDATE, that row alone) and
re-reads it first, so a Start, a completion, an outcome and a staff edit of
the same class queue behind each other, and a repeated or racing request sees
what the first one did.
"""
from datetime import timedelta

from django.db.models import TextChoices
from django.utils import timezone

from accounts.authz import has_app_permission
from activity.utils import log_activity
from core.querysets import reaches

from .models import Session, SessionOutcomeReason, SessionStatusChoices

# Start opens this long before the scheduled start and stays open until the scheduled end.
START_EARLY = timedelta(minutes=5)

# Who may correct or revoke a recorded outcome: administrators only.
CORRECT_OUTCOME = 'accounts.correct_session_outcome'
# The longest outcome or correction note kept.
NOTE_MAX_LENGTH = 500

NOT_ASSIGNED = 'SESSION_NOT_ASSIGNED'
NOT_ALLOWED = 'SESSION_NOT_ALLOWED'
SESSION_CANCELLED = 'SESSION_CANCELLED'
SESSION_ATTENDED = 'SESSION_ATTENDED'
START_TOO_EARLY = 'START_TOO_EARLY'
START_WINDOW_CLOSED = 'START_WINDOW_CLOSED'
CLASS_NOT_ENDED = 'CLASS_NOT_ENDED'
SESSION_NOT_STARTED = 'SESSION_NOT_STARTED'
SESSION_COMPLETED = 'SESSION_COMPLETED'
OUTCOME_RECORDED = 'OUTCOME_RECORDED'
NO_OUTCOME = 'NO_OUTCOME'
HOMEWORK_EXISTS = 'HOMEWORK_EXISTS'
INVALID_OUTCOME = 'INVALID_OUTCOME'
# Staff edits a started, past or attended class may no longer take (sessions.views).
SESSION_STARTED = 'SESSION_STARTED'
SESSION_ENDED = 'SESSION_ENDED'
SESSION_CHANGED = 'SESSION_CHANGED'

# What the tutor's notes do (notes_mode).
NOTES_COMPLETE = 'complete'  # started and ended, whenever they come in: they complete it
NOTES_EDIT = 'edit'          # already completed: an edit


class ClassState(TextChoices):
    UPCOMING = 'UPCOMING', 'Upcoming'
    IN_PROGRESS = 'IN_PROGRESS', 'In progress'
    NOTES_DUE = 'NOTES_DUE', 'Notes due'
    NOT_STARTED = 'NOT_STARTED', 'Not started'
    COMPLETED = 'COMPLETED', 'Completed'
    NOT_CONDUCTED = 'NOT_CONDUCTED', 'No-show / Not conducted'
    CANCELLED = 'CANCELLED', 'Cancelled'


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


def class_state(session, now):
    """Where ``session`` stands as of ``now`` (a ClassState value); sessions.services.state_q is its query twin."""
    if session.status == SessionStatusChoices.CANCELLED:
        return ClassState.CANCELLED
    if session.status == SessionStatusChoices.NOT_CONDUCTED:
        return ClassState.NOT_CONDUCTED
    if session.completed_at is not None:
        return ClassState.COMPLETED
    if now < session.end_time:
        return ClassState.IN_PROGRESS if session.started_at is not None else ClassState.UPCOMING
    return ClassState.NOTES_DUE if session.started_at is not None else ClassState.NOT_STARTED


def start_opens_at(session):
    """The first moment ``session`` may be started."""
    return session.start_time - START_EARLY


def locked(session):
    """``session``'s row, re-read under FOR UPDATE (that row only: never its student's)."""
    return Session.objects.select_for_update(of=('self',)).select_related('student').get(pk=session.pk)


def manages(session, user, request=None):
    """
    Whether ``user`` manages ``session``'s student's classes: an administrator,
    or the student's mentor (accounts.manage_session within their session
    scope), read from the session's and the student's rows as they are now.
    """
    return has_app_permission(user, 'accounts.manage_session', request) and reaches(
        'sessions', user, session.student, request
    )


def may_start(session, user, request=None):
    """Whether ``user`` may start ``session``: its assigned tutor, or whoever manages the student's sessions."""
    if session.tutor_id is not None and session.tutor_id == user.pk:
        return True
    return manages(session, user, request)


def start_session(session, user, now=None, request=None):
    """
    Record that ``user`` has started ``session``; returns (session, changed).
    Call inside ``transaction.atomic()``. Only its assigned tutor, the
    student's mentor or an administrator (may_start, else NOT_ASSIGNED), only
    while it is scheduled (SESSION_CANCELLED, SESSION_ATTENDED,
    OUTCOME_RECORDED), and only from START_EARLY before its scheduled start
    (START_TOO_EARLY) until its scheduled end (START_WINDOW_CLOSED). A class
    already started -- by anyone -- is left as it is, however often Start is
    sent again, and keeps who started it first. ``started_at`` is the server's
    clock read under the lock (``now`` pins it).
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
    if session.status == SessionStatusChoices.NOT_CONDUCTED:
        raise SessionStateError(OUTCOME_RECORDED, "This session's outcome is already recorded.")
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


# ------------------------------------------------------------- tutor's notes

def notes_mode(session, tutor, now, cancelled_message):
    """
    What ``tutor``'s notes do to ``session`` as it is now (a NOTES_* value),
    or the refusal: only its assigned tutor (NOT_ASSIGNED), never on a
    cancelled class (400, ``cancelled_message``) or one whose outcome is
    recorded (OUTCOME_RECORDED); once completed, they are edits. Until then
    only once someone has started it (SESSION_NOT_STARTED) and its scheduled
    end has passed (CLASS_NOT_ENDED); then they complete it, however long
    after its end they come in.
    """
    if session.tutor_id is None or session.tutor_id != tutor.pk:
        raise SessionStateError(NOT_ASSIGNED, 'You can only add notes to the sessions assigned to you.', status=403)
    if session.status == SessionStatusChoices.CANCELLED:
        raise SessionStateError(SESSION_CANCELLED, cancelled_message, status=400)
    if session.status == SessionStatusChoices.NOT_CONDUCTED:
        raise SessionStateError(
            OUTCOME_RECORDED, "This class's outcome is recorded as not conducted, so it takes no notes.",
        )
    if session.completed_at is not None:
        return NOTES_EDIT
    if session.started_at is None:
        raise SessionStateError(
            SESSION_NOT_STARTED, 'This class was not started, so notes cannot be submitted for it.',
        )
    if now < session.end_time:
        raise SessionStateError(
            CLASS_NOT_ENDED,
            'This class has not ended yet. Submit your notes once it ends to complete it.',
            ends_at=session.end_time.isoformat(),
        )
    return NOTES_COMPLETE


def tutor_notes_target(session, tutor, now, cancelled_message):
    """
    ``session`` re-read under its lock for ``tutor``'s notes, and what those
    notes do (notes_mode): (session, mode). Call inside ``transaction.atomic()``.
    """
    session = locked(session)
    return session, notes_mode(session, tutor, now, cancelled_message)


def apply_notes(session, mode, tutor, at):
    """What ``mode`` writes besides the notes themselves; returns the fields to save."""
    if mode == NOTES_COMPLETE:
        return mark_completed(session, tutor, at)
    return []


def mark_completed(session, tutor, at):
    """Complete ``session`` (its tutor's notes are in); returns the fields to save."""
    session.status = SessionStatusChoices.ATTENDED
    session.completed_at = at
    session.completed_by = tutor
    return ['status', 'completed_at', 'completed_by']


def log_completion(session, before_status, request, **context):
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
            'started_at': session.started_at.isoformat() if session.started_at else None,
            'completed_at': session.completed_at.isoformat(),
            'duration_hours': session.duration_hours,
            **context,
        },
        request=request,
    )


# ------------------------------------------------------------------ outcomes

def _require_manager(session, user, request):
    if not manages(session, user, request):
        raise SessionStateError(
            NOT_ALLOWED, "Only an administrator or the student's mentor can do this.", status=403,
        )


def clean_outcome(reason, note):
    """``reason`` and ``note`` as stored: (reason, note), or SessionStateError(INVALID_OUTCOME, 400)."""
    if reason not in SessionOutcomeReason.values:
        raise SessionStateError(INVALID_OUTCOME, 'Choose why the class was not conducted.', status=400, field='reason')
    note = clean_note(note, 'note')
    if reason == SessionOutcomeReason.OTHER and note is None:
        raise SessionStateError(INVALID_OUTCOME, 'Add a note saying what happened.', status=400, field='note')
    return reason, note


def clean_note(note, field):
    """A note stripped, blank as None, at most NOTE_MAX_LENGTH characters."""
    if note is not None and not isinstance(note, str):
        raise SessionStateError(INVALID_OUTCOME, 'The note must be text.', status=400, field=field)
    note = (note or '').strip() or None
    if note is not None and len(note) > NOTE_MAX_LENGTH:
        raise SessionStateError(
            INVALID_OUTCOME, f'Keep the note within {NOTE_MAX_LENGTH} characters.', status=400, field=field,
        )
    return note


def record_outcome(session, user, reason, note=None, now=None, request=None):
    """
    Record ``session`` as No-show / Not Conducted for ``reason``: status
    NOT_CONDUCTED, with what it was before kept. Call inside
    ``transaction.atomic()``. Only an administrator or the student's mentor
    (NOT_ALLOWED), only once its scheduled end has passed (CLASS_NOT_ENDED),
    never on a cancelled (SESSION_CANCELLED), completed (SESSION_COMPLETED)
    or already recorded class (OUTCOME_RECORDED), nor on one whose homework
    is under way (HOMEWORK_EXISTS). Returns the session.
    """
    session = locked(session)
    at = now or timezone.now()
    _require_manager(session, user, request)
    reason, note = clean_outcome(reason, note)
    if session.status == SessionStatusChoices.CANCELLED:
        raise SessionStateError(SESSION_CANCELLED, 'This class was cancelled.')
    if session.status == SessionStatusChoices.NOT_CONDUCTED:
        raise SessionStateError(OUTCOME_RECORDED, "This class's outcome is already recorded.")
    if session.completed_at is not None:
        raise SessionStateError(SESSION_COMPLETED, 'This class was completed by its tutor.')
    if at < session.end_time:
        raise SessionStateError(
            CLASS_NOT_ENDED, 'This class has not ended yet. Its outcome can be recorded once it ends.',
            ends_at=session.end_time.isoformat(),
        )
    if hasattr(session, 'homework'):
        raise SessionStateError(
            HOMEWORK_EXISTS, 'This class has homework set through it, so it cannot be recorded as not conducted.',
        )
    session.outcome_prior_status = session.status
    session.status = SessionStatusChoices.NOT_CONDUCTED
    session.outcome_reason = reason
    session.outcome_note = note
    session.outcome_recorded_at = at
    session.outcome_recorded_by = user
    session.save(update_fields=['status', 'outcome_prior_status', 'outcome_reason', 'outcome_note',
                                'outcome_recorded_at', 'outcome_recorded_by', 'updated_at'])
    return session


def log_outcome(session, request):
    changes = {
        'status': {'old': session.outcome_prior_status, 'new': session.status},
        'outcome_reason': {'old': None, 'new': session.outcome_reason},
    }
    log_activity(
        action='session.record_outcome',
        entity_type='session',
        entity_id=str(session.id),
        entity_label=session.title,
        student=session.student,
        changes=changes,
        context={'note': session.outcome_note, 'end_time': session.end_time.isoformat()},
        request=request,
    )


def _require_corrector(session, user, request):
    if not (has_app_permission(user, CORRECT_OUTCOME, request) and reaches('sessions', user, session.student, request)):
        raise SessionStateError(NOT_ALLOWED, 'Only an administrator can correct a recorded outcome.', status=403)


def _recorded(session):
    if session.status != SessionStatusChoices.NOT_CONDUCTED:
        raise SessionStateError(NO_OUTCOME, 'This class has no recorded outcome to correct.')


def _correction_note(correction_note):
    note = clean_note(correction_note, 'correction_note')
    if note is None:
        raise SessionStateError(
            INVALID_OUTCOME, 'Say why the recorded outcome is being corrected.', status=400, field='correction_note',
        )
    return note


def correct_outcome(session, user, reason, note, correction_note, now=None, request=None):
    """
    An administrator's correction of a recorded outcome's reason and note
    (accounts.correct_session_outcome, else NOT_ALLOWED), with
    ``correction_note`` saying why. Call inside ``transaction.atomic()``.
    Returns (session, before) -- the reason and note it replaced -- or
    (session, None) when nothing changed.
    """
    session = locked(session)
    at = now or timezone.now()
    _require_corrector(session, user, request)
    reason, note = clean_outcome(reason, note)
    correction_note = _correction_note(correction_note)
    _recorded(session)
    before = {'reason': session.outcome_reason, 'note': session.outcome_note, 'correction_note': correction_note}
    if (reason, note) == (session.outcome_reason, session.outcome_note):
        return session, None
    session.outcome_reason = reason
    session.outcome_note = note
    session.outcome_corrected_at = at
    session.outcome_corrected_by = user
    session.save(update_fields=['outcome_reason', 'outcome_note', 'outcome_corrected_at', 'outcome_corrected_by', 'updated_at'])
    return session, before


def log_outcome_correction(session, before, request):
    changes = {}
    if before['reason'] != session.outcome_reason:
        changes['outcome_reason'] = {'old': before['reason'], 'new': session.outcome_reason}
    if before['note'] != session.outcome_note:
        changes['outcome_note'] = {'old': before['note'], 'new': session.outcome_note}
    log_activity(
        action='session.correct_outcome',
        entity_type='session',
        entity_id=str(session.id),
        entity_label=session.title,
        student=session.student,
        changes=changes,
        context={'correction_note': before['correction_note']},
        request=request,
    )


def revoke_outcome(session, user, correction_note, request=None):
    """
    An administrator's revocation of a recorded outcome made by mistake
    (accounts.correct_session_outcome, else NOT_ALLOWED), with
    ``correction_note`` saying why: the class gets back the status it had
    before -- a started one takes its tutor's notes again. Call inside
    ``transaction.atomic()``. Returns (session, before): the outcome it
    removed.
    """
    session = locked(session)
    _require_corrector(session, user, request)
    correction_note = _correction_note(correction_note)
    _recorded(session)
    before = {
        'status': session.status,
        'reason': session.outcome_reason,
        'note': session.outcome_note,
        'recorded_at': session.outcome_recorded_at.isoformat(),
        'recorded_by_id': str(session.outcome_recorded_by_id) if session.outcome_recorded_by_id else None,
        'correction_note': correction_note,
    }
    session.status = session.outcome_prior_status
    for field in ('outcome_reason', 'outcome_note', 'outcome_recorded_at', 'outcome_recorded_by',
                  'outcome_prior_status', 'outcome_corrected_at', 'outcome_corrected_by'):
        setattr(session, field, None)
    session.save(update_fields=['status', 'outcome_reason', 'outcome_note', 'outcome_recorded_at', 'outcome_recorded_by',
                                'outcome_prior_status', 'outcome_corrected_at', 'outcome_corrected_by', 'updated_at'])
    return session, before


def log_outcome_revocation(session, before, request):
    changes = {
        'status': {'old': before['status'], 'new': session.status},
        'outcome_reason': {'old': before['reason'], 'new': None},
    }
    log_activity(
        action='session.revoke_outcome',
        entity_type='session',
        entity_id=str(session.id),
        entity_label=session.title,
        student=session.student,
        changes=changes,
        context={
            'correction_note': before['correction_note'],
            'outcome_note': before['note'],
            'recorded_at': before['recorded_at'],
            'recorded_by_id': before['recorded_by_id'],
        },
        request=request,
    )
