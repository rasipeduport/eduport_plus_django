// The dashboards' dates: the Admissions, Sales and Academics Dashboards each
// count a span picked from the same presets, kept in the URL (`range`, and
// `from`/`to` for Custom) and asked of the API the same way (backend
// core/dashboard_dates.py). Every date is an Indian date, worked out from
// today's date in India whatever zone this device is in.
import { format } from 'date-fns';

import { indianToday } from '@/lib/bde-booking-filters';
import { rangeLabel, toPickerDate } from '@/lib/date-range';

export const ALL_TIME = 'all';
export const CUSTOM = 'custom';

export const RANGE_OPTIONS = [
  { value: 'today', label: 'Today' },
  { value: '7d', label: '7 Days' },
  { value: 'month', label: 'This Month' },
  { value: ALL_TIME, label: 'All Time' },
  { value: CUSTOM, label: 'Custom' },
];
const RANGE_VALUES = new Set(RANGE_OPTIONS.map((option) => option.value));
// What the calendar's reset names, for each dashboard's default span.
export const DEFAULT_WORDS = { today: 'Today', '7d': 'Last 7 days', month: 'This month', [ALL_TIME]: 'All time' };

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
const DAY_MS = 24 * 60 * 60 * 1000;

function daysBefore(iso, days) {
  const [year, month, day] = iso.split('-').map(Number);
  return new Date(Date.UTC(year, month - 1, day) - days * DAY_MS).toISOString().slice(0, 10);
}

/**
 * The Indian dates a preset covers as of `now`, `{ from, to }`, inclusive,
 * each up to today: Today; 7 Days, today and the six before it; This Month,
 * from its first day; All Time, no first date at all (`from` null). Null for Custom.
 */
export function rangeSpan(preset, now = new Date()) {
  const today = indianToday(now);
  switch (preset) {
    case 'today':
      return { from: today, to: today };
    case '7d':
      return { from: daysBefore(today, 6), to: today };
    case 'month':
      return { from: `${today.slice(0, 8)}01`, to: today };
    case ALL_TIME:
      return { from: null, to: today };
    default:
      return null;
  }
}

/**
 * A dashboard's dates from its URL: `range` (a preset; `fallback`, the
 * dashboard's own default, when absent or unknown -- an old link's 30 Days
 * included) and, for Custom, `from` and `to`: a Custom range missing either
 * end, or ending before it starts, falls back to the default. Answers
 * `{ range, from, to }`.
 */
export function readRange(searchParams, fallback, now = new Date()) {
  const asked = RANGE_VALUES.has(searchParams.get('range')) ? searchParams.get('range') : fallback;
  if (asked === CUSTOM) {
    const from = DATE_RE.test(searchParams.get('from') ?? '') ? searchParams.get('from') : '';
    const to = DATE_RE.test(searchParams.get('to') ?? '') ? searchParams.get('to') : '';
    if (from && to && from <= to) return { range: CUSTOM, from, to };
  }
  const preset = asked === CUSTOM ? fallback : asked;
  return { range: preset, ...rangeSpan(preset, now) };
}

export const isAllTime = (range) => range.range === ALL_TIME;

/** What the API is asked for: All Time as `range=all` (no lower date at all), any other span as its dates. */
export const rangeQuery = (allTime, from, to) => (allTime ? { range: ALL_TIME } : { from, to });

/**
 * The dates the dashboard shows for `range`: its own, or for All Time those
 * the API answered (`answered`, its `range`: from the first record counted to
 * today) once it has -- an answer for another span is never taken for it.
 */
export function shownRange(range, answered) {
  if (!isAllTime(range)) return range;
  return answered?.all_time ? { ...range, from: answered.from, to: answered.to } : range;
}

/** The span in words, under the presets: "21 Nov 2026 – 27 Nov 2026", "All time: 3 Jan 2025 – 27 Nov 2026". */
export function rangeWords(range, answered) {
  if (!isAllTime(range)) return rangeLabel(range.from, range.to, '');
  const shown = shownRange(range, answered);
  return shown.from ? `All time: ${rangeLabel(shown.from, shown.to, '')}` : `All time, up to ${format(toPickerDate(shown.to), 'd MMM yyyy')}`;
}

/** The URL's values for a picked preset (none for the dashboard's default) or a picked Custom range (cleared: the default). */
export function rangeUpdates(picked, fallback) {
  if (picked.range === CUSTOM) return picked.from ? { range: CUSTOM, from: picked.from, to: picked.to } : { range: null, from: null, to: null };
  return { range: picked.range === fallback ? null : picked.range, from: null, to: null };
}

/**
 * A trend bucket (`{ from, to }`, Indian dates, as the API draws a span: backend
 * core/dashboard_dates.trend_buckets) in words: "12 Nov" for a day,
 * "10–16 Nov" for a week (or the part of it the span covers), "Nov 2026" for
 * a month, "2025" for a year.
 */
export function bucketLabel(bucket, unit) {
  const from = toPickerDate(bucket.from);
  const to = toPickerDate(bucket.to);
  if (unit === 'year') return format(from, 'yyyy');
  if (unit === 'month') return format(from, 'MMM yyyy');
  if (unit === 'day' || bucket.from === bucket.to) return format(from, 'd MMM');
  return from.getMonth() === to.getMonth() ? `${format(from, 'd')}–${format(to, 'd MMM')}` : `${format(from, 'd MMM')} – ${format(to, 'd MMM')}`;
}

/** What the trend's buckets are, for its subtitle: "day by day", "week by week", "month by month", "year by year". */
export const UNIT_WORDS = { day: 'day by day', week: 'week by week', month: 'month by month', year: 'year by year' };
