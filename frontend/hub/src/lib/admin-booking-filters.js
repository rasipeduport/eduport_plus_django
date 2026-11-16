// The administrators' Demo and Diagnostic Bookings filters (pages/BookingsPage):
// the class date -- Today, This Week, This Month, All Time or a Custom range,
// in Indian dates, as a BDE's booking lists offer it (lib/bde-booking-filters)
// -- then search, booking status, tutor assignment, report and schedule, every
// value kept in the URL. The booking type is the page's own address, never a
// filter. A value the API would refuse is dropped, so a hand-edited link shows
// the unfiltered list rather than an error.
import {
  ASSIGNMENT_FILTERS,
  BOOKING_STATUSES,
  DEFAULT_WHEN,
  DEMO_ONLY_STATUSES,
  REPORT_DUE,
  REPORT_FILTERS,
  TAUGHT_STATUSES,
  WHEN_FILTERS,
} from '@/lib/bookings';
import { CLASS_DATE_OPTIONS, DEFAULT_CLASS_DATES, classDateSpan } from '@/lib/bde-booking-filters';

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
const values = (options) => new Set(options.map((option) => option.value));
const ASSIGNMENT_VALUES = values(ASSIGNMENT_FILTERS);
const REPORT_VALUES = values(REPORT_FILTERS);
const WHEN_VALUES = values(WHEN_FILTERS);
const DATES_VALUES = values(CLASS_DATE_OPTIONS);

// A Re-Demo is only ever a Demo's, so Diagnostic's status filter does not offer it.
export const ADMIN_BOOKING_STATUSES = {
  DEMO: BOOKING_STATUSES,
  DIAGNOSTIC: BOOKING_STATUSES.filter((option) => !DEMO_ONLY_STATUSES.has(option.value)),
};

// What going back to the unfiltered list clears.
export const CLEARED_ADMIN_FILTERS = {
  dates: null,
  from: null,
  to: null,
  q: null,
  status: null,
  assigned: null,
  report: null,
  when: null,
  page: null,
};

/**
 * The list's filters from its URL, for the booking list of `type`: `dates` (a
 * preset; All Time when absent) and `from` / `to` -- the class dates it covers
 * as of `now`, or a Custom range; a link with only `from`/`to`, from before the
 * presets, is Custom -- then `q`, `status`, `assigned`, `report`, `when`
 * (Upcoming when absent) and `page`. Reports are due only on slots that are
 * over, so Report due reads Upcoming as Past: a link to the reports due never
 * shows an empty list. A class already taught (Completed, Re-Demo required)
 * reads Upcoming as All dates for the same reason: its slot is almost always
 * over. `filtered` says whether any filter is off its default.
 */
export function readAdminBookingFilters(searchParams, type, now = new Date()) {
  const pick = (name, allowed) => (allowed.has(searchParams.get(name)) ? searchParams.get(name) : '');
  const date = (name) => (DATE_RE.test(searchParams.get(name) ?? '') ? searchParams.get(name) : '');
  const customFrom = date('from');
  const customTo = date('to');
  const asked = searchParams.get('dates');

  let dates = DATES_VALUES.has(asked) ? asked : DEFAULT_CLASS_DATES;
  if (asked === 'custom' || (!DATES_VALUES.has(asked) && (customFrom || customTo))) {
    dates = customFrom || customTo ? 'custom' : DEFAULT_CLASS_DATES;
  }
  const span = dates === 'custom' ? { from: customFrom, to: customTo } : classDateSpan(dates, now);

  const q = (searchParams.get('q') ?? '').trim();
  const status = ADMIN_BOOKING_STATUSES[type].some((option) => option.value === searchParams.get('status'))
    ? searchParams.get('status')
    : '';
  const assigned = pick('assigned', ASSIGNMENT_VALUES);
  const report = pick('report', REPORT_VALUES);
  const askedWhen = pick('when', WHEN_VALUES);
  const asWhen = askedWhen || DEFAULT_WHEN;
  let when = asWhen;
  if (asWhen === DEFAULT_WHEN && report === REPORT_DUE) when = 'past';
  // A taught class reads every date unless Upcoming is asked for in so many words (when=upcoming).
  else if (!askedWhen && TAUGHT_STATUSES.has(status)) when = 'all';
  return {
    page: Math.max(1, parseInt(searchParams.get('page') || '1', 10) || 1),
    type,
    dates,
    from: span?.from ?? '',
    to: span?.to ?? '',
    q,
    status,
    assigned,
    report,
    when,
    filtered: Boolean(q || status || assigned || report || dates !== DEFAULT_CLASS_DATES || when !== DEFAULT_WHEN),
  };
}
