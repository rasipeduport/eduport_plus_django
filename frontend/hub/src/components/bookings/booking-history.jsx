import { useEffect, useState } from 'react';
import { format } from 'date-fns';

import api from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { bookingError, bookingHistoryUrl } from '@/lib/bookings';
import { slotLabel } from '@/lib/enquiries';
import { reportFieldsText } from '@/lib/reports';

/** One event of the timeline in words, from the names and labels the API reads back (never a child's or parent's). */
function describeBookingEvent(event) {
  const d = event.details ?? {};
  switch (event.kind) {
    case 'CREATED':
      return d.via === 'reschedule'
        ? `Booked in the new slot, ${slotLabel(d.slot)}`
        : `Booked on the booking page for ${slotLabel(d.slot)}`;
    case 'TUTOR_ASSIGNED':
      if (d.via === 'reschedule') return `${d.new_tutor?.full_name ?? 'The tutor'} carried over to the new slot`;
      return d.old_tutor
        ? `Tutor changed from ${d.old_tutor.full_name} to ${d.new_tutor?.full_name ?? '—'}`
        : `${d.new_tutor?.full_name ?? 'A tutor'} assigned`;
    case 'TUTOR_UNASSIGNED':
      return `${d.old_tutor?.full_name ?? 'The tutor'} unassigned`;
    // The tutor's own Start Demo / Start Diagnostic: the event's time is when they started it.
    case 'STARTED':
      return 'Started by the tutor';
    case 'RESCHEDULED':
      return `Moved from ${slotLabel(d.old_slot)} to ${slotLabel(d.new_slot)} — ${d.reason?.label ?? ''}`.replace(/ — $/, '');
    case 'CANCELLED':
      return d.reason?.label ? `Cancelled — ${d.reason.label}` : 'Cancelled';
    // The tutor's first report completes the booking; each later save is an edit,
    // named by its version and the fields it changed -- never by their text.
    case 'COMPLETED':
      return 'Completed — the report was submitted';
    case 'REPORT_EDITED': {
      const fields = reportFieldsText(d.changed_fields);
      return `Report edited, now version ${d.version ?? '—'}${fields ? ` — ${fields}` : ''}`;
    }
    // The tutor's permanent link changed while the booking was live; the history keeps whether there is one, never the link.
    case 'MEET_LINK_UPDATED':
      return d.has_meet_link ? "Meet link updated to the tutor's new link" : "Meet link removed with the tutor's";
    // The parent's answer to the confirmation request (PRD 3.11). Not Confirmed also cancels the booking, its own event next.
    case 'PARENT_CONFIRMED':
      return 'Parent confirmed';
    case 'PARENT_NOT_CONFIRMED':
      return d.reason?.label ? `Parent did not confirm — ${d.reason.label}` : 'Parent did not confirm';
    default:
      return event.kind_label ?? event.kind;
  }
}

function who(event) {
  if (event.actor) return event.actor.full_name;
  return event.kind === 'CREATED' ? 'the booking page' : 'the system';
}

/**
 * A booking's timeline (GET /api/bookings/<type>/<id>/history/), loaded when
 * asked for: every change to it and to the bookings before and after it in
 * its reschedule chain, oldest first, each with who made it and when.
 */
export function BookingHistory({ bookingType, bookingId, reloadKey }) {
  const [shown, setShown] = useState(false);
  const [data, setData] = useState(null);
  const [failure, setFailure] = useState(null);
  const [retryKey, setRetryKey] = useState(0);

  // Another booking starts closed again.
  const [prevId, setPrevId] = useState(bookingId);
  if (bookingId !== prevId) {
    setPrevId(bookingId);
    setShown(false);
    setData(null);
    setFailure(null);
  }

  useEffect(() => {
    if (!shown || !bookingId || !bookingType) return undefined;
    let active = true;
    setFailure(null);
    api
      .get(bookingHistoryUrl(bookingType, bookingId))
      .then((response) => {
        if (active) setData(response.data);
      })
      .catch((err) => {
        if (active) setFailure(bookingError(err, 'Could not load the history.'));
      });
    return () => {
      active = false;
    };
  }, [shown, bookingType, bookingId, reloadKey, retryKey]);

  if (!shown) {
    return (
      <Button variant="outline" size="sm" className="self-start" onClick={() => setShown(true)}>
        Show history
      </Button>
    );
  }
  if (failure) {
    return (
      <div className="flex flex-wrap items-center gap-3">
        <p className="text-destructive text-sm">{failure.message}</p>
        <Button variant="outline" size="sm" onClick={() => setRetryKey((key) => key + 1)}>
          Try again
        </Button>
      </div>
    );
  }
  if (!data) return <Skeleton className="h-24" aria-busy="true" />;
  // Which booking of the chain an event belongs to, told against this one's place in it.
  const order = data.chain.map((link) => link.id);
  const here = order.indexOf(bookingId);
  const whose = (event) => {
    const at = order.indexOf(event.booking_id);
    if (at === here || at < 0) return '';
    return at < here ? ' · on the booking it replaced' : ' · on its replacement';
  };
  return (
    <section className="rounded-lg border p-4" aria-label="History">
      <h3 className="mb-2 text-sm font-semibold">History</h3>
      <ol className="flex flex-col gap-3">
        {data.events.map((event) => (
          <li key={event.id} className="text-sm">
            <p className="font-medium">{describeBookingEvent(event)}</p>
            <p className="text-muted-foreground text-xs">
              {format(new Date(event.at), 'd MMM yyyy, h:mm a')} · by {who(event)}
              {whose(event)}
            </p>
          </li>
        ))}
      </ol>
    </section>
  );
}
