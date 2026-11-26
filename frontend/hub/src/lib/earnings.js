import { format } from 'date-fns';

import { MENTOR_TIMEZONE, formatShortDateInZone, formatTimeInZone } from './timezone';

// Tutor Earnings in the Hub (backend earnings app): every tutor's for
// administrators (/tutor-earnings), a tutor's own (/my-earnings). In Indian
// rupees only, whatever Sales and Finance use. The API serves amounts and
// units as text with two decimals ("27625.00", "46.50"); every figure here is
// the server's -- nothing is worked out on the page.

export const EARNINGS_API = '/api/earnings';

/** "₹27,625", "₹675.50", "−₹400": rupees with Indian grouping; paise only when there are some. */
export function formatInr(value, { signed = false } = {}) {
  if (value === null || value === undefined || value === '') return '—';
  const amount = Number(value);
  if (!Number.isFinite(amount)) return '—';
  const paise = Math.round(Math.abs(amount) * 100) % 100 !== 0;
  const text = new Intl.NumberFormat('en-IN', {
    style: 'currency',
    currency: 'INR',
    minimumFractionDigits: paise ? 2 : 0,
    maximumFractionDigits: paise ? 2 : 0,
  }).format(Math.abs(amount));
  if (amount < 0) return `−${text}`;
  return signed && amount > 0 ? `+${text}` : text;
}

// The rate types, in the API's order: Diagnostic and Demo are paid by the class, a normal session by the hour, and a
// Demo Conversion once per converted Demo. A Demo Conversion is not a class: its rate is the TOTAL a converted Demo
// earns, and it adds only the difference over what the Demo itself earned.
export const CLASS_TYPES = [
  { value: 'DIAGNOSTIC', label: 'Diagnostic', unit: 'CLASS' },
  { value: 'DEMO', label: 'Demo', unit: 'CLASS' },
  { value: 'SESSION', label: 'Normal Sessions', unit: 'HOUR' },
  { value: 'DEMO_CONVERSION', label: 'Demo Conversion', unit: 'CONVERSION' },
];

export const CONVERSION = 'DEMO_CONVERSION';

/** How a Demo Conversion is paid, in one line for the rate forms and the breakdown. */
export const CONVERSION_NOTE =
  'The total a converted Demo earns. When the student enrolls, the Demo’s tutor gets the difference over what the Demo earned (₹350 − ₹200 = +₹150).';

const CLASS_TYPE_SINGULAR = {
  DIAGNOSTIC: 'Diagnostic',
  DEMO: 'Demo',
  SESSION: 'Normal Session',
  DEMO_CONVERSION: 'Demo conversion',
};

/** "per class hour", "per converted Demo", "per class". */
export function unitPhrase(unit) {
  if (unit === 'HOUR') return 'per class hour';
  if (unit === 'CONVERSION') return 'per converted Demo';
  return 'per class';
}

/** "Diagnostic", "Demo", "Normal Sessions" -- or one "Normal Session" with `singular`. */
export function classTypeLabel(value, { singular = false } = {}) {
  if (singular) return CLASS_TYPE_SINGULAR[value] || value || '';
  return CLASS_TYPES.find((type) => type.value === value)?.label || value || '';
}

/** "1.5", "46.5", "2": units as read, without trailing zeros. */
export function trimUnits(value) {
  const number = Number(value);
  return Number.isFinite(number) ? String(Number(number.toFixed(2))) : '';
}

/** "14 classes", "1 class". */
export function classesLabel(count) {
  return `${count} ${Number(count) === 1 ? 'class' : 'classes'}`;
}

/** "1 conversion", "3 conversions". */
export function conversionsLabel(count) {
  return `${count} ${Number(count) === 1 ? 'conversion' : 'conversions'}`;
}

/**
 * The class counts of a period: "6 Diagnostic · 14 Demo · 38 sessions · 46.5 payable hours" -- and
 * " · 3 converted" when Demos converted (a conversion is not a class, so never in the class count).
 */
export function countsLine(counts) {
  const hours = trimUnits(counts.session_hours) || '0';
  const converted = Number(counts.conversions) > 0 ? ` · ${counts.conversions} converted` : '';
  return `${counts.diagnostic} Diagnostic · ${counts.demo} Demo · ${counts.sessions} ${
    Number(counts.sessions) === 1 ? 'session' : 'sessions'
  } · ${hours} payable ${hours === '1' ? 'hour' : 'hours'}${converted}`;
}

/** What one unit of `unit` is paid at: "₹450 / hour", "₹300 / class", "₹350 / converted Demo". */
export function rateLabel(amount, unit) {
  if (amount === null || amount === undefined) return '—';
  const per = { HOUR: 'hour', CONVERSION: 'converted Demo' }[unit] || 'class';
  return `${formatInr(amount)} / ${per}`;
}

/** The payable units of a line: "1.5 h" for a session, "2 conversions" for Demo Conversion, "1 class" otherwise. */
export function unitsLabel(units, unit) {
  if (units === null || units === undefined) return '—';
  if (unit === 'HOUR') return `${trimUnits(units)} h`;
  if (unit === 'CONVERSION') return conversionsLabel(trimUnits(units));
  return classesLabel(trimUnits(units));
}

/** "November 2026" from "2026-11". */
export function monthLabel(month) {
  if (!month) return 'All time';
  const [year, number] = month.split('-').map(Number);
  return format(new Date(year, number - 1, 1), 'MMMM yyyy');
}

// Class times read in India time on every device, as the rest of the staff Hub
// (lib/timezone MENTOR_TIMEZONE) and as earnings count months.

/** "16 Nov 2026" from an ISO date (that calendar day) or an instant (its day in India). */
export function dayLabel(iso) {
  if (!iso) return '—';
  if (/^\d{4}-\d{2}-\d{2}$/.test(iso)) {
    const [year, month, day] = iso.split('-').map(Number);
    return formatShortDateInZone(new Date(Date.UTC(year, month - 1, day, 12)), 'UTC');
  }
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? '—' : formatShortDateInZone(date, MENTOR_TIMEZONE);
}

/** "4:00 PM" of an instant, in India. */
export function timeLabel(iso) {
  if (!iso) return '';
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? '' : formatTimeInZone(date, MENTOR_TIMEZONE);
}

/** "16 Nov 2026, 4:00 PM" of an instant, in India. */
export function stampLabel(iso) {
  return iso ? `${dayLabel(iso)}, ${timeLabel(iso)}` : '—';
}

// Why a class the tutor taught is not counted yet (backend earnings.summaries.not_counted).
export const NOT_COUNTED_REASONS = {
  NOTES_DUE: { label: 'Notes due', hint: "Counts once the tutor's notes are in -- whenever they come in." },
  REPORT_DUE: { label: 'Report due', hint: 'Counts once the tutor submits its report.' },
  SLOT_NOT_ENDED: { label: 'Slot not over yet', hint: 'The report is in; it counts once the slot ends.' },
  WAITING_FOR_RATES: { label: 'Waiting for rates', hint: 'It counts; it is priced once the initial rates are set.' },
  BEING_ADDED: { label: 'Being added', hint: 'It counts; the next sync (every 10 minutes) adds it.' },
  WAITING_FOR_DEMO: {
    label: 'Waiting for its Demo',
    hint: 'The student enrolled; the conversion is added once the Demo itself counts.',
  },
};

// Why an earned class is listed for review (backend earnings.summaries.review_items).
export const REVIEW_PROBLEMS = {
  SOURCE_MISSING: 'The class no longer exists.',
  TUTOR_CHANGED: 'The class is now assigned to another tutor.',
  TIMES_CHANGED: 'The class was rescheduled after it earned.',
  NO_LONGER_ELIGIBLE: 'The class no longer meets the earning rules.',
  DEMO_EARNING_REVERSED: 'The earning of the Demo it converted was reversed after the student enrolled.',
};

/** What changed in a review item's class, as it reads now: the problem, then the specifics. */
export function reviewDetail(item) {
  const current = item?.current;
  const parts = [REVIEW_PROBLEMS[item?.problem] || item?.problem || ''];
  if (item?.problem === 'TUTOR_CHANGED' && item.current_tutor) {
    parts.push(`It is now ${item.current_tutor.name}'s${current?.eligible ? ', and counts for them' : ''}.`);
  }
  if (item?.problem === 'TIMES_CHANGED' && current?.class_end) {
    parts.push(`It now reads ${stampLabel(current.class_start)} – ${stampLabel(current.class_end)}.`);
    if (current.eligible === false) parts.push('It no longer meets the earning rules either.');
  }
  return parts.join(' ');
}

export const PAYMENT_METHODS = [
  { value: 'ACCOUNT_TRANSFER', label: 'Account Transfer' },
  { value: 'UPI', label: 'UPI' },
];

/** The student or lead a ledger line or a class is about, and its title. */
export function classSubject(item) {
  const details = item?.details || item || {};
  return details.student_name || details.title || '—';
}

/**
 * Why an earning counts, from what the sync recorded: "Started 4:01 PM · notes
 * 9 Feb, 6:02 PM" for a session, "Started 11:02 AM · report 11:55 AM · slot
 * ended 12:00 PM" for a booking, "Enrolled 4 Nov 2026, 5:30 PM · Demo earned
 * ₹200 → ₹350 converted" for a Demo conversion.
 */
export function whyItCounts(entry) {
  const details = entry?.details || {};
  if (entry?.kind !== 'EARNING') return entry?.reason || '';
  if (entry.class_type === CONVERSION) {
    // "Enrolled 4 Nov 2026, 5:30 PM · Demo earned ₹200 → ₹350 converted".
    return [
      details.converted_at ? `Enrolled ${stampLabel(details.converted_at)}` : 'Enrolled',
      details.demo_amount ? `Demo earned ${formatInr(details.demo_amount)} → ${formatInr(details.final_amount)} converted` : null,
    ]
      .filter(Boolean)
      .join(' · ');
  }
  const started = details.started_at ? `Started ${timeLabel(details.started_at)}` : 'Started';
  if (entry.class_type === 'SESSION') {
    const by = details.started_by_name ? ` by ${details.started_by_name}` : '';
    return [`${started}${by}`, details.completed_at ? `tutor notes ${stampLabel(details.completed_at)}` : null]
      .filter(Boolean)
      .join(' · ');
  }
  return [
    started,
    details.report_submitted_at ? `report ${stampLabel(details.report_submitted_at)}` : null,
    details.slot_ends_at ? `slot ended ${timeLabel(details.slot_ends_at)}` : null,
  ]
    .filter(Boolean)
    .join(' · ');
}

/** The balance a tutor stands at, as a short label: "Pending ₹7,625", "Paid in full", "Overpaid ₹450", "Nothing earned yet". */
export function balanceLabel(state, outstanding) {
  if (state === 'pending') return formatInr(outstanding);
  if (state === 'overpaid') return `Overpaid ${formatInr(Math.abs(Number(outstanding)))}`;
  if (state === 'paid') return 'Paid in full';
  return 'Nothing earned yet';
}

/** A fresh key for one recording dialog: a repeated request with it records the payment once. */
export function requestKey() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    return (c === 'x' ? r : (r & 0x3) | 0x8).toString(16);
  });
}

/** `{ status, code, message, field, data }` from a failed earnings request. */
export function earningsError(err, fallback) {
  const data = err?.response?.data || {};
  return {
    status: err?.response?.status ?? null,
    code: typeof data.code === 'string' ? data.code : null,
    message: data.error || data.detail || data.message || err?.message || fallback,
    field: typeof data.field === 'string' ? data.field : null,
    data,
  };
}

/** Today's date in India, "YYYY-MM-DD": the latest a payment may be dated. */
export function indiaToday() {
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Kolkata' }).format(new Date());
}
