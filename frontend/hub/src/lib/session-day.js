/**
 * "Today" for the dashboard, in the browser's local calendar day.
 *
 * The Sessions page prints every date and time browser-local (its DATE_FORMAT
 * / TIME_FORMAT carry no timeZone), so a class that lands on tomorrow's date
 * in that table must not be called "today" here. Comparing the UTC date would
 * get this wrong for any zone ahead of UTC: a 2:00 AM IST class on the 8th is
 * still the 7th in UTC.
 */

/** True when `iso` falls on the same local calendar day as `ref`. */
export function isOnLocalDay(iso, ref = new Date()) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return false;
  return d.getFullYear() === ref.getFullYear() && d.getMonth() === ref.getMonth() && d.getDate() === ref.getDate();
}

const isScheduled = (s) => (s.status || '').toLowerCase() === 'scheduled';

/** Scheduled classes that start on today's local date, in start order (ended ones included). */
export function sessionsToday(sessions, now = new Date()) {
  return sessions
    .filter((s) => isScheduled(s) && isOnLocalDay(s.start_time, now))
    .sort((a, b) => new Date(a.start_time) - new Date(b.start_time));
}

/** Today's scheduled classes that have not ended yet -- what "Upcoming Sessions" lists. */
export function remainingToday(sessions, now = new Date()) {
  const t = now.getTime();
  return sessionsToday(sessions, now).filter((s) => new Date(s.end_time).getTime() >= t);
}
