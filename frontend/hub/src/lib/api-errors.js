// Turns an axios error from the sessions API into something a form can show.
//
// The API answers every failure as `{ error: <text> }`; scheduling conflicts
// also carry `code` (TUTOR_SESSION_CONFLICT / STUDENT_SESSION_CONFLICT /
// SERIES_ITEMS_OVERLAP) and, for the first two, a `conflict` object naming
// the session that blocks the slot. The backend is the only place the overlap
// rule lives -- this module only renders what it says.
import { DEFAULT_TIMEZONE, formatDateInZone, formatTimeInZone, timezoneShortLabel } from './timezone';

const CONFLICT_TITLES = {
  TUTOR_SESSION_CONFLICT: 'Tutor unavailable',
  STUDENT_SESSION_CONFLICT: 'Session conflict',
  SERIES_ITEMS_OVERLAP: 'Classes overlap',
};

/** Best human-readable line from an API error body. */
export function apiErrorMessage(err, fallback) {
  const data = err?.response?.data;
  return data?.error || data?.message || fallback;
}

/**
 * `{ code, title, message, conflict }` for display. `title` is set only for
 * a recognised scheduling code; `conflict` is `{ who, when, title }` for the
 * blocking session, with times rendered in the zone the API named (the zone
 * the mentor was scheduling in).
 */
export function describeApiError(err, fallback) {
  const data = err?.response?.data || {};
  const code = typeof data.code === 'string' ? data.code : null;
  const message = apiErrorMessage(err, fallback);
  const title = code ? CONFLICT_TITLES[code] || null : null;

  let conflict = null;
  const c = data.conflict;
  if (c && c.start_time && c.end_time) {
    const zone = c.timezone || DEFAULT_TIMEZONE;
    const start = new Date(c.start_time);
    const end = new Date(c.end_time);
    if (!Number.isNaN(start.getTime()) && !Number.isNaN(end.getTime())) {
      const who =
        c.type === 'tutor'
          ? [c.tutor_name, c.student_name].filter(Boolean).join(' with ')
          : c.student_name || null;
      conflict = {
        type: c.type || null,
        title: c.title || null,
        who,
        when: `${formatDateInZone(start, zone)} · ${formatTimeInZone(start, zone)} – ${formatTimeInZone(end, zone)} ${timezoneShortLabel(zone)}`,
      };
    }
  }

  return { code, title, message, conflict };
}
