// A BDE's follow-ups and activity: the /api/bde/follow-ups/ and /api/bde/activity/
// contracts (backend communications.followups, bookings.bde_activity) as the Hub
// uses them. The API scopes both to the signed-in BDE's own leads and enforces
// every rule; this only labels what it returns.
import { callReminder } from '@/lib/communications';
import { bookingTypeLabel, slotLabel } from '@/lib/enquiries';
import { TOKEN_AMOUNT, wholeAed } from '@/lib/payments';

export const BDE_FOLLOW_UPS_URL = '/api/bde/follow-ups/';
export const BDE_ACTIVITY_URL = '/api/bde/activity/';

// The due filter (backend followups.DUE_FILTERS); no value is every reminder.
export const FOLLOW_UP_DUE = [
  { value: 'today', label: 'Due today' },
  { value: 'upcoming', label: 'Upcoming' },
  { value: 'overdue', label: 'Overdue' },
];

// The reminders (backend followups.FollowUpType), in the order an enquiry meets them.
export const FOLLOW_UP_TYPES = [
  { value: 'NEW_ENQUIRY_CALL', label: 'Call new enquiry' },
  { value: 'PARENT_CONFIRMATION', label: 'Parent confirmation' },
  { value: 'PRE_ACTIVITY_CALL', label: 'Pre-activity call' },
  { value: 'TUTOR_REPORT', label: 'Share tutor report' },
  { value: 'REDEMO_CONFIRMATION', label: 'Re-Demo confirmation' },
  { value: 'TOKEN_TUITION', label: 'Collect token reservation tuition' },
];

// Each state's badge: due by the end of today, or later.
export const FOLLOW_UP_STATE_VARIANTS = {
  DUE_TODAY: 'warning',
  PENDING: 'outline',
  OVERDUE: 'destructive',
};

// Where the parent's confirmation request stands, once they were asked.
const REQUEST_STATES = {
  WAITING: 'on its way',
  PENDING: 'on its way',
  QUEUED: 'on its way',
  SENT: 'sent',
  DELIVERED: 'delivered',
  READ: 'read',
  FAILED: 'failed: call the parent',
  CANCELLED: 'not sent',
};

const TASKS = {
  NEW_ENQUIRY_CALL: 'Call the parent and guide them to book a Demo or Diagnostic.',
  TUTOR_REPORT: 'Review the report and share it with the parent.',
  REDEMO_CONFIRMATION: 'Tell the parent the Re-Demo’s date and time, then record their answer.',
  TOKEN_TUITION: 'Collect the remaining tuition balance by the payment deadline.',
};

/**
 * A token reservation's reminder (backend followups._token_reservations): listed from the reservation until the
 * full balance is verified, the token paid or not, and flagged for an administrator once the enquiry was reassigned.
 */
// Why an administrator reviews a reservation: only one collects against another's quote (backend followups).
const REVIEW_REASONS = {
  REASSIGNED: 'Admin review needed: this enquiry was reassigned. ',
  PLAN_OWNER: 'Admin review needed: its tuition plan was issued by someone else. ',
};
function tokenTask(reservation) {
  const deadline = reservation.balance_due_date ? `by ${reservation.balance_due_date}` : `before the expected start ${reservation.expected_start_date}`;
  const unpaid = reservation.token_paid === false;
  // The amount still due, the token included until it is paid; the balance is what follows the token.
  const due = reservation.remaining_amount == null ? null : Number(reservation.remaining_amount);
  let task;
  if (due == null) task = unpaid ? 'Token not paid yet: collect AED 100 first, then choose the tuition plan in Plan Choosing.' : 'Token paid. Choose the tuition plan in Plan Choosing.';
  else if (unpaid) task = `Token not paid yet: collect AED 100 first, then the ${wholeAed(Math.max(due - TOKEN_AMOUNT, 0))} balance ${deadline}.`;
  else task = `Token paid. ${wholeAed(due)} balance due ${deadline}.`;
  const review = REVIEW_REASONS[reservation.admin_review_reason] ?? (reservation.admin_review ? 'Admin review needed. ' : '');
  return `${review}${reservation.reference} · ${task}`;
}

/** What a reminder asks of the BDE now, in a sentence. */
export function followUpTask(followUp, now = Date.now()) {
  switch (followUp.type) {
    case 'TOKEN_TUITION':
      return followUp.reservation ? tokenTask(followUp.reservation) : TASKS.TOKEN_TUITION;
    case 'PARENT_CONFIRMATION':
      return followUp.request
        ? `Confirmation request ${REQUEST_STATES[followUp.request.status] ?? followUp.request.status_label.toLowerCase()}. Record the parent’s answer.`
        : 'Ask the parent to confirm, then record their answer.';
    case 'PRE_ACTIVITY_CALL':
      return (
        callReminder(
          { step: 'PRE_ACTIVITY_CALL', active_from: followUp.opens_at, due_at: followUp.due_at },
          followUp.booking?.booking_type,
          now
        ) ?? 'Call the parent before the class starts.'
      );
    default:
      return TASKS[followUp.type] ?? null;
  }
}

/**
 * Where a reminder is acted on: a booking's communication (its enquiry's
 * workspace on Bookings, the booking highlighted and its sheet open), the
 * enquiry's tutor feedback for a report, or the enquiry itself.
 */
export function followUpPath(followUp) {
  const { enquiry, booking } = followUp;
  if (followUp.type === 'TOKEN_TUITION') return `/enquiries/${enquiry.id}?tab=sales`;
  if (followUp.type === 'TUTOR_REPORT') return `/enquiries/${enquiry.id}?tab=feedback`;
  return booking ? communicationPath(enquiry.id, booking) : `/enquiries/${enquiry.id}`;
}

/**
 * A booking's communication, where its follow-ups are acted on: its enquiry's
 * workspace on Bookings, the booking highlighted and its communication sheet open.
 */
export function communicationPath(enquiryId, booking) {
  const params = new URLSearchParams({
    tab: 'bookings',
    highlight: booking.id,
    booking: booking.id,
    booking_type: booking.booking_type,
  });
  return `/enquiries/${enquiryId}?${params}`;
}

const ORIGINS = {
  demo_invite: 'booked with a Demo invitation',
  redemo: 'scheduled as a Re-Demo',
  reschedule: 'booked in its new slot',
};

/**
 * What an activity row says happened, in a sentence: the booking type and the
 * event, with what its detail adds (how it came, where it moved, which report
 * version) -- never who else did it, nor why, which the API does not send.
 */
export function activitySentence(row) {
  const type = bookingTypeLabel(row.booking.booking_type);
  const detail = row.detail ?? {};
  switch (row.kind) {
    case 'CREATED':
      return `${type} ${ORIGINS[detail.origin] ?? 'booked'}`;
    case 'TUTOR_ASSIGNED':
      return `Tutor assigned to the ${type.toLowerCase()}`;
    case 'TUTOR_UNASSIGNED':
      return `Tutor removed from the ${type.toLowerCase()}`;
    case 'STARTED':
      return `${type} started`;
    case 'RESCHEDULED':
      return detail.to ? `${type} moved to ${slotLabel(detail.to)}` : `${type} moved to another slot`;
    case 'CANCELLED':
      return `${type} cancelled`;
    case 'COMPLETED':
      return `${type} completed`;
    case 'REPORT_EDITED':
      return detail.version ? `Report updated to version ${detail.version}` : 'Report updated';
    case 'MEET_LINK_UPDATED':
      return `Meet link updated for the ${type.toLowerCase()}`;
    case 'PARENT_CONFIRMED':
      return `Parent confirmed the ${type.toLowerCase()}`;
    case 'PARENT_NOT_CONFIRMED':
      return `Parent did not confirm the ${type.toLowerCase()}`;
    case 'REDEMO_REQUESTED':
      return 'Re-Demo requested';
    case 'REDEMO_CLOSED':
      return 'Re-Demo request closed';
    case 'REDEMO_REOPENED':
      return 'Re-Demo request reopened';
    default:
      return row.kind_label ?? row.kind;
  }
}
