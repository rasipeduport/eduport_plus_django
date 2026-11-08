// A student's History (backend bookings.timeline): one entry per change to
// their bookings, as the bookings' own histories keep them -- what happened,
// when, to which booking, who did it and what changed. The same entries reach
// administrators, the lead's BDE and the tutor teaching a booking; the API
// leaves out what each may not read, so this only words what it returns.
import { bookingTypeLabel, slotLabel } from '@/lib/enquiries';
import { reportFieldsText } from '@/lib/reports';

// Booking statuses as a history entry names them before and after a change.
const STATUS_LABELS = {
  BOOKED: 'Booked',
  COMPLETED: 'Completed',
  CANCELLED: 'Cancelled',
  RESCHEDULED: 'Rescheduled',
  REDEMO_REQUIRED: 'Re-Demo required',
};

// How a booking came to be, as its creation recorded it (backend booking_service: codes only).
const ORIGINS = {
  public_booking: 'booked on the booking page',
  demo_invite: 'booked with a Demo invitation',
  redemo: 'scheduled as a Re-Demo',
  reschedule: 'booked in its new slot',
};

export const statusLabel = (status) => STATUS_LABELS[status] ?? status ?? '—';

/** The booking an entry belongs to, as a chip reads it: "Demo · Tue, 3 Nov · 5:00 PM IST" (Re-Demos say so). */
export function historyBookingLabel(booking) {
  if (!booking) return '';
  const type = booking.redemo ? 'Re-Demo' : bookingTypeLabel(booking.booking_type);
  return booking.slot ? `${type} · ${slotLabel(booking.slot)}` : type;
}

/** What happened, in a few words: the title of an entry. */
export function historyTitle(entry) {
  const type = entry.booking?.redemo ? 'Re-Demo' : bookingTypeLabel(entry.booking?.booking_type);
  const d = entry.details ?? {};
  switch (entry.kind) {
    case 'CREATED':
      // A Re-Demo an administrator booked says just that.
      if (d.via === 'redemo') return 'Re-Demo scheduled';
      return `${type} ${ORIGINS[d.via] ?? 'booked'}`;
    case 'TUTOR_ASSIGNED':
      if (d.old_tutor && d.new_tutor) return `Tutor changed from ${d.old_tutor.full_name} to ${d.new_tutor.full_name}`;
      return `Tutor assigned: ${d.new_tutor?.full_name ?? '—'}`;
    case 'TUTOR_UNASSIGNED':
      return `Tutor removed: ${d.old_tutor?.full_name ?? '—'}`;
    case 'STARTED':
      return `${type} started by its tutor`;
    case 'RESCHEDULED':
      return `${type} moved`;
    case 'CANCELLED':
      return `${type} cancelled`;
    case 'COMPLETED':
      return 'Report submitted · class completed';
    case 'REPORT_EDITED':
      return d.version ? `Report updated to version ${d.version}` : 'Report updated';
    case 'MEET_LINK_UPDATED':
      return d.has_meet_link === false ? 'Meet link removed' : 'Meet link updated';
    case 'PARENT_CONFIRMED':
      return 'Parent confirmed';
    case 'PARENT_NOT_CONFIRMED':
      return 'Parent did not confirm';
    case 'REDEMO_REQUESTED':
      return 'Re-Demo requested';
    case 'REDEMO_CLOSED':
      return 'Re-Demo request closed';
    case 'REDEMO_REOPENED':
      return 'Re-Demo request reopened';
    default:
      return entry.kind_label ?? entry.kind;
  }
}

/** What changed, as short lines: the slot before and after, the status before and after, the reason, the version. */
export function historyDetails(entry) {
  const d = entry.details ?? {};
  const lines = [];
  if (entry.kind === 'CREATED' && d.slot) lines.push(`Slot: ${slotLabel(d.slot)}`);
  if (entry.kind === 'RESCHEDULED') {
    lines.push(`From ${d.old_slot ? slotLabel(d.old_slot) : '—'} to ${d.new_slot ? slotLabel(d.new_slot) : '—'}`);
  }
  if (d.from_status && d.to_status && d.from_status !== d.to_status) {
    lines.push(`Status: ${statusLabel(d.from_status)} → ${statusLabel(d.to_status)}`);
  }
  if (d.reason?.label) lines.push(`Reason: ${d.reason.label}`);
  if (entry.kind === 'COMPLETED' && d.version) lines.push(`Version ${d.version}`);
  if (entry.kind === 'REPORT_EDITED' && d.changed_fields?.length) lines.push(`Changed: ${reportFieldsText(d.changed_fields)}`);
  return lines;
}

/**
 * Who did it, after "By": "Asha Menon (Admin)", "staff" where the API names
 * nobody (a tutor is never told who asked for or scheduled a Re-Demo), "the
 * parent, on the booking page", or "the system".
 */
export function historyWho(entry) {
  if (entry.by === 'STAFF' && entry.actor) {
    return entry.actor.role_label ? `${entry.actor.full_name} (${entry.actor.role_label})` : entry.actor.full_name;
  }
  if (entry.by === 'STAFF') return 'staff';
  if (entry.by === 'PARENT') return 'the parent, on the booking page';
  return 'the system';
}

// The entry kinds a timeline marks out: the ones that end or stop something, and the Re-Demo's own.
export const HISTORY_TONES = {
  CANCELLED: 'destructive',
  PARENT_NOT_CONFIRMED: 'destructive',
  REDEMO_CLOSED: 'muted',
  REDEMO_REQUESTED: 'warning',
  REDEMO_REOPENED: 'warning',
  COMPLETED: 'success',
  PARENT_CONFIRMED: 'success',
};
