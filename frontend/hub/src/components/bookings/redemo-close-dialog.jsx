import { useState } from 'react';

import api from '@/lib/api';
import { FormDialog } from '@/components/form-dialog';
import { REDEMO_CLOSE_REASONS, bookingError } from '@/lib/bookings';
import { cn } from '@/lib/utils';

/**
 * Closing a Re-Demo request, or opening it again (`mode` 'close' or
 * 'reopen'), with nothing booked for it: closing needs a reason picked from
 * the list -- never typed -- and turns its Demo back to Completed until it is
 * reopened, when an administrator schedules it again. `url` is the route to
 * POST to: the administrators' (…/redemos/<id>/close/ or reopen/) or the BDE's
 * for their own lead (…/bde/bookings/demo/<id>/redemo/close/ or reopen/). The
 * API checks it all again -- that nothing is booked for it and, for a BDE, that
 * the lead is theirs -- and its refusal is shown as it comes, `onRefused`
 * then letting the page read what it shows again. `onDone` receives the
 * API's answer.
 */
export function RedemoCloseDialog({ mode = 'close', subject, open, onOpenChange, url, onDone, onRefused }) {
  const closing = mode === 'close';
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

  async function submit() {
    if (!url || (closing && !reason)) return;
    setPending(true);
    setError(null);
    try {
      const response = await api.post(url, closing ? { reason } : {});
      onDone?.(response.data);
      onOpenChange(false);
    } catch (err) {
      setError(bookingError(err, closing ? 'Could not close the request.' : 'Could not reopen the request.').message);
      onRefused?.();
    } finally {
      setPending(false);
    }
  }

  return (
    <FormDialog
      open={open}
      onOpenChange={onOpenChange}
      title={closing ? 'Close Re-Demo request' : 'Reopen Re-Demo request'}
      description={subject}
      error={error}
      onConfirm={submit}
      confirmLabel={closing ? 'Close request' : 'Reopen request'}
      pendingLabel={closing ? 'Closing…' : 'Reopening…'}
      confirmVariant={closing ? 'destructive' : 'default'}
      confirmDisabled={closing && !reason}
      cancelLabel={closing ? 'Keep it open' : 'Cancel'}
      pending={pending}
    >
      {closing ? (
        <div className="flex flex-col gap-3">
          <fieldset className="flex flex-col gap-2" disabled={pending}>
            <legend className="mb-1 text-sm font-medium">Why is it closed?</legend>
            {REDEMO_CLOSE_REASONS.map((option) => (
              <label
                key={option.value}
                className={cn(
                  'hover:bg-muted/40 flex cursor-pointer items-start gap-3 rounded-md border p-3 text-sm',
                  reason === option.value && 'border-primary bg-muted/40'
                )}
              >
                <input
                  type="radio"
                  name="redemo-close-reason"
                  value={option.value}
                  checked={reason === option.value}
                  onChange={() => setReason(option.value)}
                  className="mt-0.5"
                />
                <span className="font-medium">{option.label}</span>
              </label>
            ))}
          </fieldset>
          <p className="text-muted-foreground text-xs">
            The Demo reads Completed again and nothing is scheduled. The request and its history are kept, and it can be
            reopened later.
          </p>
        </div>
      ) : (
        <p className="text-muted-foreground text-sm">
          The Demo becomes Re-Demo required again, and an administrator schedules the Re-Demo. Its reason, remarks and
          history stay as they are.
        </p>
      )}
    </FormDialog>
  );
}
