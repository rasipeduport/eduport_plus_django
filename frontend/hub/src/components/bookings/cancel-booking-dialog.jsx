import { useState } from 'react';

import api from '@/lib/api';
import { FormDialog } from '@/components/form-dialog';
import { CANCEL_REASONS, bookingCancelUrl, bookingError } from '@/lib/bookings';
import { bookingTypeLabel, slotLabel } from '@/lib/enquiries';
import { cn } from '@/lib/utils';

/**
 * Cancelling a booking (POST /api/bookings/<type>/<id>/cancel/, or the BDE's
 * own route when `cancelUrl` is given) with a reason picked from the list --
 * never typed (Q9): No-show only once its scheduled time has passed, whether
 * or not the tutor started it (the booking's actions.no_show, D12). The API
 * checks it all again -- for a BDE, that the
 * booking's lead is theirs -- and its refusal is shown as it comes.
 */
export function CancelBookingDialog({ booking, open, onOpenChange, onCancelled, cancelUrl }) {
  const [reason, setReason] = useState('');
  const [error, setError] = useState(null);
  const [pending, setPending] = useState(false);

  // A fresh dialog on every open.
  const [prevOpen, setPrevOpen] = useState(open);
  if (open !== prevOpen) {
    setPrevOpen(open);
    if (open) {
      setReason('');
      setError(null);
    }
  }

  const noShowAllowed = Boolean(booking?.actions?.no_show);

  async function cancel() {
    if (!booking || !reason) return;
    setPending(true);
    setError(null);
    try {
      const url = cancelUrl ? cancelUrl(booking) : bookingCancelUrl(booking.booking_type, booking.id);
      const response = await api.post(url, { reason });
      onCancelled?.(response.data);
      onOpenChange(false);
    } catch (err) {
      setError(bookingError(err, 'Could not cancel the booking.').message);
    } finally {
      setPending(false);
    }
  }

  return (
    <FormDialog
      open={open}
      onOpenChange={onOpenChange}
      title="Cancel booking"
      description={
        booking ? `${booking.student_name} · ${bookingTypeLabel(booking.booking_type)} · ${slotLabel(booking.slot)}` : null
      }
      error={error}
      onConfirm={cancel}
      confirmLabel="Cancel booking"
      pendingLabel="Cancelling…"
      confirmVariant="destructive"
      confirmDisabled={!reason}
      cancelLabel="Keep booking"
      pending={pending}
    >
      <fieldset className="flex flex-col gap-2" disabled={pending}>
        <legend className="mb-1 text-sm font-medium">Why is it cancelled?</legend>
        {CANCEL_REASONS.map((option) => {
          const unavailable = option.value === 'NO_SHOW' && !noShowAllowed;
          return (
            <label
              key={option.value}
              className={cn(
                'flex items-start gap-3 rounded-md border p-3 text-sm',
                unavailable ? 'cursor-not-allowed opacity-60' : 'hover:bg-muted/40 cursor-pointer',
                reason === option.value && 'border-primary bg-muted/40'
              )}
            >
              <input
                type="radio"
                name="cancel-reason"
                value={option.value}
                checked={reason === option.value}
                onChange={() => setReason(option.value)}
                disabled={unavailable}
                className="mt-0.5"
              />
              <span>
                <span className="font-medium">{option.label}</span>
                {unavailable ? (
                  <span className="text-muted-foreground block text-xs">Available once the scheduled time has passed.</span>
                ) : null}
              </span>
            </label>
          );
        })}
      </fieldset>
    </FormDialog>
  );
}
