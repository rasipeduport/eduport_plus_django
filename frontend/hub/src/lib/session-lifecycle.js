// Where a normal session stands -- Start Session, the completion its tutor's
// notes make (whenever they come in after the class) and a recorded outcome
// (backend sessions.lifecycle).
// Every moment here is an instant from the API (UTC ISO), so the window is the
// same whatever zone the device is in; only labels are formatted, in the zone
// the Sessions table already reads in. The server decides every start,
// completion and outcome -- this only says what to offer.

const instant = (iso) => (iso ? new Date(iso).getTime() : NaN);
const ms = (now) => (now instanceof Date ? now.getTime() : now);

// The backend's START_EARLY, read only when an answer lacks `start_opens_at`.
const START_EARLY_MS = 5 * 60 * 1000;

/** The first moment its tutor may start the session, as a Date: the API's `start_opens_at`. */
export function startOpensAt(session) {
  const opens = instant(session?.start_opens_at);
  return new Date(Number.isFinite(opens) ? opens : instant(session?.start_time) - START_EARLY_MS);
}

/** Whether `user` is the tutor this session is assigned to (only they start it and complete it). */
export function isAssignedTutor(session, user) {
  const tutorId = session?.tutor_profile?.id ?? session?.tutor ?? null;
  return Boolean(user?.id) && tutorId != null && String(tutorId) === String(user.id);
}

/** Whether the session's scheduled end has passed. */
export function hasEnded(session, now) {
  return ms(now) >= instant(session?.end_time);
}

/**
 * Where the class stands now -- the backend's `class_state`, worked out from
 * the same fields so the page moves on with its clock: 'upcoming' (not
 * started, not ended -- under way with nobody having started it included),
 * 'in_progress' (started, not ended), 'notes_due' (started, ended, its tutor's
 * completion not in), 'not_started' (ended with nobody having started it),
 * 'completed', 'not_conducted' (No-show / Not Conducted, as recorded) or
 * 'cancelled'.
 */
export function classState(session, now) {
  const status = (session?.status || '').toLowerCase();
  if (status === 'cancelled') return 'cancelled';
  if (status === 'not_conducted') return 'not_conducted';
  if (session?.completed_at) return 'completed';
  if (!hasEnded(session, now)) return session?.started_at ? 'in_progress' : 'upcoming';
  return session?.started_at ? 'notes_due' : 'not_started';
}

/**
 * Whether an administrator or the student's mentor may record its outcome now:
 * once it has ended with no completion, and no homework set through it.
 */
export function mayRecordOutcome(session, now) {
  const state = classState(session, now);
  return (state === 'notes_due' || state === 'not_started') && !session?.homework;
}

/** Whether it may still be cancelled: a scheduled class, until its scheduled end (then its outcome is recorded). */
export function mayCancel(session, now) {
  return (session?.status || '').toLowerCase() === 'scheduled' && !hasEnded(session, now);
}

/**
 * Where its tutor's Start stands, for a scheduled session: 'upcoming' (opens
 * at `start_opens_at`, 5 minutes before the class), 'ready', 'started', or
 * 'closed' (its time passed with no start). Null for any other status.
 */
export function startState(session, now) {
  if ((session?.status || '').toLowerCase() !== 'scheduled') return null;
  if (session.started_at) return 'started';
  if (hasEnded(session, now)) return 'closed';
  if (ms(now) >= startOpensAt(session).getTime()) return 'ready';
  return 'upcoming';
}

/**
 * What the assigned tutor's notes do now: 'not_started' (nobody started the
 * class: no notes at all), 'wait' (started, not over yet), 'complete' (started
 * and ended: they complete it, however long after the class they come in),
 * 'save' (completed: an edit), or null (cancelled, or recorded as not
 * conducted: no notes).
 */
export function notesMode(session, now) {
  const status = (session?.status || '').toLowerCase();
  if (status === 'cancelled' || status === 'not_conducted') return null;
  if (session?.completed_at) return 'save';
  if (!session?.started_at) return 'not_started';
  if (!hasEnded(session, now)) return 'wait';
  return 'complete';
}

// Why a class was not conducted (backend SessionOutcomeReason), and what it does to the student's credit.
export const OUTCOME_REASONS = [
  { value: 'STUDENT_NO_SHOW', label: 'Student no-show', hint: "The student didn't attend. The class's credit stays used." },
  { value: 'TUTOR_ABSENT', label: 'Tutor absent', hint: "The tutor didn't attend. The class's credit is returned." },
  { value: 'TECHNICAL_ISSUE', label: 'Technical issue', hint: "A technical problem stopped the class. The class's credit is returned." },
  { value: 'OTHER', label: 'Other', hint: "Anything else; add a note saying what happened. The class's credit is returned." },
];

/** The label of an outcome reason code. */
export function outcomeReasonLabel(code) {
  return OUTCOME_REASONS.find((reason) => reason.value === code)?.label || code || '';
}

// The backend's NOTE_MAX_LENGTH for outcome and correction notes.
export const OUTCOME_NOTE_MAX = 500;

/** "1 hour", "30 mins", "1.5 hours": the class as booked (`duration_hours`, end - start). */
export function bookedLength(session) {
  const hours = Number(session?.duration_hours ?? (instant(session?.end_time) - instant(session?.start_time)) / 3600000);
  if (!Number.isFinite(hours) || hours <= 0) return '';
  if (hours < 1) return `${Math.round(hours * 60)} mins`;
  return hours === 1 ? '1 hour' : `${hours} hours`;
}

// What a refused Start or completion says (backend sessions.lifecycle), by its code.
const REFUSALS = {
  START_TOO_EARLY: 'It is too early to start. You can start from 5 minutes before the scheduled time.',
  START_WINDOW_CLOSED: "This session's scheduled time has passed, so it can no longer be started.",
  SESSION_CANCELLED: 'This session was cancelled.',
  SESSION_ATTENDED: 'This session is already attended.',
  CLASS_NOT_ENDED: 'This class has not ended yet. Submit your notes once it ends to complete it.',
  SESSION_NOT_STARTED: 'This class was not started, so notes cannot be submitted for it.',
  OUTCOME_RECORDED: "This class's outcome is already recorded.",
  SESSION_COMPLETED: 'This class was completed by its tutor.',
  HOMEWORK_EXISTS: 'This class has homework set through it, so it cannot be recorded as not conducted.',
  NO_OUTCOME: 'This class has no recorded outcome to correct.',
  SESSION_ENDED: "This class's scheduled time has ended, so it can no longer be cancelled. Record its outcome instead.",
};

/** `{ status, code, message }` from a failed Start, notes or outcome request, with the wording for each refusal. */
export function lifecycleError(err, fallback) {
  const data = err?.response?.data || {};
  const code = typeof data.code === 'string' ? data.code : null;
  const message = REFUSALS[code] || data.error || data.message || err?.message || fallback;
  return { status: err?.response?.status ?? null, code, message };
}
