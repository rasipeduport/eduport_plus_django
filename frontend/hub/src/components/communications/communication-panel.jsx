import { useState } from 'react';

import { confirmationRequestNotice, parentAnswerNotice } from '@/lib/communications';
import { CommunicationBody } from './communication-details';
import { ConfirmationRequestDialog } from './confirmation-request-dialog';
import { ParentAnswerDialog } from './parent-answer-dialog';

/**
 * A booking's communication with the actions it offers (Phase 3.2), shared by
 * the administrators' booking sheet and the BDE's communication sheet:
 * CommunicationBody, the Request confirmation and Record answer dialogs the
 * API's `actions` allow, and what the last action did, inline. An action is
 * answered with the communication as it now stands; the page is told
 * (`onChanged`) so it reads the booking and its timeline again. Given a
 * function as `children`, the panel renders what it returns in the body's
 * place -- handed the communication's state, the two actions and the notice --
 * so the BDE's sheet lays it out its own way with the same dialogs.
 */
export function CommunicationPanel({ state, onChanged, children }) {
  const [dialog, setDialog] = useState(null);
  const [notice, setNotice] = useState(null);
  const booking = state.communication?.booking;
  const actions = {
    onRequestConfirmation: () => setDialog('request'),
    onRecordAnswer: () => setDialog('answer'),
  };

  function done(data, message) {
    state.update(data);
    setNotice(message);
    onChanged?.();
  }

  return (
    <>
      {children ? (
        children({ ...state, ...actions, notice })
      ) : (
        <>
          {notice ? (
            <p role="status" className="bg-success/10 text-success mb-2 rounded-md px-3 py-2 text-sm">
              {notice}
            </p>
          ) : null}
          <CommunicationBody {...state} {...actions} />
        </>
      )}
      {booking ? (
        <>
          <ConfirmationRequestDialog
            booking={booking}
            open={dialog === 'request'}
            onOpenChange={(open) => setDialog(open ? 'request' : null)}
            onRequested={(data) => done(data, confirmationRequestNotice(data))}
          />
          <ParentAnswerDialog
            booking={booking}
            open={dialog === 'answer'}
            onOpenChange={(open) => setDialog(open ? 'answer' : null)}
            onRecorded={(data, outcome) => done(data, parentAnswerNotice(data, outcome))}
          />
        </>
      ) : null}
    </>
  );
}
