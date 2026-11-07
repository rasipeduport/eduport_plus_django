import { useState } from 'react';

import api from '@/lib/api';
import { FormDialog } from '@/components/form-dialog';
import { Choice } from '@/components/communications/parent-answer-dialog';
import { CALL_OUTCOME_CHOICES, callOutcomeUrl, communicationError } from '@/lib/communications';
import { bookingTypeLabel, slotLabel } from '@/lib/enquiries';
import { NEW_ENQUIRY_OUTCOMES, followUpCompleteUrl } from '@/lib/follow-ups';

/** Whose follow-up it is and, for a booking's, which booking: the dialogs' description. */
function about(followUp) {
  if (!followUp) return null;
  const { enquiry, booking } = followUp;
  return booking
    ? `${enquiry.student_name} · ${bookingTypeLabel(booking.booking_type)} · ${slotLabel(booking)}`
    : `${enquiry.student_name} · ${enquiry.parent_name} · ${enquiry.phone}`;
}

/**
 * How a call went, picked from the list -- never typed: a new enquiry's call
 * (POST /api/bde/follow-ups/<id>/complete/) or the 15-minute call before a
 * class (POST …/call-outcome/ on the booking's communication). Recording it
 * completes the follow-up. The API checks every rule again, and its refusal is
 * shown as it comes.
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

  const call = followUp?.type === 'PRE_ACTIVITY_CALL';
  const options = call ? CALL_OUTCOME_CHOICES : NEW_ENQUIRY_OUTCOMES;

  async function record() {
    if (!outcome) return;
    setPending(true);
    setError(null);
    try {
      if (call) {
        await api.post(callOutcomeUrl(followUp.booking.booking_type, followUp.booking.id), { outcome });
      } else {
        await api.post(followUpCompleteUrl(followUp.id), { outcome });
      }
      const label = options.find((option) => option.value === outcome)?.label ?? outcome;
      onRecorded?.(`Recorded “${label}” for ${followUp.enquiry.student_name}. The follow-up is completed.`);
      onOpenChange(false);
    } catch (err) {
      setError(communicationError(err, 'Could not record the outcome.').message);
    } finally {
      setPending(false);
    }
  }

  return (
    <FormDialog
      open={open}
      onOpenChange={onOpenChange}
      title={call ? 'Record the pre-activity call' : 'Record the call'}
      description={about(followUp)}
      error={error}
      onConfirm={record}
      confirmLabel="Record outcome"
      pendingLabel="Recording…"
      confirmDisabled={!outcome}
      pending={pending}
    >
      <fieldset className="flex flex-col gap-2" disabled={pending}>
        <legend className="mb-1 text-sm font-medium">How did it go?</legend>
        {options.map((option) => (
          <Choice
            key={option.value}
            name="follow-up-outcome"
            option={option}
            checked={outcome === option.value}
            onChange={() => setOutcome(option.value)}
          />
        ))}
      </fieldset>
    </FormDialog>
  );
}

/**
 * Marking a tutor report's discussion done (POST /api/bde/follow-ups/<id>/complete/),
 * once the BDE has shared the report with the parent and talked it through.
 */
export function CompleteReportDialog({ followUp, open, onOpenChange, onCompleted }) {
  const [error, setError] = useState(null);
  const [pending, setPending] = useState(false);

  const [prevOpen, setPrevOpen] = useState(open);
  if (open !== prevOpen) {
    setPrevOpen(open);
    if (open) setError(null);
  }

  async function complete() {
    setPending(true);
    setError(null);
    try {
      await api.post(followUpCompleteUrl(followUp.id), { outcome: 'DISCUSSED' });
      onCompleted?.(`Marked the report discussion for ${followUp.enquiry.student_name} as completed.`);
      onOpenChange(false);
    } catch (err) {
      setError(communicationError(err, 'Could not complete the follow-up.').message);
    } finally {
      setPending(false);
    }
  }

  return (
    <FormDialog
      open={open}
      onOpenChange={onOpenChange}
      title="Complete the report discussion"
      description={about(followUp)}
      error={error}
      onConfirm={complete}
      confirmLabel="Mark as completed"
      pendingLabel="Completing…"
      pending={pending}
    >
      <p className="text-sm">
        Mark this as completed once you have shared the report with {followUp?.enquiry.parent_name ?? 'the parent'} and
        discussed it with them.
      </p>
    </FormDialog>
  );
}
