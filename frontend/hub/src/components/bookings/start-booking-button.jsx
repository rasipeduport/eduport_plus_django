import { useState } from 'react';
import { PlayIcon } from 'lucide-react';

import api from '@/lib/api';
import { Button } from '@/components/ui/button';
import { FormDialog } from '@/components/form-dialog';
import { startError, startLabel, tutorBookingStartUrl } from '@/lib/bookings';
import { bookingTypeLabel, slotLabel } from '@/lib/enquiries';

/**
 * Start Demo / Start Diagnostic, for the booking's tutor (POST
 * /api/tutor/bookings/<type>/<id>/start/): offered only while the API says
 * the booking may be started (its `actions.start`), and confirmed first --
 * a start is recorded by the server's clock and cannot be undone here. It
 * never opens the Meet link. `onStarted` gets the booking as the API answers
 * it; a refusal (the slot ended, a reassignment) is shown in the dialog, and
 * `onRefresh` is asked to read the booking again once the dialog closes.
 */
export function StartBookingButton({ booking, onStarted, onRefresh, size = 'sm' }) {
  const [open, setOpen] = useState(false);
  const [error, setError] = useState(null);
  const [pending, setPending] = useState(false);
  const [refused, setRefused] = useState(false);

  if (!booking?.actions?.start) return null;
  const label = startLabel(booking.booking_type);
  const kind = bookingTypeLabel(booking.booking_type);

  function changeOpen(next) {
    setOpen(next);
    if (next) {
      setError(null);
      setRefused(false);
    } else if (refused) {
      onRefresh?.();
    }
  }

  async function start() {
    setPending(true);
    setError(null);
    try {
      const response = await api.post(tutorBookingStartUrl(booking.booking_type, booking.id));
      setOpen(false);
      onStarted?.(response.data.booking);
    } catch (err) {
      const failure = startError(err);
      setError(failure.message);
      // Refused for good (409/404): what the page shows is out of date.
      setRefused(failure.status === 404 || failure.status === 409);
    } finally {
      setPending(false);
    }
  }

  return (
    <>
      <Button size={size} onClick={() => changeOpen(true)} aria-label={`${label} for ${booking.student_name}`}>
        <PlayIcon className="size-4" />
        {label}
      </Button>
      <FormDialog
        open={open}
        onOpenChange={changeOpen}
        title={`${label}?`}
        description={`${booking.student_name} · ${kind} · ${slotLabel(booking.slot)}`}
        error={error}
        onConfirm={start}
        confirmLabel={label}
        pendingLabel="Starting…"
        confirmDisabled={refused}
        cancelLabel="Not yet"
        pending={pending}
      >
        <p className="text-muted-foreground text-sm">
          This records that you have started the {kind} now. It cannot be undone. The Meet link does not open by itself.
        </p>
      </FormDialog>
    </>
  );
}
