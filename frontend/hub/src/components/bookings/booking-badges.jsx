import { Badge } from '@/components/ui/badge';
import { bookingState } from '@/lib/bookings';

/** Upcoming, In progress, Done or Cancelled (lib/bookings bookingState). */
export function BookingStateBadge({ booking }) {
  const state = bookingState(booking);
  return <Badge variant={state.variant}>{state.label}</Badge>;
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
