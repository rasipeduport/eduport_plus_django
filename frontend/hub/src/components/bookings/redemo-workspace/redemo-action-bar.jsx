import { CalendarClockIcon, CalendarX2Icon, CircleOffIcon, RotateCcwIcon, UserRoundCogIcon } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { slotLabel } from '@/lib/enquiries';
import { liveBooking } from '@/lib/redemo-workspace';

/** Where the request stands, in a line beside its actions. */
function summary(redemo) {
  const booking = liveBooking(redemo);
  if (redemo.status === 'CLOSED') return `Closed${redemo.closed?.reason?.label ? ` · ${redemo.closed.reason.label}` : ''}`;
  if (booking?.status === 'BOOKED')
    return `Scheduled for ${slotLabel(booking.slot)}${booking.tutor ? ` with ${booking.tutor.full_name}` : ''}`;
  if (booking) return 'Taught';
  return 'Waiting to be scheduled';
}

/**
 * The workspace's sticky bar of what may be done with the request now, and
 * only that -- each button there because the API allows it (`actions`,
 * `booking_actions`) and, for changing the tutor, because the user may
 * (`canChangeTutor`): waiting to be scheduled, Schedule Re-Demo (to the
 * Scheduling tab, unless it is open: `onSchedule`) and Close request; booked,
 * Reschedule, Change tutor and Cancel Re-Demo (`onBookingAction(action,
 * bookingId)`); closed, Reopen request. With nothing allowed it is not shown.
 */
export function RedemoActionBar({ redemo, tab, canChangeTutor, onSchedule, onClose, onReopen, onBookingAction }) {
  const actions = redemo.actions ?? {};
  const bookingActions = redemo.booking_actions ?? {};
  const booking = liveBooking(redemo);

  const buttons = [];
  if (booking && bookingActions.cancel) {
    buttons.push(
      <Button key="cancel" variant="outline" onClick={() => onBookingAction('cancel', booking.id)}>
        <CalendarX2Icon />
        Cancel Re-Demo
      </Button>
    );
  }
  if (booking && bookingActions.change_tutor && canChangeTutor) {
    buttons.push(
      <Button key="change_tutor" variant="outline" onClick={() => onBookingAction('change_tutor', booking.id)}>
        <UserRoundCogIcon />
        Change tutor
      </Button>
    );
  }
  if (booking && bookingActions.reschedule) {
    buttons.push(
      <Button key="reschedule" onClick={() => onBookingAction('reschedule', booking.id)}>
        <CalendarClockIcon />
        Reschedule
      </Button>
    );
  }
  if (actions.close) {
    buttons.push(
      <Button key="close" variant="outline" onClick={onClose}>
        <CircleOffIcon />
        Close request
      </Button>
    );
  }
  if (actions.schedule && tab !== 'scheduling') {
    buttons.push(
      <Button key="schedule" onClick={onSchedule}>
        <CalendarClockIcon />
        Schedule Re-Demo
      </Button>
    );
  }
  if (actions.reopen) {
    buttons.push(
      <Button key="reopen" onClick={onReopen}>
        <RotateCcwIcon />
        Reopen request
      </Button>
    );
  }
  if (!buttons.length) return null;

  return (
    <div
      role="region"
      aria-label="Re-Demo actions"
      className="bg-background/95 supports-[backdrop-filter]:bg-background/80 sticky bottom-4 z-20 flex flex-col gap-3 rounded-lg border px-4 py-3 shadow-lg backdrop-blur sm:flex-row sm:items-center sm:justify-between"
    >
      <p className="text-muted-foreground min-w-0 text-sm">{summary(redemo)}</p>
      <div className="flex flex-wrap gap-2 sm:justify-end">{buttons}</div>
    </div>
  );
}
