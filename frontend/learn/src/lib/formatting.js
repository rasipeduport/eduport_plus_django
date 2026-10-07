// Timezone-safe date/time formatting for the student app.
//
// Every formatter pins BOTH the locale and the time zone. Sessions are stored
// as absolute UTC instants; these helpers only decide which wall clock that
// instant is projected onto -- always the student's own zone, never the
// device's. (An unpinned formatter made a 12:30 PM Dubai class read as
// 2:00 PM on a phone set to IST.) Ported from the original Learn's
// lib/datetime.ts.

/** Used until a student has an explicit timezone on their record. */
export const FALLBACK_TIMEZONE = 'Asia/Kolkata';

// Pinned for the same reason the zone is: an unpinned locale renders
// "5:30 pm" on one device and "5:30 PM" on another.
const LOCALE = 'en-US';

/** The zone a student's times are displayed in: their own, else IST. */
export function resolveStudentZone(student) {
  const zone = typeof student?.timezone === 'string' ? student.timezone.trim() : '';
  return zone || FALLBACK_TIMEZONE;
}

// Intl.DateTimeFormat construction is expensive and these run per card, so
// instances are memoised per (zone + options) pair.
const formatterCache = new Map();

function formatter(zone, options) {
  const key = `${zone}|${JSON.stringify(options)}`;
  const cached = formatterCache.get(key);
  if (cached) return cached;
  const created = new Intl.DateTimeFormat(LOCALE, { ...options, timeZone: zone });
  formatterCache.set(key, created);
  return created;
}

function toDate(value) {
  return value instanceof Date ? value : new Date(value);
}

// ------------------------------------------------------------------ day keys

/**
 * The calendar day an instant falls on *in a given zone*, as `YYYY-MM-DD`.
 * Replaces `toDateString()`, which always answers in the device's zone.
 * `en-CA` is the one common locale that formats as ISO-ordered parts.
 */
export function dayKeyInZone(value, zone) {
  return new Intl.DateTimeFormat('en-CA', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    timeZone: zone,
  }).format(toDate(value));
}

/** Shift a `YYYY-MM-DD` key by whole days, without touching any clock. */
export function shiftDayKey(dayKey, days) {
  const [y, m, d] = dayKey.split('-').map(Number);
  const shifted = new Date(Date.UTC(y, m - 1, d + days));
  const pad = (n) => String(n).padStart(2, '0');
  return `${shifted.getUTCFullYear()}-${pad(shifted.getUTCMonth() + 1)}-${pad(shifted.getUTCDate())}`;
}

// ---------------------------------------------------------------- formatting

/**
 * A session's start/end as a relative date label and a time range, both in
 * `zone` (the student's; see resolveStudentZone).
 *
 * @param {string} startIso
 * @param {string} endIso
 * @param {string} zone IANA zone; falls back to IST when empty
 * @param {{ relative?: 'future' | 'past', now?: Date }} options
 *   'future' (default) labels the adjacent day "Tomorrow"; 'past' labels it
 *   "Yesterday". Today is always "Today". `now` exists for tests.
 * @returns {{ dateLabel: string, timeLabel: string }}
 */
export function formatSessionDateTime(startIso, endIso, zone, { relative = 'future', now } = {}) {
  if (!startIso || !endIso) return { dateLabel: '', timeLabel: '' };
  const tz = zone || FALLBACK_TIMEZONE;
  const start = toDate(startIso);
  const end = toDate(endIso);

  const todayKey = dayKeyInZone(now || new Date(), tz);
  const startKey = dayKeyInZone(start, tz);
  const adjacentKey = shiftDayKey(todayKey, relative === 'past' ? -1 : 1);

  let dateLabel;
  if (startKey === todayKey) dateLabel = 'Today';
  else if (startKey === adjacentKey) dateLabel = relative === 'past' ? 'Yesterday' : 'Tomorrow';
  else dateLabel = formatter(tz, { weekday: 'short', month: 'short', day: 'numeric' }).format(start);

  const timeFmt = formatter(tz, { hour: 'numeric', minute: '2-digit', hour12: true });
  const timeLabel = `${timeFmt.format(start)} - ${timeFmt.format(end)}`;

  return { dateLabel, timeLabel };
}

/** `Jun 24, 2026` in `zone`. */
export function formatDate(iso, zone) {
  if (!iso) return '';
  return formatter(zone || FALLBACK_TIMEZONE, { month: 'short', day: 'numeric', year: 'numeric' }).format(toDate(iso));
}

/** `Wednesday, 24 June 2026, 12:30 PM` in `zone` (exam detail header). */
export function formatFullDateTime(iso, zone) {
  if (!iso) return '';
  return formatter(zone || FALLBACK_TIMEZONE, {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  }).format(toDate(iso));
}
