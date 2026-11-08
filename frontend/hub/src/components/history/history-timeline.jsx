import { useState } from 'react';
import { HistoryIcon } from 'lucide-react';

import { istMoment } from '@/lib/communications';
import { HISTORY_TONES, historyBookingLabel, historyDetails, historyTitle, historyWho, statusLabel } from '@/lib/history';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { Panel, PanelEmpty } from '@/components/dashboard/dashboard-primitives';
import { FilterSelect } from '@/components/page/list-toolbar';
import { StudentTimeLine } from '@/components/bookings/student-time';

const DOTS = {
  destructive: 'bg-destructive',
  success: 'bg-success',
  warning: 'bg-warning',
  muted: 'bg-muted-foreground',
};

function Entry({ entry, showBooking, studentTimezone }) {
  const tone = HISTORY_TONES[entry.kind];
  const lines = historyDetails(entry);
  return (
    <li className="relative flex gap-3 pb-5 last:pb-0">
      <span className="bg-border absolute top-3 bottom-0 left-[5px] w-px" aria-hidden="true" />
      <span
        className={cn('relative mt-1.5 size-[11px] shrink-0 rounded-full border-2 border-background', DOTS[tone] ?? 'bg-primary')}
        aria-hidden="true"
      />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
          <p className="text-sm font-medium">{historyTitle(entry)}</p>
          <time className="text-muted-foreground text-xs whitespace-nowrap" dateTime={entry.at}>
            {istMoment(entry.at)}
          </time>
        </div>
        <p className="text-muted-foreground text-xs">By {historyWho(entry)}</p>
        {showBooking && entry.booking ? (
          <p className="text-muted-foreground mt-0.5 text-xs">{historyBookingLabel(entry.booking)}</p>
        ) : null}
        {lines.length ? (
          <ul className="mt-1 flex flex-col gap-0.5 text-sm">
            {lines.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        ) : null}
        {entry.kind === 'RESCHEDULED' && entry.details?.new_slot ? (
          <StudentTimeLine startsAt={entry.details.new_slot.starts_at} timezone={studentTimezone} className="text-xs" />
        ) : null}
      </div>
    </li>
  );
}

// "This booking": the booking a workspace opened and the ones it replaced when moved.
const THIS = 'this';

/**
 * A student's History (lib/history), oldest first, as a timeline: each change
 * with when (IST), who and what changed. With `chain_ids` -- opened from one
 * booking's workspace -- it starts on "This booking" (that booking and the
 * ones it replaced) with All bookings a choice away; the filter also lists
 * each of the student's bookings. `state` is useHistory's.
 */
export function HistoryTimeline({ state, title = 'History', subtitle, emptyMessage = 'Nothing has happened yet.' }) {
  const { data, failure, retry } = state;
  const chain = data?.chain_ids ?? [];
  // '' is every booking of the student; THIS the opened booking's chain; else one booking's id.
  const [scope, setScope] = useState(chain.length ? THIS : '');
  const [prevBooking, setPrevBooking] = useState(data?.booking_id ?? null);
  if ((data?.booking_id ?? null) !== prevBooking) {
    setPrevBooking(data?.booking_id ?? null);
    setScope(data?.chain_ids?.length ? THIS : '');
  }

  let body;
  if (failure && !data) {
    body = (
      <div className="flex flex-wrap items-center gap-3">
        <p className="text-destructive text-sm">{failure.message}</p>
        <Button variant="outline" size="sm" onClick={retry}>
          Try again
        </Button>
      </div>
    );
  } else if (!data) {
    body = (
      <div className="flex flex-col gap-3" aria-busy="true">
        <Skeleton className="h-12" />
        <Skeleton className="h-12" />
        <Skeleton className="h-12" />
      </div>
    );
  } else {
    const bookings = data.bookings ?? [];
    const chainIds = new Set(chain);
    let entries = data.entries ?? [];
    if (scope === THIS) entries = entries.filter((entry) => chainIds.has(entry.booking?.id));
    else if (scope) entries = entries.filter((entry) => entry.booking?.id === scope);
    const options = [
      ...(chain.length ? [{ value: THIS, label: 'This booking' }] : []),
      ...bookings.map((booking) => ({
        value: booking.id,
        label: `${historyBookingLabel(booking)} · ${statusLabel(booking.status)}`,
      })),
    ];
    body = (
      <div className="flex flex-col gap-4">
        {options.length > 1 ? (
          <FilterSelect
            label="Show the history of"
            placeholder="All bookings"
            value={scope}
            onChange={setScope}
            options={options}
            className="sm:w-96"
          />
        ) : null}
        {entries.length ? (
          <ol className="flex flex-col" aria-label="History">
            {entries.map((entry) => (
              <Entry
                key={entry.id}
                entry={entry}
                showBooking={bookings.length > 1}
                studentTimezone={data.student_timezone}
              />
            ))}
          </ol>
        ) : (
          <PanelEmpty icon={HistoryIcon} message={emptyMessage} />
        )}
      </div>
    );
  }

  return (
    <Panel
      icon={HistoryIcon}
      title={title}
      subtitle={subtitle ?? 'Every change, oldest first, in Indian time (IST), with who made it'}
    >
      {body}
    </Panel>
  );
}
