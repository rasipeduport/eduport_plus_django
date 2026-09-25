import { format } from 'date-fns';

// Short, human label per action — used for badges and the action filter.
export const ACTION_LABELS = {
  'student.create': 'Student added',
  'student.update_status': 'Status changed',
  'student.update_quota': 'Quota changed',
  'student.update_meet_link': 'Meet link updated',
  'session.create': 'Session created',
  'session.create_series': 'Series created',
  'session.update': 'Session updated',
  'session.update_links': 'Session links updated',
  'session.reschedule': 'Session rescheduled',
  'session.mark_attended': 'Marked attended',
  'session.cancel': 'Session cancelled',
  'session.cancel_series': 'Series class cancelled',
  'session.rate': 'Session rated',
  'invitation.create': 'Invitation sent',
  'invitation.update_email': 'Invitation email changed',
  'invitation.withdraw': 'Invitation withdrawn',
  'user.deactivate': 'User deactivated',
  'user.reactivate': 'User reactivated',
  'staff.reassign_all': 'Workload reassigned',
  ONBOARDED: 'Onboarded',
  LOGIN: 'Logged in',
  LOGOUT: 'Logged out',
  USER_UPDATE: 'User details updated',
  tampered: 'Tampered entry',
};

export function actionLabel(action) {
  return ACTION_LABELS[action] ?? humanize(action);
}

const ISO_DATE_RE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/;

/** Render a stored old/new value for display. */
export function formatValue(value) {
  if (value === null || value === undefined || value === '') return '—';
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  if (typeof value === 'string' && ISO_DATE_RE.test(value)) {
    const d = new Date(value);
    if (!Number.isNaN(d.getTime())) return format(d, 'd MMM yyyy, h:mm a');
  }
  return String(value);
}

function humanize(action) {
  const text = action.replace(/[._]/g, ' ').trim();
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function reasonOf(row) {
  const reason = row.context?.reason;
  return typeof reason === 'string' && reason.trim() ? reason.trim() : null;
}

/**
 * A concise, human description of WHAT happened (the actor and timestamp are
 * shown separately in the UI). Falls back to a generic label + raw diff.
 */
export function describeActivity(row) {
  const c = row.changes ?? {};

  switch (row.action) {
    case 'student.create':
      return 'Added the student';
    case 'student.update_status': {
      const s = c.status;
      const note = c.status_note?.new;
      const base = s
        ? `Changed status from "${formatValue(s.old)}" to "${formatValue(s.new)}"`
        : 'Updated status';
      return note ? `${base} — ${formatValue(note)}` : base;
    }
    case 'student.update_quota': {
      const q = c.total_class_quota;
      return q ? `Changed class quota from ${formatValue(q.old)} to ${formatValue(q.new)}` : 'Updated class quota';
    }
    case 'student.update_meet_link':
      return 'Updated the meet link';
    case 'session.create':
      return 'Created a session';
    case 'session.create_series':
      return 'Created a recurring session series';
    case 'session.reschedule':
      return 'Rescheduled the session';
    case 'session.mark_attended':
      return 'Marked the session attended';
    case 'session.cancel': {
      const reason = reasonOf(row);
      return reason ? `Cancelled the session — ${reason}` : 'Cancelled the session';
    }
    case 'session.cancel_series':
      return 'Cancelled a class in the series';
    case 'session.rate':
      return 'Rated the session';
    case 'session.update_links':
      return 'Updated the session links';
    default:
      return actionLabel(row.action);
  }
}
