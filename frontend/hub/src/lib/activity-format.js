import { format } from 'date-fns';

import { cancelReasonLabel, rescheduleReasonLabel } from './bookings';
import { notConfirmedReasonLabel } from './communications';
import { sourceLabel } from './enquiries';
import { NEW_ENQUIRY_OUTCOMES } from './follow-ups';
import { reportFieldsText } from './reports';

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
  // Team Management and password sign-in.
  'staff.create': 'Staff account created',
  'user.role_change': 'Role changed',
  'user.password_reset': 'Password reset',
  'user.password_change': 'Password changed',
  'user.permissions_update': 'Permissions updated',
  // A tutor's permanent Google Meet link: the log keeps how it changed, never the link.
  'user.meet_link_update': 'Meet link updated',
  'user.sign_in_failed': 'Sign-in refused',
  'user.unlock': 'Account unlocked',
  'user.lockout_update': 'Lockout changed',
  // BDE workspace.
  'booking_link.issue': 'Booking link issued',
  'enquiry.create': 'Enquiry added',
  // Leads (backend bookings.lead_intake, bookings.ownership): ids and choices only, never a name.
  'lead.create': 'Lead added',
  'lead.assign_owner': 'Lead assigned',
  // Demo/Diagnostic bookings. An action is labelled once something logs it:
  // the action filter offers every label here.
  'booking.create': 'Booking received',
  'booking.cancel': 'Booking cancelled',
  'booking.reschedule': 'Booking rescheduled',
  'booking.assign_tutor': 'Tutor assigned',
  'booking.unassign_tutor': 'Tutor unassigned',
  'booking.start': 'Booking started',
  'booking.complete': 'Booking completed',
  'booking.confirmation_request': 'Confirmation requested',
  'booking.parent_confirmation': 'Parent confirmation recorded',
  // A BDE's own follow-ups (backend communications.followups): the kind and the outcome's code only.
  'follow_up.complete': 'Follow-up completed',
  // Demo invitations (backend bookings.demo_invites): ids only, never the link.
  'demo_invite.issue': 'Demo invitation issued',
  'demo_invite.revoke': 'Demo invitation revoked',
  // Re-Demos (backend bookings.redemos): ids only, never the reason or the remarks.
  'redemo.request': 'Re-Demo requested',
  'redemo.remarks': 'Re-Demo remarks updated',
  // Assessment reports (P6): the log keeps ids, the version and field names, never a report's text.
  'report.submit': 'Report submitted',
  'report.edit': 'Report edited',
  'booking_slot.close': 'Slot closed',
  'booking_slot.reopen': 'Slot reopened',
  'booking_schedule.update': 'Booking times changed',
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
  if (Array.isArray(value)) return value.length ? value.join(', ') : '—';
  if (typeof value === 'string' && ISO_DATE_RE.test(value)) {
    const d = new Date(value);
    if (!Number.isNaN(d.getTime())) return format(d, 'd MMM yyyy, h:mm a');
  }
  return String(value);
}

// How a new enquiry's call went, as its follow-up's log entry names it by code.
const FOLLOW_UP_OUTCOME_LABELS = Object.fromEntries(NEW_ENQUIRY_OUTCOMES.map((option) => [option.value, option.label]));

function humanize(action) {
  const text = action.replace(/[._]/g, ' ').trim();
  return text.charAt(0).toUpperCase() + text.slice(1);
}

// Why a sign-in was refused (accounts.backends audit reasons, and the Google
// sign-in's refusal of staff accounts). The password sign-in page itself never
// says; only this admin-facing log does.
const SIGN_IN_REFUSALS = {
  invalid_password: 'Sign-in refused: wrong password',
  locked: 'Sign-in refused: account locked after repeated failures',
  inactive: 'Sign-in refused: account deactivated',
  no_password: 'Sign-in refused: no password set',
  student_account: 'Password sign-in refused: student account',
  google_staff_account: 'Google sign-in refused: staff sign in with a username and password',
};

const formatRole = (role) => (typeof role === 'string' ? role.charAt(0) + role.slice(1).toLowerCase() : '—');

/** "a demo booking" / "a diagnostic booking" from the entry's context, or "a booking". */
function bookingOfType(row) {
  const type = String(row.context?.booking_type ?? '').toLowerCase();
  return type ? `a ${type} booking` : 'a booking';
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
    case 'staff.create': {
      const role = row.context?.role;
      return role ? `Created the staff account as ${formatRole(role)}` : 'Created the staff account';
    }
    case 'user.role_change': {
      const r = c.role;
      const sentence = r ? `Changed role from ${formatRole(r.old)} to ${formatRole(r.new)}` : 'Changed the role';
      return row.context?.meet_link_removed ? `${sentence}; their Meet link was removed` : sentence;
    }
    case 'user.meet_link_update': {
      const verb = { added: 'Set', changed: 'Changed', removed: 'Removed' }[row.context?.change] ?? 'Updated';
      const count = row.context?.live_bookings_updated ?? 0;
      const bookings = count ? `; ${count} booking${count === 1 ? '' : 's'} not yet ended now use${count === 1 ? 's' : ''} it` : '';
      return `${verb} the tutor's Google Meet link${row.context?.change === 'removed' ? '' : bookings}`;
    }
    case 'user.update_details':
      return 'Updated the account details';
    case 'user.password_reset':
      return row.context?.unlocked
        ? 'Set a temporary password and cleared a sign-in lockout'
        : 'Set a temporary password';
    case 'user.password_change':
      return 'Changed their password';
    case 'user.permissions_update': {
      const added = row.context?.added ?? [];
      const removed = row.context?.removed ?? [];
      const parts = [];
      if (added.length) parts.push(`granted ${added.join(', ')}`);
      if (removed.length) parts.push(`revoked ${removed.join(', ')}`);
      return parts.length ? `Permissions: ${parts.join('; ')}` : 'Updated permissions';
    }
    case 'user.sign_in_failed':
      return SIGN_IN_REFUSALS[row.context?.reason] ?? 'Sign-in refused';
    case 'user.deactivate': {
      const reason = reasonOf(row);
      return reason ? `Deactivated the account — ${reason}` : 'Deactivated the account';
    }
    case 'user.reactivate':
      return 'Reactivated the account';
    case 'user.unlock':
      return 'Cleared the sign-in lockout';
    case 'booking_link.issue': {
      const type = row.entity_label;
      return type ? `Issued a ${type.toLowerCase()} booking link` : 'Issued a booking link';
    }
    case 'enquiry.create': {
      // The log keeps no names (backend bookings.enquiries): the class and source only.
      const source = row.context?.source ? sourceLabel(row.context.source) : null;
      return source ? `Added an enquiry (${source.toLowerCase()})` : 'Added an enquiry';
    }
    case 'lead.create': {
      // From a lead form on the website or landing page, or added by an administrator.
      const source = row.context?.source ? sourceLabel(row.context.source) : null;
      if (row.context?.via === 'lead_form') return source ? `Received a lead from the ${source.toLowerCase()}` : 'Received a lead';
      return source ? `Added a lead (${source.toLowerCase()})` : 'Added a lead';
    }
    case 'lead.assign_owner':
      return row.context?.previous_owner_id ? 'Reassigned a lead to another BDE' : 'Assigned a lead to a BDE';
    case 'booking.create': {
      const type = String(row.context?.booking_type ?? '').toLowerCase();
      if (row.context?.via === 'demo_invite') return 'Booked a demo slot with a Demo invitation';
      if (row.context?.via === 'redemo') return 'Scheduled a Re-Demo';
      const via = row.context?.referral_status === 'ATTRIBUTED' ? ' through a BDE link' : '';
      return `Booked a ${type || 'demo'} slot${via}`;
    }
    case 'demo_invite.issue':
      return row.context?.replaced_invite_id
        ? 'Issued a new Demo invitation link (the last one had expired)'
        : 'Issued a Demo invitation link';
    case 'demo_invite.revoke':
      return 'Revoked a Demo invitation link';
    case 'redemo.request':
      return 'Asked for a completed Demo to be taught again';
    case 'redemo.remarks':
      return row.context?.cleared ? "Cleared the Re-Demo's remarks" : "Updated the Re-Demo's remarks";
    case 'booking.cancel': {
      // A reason code since P3; entries from before carry the text they were given.
      const reason = cancelReasonLabel(row.context?.reason_code) || reasonOf(row);
      return reason ? `Cancelled the booking — ${reason}` : 'Cancelled the booking';
    }
    case 'booking.reschedule': {
      const reason = rescheduleReasonLabel(row.context?.reason_code);
      let tutor = '';
      if (row.context?.tutor_carried_over) tutor = '; the tutor carried over';
      else if (row.context?.tutor_id) tutor = '; the tutor was not free, so it needs one';
      return `Rescheduled ${bookingOfType(row)}${reason ? ` — ${reason}` : ''}${tutor}`;
    }
    // The log keeps ids only (backend booking_service): the booking's type, never who teaches it.
    case 'booking.assign_tutor':
      return row.context?.old_tutor_id
        ? `Reassigned the tutor of ${bookingOfType(row)}`
        : `Assigned a tutor to ${bookingOfType(row)}`;
    case 'booking.unassign_tutor':
      return `Unassigned the tutor from ${bookingOfType(row)}`;
    // The tutor's own Start (backend booking_service.start_booking): ids and instants only.
    case 'booking.start':
      return `Started ${bookingOfType(row)}`;
    // The first report completes its booking (backend reports.services): two entries, one each.
    case 'booking.complete':
      return `Completed ${bookingOfType(row)} with its report`;
    // Asking the parent to confirm (backend communications.services.request_confirmation): logged once, ids only.
    case 'booking.confirmation_request':
      return `Asked the parent to confirm ${bookingOfType(row)}`;
    // The parent's answer (backend booking_service.record_parent_confirmation): codes only. Not Confirmed cancels the booking.
    case 'booking.parent_confirmation': {
      if (row.context?.outcome !== 'NOT_CONFIRMED') return `Recorded the parent's confirmation of ${bookingOfType(row)}`;
      const reason = notConfirmedReasonLabel(row.context?.reason_code);
      return `Recorded that the parent did not confirm ${bookingOfType(row)}${reason ? ` — ${reason}` : ''}`;
    }
    // A new enquiry's call or a report's discussion, completed by its BDE: codes only.
    case 'follow_up.complete': {
      if (row.context?.kind === 'REPORT_DISCUSSION') return "Completed the discussion of a tutor's report with the parent";
      const outcome = FOLLOW_UP_OUTCOME_LABELS[row.context?.outcome];
      return `Completed the call to a new enquiry${outcome ? ` — ${outcome}` : ''}`;
    }
    case 'report.submit':
      return `Submitted the report on ${bookingOfType(row)}`;
    case 'report.edit': {
      const version = row.context?.version ? `, now version ${row.context.version}` : '';
      const fields = reportFieldsText(row.context?.changed_fields);
      return `Edited the report on ${bookingOfType(row)}${version}${fields ? ` — ${fields}` : ''}`;
    }
    case 'booking_slot.close': {
      const reason = reasonOf(row);
      return reason ? `Closed the slot — ${reason}` : 'Closed the slot';
    }
    case 'booking_slot.reopen':
      return 'Reopened the slot';
    case 'booking_schedule.update': {
      const parts = [];
      if (row.context?.added?.length) parts.push(`added ${row.context.added.join(', ')}`);
      if (row.context?.removed?.length) parts.push(`removed ${row.context.removed.join(', ')}`);
      return parts.length ? `Booking times: ${parts.join('; ')}` : 'Changed the booking times';
    }
    default:
      return actionLabel(row.action);
  }
}
