// A BDE's follow-ups and activity: the /api/bde/follow-ups/ and /api/bde/activity/
// contracts (backend communications.followups, bookings.bde_activity) as the Hub
// uses them. The API scopes both to the signed-in BDE's own leads and enforces
// every rule; this only labels what it returns.
import { stepLabel } from '@/lib/communications';
import { bookingTypeLabel, slotLabel } from '@/lib/enquiries';

export const BDE_FOLLOW_UPS_URL = '/api/bde/follow-ups/';
export const BDE_ACTIVITY_URL = '/api/bde/activity/';

// The due filter (backend followups.DUE_FILTERS); no value is every open follow-up.
export const FOLLOW_UP_DUE = [
  { value: 'overdue', label: 'Overdue' },
  { value: 'today', label: 'Due today' },
  { value: 'upcoming', label: 'Upcoming' },
];

// The communication steps, named as a booking's communication names them (lib/communications).
export const FOLLOW_UP_STEPS = ['ACKNOWLEDGEMENT', 'CONFIRMATION_REQUEST', 'PARENT_CONFIRMATION', 'PRE_ACTIVITY_CALL', 'AFTER_ACTIVITY'].map(
  (step) => ({ value: step, label: stepLabel({ step }) })
);

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
    default:
      return row.kind_label ?? row.kind;
  }
}
