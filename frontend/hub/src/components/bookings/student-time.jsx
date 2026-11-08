import { Button } from '@/components/ui/button';
import { savedTimezoneLabel, studentTime, studentTimeState } from '@/lib/timezone';
import { cn } from '@/lib/utils';

/**
 * A booking's Student Time in a list's own Student Time column or card field
 * (lib/timezone studentTime): the student's time where it reads differently
 * from India's ("6:00 AM UAE", or "Fri, 6 Nov · 9:00 PM New York" on another
 * day), "Same as IST" where it does not, a dash while the student's zone is
 * not known. `startsAt` is the booking's own instant (the API's UTC
 * `starts_at`), so a rescheduled booking reads at its new slot; `timezone` is
 * the API's `student_timezone` -- never its `timezone`, which is India's.
 * A table's column keeps it on one line; a card lets it wrap.
 */
export function StudentTimeCell({ startsAt, timezone }) {
  const time = studentTime(startsAt, timezone);
  if (time) return <span className="font-medium">{time.label}</span>;
  return (
    <span className="text-muted-foreground">{studentTimeState(startsAt, timezone) === 'same' ? 'Same as IST' : '—'}</span>
  );
}

/**
 * "Student Time: 6:00 AM UAE" under a booking's Indian time -- a workspace
 * header's slot, a booking named beside other facts -- and nothing at all
 * where it would add nothing: no zone known, or the student's clock reads
 * India's. `className` places it.
 */
export function StudentTimeLine({ startsAt, timezone, className }) {
  const time = studentTime(startsAt, timezone);
  if (!time) return null;
  return (
    <span className={cn('text-muted-foreground block text-sm', className)}>
      Student Time: <span className="text-foreground font-medium">{time.label}</span>
    </span>
  );
}

/**
 * A lead's saved zone among its details (lib/timezone savedTimezoneLabel):
 * "United Arab Emirates (Asia/Dubai)", or a muted "Not set"; with Change
 * beside it for whoever may correct it (`onChange`, opening the page's
 * StudentTimezoneDialog) -- read-only without.
 */
export function StudentTimezone({ zone, onChange }) {
  return (
    <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
      <span className={zone ? undefined : 'text-muted-foreground'}>{savedTimezoneLabel(zone)}</span>
      {onChange ? (
        <Button variant="link" size="sm" className="h-auto p-0" onClick={onChange} aria-label="Change student timezone">
          Change
        </Button>
      ) : null}
    </span>
  );
}
