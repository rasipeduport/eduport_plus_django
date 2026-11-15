// Start Session and the completion a tutor's notes make (backend
// sessions.lifecycle). Every moment here is an instant from the API (UTC ISO),
// so the window is the same whatever zone the device is in; only labels are
// formatted, in the zone the Sessions table already reads in. The server
// decides every start and completion -- this only says what to offer.

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
 * What the assigned tutor's notes do now: 'complete' (its scheduled end has
 * passed: they complete it, whether or not anyone started it), 'wait' (not
 * over yet: the API refuses them until it ends), or 'save' (already
 * completed: an edit). Whether it was started never matters.
 */
export function notesMode(session, now) {
  const status = (session?.status || '').toLowerCase();
  if (!session?.completed_at && status !== 'cancelled') {
    return hasEnded(session, now) ? 'complete' : 'wait';
  }
  return 'save';
}

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
};

/** `{ status, code, message }` from a failed Start or notes request, with the tutor's wording for each refusal. */
export function lifecycleError(err, fallback) {
  const data = err?.response?.data || {};
  const code = typeof data.code === 'string' ? data.code : null;
  const message = REFUSALS[code] || data.error || data.message || err?.message || fallback;
  return { status: err?.response?.status ?? null, code, message };
}
