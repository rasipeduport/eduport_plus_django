// The administrators' Admissions Dashboard: the /api/admissions/dashboard/
// contract (backend bookings/admissions.py) as the Hub uses it, and where each
// of its counts opens. Its dates are every dashboard's (lib/dashboard-range):
// Indian dates, worked out from today's date in India whatever zone this
// device is in, as the booking lists' class dates are (lib/bde-booking-filters).
import { bookingPagePath, bookingsPagePath } from '@/lib/bookings';

export const ADMISSIONS_DASHBOARD_URL = '/api/admissions/dashboard/';
// What the dashboard shows without dates: the last seven days, today included.
export const ADMISSIONS_DEFAULT_RANGE = '7d';

// A list's URL with `params`, leaving out those without a value (All Time's missing first date, say).
const withQuery = (path, params) =>
  `${path}?${new URLSearchParams(Object.entries(params).filter(([, value]) => value != null && value !== ''))}`;

/** The Leads page showing the leads that came in on `range`'s dates, at `status` (a stage, or none). */
export function leadsPath(range, status = null) {
  return withQuery('/leads', { ...(status ? { status } : {}), from: range.from, to: range.to });
}

/** A booking type's page showing its classes on `range`'s dates, whatever their schedule. */
export function bookingsInRangePath(type, range) {
  return withQuery(bookingsPagePath(type), { from: range.from, to: range.to, when: 'all' });
}

/** A booking type's page filtered by `params` (the list's own URL values). */
export const bookingsListPath = (type, params) => withQuery(bookingsPagePath(type), params);

/** One of today's bookings, in its workspace. */
export const todaysBookingPath = (booking) => bookingPagePath(booking.booking_type, booking.id);

/** The type of `counts` ({ DEMO, DIAGNOSTIC }) whose list to open: Demo, unless only Diagnostic has any. */
export function busierType(counts) {
  return !counts?.DEMO && counts?.DIAGNOSTIC ? 'DIAGNOSTIC' : 'DEMO';
}

/** `counts` ({ DEMO, DIAGNOSTIC }) added up; null when the caller may not see them. */
export function totalOf(counts) {
  return counts ? (counts.DEMO ?? 0) + (counts.DIAGNOSTIC ?? 0) : null;
}
