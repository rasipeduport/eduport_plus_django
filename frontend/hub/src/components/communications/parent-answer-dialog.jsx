import { useState } from 'react';

import api from '@/lib/api';
import { FormDialog } from '@/components/form-dialog';
import { NOT_CONFIRMED_REASONS, PARENT_ANSWERS, communicationError, parentConfirmationUrl } from '@/lib/communications';
import { bookingTypeLabel, slotLabel } from '@/lib/enquiries';
import { cn } from '@/lib/utils';

/** One radio choice of a dialog's list (the parent's answer, a reason, an outcome). */
export function Choice({ name, option, checked, onChange }) {
  return (
    <label
      className={cn(
        'hover:bg-muted/40 flex cursor-pointer items-start gap-3 rounded-md border p-3 text-sm',
        checked && 'border-primary bg-muted/40'
      )}
    >
      <input type="radio" name={name} value={option.value} checked={checked} onChange={onChange} className="mt-0.5" />
      <span className="font-medium">{option.label}</span>
    </label>
  );
}

/**
 * Recording the parent's answer to the confirmation request (Phase 3.2;
 * POST …/parent-confirmation/): Confirmed, or Not confirmed with a reason
 * picked from the list -- never typed -- which cancels the booking in the same
 * step, so the cancellation is agreed to first. The API checks every rule
 * again, and its refusal is shown as it comes.
 */
export function ParentAnswerDialog({ booking, open, onOpenChange, onRecorded }) {
  const [outcome, setOutcome] = useState('');
  const [reason, setReason] = useState('');
  const [agreed, setAgreed] = useState(false);
  const [error, setError] = useState(null);
  const [pending, setPending] = useState(false);

  // A fresh dialog on every open.
  const [prevOpen, setPrevOpen] = useState(open);
  if (open !== prevOpen) {
    setPrevOpen(open);
    if (open) {
      setOutcome('');
      setReason('');
      setAgreed(false);
      setError(null);
    }
  }

  const notConfirmed = outcome === 'NOT_CONFIRMED';
  const ready = outcome === 'CONFIRMED' || (notConfirmed && Boolean(reason) && agreed);
  const what = booking ? `${booking.student_name}'s ${bookingTypeLabel(booking.booking_type).toLowerCase()}` : 'the booking';

  async function record() {
    if (!ready) return;
    setPending(true);
    setError(null);
    try {
      const answer = notConfirmed ? { outcome, reason, confirm_cancellation: true } : { outcome };
      const response = await api.post(parentConfirmationUrl(booking.booking_type, booking.id), answer);
      onRecorded?.(response.data, outcome);
      onOpenChange(false);
    } catch (err) {
      setError(communicationError(err, "Could not record the parent's answer.").message);
    } finally {
      setPending(false);
    }
  }

  return (
    <FormDialog
      open={open}
      onOpenChange={onOpenChange}
      title="Record parent's answer"
      description={
        booking ? `${booking.student_name} · ${bookingTypeLabel(booking.booking_type)} · ${slotLabel(booking.slot)}` : null
      }
      error={error}
      onConfirm={record}
      confirmLabel={notConfirmed ? 'Record and cancel booking' : 'Record answer'}
      pendingLabel="Recording…"
      confirmVariant={notConfirmed ? 'destructive' : 'default'}
      confirmDisabled={!ready}
      pending={pending}
    >
      <fieldset className="flex flex-col gap-2" disabled={pending}>
        <legend className="mb-1 text-sm font-medium">What did the parent say?</legend>
        {PARENT_ANSWERS.map((option) => (
          <Choice
            key={option.value}
            name="parent-answer"
            option={option}
            checked={outcome === option.value}
            onChange={() => setOutcome(option.value)}
          />
        ))}
      </fieldset>
      {notConfirmed ? (
        <>
          <fieldset className="flex flex-col gap-2" disabled={pending}>
            <legend className="mb-1 text-sm font-medium">Why not?</legend>
            {NOT_CONFIRMED_REASONS.map((option) => (
              <Choice
                key={option.value}
                name="not-confirmed-reason"
                option={option}
                checked={reason === option.value}
                onChange={() => setReason(option.value)}
              />
            ))}
          </fieldset>
          <label className="border-destructive/40 flex cursor-pointer items-start gap-3 rounded-md border p-3 text-sm">
            <input
              type="checkbox"
              checked={agreed}
              onChange={(event) => setAgreed(event.target.checked)}
              disabled={pending}
              className="mt-0.5"
            />
            <span>Cancel {what} on {booking ? slotLabel(booking.slot) : 'its slot'}. Not confirmed always cancels the booking.</span>
          </label>
        </>
      ) : null}
    </FormDialog>
  );
}
