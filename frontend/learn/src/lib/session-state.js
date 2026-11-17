// Where a class stands for the student, from the same fields the Hub reads
// (backend sessions.lifecycle class_state): upcoming, in_progress, notes_due
// (started and over, its tutor's notes still to come), not_started (over with
// nobody having started it), completed, not_conducted or cancelled. A student
// is told only whether a class not conducted was their own no-show
// (`outcome_kind`), never the staff's reason or note.

export function sessionState(session, now = new Date()) {
  const status = (session?.status || '').toLowerCase();
  if (status === 'cancelled') return 'cancelled';
  if (status === 'not_conducted') return 'not_conducted';
  if (session?.completed_at) return 'completed';
  const ended = now.getTime() >= new Date(session?.end_time).getTime();
  if (!ended) return session?.started_at ? 'in_progress' : 'upcoming';
  return session?.started_at ? 'notes_due' : 'not_started';
}

/** Whether the class is still to come or under way (the Upcoming tab). */
export function isUpcoming(session, now = new Date()) {
  const state = sessionState(session, now);
  return state === 'upcoming' || state === 'in_progress';
}

/**
 * The label and tone a student sees: Attended for a class held (its tutor's
 * completion, or staff marking it attended), Notes pending while a started
 * class awaits its tutor's notes, Awaiting update for one over that nobody
 * started, Missed for their own no-show, Not held for any other class not
 * conducted.
 */
export function sessionBadge(session, now = new Date()) {
  const state = sessionState(session, now);
  const attended = (session?.status || '').toLowerCase() === 'attended';
  switch (state) {
    case 'cancelled':
      return { label: 'Cancelled', tone: 'danger' };
    case 'not_conducted':
      return session?.outcome_kind === 'no_show' ? { label: 'Missed', tone: 'danger' } : { label: 'Not held', tone: 'danger' };
    case 'completed':
      return { label: 'Attended', tone: 'primary' };
    case 'in_progress':
      return { label: 'In progress', tone: 'info' };
    case 'notes_due':
      return attended ? { label: 'Attended', tone: 'primary' } : { label: 'Notes pending', tone: 'warning' };
    case 'not_started':
      return attended ? { label: 'Attended', tone: 'primary' } : { label: 'Awaiting update', tone: 'warning' };
    default:
      return { label: 'Scheduled', tone: 'info' };
  }
}
