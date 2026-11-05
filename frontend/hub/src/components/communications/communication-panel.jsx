import { useState } from 'react';

import { CommunicationBody } from './communication-details';
import { ConfirmationRequestDialog } from './confirmation-request-dialog';
import { ParentAnswerDialog } from './parent-answer-dialog';

function requested(data) {
  return data.created
    ? 'Confirmation request added. It is sent to the parent on WhatsApp.'
    : 'A confirmation request was already added for this booking.';
}

function recorded(data, outcome) {
  if (!data.changed) return "The parent's answer was already recorded.";
  return outcome === 'NOT_CONFIRMED'
    ? 'Recorded that the parent did not confirm. The booking is cancelled.'
    : 'Recorded that the parent confirmed.';
}

/**
 * A booking's communication with the actions it offers (Phase 3.2), shared by
 * the administrators' booking sheet and the BDE's communication sheet:
 * CommunicationBody, the Request confirmation and Record answer dialogs the
 * API's `actions` allow, and what the last action did, inline. An action is
 * answered with the communication as it now stands; the page is told
 * (`onChanged`) so it reads the booking and its timeline again.
 */
export function CommunicationPanel({ state, onChanged }) {
  const [dialog, setDialog] = useState(null);
  const [notice, setNotice] = useState(null);
  const booking = state.communication?.booking;

  function done(data, message) {
    state.update(data);
    setNotice(message);
    onChanged?.();
  }

  return (
    <>
      {notice ? (
        <p role="status" className="bg-success/10 text-success mb-2 rounded-md px-3 py-2 text-sm">
          {notice}
        </p>
      ) : null}
      <CommunicationBody
        {...state}
        onRequestConfirmation={() => setDialog('request')}
        onRecordAnswer={() => setDialog('answer')}
      />
      {booking ? (
        <>
          <ConfirmationRequestDialog
            booking={booking}
            open={dialog === 'request'}
            onOpenChange={(open) => setDialog(open ? 'request' : null)}
            onRequested={(data) => done(data, requested(data))}
          />
          <ParentAnswerDialog
            booking={booking}
            open={dialog === 'answer'}
            onOpenChange={(open) => setDialog(open ? 'answer' : null)}
            onRecorded={(data, outcome) => done(data, recorded(data, outcome))}
          />
        </>
      ) : null}
    </>
  );
}
