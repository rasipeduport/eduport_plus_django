// The administrators' Sales Dashboard: the /api/sales/dashboard/ contract
// (backend sales/dashboard.py) as the Hub uses it, its dates and its words.
// The dates are Indian dates, picked as the Admissions Dashboard's are
// (lib/admissions); amounts are whole AED, written as lib/payments writes them.
import { format } from 'date-fns';

import { readRange } from '@/lib/admissions';
import { toPickerDate } from '@/lib/date-range';

export const SALES_DASHBOARD_URL = '/api/sales/dashboard/';
// What the dashboard shows without dates: this month, as sales are reviewed month by month.
export const SALES_DEFAULT_RANGE = 'month';

/** The dashboard's dates from its URL: this month unless others were picked. */
export const readSalesRange = (searchParams, now = new Date()) => readRange(searchParams, now, SALES_DEFAULT_RANGE);

// What each part of the API's answer counts, in the Hub's words.
export const SALE_KINDS = { INITIAL: 'New enrollments', ADDITIONAL: 'Additional purchases' };
export const COLLECTION_PLANS = { FULL: 'Full payment', PARTIAL: 'Partial payment', AUTOPAY: 'AutoPay' };
export const FUNNEL_HINTS = {
  LEADS: 'Came in on these dates',
  QUOTED: 'A quote was issued',
  SALE_STARTED: 'A sale was started',
  ENROLLED: 'Paid and enrolled',
};

/** `part` of `whole` as a whole percentage; 0 when there is no whole. */
export const percent = (part, whole) => (whole > 0 ? Math.round((part / whole) * 100) : 0);

/** A whole AED amount's digits alone, "10,362", for a figure that names its currency apart. */
export const aedDigits = (amount) => new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 }).format(Number(amount));

/** The top of a chart's AED axis: `max` rounded up to 1, 2, 2.5 or 5 times a power of ten, at least AED 1,000. */
export function axisCeiling(max) {
  if (!(max > 1000)) return 1000;
  const step = 10 ** Math.floor(Math.log10(max));
  return [1, 2, 2.5, 5, 10].map((times) => times * step).find((ceiling) => ceiling >= max);
}

/** An amount on a chart's axis: "AED 950", "AED 12K", "AED 1.2M". */
export function compactAed(amount) {
  return `AED ${new Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 1 }).format(Number(amount))}`;
}

/** A student's Finance tab, where their purchases are collected. */
export const studentFinancePath = (studentId) => `/students/${studentId}?tab=finance`;

/**
 * A trend bucket (`{ from, to }`, Indian dates) in words: "12 Nov" for a day,
 * "10–16 Nov" for a week (or the part of it the span covers), "Nov 2026" for a month.
 */
export function bucketLabel(bucket, unit) {
  const from = toPickerDate(bucket.from);
  const to = toPickerDate(bucket.to);
  if (unit === 'month') return format(from, 'MMM yyyy');
  if (unit === 'day' || bucket.from === bucket.to) return format(from, 'd MMM');
  return from.getMonth() === to.getMonth() ? `${format(from, 'd')}–${format(to, 'd MMM')}` : `${format(from, 'd MMM')} – ${format(to, 'd MMM')}`;
}

/** What the trend's buckets are, for its subtitle: "day by day", "week by week", "month by month". */
export const UNIT_WORDS = { day: 'day by day', week: 'week by week', month: 'month by month' };
