// Parent communication: the /api/communications/ contract (backend
// communications/views.py and communications/overview.py) as the Hub reads
// it. The API decides who sees what -- every booking's for administrators, a
// BDE's own leads' only -- and labels every code it sends; this builds the
// request, picks each state's badge and shows every moment in Indian time.

import { bookingError, typePath } from './bookings';
import { formatShortDateInZone, formatTimeInZone } from './timezone';

/** A booking's communication, read-only: GET /api/communications/bookings/<demo|diagnostic>/<id>/. */
export const bookingCommunicationUrl = (type, id) => `/api/communications/bookings/${typePath(type)}/${id}/`;
// What one of its messages would say now (GET ?step=<STEP>), asking the parent
// to confirm (POST) and recording their answer (POST) -- Phase 3.2.
export const messagePreviewUrl = (type, id) => `${bookingCommunicationUrl(type, id)}preview/`;
export const confirmationRequestUrl = (type, id) => `${bookingCommunicationUrl(type, id)}confirmation-request/`;
export const parentConfirmationUrl = (type, id) => `${bookingCommunicationUrl(type, id)}parent-confirmation/`;

// Errors answer `{ error: CODE, message }`, as the booking API's do.
export const communicationError = bookingError;

// Moments are shown in Indian time and labelled so, whatever zone this device
// is in -- as the slots are (lib/enquiries slotLabel).
const INDIAN_TIME = 'Asia/Kolkata';

/** An API timestamp's Indian date and time, as "30 Oct 2026" and "7:31 PM IST", or null. */
export function istParts(value) {
  if (!value) return null;
  const moment = new Date(value);
  if (Number.isNaN(moment.getTime())) return null;
  return { date: formatShortDateInZone(moment, INDIAN_TIME), time: `${formatTimeInZone(moment, INDIAN_TIME)} IST` };
}

/** An API timestamp as "30 Oct 2026, 7:31 PM IST", or null. */
export function istMoment(value) {
  const parts = istParts(value);
  return parts ? `${parts.date}, ${parts.time}` : null;
}

// What the parent answered when asked to confirm (backend bookings.models.ParentConfirmation).
const CONFIRMATION_LABELS = {
  AWAITING: 'Awaiting confirmation',
  CONFIRMED: 'Confirmed',
  NOT_CONFIRMED: 'Not confirmed',
};

/**
 * The parent's answer as a badge: still to follow up while the booking is
 * booked (warning), merely never given once it is not (outline); null when
 * the API showed none.
 */
export function parentConfirmationState(status, booked) {
  if (!status) return null;
  const label = CONFIRMATION_LABELS[status] ?? status;
  if (status === 'CONFIRMED') return { label, variant: 'success' };
  if (status === 'NOT_CONFIRMED') return { label, variant: 'destructive' };
  return { label, variant: booked ? 'warning' : 'outline' };
}

// What a parent may answer (backend booking_service.record_parent_confirmation): Not confirmed cancels the booking.
export const PARENT_ANSWERS = [
  { value: 'CONFIRMED', label: 'Confirmed' },
  { value: 'NOT_CONFIRMED', label: 'Not confirmed' },
];

// Why a parent did not confirm: a code from a fixed list (backend bookings.models.NotConfirmedReason).
export const NOT_CONFIRMED_REASONS = [
  { value: 'PARENT_DECLINED', label: 'Parent declined' },
  { value: 'NO_RESPONSE', label: 'No response' },
  { value: 'NOT_INTERESTED', label: 'Not interested' },
  { value: 'TIME_NOT_SUITABLE', label: "Time doesn't suit" },
  { value: 'OTHER', label: 'Other' },
];

export function notConfirmedReasonLabel(code) {
  return NOT_CONFIRMED_REASONS.find((option) => option.value === code)?.label ?? '';
}

// The five steps (backend communications.models.Step), named as the Hub shows them. The pre-activity call is a
// reminder to the BDE, nothing more (reminderState).
const STEP_LABELS = {
  ACKNOWLEDGEMENT: 'Initial acknowledgement',
  CONFIRMATION_REQUEST: 'Confirmation request',
  PARENT_CONFIRMATION: 'Confirmed message',
  PRE_ACTIVITY_CALL: 'Pre-activity BDE reminder',
  AFTER_ACTIVITY: 'After-activity message',
};

/** The step a task or message belongs to, by name. */
export function stepLabel(row) {
  return STEP_LABELS[row.step] ?? row.step_label ?? row.step;
}

/**
 * A task's state as a badge (backend communications.models.TaskStatus; `overdue` is still open past its target);
 * the pre-activity BDE reminder's by its own states (reminderState), for which `booking` is its booking.
 */
export function taskState(task, booking) {
  if (task.step === 'PRE_ACTIVITY_CALL') return REMINDER_STATES[reminderState(task, booking)];
  switch (task.status) {
    case 'DONE':
      return { label: 'Done', variant: 'success' };
    case 'MISSED':
      return { label: 'Missed', variant: 'destructive' };
    case 'CANCELLED':
      return { label: 'Cancelled', variant: 'outline' };
    default:
      return task.overdue ? { label: 'Overdue', variant: 'warning' } : { label: 'Open', variant: 'info' };
  }
}

// A message's state as a badge, in plain words (backend communications.models.MessageStatus):
// Pending is ready to send, Queued is with WhatsApp to send, Cancelled was never sent.
const MESSAGE_STATES = {
  WAITING: { label: 'Waiting', variant: 'outline' },
  PENDING: { label: 'Ready to send', variant: 'info' },
  QUEUED: { label: 'Sending', variant: 'info' },
  SENT: { label: 'Sent', variant: 'success' },
  DELIVERED: { label: 'Delivered', variant: 'success' },
  READ: { label: 'Read', variant: 'success' },
  FAILED: { label: 'Failed', variant: 'destructive' },
  CANCELLED: { label: 'Not sent', variant: 'outline' },
};

export function messageState(message) {
  return MESSAGE_STATES[message.status] ?? { label: message.status_label || message.status, variant: 'outline' };
}

/** The parts that are there, as one line: "Sent · 28 Oct 2026, 2:31 PM IST". */
export const joined = (...parts) => parts.filter(Boolean).join(' · ');

// How a message step was done, in a word or two (backend communications.models.TaskResolution).
const DONE_AS = {
  ACCEPTED: 'Sent',
  SENT: 'Sent',
  MARKED_SENT: 'Sent manually',
  ALREADY_ACKNOWLEDGED: 'Sent for the earlier booking',
  NOT_NEEDED: 'Not needed',
};

const ACTIVITY_NAMES = { DEMO: 'Demo', DIAGNOSTIC: 'Diagnostic' };

/**
 * The pre-activity BDE reminder's words while it is on -- from its `active_from`, 15 minutes before the start,
 * until the start (`due_at`), when the backend closes it by itself -- or null.
 */
export function callReminder(task, bookingType, now = Date.now()) {
  if (task.step !== 'PRE_ACTIVITY_CALL' || !task.active_from || !task.due_at) return null;
  const left = new Date(task.due_at).getTime() - now;
  if (now < new Date(task.active_from).getTime() || left <= 0) return null;
  const minutes = Math.ceil(left / 60000);
  return `Call parent – ${ACTIVITY_NAMES[bookingType] ?? 'Booking'} starts in ${minutes} minute${minutes === 1 ? '' : 's'}.`;
}

// The pre-activity BDE reminder's states (reminderState) as badges: when the BDE was reminded to call, never
// whether they called -- nothing records that.
const REMINDER_STATES = {
  scheduled: { label: 'Scheduled', variant: 'outline' },
  triggered: { label: 'Reminder triggered', variant: 'info' },
  'not-needed': { label: 'Not needed', variant: 'outline' },
  cancelled: { label: 'Cancelled', variant: 'outline' },
};

// A booking that is no longer to happen: its reminder goes with it, even before the backend closes its step.
const BOOKING_GONE = new Set(['CANCELLED', 'RESCHEDULED']);

/**
 * Where the pre-activity BDE reminder (`task`, its step PRE_ACTIVITY_CALL) of `booking` stands: 'scheduled'
 * until its time (`active_from`, 15 minutes before the start); 'triggered' from then -- in the BDE's
 * follow-ups until the class starts, when the backend closes it by itself; 'not-needed' when the class was
 * started before its time; 'cancelled' with its booking, cancelled or moved. Whether the BDE called is never
 * tracked, so a call closed before as Missed, or with an outcome, reads 'triggered' too.
 */
export function reminderState(task, booking, now = Date.now()) {
  if (task.status === 'CANCELLED' || (task.status === 'OPEN' && BOOKING_GONE.has(booking?.status))) return 'cancelled';
  const from = task.active_from ? new Date(task.active_from).getTime() : null;
  const started = booking?.started_at ? new Date(booking.started_at).getTime() : null;
  if (from !== null && started !== null && started <= from) return 'not-needed';
  if (from === null || now < from) return 'scheduled';
  return 'triggered';
}

/**
 * The pre-activity BDE reminder's one line: its words while it is on, else when it shows (or showed), why it
 * never showed, or why it was cancelled.
 */
function reminderLine(task, booking, now = Date.now()) {
  switch (reminderState(task, booking, now)) {
    case 'cancelled':
      return joined(task.resolution_label || booking?.status_label, istMoment(task.resolved_at)) || null;
    case 'not-needed':
      return 'The class started before the reminder time';
    case 'triggered':
      return callReminder(task, booking?.booking_type, now) ?? `Reminder at ${istMoment(task.active_from)}`;
    default:
      return task.active_from ? `Reminder at ${istMoment(task.active_from)}` : null;
  }
}

/**
 * A step's one line (`booking` is the communication's): how and when it was done, or when it is due or closed;
 * for the pre-activity BDE reminder, when it shows or its words while it is on.
 */
export function stepLine(task, booking) {
  if (task.step === 'PRE_ACTIVITY_CALL') return reminderLine(task, booking);
  switch (task.status) {
    case 'DONE':
      return joined(DONE_AS[task.resolution] ?? task.resolution_label, istMoment(task.resolved_at));
    case 'MISSED':
      return task.resolved_at ? `Time ran out ${istMoment(task.resolved_at)}` : null;
    case 'CANCELLED':
      return joined(task.resolution_label, istMoment(task.resolved_at));
    default:
      return task.due_at ? `Due ${istMoment(task.due_at)}` : 'After the class';
  }
}

/** A message's one line: when it reached its status, what it waits for, or why it was not sent. */
export function messageLine(message) {
  switch (message.status) {
    case 'WAITING':
      return message.waiting_for.length ? `Waiting for: ${message.waiting_for.map((item) => item.label).join(', ')}` : null;
    case 'PENDING':
      return message.next_attempt_at ? `Trying again ${istMoment(message.next_attempt_at)}` : null;
    case 'QUEUED':
      return istMoment(message.queued_at);
    case 'SENT':
      return istMoment(message.sent_at);
    case 'DELIVERED':
      return istMoment(message.delivered_at);
    case 'READ':
      return istMoment(message.read_at);
    case 'FAILED':
      return istMoment(message.failed_at);
    case 'CANCELLED':
      return joined(message.cancel_reason?.label, istMoment(message.cancelled_at));
    default:
      return null;
  }
}

// What a message has been through, in order, for its details.
export const MESSAGE_MOMENTS = [
  ['Sent to WhatsApp', 'queued_at'],
  ['Sent', 'sent_at'],
  ['Delivered', 'delivered_at'],
  ['Read', 'read_at'],
  ['Failed', 'failed_at'],
  ['Not sent', 'cancelled_at'],
];

/**
 * Why a booking that is not a Re-Demo shows no plan, in a sentence (its communication's `planned` is false):
 * a plan still on its way from the backend's outbox, a plan whose event failed, or a booking made before
 * parent communication began (`plan_status`, backend communications.outbox.PlanStatus).
 */
export function unplannedText(communication) {
  if (communication.plan_status === 'PENDING') {
    return 'Parent messages for this booking are being prepared and will appear here once ready.';
  }
  if (communication.plan_status === 'FAILED') {
    return 'Parent messages for this booking could not be prepared. Please contact the technical team.';
  }
  return 'No messages were planned for this booking: it was made before parent communication began.';
}

/** What asking the parent to confirm did, in a sentence (POST …/confirmation-request/ answers `created`). */
export function confirmationRequestNotice(data) {
  return data.created
    ? 'Confirmation request added. It is sent to the parent on WhatsApp.'
    : 'A confirmation request was already added for this booking.';
}

/** What recording the parent's answer did, in a sentence (POST …/parent-confirmation/ answers `changed`). */
export function parentAnswerNotice(data, outcome) {
  if (!data.changed) return "The parent's answer was already recorded.";
  return outcome === 'NOT_CONFIRMED'
    ? 'Recorded that the parent did not confirm. The booking is cancelled.'
    : 'Recorded that the parent confirmed.';
}

/** Each step's latest message, by step (the API lists them oldest first). */
export function latestMessages(messages) {
  return Object.fromEntries(messages.map((message) => [message.step, message]));
}

// A message step closes as soon as the provider takes its message (ACCEPTED, SENT), and the message may
// still fail after; one sent by hand (MARKED_SENT) or no longer needed is done whatever became of it.
const TAKEN_BY_PROVIDER = new Set(['ACCEPTED', 'SENT']);
const SENT_AS = new Set(['ACCEPTED', 'SENT', 'MARKED_SENT']);
const ON_ITS_WAY = new Set(['QUEUED', 'SENT', 'DELIVERED', 'READ']);

/**
 * Where one message step of a booking's communication stands (the pre-activity
 * BDE reminder's is reminderState), from its task and the
 * step's latest message, for the BDE's workflow timeline: 'failed' (its
 * message failed and nothing else closed the step), 'sent' or 'completed'
 * (done), 'missed', 'cancelled', 'overdue', 'pending' (open now) or
 * 'scheduled' (open from a later moment -- after the class, say).
 */
export function workflowState(task, message, now = Date.now()) {
  const failed =
    message?.status === 'FAILED' &&
    task.status !== 'CANCELLED' &&
    (task.status !== 'DONE' || TAKEN_BY_PROVIDER.has(task.resolution));
  if (failed) return 'failed';
  if (task.status === 'DONE') return SENT_AS.has(task.resolution) ? 'sent' : 'completed';
  if (task.status === 'MISSED') return 'missed';
  if (task.status === 'CANCELLED') return 'cancelled';
  if (task.overdue) return 'overdue';
  if (message && ON_ITS_WAY.has(message.status)) return 'sent';
  const later = (value) => Boolean(value) && new Date(value).getTime() > now;
  if (!task.active_from || later(task.active_from) || later(message?.scheduled_for)) return 'scheduled';
  return 'pending';
}
