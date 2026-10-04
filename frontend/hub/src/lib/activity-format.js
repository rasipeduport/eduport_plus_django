import { format } from 'date-fns';

// Short, human label per action — used for badges and the action filter.
export const ACTION_LABELS = {
  'student.create': 'Student added',
  'student.update_status': 'Status changed',
  'student.update_quota': 'Quota changed',
  'student.update_meet_link': 'Meet link updated',
  'student.update_timezone': 'Timezone changed',
  'student.update_details': 'Profile updated',
  'student.reassign_mentor': 'Mentor reassigned',
  'student.reassign_tutor': 'Tutor reassigned',
  'student.purge': 'Student purged',
  'student.note_add': 'Note added',
  'student.note_update': 'Note edited',
  'student.note_delete': 'Note deleted',
  'session.create': 'Session created',
  'session.create_series': 'Series created',
  'session.update': 'Session updated',
  'session.update_links': 'Session links updated',
  'session.reschedule': 'Session rescheduled',
  'session.mark_attended': 'Marked attended',
  'session.cancel': 'Session cancelled',
  'session.cancel_series': 'Series class cancelled',
  'session.rate': 'Session rated',
  'exam.create': 'Exam scheduled',
  'exam.reschedule': 'Exam rescheduled',
  'exam.cancel': 'Exam cancelled',
  'exam.mark_attended': 'Exam marked attended',
  'exam.update_result': 'Exam result updated',
  'additional_exam.create': 'Additional exam assigned',
  'additional_exam.submit': 'Answer sheet submitted',
  'additional_exam.score': 'Additional exam scored',
  'homework.assign': 'Homework assigned',
  'homework.submit': 'Homework submitted',
  'homework.score': 'Homework scored',
  'invitation.create': 'Invitation sent',
  'invitation.update_email': 'Invitation email changed',
  'invitation.withdraw': 'Invitation withdrawn',
  'user.deactivate': 'User deactivated',
  'user.reactivate': 'User reactivated',
  'staff.reassign_all': 'Workload reassigned',
  'user.update_details': 'User details updated',
  // Auth/provisioning entries. Kept out of the unfiltered feed by the API, but
  // labelled so they read properly when picked from the action filter.
  'user.onboarded': 'Onboarded',
  'user.sign_in': 'Signed in',
  'user.sign_out': 'Signed out',
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
    case 'student.update_timezone': {
      const t = c.timezone;
      return t ? `Changed timezone from ${formatValue(t.old)} to ${formatValue(t.new)}` : 'Updated the timezone';
    }
    case 'student.update_details':
      return 'Updated the profile';
    case 'student.reassign_mentor': {
      const m = c.mentor;
      return m ? `Reassigned mentor from ${formatValue(m.old)} to ${formatValue(m.new)}` : 'Reassigned the mentor';
    }
    case 'student.reassign_tutor': {
      const t = c.tutor;
      return t ? `Reassigned tutor from ${formatValue(t.old)} to ${formatValue(t.new)}` : 'Reassigned the tutor';
    }
    case 'student.purge':
      return `Permanently removed ${row.entity_label ?? 'the student'}`;
    case 'student.note_add':
      return 'Added an internal note';
    case 'student.note_update':
      return 'Edited their internal note';
    case 'student.note_delete':
      return 'Deleted an internal note';
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
    case 'exam.create':
      return 'Scheduled a chapter exam';
    case 'exam.reschedule':
      return 'Rescheduled the exam';
    case 'exam.cancel': {
      const reason = reasonOf(row);
      return reason ? `Cancelled the exam — ${reason}` : 'Cancelled the exam';
    }
    case 'exam.mark_attended': {
      const s = c.score?.new;
      const m = c.max_score?.new;
      return s != null && m != null ? `Marked the exam attended — scored ${s}/${m}` : 'Marked the exam attended';
    }
    case 'exam.update_result': {
      const s = c.score;
      return s ? `Changed the score from ${formatValue(s.old)} to ${formatValue(s.new)}` : 'Updated the exam result';
    }
    case 'homework.assign':
      return 'Assigned homework';
    case 'homework.submit':
      return 'Submitted homework';
    case 'homework.score': {
      const s = c.score?.new;
      const m = c.max_score?.new;
      return s != null && m != null ? `Scored homework ${s}/${m}` : 'Scored homework';
    }
    case 'additional_exam.create':
      return 'Assigned an additional exam';
    case 'additional_exam.submit':
      return 'Submitted the answer sheet';
    case 'additional_exam.score': {
      const s = c.score?.new;
      const m = c.max_score?.new;
      return s != null && m != null ? `Scored the additional exam ${s}/${m}` : 'Scored the additional exam';
    }
    default:
      return actionLabel(row.action);
  }
}
