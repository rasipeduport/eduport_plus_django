import { useState } from 'react';

import api from '@/lib/api';
import { FormDialog } from '@/components/form-dialog';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { REDEMO_REASON_MAX_LENGTH, bookingError } from '@/lib/bookings';
import { slotLabel } from '@/lib/enquiries';

// Whoever writes the reason is told who reads it (backend bookings.tutor_bookings: the Re-Demo's tutor).
const TUTOR_NOTICE = 'The tutor assigned to the Re-Demo will see this reason.';

/**
 * Request Re-Demo, on a completed Demo (the API's actions.request_redemo):
 * the reason first -- required, in the caller's own words, and shown to the
 * Re-Demo's tutor, as the dialog says -- then the reason shown back as it
 * will be sent, and only then the request (POST
 * `requestUrl`: the Admin's route, or the BDE's for their own lead). The
 * Demo is Re-Demo required at once; no approval follows. The API checks
 * everything again -- that the Demo is completed and not already sent, and for
 * a BDE that the lead is theirs -- and its refusal is shown as it comes.
 * `onRequested` receives the API's answer.
 */
export function RequestRedemoDialog({ booking, open, onOpenChange, requestUrl, onRequested }) {
  const [reason, setReason] = useState('');
  const [reviewing, setReviewing] = useState(false);
  const [error, setError] = useState(null);
  const [pending, setPending] = useState(false);

  // A fresh dialog on every open.
  const [prevOpen, setPrevOpen] = useState(open);
  if (open !== prevOpen) {
    setPrevOpen(open);
    if (open) {
      setReason('');
      setReviewing(false);
      setError(null);
    }
  }

  const trimmed = reason.trim();
  const tooLong = trimmed.length > REDEMO_REASON_MAX_LENGTH;

  async function submit() {
    if (!reviewing) {
      if (!trimmed) {
        setError('Give the reason for the Re-Demo.');
        return;
      }
      if (tooLong) return;
      setError(null);
      setReviewing(true);
      return;
    }
    setPending(true);
    setError(null);
    try {
      const response = await api.post(requestUrl, { reason: trimmed });
      onRequested?.(response.data);
      onOpenChange(false);
    } catch (err) {
      setError(bookingError(err, 'Could not request the Re-Demo.').message);
    } finally {
      setPending(false);
    }
  }

  return (
    <FormDialog
      open={open}
      onOpenChange={onOpenChange}
      title={reviewing ? 'Confirm the Re-Demo request' : 'Request Re-Demo'}
      description={booking ? `${booking.student_name} · Demo · ${slotLabel(booking.slot)}` : null}
      error={error}
      onConfirm={submit}
      confirmLabel={reviewing ? 'Request Re-Demo' : 'Review request'}
      pendingLabel="Requesting…"
      confirmDisabled={!trimmed || tooLong}
      cancelLabel="Cancel"
      pending={pending}
      size="md"
    >
      {reviewing ? (
        <div className="flex flex-col gap-3 text-sm">
          <div className="bg-muted/40 rounded-md border p-3">
            <p className="text-muted-foreground mb-1 text-xs font-medium">Reason</p>
            <p className="break-words whitespace-pre-wrap">{trimmed}</p>
          </div>
          <p role="note" className="text-muted-foreground text-xs">
            {TUTOR_NOTICE}
          </p>
          <p className="text-muted-foreground">
            This Demo becomes <span className="text-foreground font-medium">Re-Demo required</span> straight away. Its
            report, tutor and history stay as they are, and an administrator schedules the new Demo with its tutor.
          </p>
          <Button
            type="button"
            variant="link"
            size="sm"
            className="h-auto self-start p-0"
            onClick={() => setReviewing(false)}
            disabled={pending}
          >
            Edit the reason
          </Button>
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          <Label htmlFor="redemo-reason">Why does this Demo need to be taught again?</Label>
          <Textarea
            id="redemo-reason"
            value={reason}
            onChange={(event) => {
              setReason(event.target.value);
              if (error) setError(null);
            }}
            rows={4}
            maxLength={REDEMO_REASON_MAX_LENGTH + 100}
            aria-invalid={tooLong || undefined}
            placeholder="For example: the parent asked for a different teaching style."
          />
          <p className={tooLong ? 'text-destructive text-xs' : 'text-muted-foreground text-xs'}>
            {trimmed.length}/{REDEMO_REASON_MAX_LENGTH} characters · required
          </p>
          <p role="note" className="text-muted-foreground text-xs">
            {TUTOR_NOTICE}
          </p>
        </div>
      )}
    </FormDialog>
  );
}
