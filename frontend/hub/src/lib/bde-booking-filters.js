// The BDE's Demo and Diagnostic Bookings filters (pages/BdeBookingsPage): the
// class date -- Today, This Week, This Month, All Time or a Custom range --
// then search, booking status and schedule, every value kept in the URL.
//
// A class date is its slot's date in India: the API's `from` and `to` are the
// slot's Indian date, inclusive (backend bookings.coordination), never the day
// the booking was made. So every span here is a pair of Indian dates, worked
// out from today's date in India -- whatever zone this device is in -- with
// plain calendar arithmetic from there.
import { DEFAULT_WHEN, TAUGHT_STATUSES } from '@/lib/bookings';
import { utcToZonedWallTime } from '@/lib/timezone';

const INDIA = 'Asia/Kolkata';
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
const DAY_MS = 24 * 60 * 60 * 1000;

export const CLASS_DATE_OPTIONS = [
  { value: 'today', label: 'Today' },
  { value: 'week', label: 'This Week' },
  { value: 'month', label: 'This Month' },
  { value: 'all', label: 'All Time' },
  { value: 'custom', label: 'Custom' },
];
export const DEFAULT_CLASS_DATES = 'all';

// Upcoming (the default: the slot has not ended), Past (it has) or both.
export const SCHEDULE_OPTIONS = [
  { value: 'upcoming', label: 'Upcoming' },
  { value: 'past', label: 'Past' },
  { value: 'all', label: 'All Schedules' },
];

/** Today's date in India at the instant `now`, as YYYY-MM-DD. */
export function indianToday(now = new Date()) {
  return utcToZonedWallTime(now, INDIA).date;
}

// Dates as UTC midnights, so no zone's clock change can move a day.
function parseDate(iso) {
  const [year, month, day] = iso.split('-').map(Number);
  return new Date(Date.UTC(year, month - 1, day));
}

const isoDate = (date) => date.toISOString().slice(0, 10);
const addDays = (date, days) => new Date(date.getTime() + days * DAY_MS);

/**
 * The class dates a preset covers on Indian dates as of `now`, as
 * `{ from, to }` (YYYY-MM-DD, inclusive): Today; This Week, Monday to Sunday;
 * This Month, its first to its last day. All Time and Custom have no span of
 * their own (null).
 */
export function classDateSpan(preset, now = new Date()) {
  const today = parseDate(indianToday(now));
  switch (preset) {
    case 'today':
      return { from: isoDate(today), to: isoDate(today) };
    case 'week': {
      const monday = addDays(today, -((today.getUTCDay() + 6) % 7));
      return { from: isoDate(monday), to: isoDate(addDays(monday, 6)) };
    }
    case 'month': {
      const first = new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), 1));
      const last = new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth() + 1, 0));
      return { from: isoDate(first), to: isoDate(last) };
    }
    default:
      return null;
  }
}

/**
 * The list's filters from its URL -- `dates` (a preset; All Time when absent),
 * `from` and `to` (a Custom range), `q`, `status` (one of `statuses`), `when`
 * (Upcoming when absent) and `page` -- every value the list does not know
 * dropped. A link with only `from`/`to`, from before the presets, is Custom;
 * Custom with neither is All Time. `from`/`to` come back as the class dates
 * the list is for: the preset's span as of `now`, or the Custom range.
 * `filtered` says whether any filter is off its default.
 */
export function readBdeBookingFilters(searchParams, statuses, now = new Date()) {
  const date = (name) => (DATE_RE.test(searchParams.get(name) ?? '') ? searchParams.get(name) : '');
  const known = (options, value) => options.some((option) => option.value === value);
  const customFrom = date('from');
  const customTo = date('to');
  const asked = searchParams.get('dates');

  let dates = known(CLASS_DATE_OPTIONS, asked) ? asked : DEFAULT_CLASS_DATES;
  if (asked === 'custom' || (!known(CLASS_DATE_OPTIONS, asked) && (customFrom || customTo))) {
    dates = customFrom || customTo ? 'custom' : DEFAULT_CLASS_DATES;
  }
  const span = dates === 'custom' ? { from: customFrom, to: customTo } : classDateSpan(dates, now);

  const q = (searchParams.get('q') ?? '').trim();
  const status = known(statuses, searchParams.get('status')) ? searchParams.get('status') : '';
  // A class already taught (Completed, Re-Demo required) has a slot that is almost always over: with no
  // schedule chosen its list reads every date, never an empty Upcoming list.
  const askedWhen = known(SCHEDULE_OPTIONS, searchParams.get('when')) ? searchParams.get('when') : '';
  const when = askedWhen || (TAUGHT_STATUSES.has(status) ? 'all' : DEFAULT_WHEN);
  return {
    page: Math.max(1, parseInt(searchParams.get('page') || '1', 10) || 1),
    q,
    status,
    when,
    dates,
    from: span?.from ?? '',
    to: span?.to ?? '',
    filtered: Boolean(q || status || dates !== DEFAULT_CLASS_DATES || when !== DEFAULT_WHEN),
  };
}

/** What GET /api/bde/bookings/<type>/ is asked for `filters` (from readBdeBookingFilters). */
export function bdeBookingParams(filters, pageSize) {
  const params = { page: filters.page, page_size: pageSize };
  if (filters.q) params.q = filters.q;
  if (filters.status) params.status = filters.status;
  // All Schedules is the page's own word for asking for neither.
  if (filters.when !== 'all') params.when = filters.when;
  if (filters.from) params.from = filters.from;
  if (filters.to) params.to = filters.to;
  return params;
}
