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

/** An API timestamp as "30 Oct 2026, 7:31 PM IST", or null. */
export function istMoment(value) {
  if (!value) return null;
  const moment = new Date(value);
  if (Number.isNaN(moment.getTime())) return null;
  return `${formatShortDateInZone(moment, INDIAN_TIME)}, ${formatTimeInZone(moment, INDIAN_TIME)} IST`;
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

// The five steps (backend communications.models.Step), named as the Hub shows them.
const STEP_LABELS = {
  ACKNOWLEDGEMENT: 'Initial acknowledgement',
  CONFIRMATION_REQUEST: 'Confirmation request',
  PARENT_CONFIRMATION: 'Confirmed message',
  PRE_ACTIVITY_CALL: 'Pre-activity BDE call',
  AFTER_ACTIVITY: 'After-activity message',
};

/** The step a task or message belongs to, by name. */
export function stepLabel(row) {
  return STEP_LABELS[row.step] ?? row.step_label ?? row.step;
}

/** A task's state as a badge (backend communications.models.TaskStatus; `overdue` is still open past its target). */
export function taskState(task) {
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
