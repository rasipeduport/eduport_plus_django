import { Link2Icon, ListOrderedIcon } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { slotLabel } from '@/lib/enquiries';
import { reportText } from '@/lib/redemo-workspace';
import { PanelEmpty } from '@/components/dashboard/dashboard-primitives';
import { BookingStateBadge, RedemoStatusBadge } from '../booking-badges';
import { StudentTimeLine } from '../student-time';
import { WorkspaceCard } from './parts';

/** One booking of the request, in a row: which it is, when (IST and the student's time), its tutor, state and report. */
function Attempt({ label, booking, zone, onOpenBooking }) {
  return (
    <li className="grid gap-x-4 gap-y-1 py-3 text-sm sm:grid-cols-[9rem_minmax(0,1.4fr)_minmax(0,1fr)_minmax(0,1fr)_auto] sm:items-start">
      <span className="font-medium">{label}</span>
      <span className="flex min-w-0 flex-col">
        <span>{slotLabel(booking.slot)}</span>
        <StudentTimeLine startsAt={booking.slot?.starts_at} timezone={zone} />
      </span>
      <span className="min-w-0">
        <span className="text-muted-foreground sm:hidden">Tutor: </span>
        {booking.tutor?.full_name ?? <span className="text-muted-foreground">No tutor</span>}
      </span>
      <span className="flex min-w-0 flex-col items-start gap-1">
        <BookingStateBadge booking={booking} />
        {booking.cancel_reason ? <span className="text-muted-foreground text-xs">{booking.cancel_reason.label}</span> : null}
        <span className="text-muted-foreground text-xs">
          Report: {reportText(booking)}
          {booking.has_report && booking.report_shared ? ' · shared' : ''}
        </span>
      </span>
      <Button variant="link" size="sm" className="h-auto justify-self-start p-0" onClick={() => onOpenBooking(booking.id)}>
        Open booking
      </Button>
    </li>
  );
}

/**
 * The workspace's Attempts tab: the Demo the request repeats, then every
 * Re-Demo booked for it in the order they were booked (the API's `bookings`,
 * oldest first: cancelled attempts, then the one that stands), each with its
 * tutor, state and report, opening in its booking's workspace
 * (`onOpenBooking`). When the lead has more Re-Demo requests than this one
 * (`chain`), they follow, each opening in its own workspace (`onOpenRedemo`).
 */
export function RedemoAttempts({ redemo, onOpenBooking, onOpenRedemo }) {
  const zone = redemo.student_timezone;
  const attempts = redemo.bookings ?? [];
  const chain = redemo.chain ?? [];
  return (
    <div className="flex flex-col gap-4">
      <WorkspaceCard icon={ListOrderedIcon} title="Attempts">
        <div className="text-muted-foreground hidden gap-x-4 border-b pb-2 text-xs font-medium sm:grid sm:grid-cols-[9rem_minmax(0,1.4fr)_minmax(0,1fr)_minmax(0,1fr)_auto]">
          <span>Booking</span>
          <span>Date and time</span>
          <span>Tutor</span>
          <span>Status and report</span>
          <span className="sr-only">Open</span>
        </div>
        <ol className="divide-y" aria-label="Attempts">
          <Attempt label="Original Demo" booking={redemo.original} zone={zone} onOpenBooking={onOpenBooking} />
          {attempts.map((booking, index) => (
            <Attempt
              key={booking.id}
              label={`Re-Demo attempt ${index + 1}`}
              booking={booking}
              zone={zone}
              onOpenBooking={onOpenBooking}
            />
          ))}
        </ol>
        {attempts.length ? null : <PanelEmpty icon={ListOrderedIcon} message="No Re-Demo has been booked for this request yet." />}
      </WorkspaceCard>

      {chain.length > 1 ? (
        <WorkspaceCard icon={Link2Icon} title="Re-Demo chain">
          <ol className="flex flex-col divide-y text-sm" aria-label="Re-Demo chain">
            {chain.map((link, index) => (
              <li key={link.id} className="flex flex-wrap items-center justify-between gap-2 py-2.5">
                <span className="min-w-0">
                  <span className="font-medium">Re-Demo {index + 1}</span>
                  <span className="text-muted-foreground">
                    {' '}
                    · of {slotLabel(link.original.slot)}
                    {/* A cancelled attempt is not the Re-Demo: it waits to be scheduled again. */}
                    {link.booking && link.booking.status !== 'CANCELLED' ? ` → ${slotLabel(link.booking.slot)}` : ''}
                  </span>
                </span>
                <span className="flex items-center gap-2">
                  <RedemoStatusBadge status={link.status} />
                  {link.current ? (
                    <Badge variant="outline">This request</Badge>
                  ) : (
                    <Button variant="link" size="sm" className="h-auto p-0" onClick={() => onOpenRedemo(link.id)}>
                      Open
                    </Button>
                  )}
                </span>
              </li>
            ))}
          </ol>
        </WorkspaceCard>
      ) : null}
    </div>
  );
}
