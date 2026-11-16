// Small readings of a Re-Demo request (GET /api/bookings/redemos/<id>/) shared by its workspace's parts
// (components/bookings/redemo-workspace).

/** A person as the request names them: their name and role. */
export const who = (person) => (person ? [person.full_name, person.role_label].filter(Boolean).join(' · ') : '—');

/** Where a booking's report stands, in a few words. */
export const reportText = (booking) => (booking.has_report ? `Version ${booking.report_version}` : 'Not submitted yet');

/** The Re-Demo booked for the request, while it stands: booked, taught, or taught and asked for again. */
export function liveBooking(redemo) {
  const booking = redemo.booking;
  return booking && ['BOOKED', 'COMPLETED', 'REDEMO_REQUIRED'].includes(booking.status) ? booking : null;
}
