import { CalendarDays } from 'lucide-react';
import { format } from 'date-fns';

function greetingFor(date) {
  const hour = date.getHours();
  if (hour < 12) return 'Good morning';
  if (hour < 17) return 'Good afternoon';
  return 'Good evening';
}

/** The browser's zone plus its offset, e.g. "Asia/Dubai (GMT+4)". */
function zoneLabel(date) {
  try {
    const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    const offset = new Intl.DateTimeFormat('en-US', { timeZoneName: 'shortOffset' })
      .formatToParts(date)
      .find((part) => part.type === 'timeZoneName')?.value;
    return [zone, offset ? `(${offset})` : null].filter(Boolean).join(' ');
  } catch {
    return null;
  }
}

/**
 * Greeting + today's date. The name comes from the signed-in user the layout
 * already holds; the date and zone are the browser's, the same clock the
 * session times on this page are shown in.
 */
export function DashboardHeader({ user }) {
  const now = new Date();
  const firstName = (user?.full_name || '').trim().split(' ')[0] || null;
  const zone = zoneLabel(now);

  return (
    <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
      <div className="min-w-0">
        <h1 className="text-xl font-semibold">
          {greetingFor(now)}
          {firstName ? `, ${firstName}` : ''} <span aria-hidden="true">👋</span>
        </h1>
        <p className="text-muted-foreground mt-1 text-sm">Here&apos;s what&apos;s happening across Eduport Plus.</p>
      </div>
      <div className="flex items-center gap-2.5">
        <span className="bg-muted text-muted-foreground flex size-8 shrink-0 items-center justify-center rounded-md">
          <CalendarDays className="size-4" />
        </span>
        <div className="min-w-0">
          <p className="text-sm font-medium whitespace-nowrap">{format(now, 'EEEE, d MMM yyyy')}</p>
          {zone ? <p className="text-muted-foreground text-xs">{zone}</p> : null}
        </div>
      </div>
    </div>
  );
}
