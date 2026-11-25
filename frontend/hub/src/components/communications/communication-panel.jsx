import { useState } from 'react';

import { confirmationRequest, parentAnswerNotice, requestSentNotice } from '@/lib/communications';
import { CommunicationBody } from './communication-details';
import { ConfirmationRequestDialog } from './confirmation-request-dialog';
import { ParentAnswerDialog } from './parent-answer-dialog';

/**
 * A booking's communication with the actions it offers (Phase 3.2), shared by
 * the administrators' booking sheet and the BDE's communication sheet:
 * CommunicationBody, the confirmation request dialog -- Open WhatsApp, then
 * Mark as sent -- and the Record answer dialog the API's `actions` allow, and
 * what the last action did, inline. An action is
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
    onOpenWhatsApp: () => setDialog('request'),
    onRecordAnswer: () => setDialog('answer'),
  };

  // A request refused as out of date (404/409): the communication, and the page, as they now stand.
  const refused = () => {
    state.retry();
    onChanged?.();
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
            request={confirmationRequest(state.communication)}
            canMark={Boolean(state.communication?.actions?.mark_request_sent)}
            open={dialog === 'request'}
            onOpenChange={(open) => setDialog(open ? 'request' : null)}
            onMarked={(data) => done(data, requestSentNotice(data))}
            onRefused={refused}
          />
          <ParentAnswerDialog
            booking={booking}
            open={dialog === 'answer'}
            onOpenChange={(open) => setDialog(open ? 'answer' : null)}
            onRecorded={(data, outcome) => done(data, parentAnswerNotice(data, outcome))}
            onRefused={refused}
          />
        </>
      ) : null}
    </>
  );
}
