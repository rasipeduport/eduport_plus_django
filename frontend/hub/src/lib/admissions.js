// The administrators' Admissions Dashboard: the /api/admissions/dashboard/
// contract (backend bookings/admissions.py) as the Hub uses it, its dates, and
// where each of its counts opens. Every date is an Indian date, worked out
// from today's date in India whatever zone this device is in, as the booking
// lists' class dates are (lib/bde-booking-filters).
import { bookingPagePath, bookingsPagePath } from '@/lib/bookings';
import { classDateSpan, indianToday } from '@/lib/bde-booking-filters';

export const ADMISSIONS_DASHBOARD_URL = '/api/admissions/dashboard/';

export const RANGE_OPTIONS = [
  { value: 'today', label: 'Today' },
  { value: '7d', label: '7 Days' },
  { value: '30d', label: '30 Days' },
  { value: 'month', label: 'This Month' },
  { value: 'custom', label: 'Custom' },
];
// What the API shows without dates, too: the last seven days, today included.
export const DEFAULT_RANGE = '7d';
const RANGE_VALUES = new Set(RANGE_OPTIONS.map((option) => option.value));
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
const DAY_MS = 24 * 60 * 60 * 1000;

function daysBefore(iso, days) {
  const [year, month, day] = iso.split('-').map(Number);
  return new Date(Date.UTC(year, month - 1, day) - days * DAY_MS).toISOString().slice(0, 10);
}

/** The Indian dates a preset covers as of `now`, `{ from, to }`, inclusive; null for Custom. */
export function rangeSpan(preset, now = new Date()) {
  const today = indianToday(now);
  if (preset === '7d') return { from: daysBefore(today, 6), to: today };
  if (preset === '30d') return { from: daysBefore(today, 29), to: today };
  return classDateSpan(preset, now);
}

/**
 * The dashboard's dates from its URL: `range` (a preset; the last 7 days when
 * absent) and, for Custom, `from` and `to` -- a Custom range missing either
 * end falls back to the default. Answers `{ range, from, to }`.
 */
export function readRange(searchParams, now = new Date()) {
  const asked = RANGE_VALUES.has(searchParams.get('range')) ? searchParams.get('range') : DEFAULT_RANGE;
  if (asked === 'custom') {
    const from = DATE_RE.test(searchParams.get('from') ?? '') ? searchParams.get('from') : '';
    const to = DATE_RE.test(searchParams.get('to') ?? '') ? searchParams.get('to') : '';
    if (from && to && from <= to) return { range: 'custom', from, to };
  }
  const preset = asked === 'custom' ? DEFAULT_RANGE : asked;
  return { range: preset, ...rangeSpan(preset, now) };
}

const withQuery = (path, params) => `${path}?${new URLSearchParams(params)}`;

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
