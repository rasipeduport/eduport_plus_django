/**
 * Timezone handling for session scheduling. Port of the Hub's lib/timezone.ts.
 *
 * Sessions are stored as absolute UTC instants. Mentors enter the *student's*
 * local wall-clock time, so the conversion from that wall time to an instant
 * needs an explicit IANA zone — never the mentor's browser zone.
 *
 * The API performs the authoritative conversion (items carry local_date +
 * local_time and the request carries the zone); this module exists for the
 * client-side preview and the pre-flight DST-gap check -- and for a Demo or
 * Diagnostic booking's Student Time (studentTime, below).
 */

import { slotParts } from './enquiries';

/** Mentors operate on IST. Fixed — never read from the runtime. */
export const MENTOR_TIMEZONE = 'Asia/Kolkata';

/** Applied when a student has no timezone set. Matches historical behaviour. */
export const DEFAULT_TIMEZONE = 'Asia/Kolkata';

/**
 * Zones offered in the scheduling UI, ordered by how often Eduport uses them.
 * A curated list, not the full IANA database; any valid IANA string is still
 * accepted by `isValidTimezone`, so a stored value outside it keeps working.
 * `place` names where a zone is when its `short` is an abbreviation (ET,
 * AEST) rather than a place: staff read a booking's Student Time with it
 * ("9:00 PM New York", studentTimezoneLabel). The selects never show it.
 */
export const TIMEZONE_OPTIONS = [
  { value: 'Asia/Kolkata', label: 'India', short: 'IST', place: 'India' },
  { value: 'Asia/Dubai', label: 'United Arab Emirates', short: 'UAE' },
  { value: 'Asia/Qatar', label: 'Qatar', short: 'Qatar' },
  { value: 'Asia/Riyadh', label: 'Saudi Arabia', short: 'KSA' },
  { value: 'Asia/Kuwait', label: 'Kuwait', short: 'Kuwait' },
  { value: 'Asia/Bahrain', label: 'Bahrain', short: 'Bahrain' },
  { value: 'Asia/Muscat', label: 'Oman', short: 'Oman' },
  { value: 'Asia/Singapore', label: 'Singapore', short: 'SGT', place: 'Singapore' },
  { value: 'Europe/London', label: 'United Kingdom', short: 'UK' },
  { value: 'America/New_York', label: 'US — Eastern', short: 'ET', place: 'New York' },
  { value: 'America/Chicago', label: 'US — Central', short: 'CT', place: 'Chicago' },
  { value: 'America/Denver', label: 'US — Mountain', short: 'MT', place: 'Denver' },
  { value: 'America/Los_Angeles', label: 'US — Pacific', short: 'PT', place: 'Los Angeles' },
  { value: 'Australia/Sydney', label: 'Australia — Sydney', short: 'AEST', place: 'Sydney' },
  { value: 'Australia/Perth', label: 'Australia — Perth', short: 'AWST', place: 'Perth' },
  { value: 'Asia/Colombo', label: 'Sri Lanka', short: 'Sri Lanka' },
  { value: 'Asia/Kathmandu', label: 'Nepal', short: 'Nepal' },
  { value: 'Asia/Dhaka', label: 'Bangladesh', short: 'Bangladesh' },
];

const OPTION_BY_VALUE = new Map(TIMEZONE_OPTIONS.map((o) => [o.value, o]));

/** Short label for the inline reference; falls back to the raw identifier. */
export function timezoneShortLabel(zone) {
  return OPTION_BY_VALUE.get(zone)?.short ?? zone;
}

/** True when the runtime's ICU data recognises this identifier. */
export function isValidTimezone(zone) {
  if (!zone || typeof zone !== 'string') return false;
  try {
    new Intl.DateTimeFormat('en-US', { timeZone: zone });
    return true;
  } catch {
    return false;
  }
}

// --------------------------------------------------------------- conversion

/**
 * The wall-clock time `zone` was showing at a given instant, as UTC-epoch ms.
 * Formatting an instant into a zone and reading the parts back as if they were
 * UTC yields `instant + offset`.
 */
function zonedPartsAsUtcMs(instant, zone) {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: zone,
    hour12: false,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }).formatToParts(instant);

  const get = (type) => Number(parts.find((p) => p.type === type)?.value ?? '0');

  // `hour12: false` renders midnight as hour 24 in some ICU versions.
  const hour = get('hour') % 24;

  return Date.UTC(get('year'), get('month') - 1, get('day'), hour, get('minute'), get('second'));
}

/** The zone's UTC offset, in ms, at a given instant. */
function offsetMsAt(instant, zone) {
  return zonedPartsAsUtcMs(instant, zone) - instant.getTime();
}

export class TimezoneConversionError extends Error {
  constructor(message) {
    super(message);
    this.name = 'TimezoneConversionError';
  }
}

const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;
const TIME_PATTERN = /^([01]\d|2[0-3]):[0-5]\d$/;

/**
 * Convert a wall-clock time `{ date: 'YYYY-MM-DD', time: 'HH:mm' }` in `zone`
 * to the UTC instant it names.
 *
 * Spring-forward gaps are rejected (the time never occurs); fall-back
 * repeats resolve to the earlier instant. Same rules as the API.
 */
export function zonedWallTimeToUtc(wall, zone) {
  if (!DATE_PATTERN.test(wall.date)) {
    throw new TimezoneConversionError(`date must be YYYY-MM-DD, received "${wall.date}"`);
  }
  if (!TIME_PATTERN.test(wall.time)) {
    throw new TimezoneConversionError(`time must be HH:mm (24-hour), received "${wall.time}"`);
  }
  if (!isValidTimezone(zone)) {
    throw new TimezoneConversionError(`unknown time zone "${zone}"`);
  }

  const [year, month, day] = wall.date.split('-').map(Number);
  const [hour, minute] = wall.time.split(':').map(Number);

  // Guard against dates the calendar rolls over (e.g. 2026-02-30).
  const naiveUtcMs = Date.UTC(year, month - 1, day, hour, minute, 0, 0);
  const naive = new Date(naiveUtcMs);
  if (naive.getUTCFullYear() !== year || naive.getUTCMonth() !== month - 1 || naive.getUTCDate() !== day) {
    throw new TimezoneConversionError(`"${wall.date}" is not a real date`);
  }

  // Pass 1: assume the offset at the naive reading; pass 2: re-solve with the
  // offset that actually applies at that candidate.
  let candidateMs = naiveUtcMs - offsetMsAt(naive, zone);
  candidateMs = naiveUtcMs - offsetMsAt(new Date(candidateMs), zone);

  const candidate = new Date(candidateMs);

  if (zonedPartsAsUtcMs(candidate, zone) !== naiveUtcMs) {
    throw new TimezoneConversionError(
      `${wall.date} ${wall.time} does not exist in ${zone} — clocks move forward past it`
    );
  }

  // Ambiguous times (fall-back) resolve to whichever instant came first.
  const earlierMs = candidateMs - 3_600_000;
  if (zonedPartsAsUtcMs(new Date(earlierMs), zone) === naiveUtcMs) {
    return new Date(earlierMs);
  }

  return candidate;
}

/** Read an instant back as wall-clock parts in `zone` — the inverse of above. */
export function utcToZonedWallTime(instant, zone) {
  const date = instant instanceof Date ? instant : new Date(instant);
  const asUtc = new Date(zonedPartsAsUtcMs(date, zone));
  const pad = (n) => String(n).padStart(2, '0');
  return {
    date: `${asUtc.getUTCFullYear()}-${pad(asUtc.getUTCMonth() + 1)}-${pad(asUtc.getUTCDate())}`,
    time: `${pad(asUtc.getUTCHours())}:${pad(asUtc.getUTCMinutes())}`,
  };
}

// --------------------------------------------------------------- formatting

/** `5:00 PM` — locale pinned for the same reason the zone is. */
export function formatTimeInZone(instant, zone) {
  return new Intl.DateTimeFormat('en-US', {
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
    timeZone: zone,
  }).format(instant instanceof Date ? instant : new Date(instant));
}

/** `10 Aug 2026` in the given zone -- the profile tabs' compact date. */
export function formatShortDateInZone(instant, zone) {
  return new Intl.DateTimeFormat('en-GB', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    timeZone: zone,
  }).format(instant instanceof Date ? instant : new Date(instant));
}

/**
 * An `Intl.DateTimeFormat` pinned to en-US and MENTOR_TIMEZONE for the staff
 * tables: a session scheduled at 12:30 PM Dubai reads 2:00 PM IST on every
 * staff device, whatever zone that device is set to.
 */
export function mentorZoneFormatter(options) {
  return new Intl.DateTimeFormat('en-US', { ...options, timeZone: MENTOR_TIMEZONE });
}

/** `Mon, 10 Aug 2026` in the given zone (date-fns would use the browser's). */
export function formatDateInZone(instant, zone) {
  return new Intl.DateTimeFormat('en-GB', {
    weekday: 'short',
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    timeZone: zone,
  }).format(instant instanceof Date ? instant : new Date(instant));
}

// ------------------------------------------------------------- student time
//
// A Demo or Diagnostic booking is offered, booked and moved in Indian time
// (backend bookings.scheduling); staff also read it at the student's own time
// -- "Student Time" -- from the booking's real instant (the API's UTC
// `starts_at`) and the zone the student's lead keeps (the API's
// `student_timezone`, an IANA zone or null). Never from a slot's date and time
// strings, and never from the responses' `timezone`, which is India's. Every
// zone reaches Intl only once isValidTimezone has passed it: Intl throws on
// one it does not know, and a render that throws blanks the Hub.

/** An API instant (an ISO string or a Date) as a Date, or null when it is missing or not a moment. */
function asInstant(value) {
  if (value instanceof Date) return Number.isNaN(value.getTime()) ? null : value;
  if (typeof value !== 'string' || !value) return null;
  const instant = new Date(value);
  return Number.isNaN(instant.getTime()) ? null : instant;
}

// The older names (tzdata's backward links) a browser may give for a listed
// zone -- Chrome reports India as Asia/Calcutta -- written out, so a student
// reads the same on every staff browser: engines differ in which name they resolve to.
const LISTED_ALIASES = new Map([
  ['Asia/Calcutta', 'Asia/Kolkata'],
  ['Asia/Katmandu', 'Asia/Kathmandu'],
  ['Asia/Dacca', 'Asia/Dhaka'],
  ['Singapore', 'Asia/Singapore'],
  ['GB', 'Europe/London'],
  ['GB-Eire', 'Europe/London'],
  ['Europe/Belfast', 'Europe/London'],
  ['US/Eastern', 'America/New_York'],
  ['US/Central', 'America/Chicago'],
  ['US/Mountain', 'America/Denver'],
  ['US/Pacific', 'America/Los_Angeles'],
  ['Australia/ACT', 'Australia/Sydney'],
  ['Australia/Canberra', 'Australia/Sydney'],
  ['Australia/NSW', 'Australia/Sydney'],
  ['Australia/West', 'Australia/Perth'],
]);

/** The curated option for `zone` under any of its names, or null for a zone the list does not hold. */
function listedOption(zone) {
  return OPTION_BY_VALUE.get(zone) ?? OPTION_BY_VALUE.get(LISTED_ALIASES.get(zone)) ?? null;
}

/**
 * A saved zone as a timezone select holds it: the curated option's value
 * under any of its names (Asia/Calcutta -> Asia/Kolkata), any other zone as
 * it is -- the select lists it on its own -- or '' for none.
 */
export function listedTimezone(zone) {
  if (!zone || typeof zone !== 'string') return '';
  return listedOption(zone)?.value ?? zone;
}

/**
 * Where a student's zone is, as staff read it after a time: the curated
 * list's name for a listed zone, under any of its names -- its `place` ("New
 * York", "Sydney") where its short label is an abbreviation, else that label
 * ("UAE", "UK"); for any other zone its IANA city ("Europe/Berlin" ->
 * "Berlin", "America/Argentina/Buenos_Aires" -> "Buenos Aires"); for one that
 * names no place (Etc/GMT+5, UTC) its offset at `at` as Intl names it
 * ("GMT-5"), else the identifier itself.
 */
export function studentTimezoneLabel(zone, at = new Date()) {
  if (!zone || typeof zone !== 'string') return '';
  const option = listedOption(zone);
  if (option) return option.place ?? option.short;
  if (/^Etc\//i.test(zone) || !zone.includes('/')) {
    try {
      const offset = new Intl.DateTimeFormat('en-US', { timeZone: zone, timeZoneName: 'shortOffset' })
        .formatToParts(at instanceof Date ? at : new Date(at))
        .find((part) => part.type === 'timeZoneName')?.value;
      return offset || zone;
    } catch {
      return zone;
    }
  }
  return zone.slice(zone.lastIndexOf('/') + 1).replace(/_/g, ' ');
}

/**
 * A booking's Student Time: its instant (`startsAt`) on the clock of the
 * student's zone (`zone`), daylight saving included, as the zone's Intl data
 * has it then. Null when either is missing or not one this runtime knows, and
 * when the student's clock reads India's date and time at that instant --
 * Asia/Kolkata, its old name Asia/Calcutta, Asia/Colombo -- where Indian time
 * already says it. Otherwise `{ time, day, otherDay, place, label }`: "6:00
 * AM" and "Sun, 8 Nov" (slotParts' look, in the student's zone), whether that
 * day is not India's, where the zone is (studentTimezoneLabel), and the whole
 * as staff read it: "6:00 AM UAE", or "Fri, 6 Nov · 9:00 PM New York" on
 * another day.
 */
export function studentTime(startsAt, zone) {
  if (!isValidTimezone(zone)) return null;
  const instant = asInstant(startsAt);
  if (!instant) return null;
  const student = utcToZonedWallTime(instant, zone);
  const india = utcToZonedWallTime(instant, MENTOR_TIMEZONE);
  if (student.date === india.date && student.time === india.time) return null;
  const { day, time } = slotParts(student.date, student.time);
  const otherDay = student.date !== india.date;
  const place = studentTimezoneLabel(zone, instant);
  return { time, day, otherDay, place, label: otherDay ? `${day} · ${time} ${place}` : `${time} ${place}` };
}

/**
 * How a booking's Student Time reads: 'unknown' without a zone this runtime
 * knows (or an instant), 'same' when the student's clock reads India's, else
 * 'different'.
 */
export function studentTimeState(startsAt, zone) {
  if (!isValidTimezone(zone) || !asInstant(startsAt)) return 'unknown';
  return studentTime(startsAt, zone) ? 'different' : 'same';
}

/**
 * Whether a list shows its Student Time column: when at least one of `rows`
 * reads differently from India -- `startsAtOf(row)` its instant, `zoneOf(row)`
 * its student's zone. A list of Indian students only, or of unknown zones,
 * has nothing to add to its Indian time.
 */
export function showsStudentTime(rows, startsAtOf, zoneOf) {
  return (rows ?? []).some((row) => studentTimeState(startsAtOf(row), zoneOf(row)) === 'different');
}

/**
 * A lead's saved zone as its details show it: "United Arab Emirates
 * (Asia/Dubai)" for a listed zone (under any of its names: "India
 * (Asia/Calcutta)"), any other zone's IANA identifier -- one this browser's
 * own zone data does not know yet included -- or "Not set" for none.
 */
export function savedTimezoneLabel(zone) {
  if (!zone || typeof zone !== 'string') return 'Not set';
  const option = listedOption(zone);
  return option ? `${option.label} (${zone})` : zone;
}
