/**
 * Timezone handling for session scheduling. Port of the Hub's lib/timezone.ts.
 *
 * Sessions are stored as absolute UTC instants. Mentors enter the *student's*
 * local wall-clock time, so the conversion from that wall time to an instant
 * needs an explicit IANA zone — never the mentor's browser zone.
 *
 * The API performs the authoritative conversion (items carry local_date +
 * local_time and the request carries the zone); this module exists for the
 * client-side preview and the pre-flight DST-gap check.
 */

/** Mentors operate on IST. Fixed — never read from the runtime. */
export const MENTOR_TIMEZONE = 'Asia/Kolkata';

/** Applied when a student has no timezone set. Matches historical behaviour. */
export const DEFAULT_TIMEZONE = 'Asia/Kolkata';

/**
 * Zones offered in the scheduling UI, ordered by how often Eduport uses them.
 * A curated list, not the full IANA database; any valid IANA string is still
 * accepted by `isValidTimezone`, so a stored value outside it keeps working.
 */
export const TIMEZONE_OPTIONS = [
  { value: 'Asia/Kolkata', label: 'India', short: 'IST' },
  { value: 'Asia/Dubai', label: 'United Arab Emirates', short: 'UAE' },
  { value: 'Asia/Qatar', label: 'Qatar', short: 'Qatar' },
  { value: 'Asia/Riyadh', label: 'Saudi Arabia', short: 'KSA' },
  { value: 'Asia/Kuwait', label: 'Kuwait', short: 'Kuwait' },
  { value: 'Asia/Bahrain', label: 'Bahrain', short: 'Bahrain' },
  { value: 'Asia/Muscat', label: 'Oman', short: 'Oman' },
  { value: 'Asia/Singapore', label: 'Singapore', short: 'SGT' },
  { value: 'Europe/London', label: 'United Kingdom', short: 'UK' },
  { value: 'America/New_York', label: 'US — Eastern', short: 'ET' },
  { value: 'America/Chicago', label: 'US — Central', short: 'CT' },
  { value: 'America/Denver', label: 'US — Mountain', short: 'MT' },
  { value: 'America/Los_Angeles', label: 'US — Pacific', short: 'PT' },
  { value: 'Australia/Sydney', label: 'Australia — Sydney', short: 'AEST' },
  { value: 'Australia/Perth', label: 'Australia — Perth', short: 'AWST' },
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

/** A student's zone, with the documented fallback applied. */
export function resolveStudentTimezone(zone) {
  const trimmed = zone?.trim();
  return trimmed && isValidTimezone(trimmed) ? trimmed : DEFAULT_TIMEZONE;
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
