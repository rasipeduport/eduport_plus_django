import { useEffect, useState } from 'react';

import api from '@/lib/api';
import { Skeleton } from '@/components/ui/skeleton';
import { ErrorState } from '@/components/page/states';
import { bookingError, bookingHistoryUrl } from '@/lib/bookings';
import { istMoment } from '@/lib/communications';
import { slotLabel } from '@/lib/enquiries';
import { reportFieldsText } from '@/lib/reports';
import { cn } from '@/lib/utils';

/** One event of the timeline in words, from the names and labels the API reads back (never a child's or parent's). */
function describeBookingEvent(event) {
  const d = event.details ?? {};
  switch (event.kind) {
    case 'CREATED':
      if (d.via === 'reschedule') return `Booked in the new slot, ${slotLabel(d.slot)}`;
      // The parent picked the slot on the page a Demo invitation opens (backend bookings.demo_invites).
      if (d.via === 'demo_invite') return `Booked with a Demo invitation for ${slotLabel(d.slot)}`;
      // A Re-Demo an administrator scheduled, with its tutor (backend bookings.redemos).
      if (d.via === 'redemo') return `Re-Demo scheduled for ${slotLabel(d.slot)}`;
      return `Booked on the booking page for ${slotLabel(d.slot)}`;
    case 'TUTOR_ASSIGNED':
      if (d.via === 'reschedule') return `${d.new_tutor?.full_name ?? 'The tutor'} carried over to the new slot`;
      if (d.via === 'redemo') return `${d.new_tutor?.full_name ?? 'The tutor'} assigned for the Re-Demo`;
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
    // A completed Demo sent to be taught again: its report and tutor stay; the reason stays on the request.
    case 'REDEMO_REQUESTED':
      return 'Re-Demo requested — the Demo is now Re-Demo required';
    default:
      return event.kind_label ?? event.kind;
  }
}

function who(event) {
  if (event.actor) return event.actor.full_name;
  if (event.kind !== 'CREATED') return 'the system';
  return event.details?.via === 'demo_invite' ? 'the invitation page' : 'the booking page';
}

// Each kind of event's mark on the timeline.
const TONE = {
  CREATED: 'bg-primary',
  COMPLETED: 'bg-success',
  PARENT_CONFIRMED: 'bg-success',
  CANCELLED: 'bg-destructive',
  PARENT_NOT_CONFIRMED: 'bg-destructive',
  RESCHEDULED: 'bg-warning',
  REDEMO_REQUESTED: 'bg-warning',
};

/**
 * A booking's timeline (GET /api/bookings/<type>/<id>/history/), read while
 * `bookingType` and `bookingId` are set and again when `reloadKey` changes:
 * `{ history, failure, retry }`. Nothing of another booking shows while this
 * one loads.
 */
export function useBookingHistory(bookingType, bookingId, reloadKey) {
  const [data, setData] = useState(null);
  const [failure, setFailure] = useState(null);
  const [retryKey, setRetryKey] = useState(0);

  useEffect(() => {
    if (!bookingId || !bookingType) return undefined;
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
  }, [bookingType, bookingId, reloadKey, retryKey]);

  const shown = data && data.booking_id === bookingId ? data : null;
  return { history: shown, failure, retry: () => setRetryKey((key) => key + 1) };
}

/**
 * The events of a booking's timeline (useBookingHistory), oldest first: every
 * change to it and to the bookings before and after it in its reschedule
 * chain, each with who made it and when (Indian time) -- or only the events
 * of `kinds` (e.g. its tutor's). `emptyMessage` says when there are none.
 */
export function BookingEvents({ state, bookingId, kinds, emptyMessage = 'Nothing recorded yet.' }) {
  const { history, failure, retry } = state;
  if (failure && !history) return <ErrorState message={failure.message} onRetry={retry} />;
  if (!history) return <Skeleton className="h-24" aria-busy="true" />;
  // Which booking of the chain an event belongs to, told against this one's place in it.
  const order = history.chain.map((link) => link.id);
  const here = order.indexOf(bookingId);
  const whose = (event) => {
    const at = order.indexOf(event.booking_id);
    if (at === here || at < 0) return '';
    return at < here ? ' · on the booking it replaced' : ' · on its replacement';
  };
  const events = kinds ? history.events.filter((event) => kinds.includes(event.kind)) : history.events;
  if (!events.length) return <p className="text-muted-foreground text-sm">{emptyMessage}</p>;
  return (
    <ol aria-label="Booking history">
      {events.map((event) => (
        <li key={event.id} className="group flex gap-3">
          <span className="flex flex-col items-center" aria-hidden="true">
            <span className={cn('mt-1.5 size-2.5 shrink-0 rounded-full', TONE[event.kind] ?? 'bg-muted-foreground')} />
            <span className="bg-border mt-1.5 w-px flex-1 group-last:hidden" />
          </span>
          <div className="min-w-0 flex-1 pb-4 group-last:pb-0">
            <p className="text-sm font-medium">{describeBookingEvent(event)}</p>
            <p className="text-muted-foreground text-xs">
              {istMoment(event.at)} · by {who(event)}
              {whose(event)}
            </p>
          </div>
        </li>
      ))}
    </ol>
  );
}
