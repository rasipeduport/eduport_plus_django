import { Badge } from '@/components/ui/badge';
import { bookingState } from '@/lib/bookings';
import { istMoment } from '@/lib/communications';
import { reportState } from '@/lib/reports';

/** Where the booking stands as a class, as the API says (lib/bookings bookingState). */
export function BookingStateBadge({ booking }) {
  const state = bookingState(booking);
  return <Badge variant={state.variant}>{state.label}</Badge>;
}

/**
 * Where a tutor's booking stands with its report: Upcoming, In progress,
 * Report due, Completed, Cancelled or Rescheduled (lib/reports reportState).
 */
export function ReportStateBadge({ booking }) {
  const state = reportState(booking);
  return <Badge variant={state.variant}>{state.label}</Badge>;
}

/**
 * Whether the booking's tutor has started it, to read only: when, in Indian
 * time (and by whom, with `showBy`), or Not started -- flagged once its
 * scheduled time has passed without a start. A booking completed before
 * starts were recorded says so rather than showing a time it never had.
 */
export function StartInfo({ booking, showBy = false }) {
  if (booking.started_at) {
    const by = showBy && booking.started_by ? ` by ${booking.started_by.full_name}` : '';
    return (
      <span>
        Started {istMoment(booking.started_at)}
        {by}
      </span>
    );
  }
  if (booking.status === 'COMPLETED') return <span className="text-muted-foreground">Start not recorded</span>;
  if (booking.activity_state === 'LATE' || booking.activity_state === 'NOT_STARTED') {
    return <Badge variant="warning">Not started</Badge>;
  }
  return <span className="text-muted-foreground">Not started</span>;
}

/**
 * Who teaches the booking. A booked one that is not over and has nobody yet
 * says so plainly -- the rows an administrator still has to act on.
 */
export function TutorName({ booking }) {
  if (booking.tutor) return <span className="font-medium">{booking.tutor.full_name}</span>;
  if (booking.status === 'BOOKED' && !booking.slot?.ended) return <Badge variant="warning">Unassigned</Badge>;
  return <span className="text-muted-foreground">—</span>;
}

/** Available or Unavailable for the booking's slot, as the API reports it. */
export function AvailabilityBadge({ status }) {
  return status === 'AVAILABLE' ? (
    <Badge variant="success">Available</Badge>
  ) : (
    <Badge variant="destructive">Unavailable</Badge>
  );
}
