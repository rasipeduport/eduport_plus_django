// Session status vocabulary, keyed by the API's `display_status`: the
// attendance status, except that an attended class whose notes / recording /
// homework are not all in reads as "pending" until the last one lands
// (derived server-side from the link columns, never stored).
//
// SessionsPage still carries its own inline copy of these maps; it is one of
// the pages not yet ported to the design system, so it is left alone until it
// is. New code should import from here.
export const SESSION_STATUS_LABEL = {
  scheduled: 'Scheduled',
  pending: 'Pending',
  attended: 'Attended',
  cancelled: 'Cancelled',
  not_conducted: 'Not Conducted',
};

export const SESSION_STATUS_VARIANT = {
  scheduled: 'secondary',
  pending: 'warning',
  attended: 'success',
  cancelled: 'destructive',
  not_conducted: 'destructive',
};

export const SESSION_CONTENT_LABEL = { notes: 'Notes', recording: 'Recording', homework: 'Homework' };

// Where a class stands (lib/session-lifecycle classState, the backend's
// class_state): the lifecycle a row is badged with. A class not conducted is
// "No-show" when it was the student's, "Not Conducted" otherwise.
export const CLASS_STATE_LABEL = {
  upcoming: 'Upcoming',
  in_progress: 'In Progress',
  notes_due: 'Notes Due',
  not_started: 'Not Started',
  completed: 'Completed',
  not_conducted: 'Not Conducted',
  cancelled: 'Cancelled',
};

export const CLASS_STATE_VARIANT = {
  upcoming: 'secondary',
  in_progress: 'info',
  notes_due: 'warning',
  not_started: 'warning',
  completed: 'success',
  not_conducted: 'destructive',
  cancelled: 'destructive',
};

/** A class state's label, the not-conducted one by what was recorded (`outcome_kind`). */
export function classStateLabel(state, session) {
  if (state === 'not_conducted' && session?.outcome_kind === 'no_show') return 'No-show';
  return CLASS_STATE_LABEL[state] || 'Upcoming';
}

/** What a row is labelled: prefers the server's derived status. */
export function sessionStatusKey(session) {
  return session?.display_status || (session?.status || '').toLowerCase();
}

export function sessionStatusLabel(session) {
  return SESSION_STATUS_LABEL[sessionStatusKey(session)] || 'Scheduled';
}

export function sessionStatusVariant(session) {
  return SESSION_STATUS_VARIANT[sessionStatusKey(session)] || 'secondary';
}

/** Hours between start and end, the unit class quota is measured in. */
export function sessionHours(session) {
  const start = new Date(session.start_time).getTime();
  const end = new Date(session.end_time).getTime();
  if (Number.isNaN(start) || Number.isNaN(end)) return 0;
  return Math.max(0, (end - start) / 3600000);
}
