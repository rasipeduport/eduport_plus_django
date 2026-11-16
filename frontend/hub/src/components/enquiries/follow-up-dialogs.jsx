import { useState } from 'react';

import api from '@/lib/api';
import { FormDialog } from '@/components/form-dialog';
import { Choice } from '@/components/communications/parent-answer-dialog';
import { CALL_OUTCOME_CHOICES, callOutcomeUrl, communicationError } from '@/lib/communications';
import { bookingTypeLabel, slotLabel } from '@/lib/enquiries';

/**
 * How the call before a class went, picked from the list -- never typed --
 * and kept on the booking's communication (POST …/call-outcome/), which ends
 * the reminder. The API checks every rule again, and its refusal is shown as
 * it comes.
 */
export function RecordOutcomeDialog({ followUp, open, onOpenChange, onRecorded }) {
  const [outcome, setOutcome] = useState('');
  const [error, setError] = useState(null);
  const [pending, setPending] = useState(false);

  // A fresh dialog on every open.
  const [prevOpen, setPrevOpen] = useState(open);
  if (open !== prevOpen) {
    setPrevOpen(open);
    if (open) {
      setOutcome('');
      setError(null);
    }
  }

  const booking = followUp?.booking;

  async function record() {
    if (!outcome) return;
    setPending(true);
    setError(null);
    try {
      await api.post(callOutcomeUrl(booking.booking_type, booking.id), { outcome });
      const label = CALL_OUTCOME_CHOICES.find((option) => option.value === outcome)?.label ?? outcome;
      onRecorded?.(`Recorded “${label}” for the call to ${followUp.enquiry.parent_name}.`);
      onOpenChange(false);
    } catch (err) {
      setError(communicationError(err, 'Could not record the call.').message);
    } finally {
      setPending(false);
    }
  }

  return (
    <FormDialog
      open={open}
      onOpenChange={onOpenChange}
      title="Record the pre-activity call"
      description={
        booking
          ? `${followUp.enquiry.student_name} · ${bookingTypeLabel(booking.booking_type)} · ${slotLabel(booking)}`
          : null
      }
      error={error}
      onConfirm={record}
      confirmLabel="Record outcome"
      pendingLabel="Recording…"
      confirmDisabled={!outcome}
      pending={pending}
    >
      <fieldset className="flex flex-col gap-2" disabled={pending}>
        <legend className="mb-1 text-sm font-medium">How did it go?</legend>
        {CALL_OUTCOME_CHOICES.map((option) => (
          <Choice
            key={option.value}
            name="call-outcome"
            option={option}
            checked={outcome === option.value}
            onChange={() => setOutcome(option.value)}
          />
        ))}
      </fieldset>
    </FormDialog>
  );
}
