import { Fragment, useState } from 'react';

import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { istMoment, stepLabel } from '@/lib/communications';
import { MessageStateBadge, ParentConfirmationBadge, TaskStateBadge } from './communication-badges';

function Detail({ label, children }) {
  return (
    <div className="grid grid-cols-[8rem_1fr] gap-3 py-2 text-sm">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="min-w-0 font-medium break-words">{children || <span className="text-muted-foreground">—</span>}</dd>
    </div>
  );
}

function Heading({ children }) {
  return <h4 className="pt-1 text-sm font-medium">{children}</h4>;
}

const joined = (...parts) => parts.filter(Boolean).join(' · ');

// How a message step was done, in a word or two (backend communications.models.TaskResolution).
const DONE_AS = {
  ACCEPTED: 'Sent',
  SENT: 'Sent',
  MARKED_SENT: 'Sent manually',
  ALREADY_ACKNOWLEDGED: 'Sent for the earlier booking',
  NOT_NEEDED: 'Not needed',
};

const ACTIVITY_NAMES = { DEMO: 'Demo', DIAGNOSTIC: 'Diagnostic' };

/**
 * The 15-minute call's reminder while it is on -- from its `active_from` until
 * the start (`due_at`), when the backend marks it done -- or null. A reminder
 * only: nothing is recorded on it.
 */
function callReminder(task, bookingType, now = Date.now()) {
  if (task.step !== 'PRE_ACTIVITY_CALL' || !task.active_from || !task.due_at) return null;
  const left = new Date(task.due_at).getTime() - now;
  if (now < new Date(task.active_from).getTime() || left <= 0) return null;
  const minutes = Math.ceil(left / 60000);
  return `Call parent – ${ACTIVITY_NAMES[bookingType] ?? 'Booking'} starts in ${minutes} minute${minutes === 1 ? '' : 's'}.`;
}

/** A step's one line: how and when it was done, the call's reminder, or when it is due or closed. */
function stepLine(task, bookingType) {
  switch (task.status) {
    case 'DONE':
      return joined(DONE_AS[task.resolution] ?? task.resolution_label, istMoment(task.resolved_at));
    case 'MISSED':
      return task.resolved_at ? `Time ran out ${istMoment(task.resolved_at)}` : null;
    case 'CANCELLED':
      return joined(task.resolution_label, istMoment(task.resolved_at));
    default:
      return callReminder(task, bookingType) ?? (task.due_at ? `Due ${istMoment(task.due_at)}` : 'After the class');
  }
}

/** A message's one line: when it reached its status, what it waits for, or why it was not sent. */
function messageLine(message) {
  switch (message.status) {
    case 'WAITING':
      return message.waiting_for.length ? `Waiting for: ${message.waiting_for.map((item) => item.label).join(', ')}` : null;
    case 'PENDING':
      return message.next_attempt_at ? `Trying again ${istMoment(message.next_attempt_at)}` : null;
    case 'QUEUED':
      return istMoment(message.queued_at);
    case 'SENT':
      return istMoment(message.sent_at);
    case 'DELIVERED':
      return istMoment(message.delivered_at);
    case 'READ':
      return istMoment(message.read_at);
    case 'FAILED':
      return istMoment(message.failed_at);
    case 'CANCELLED':
      return joined(message.cancel_reason?.label, istMoment(message.cancelled_at));
    default:
      return null;
  }
}

// What a message has been through, in order, for its details.
const MOMENTS = [
  ['Sent to WhatsApp', 'queued_at'],
  ['Sent', 'sent_at'],
  ['Delivered', 'delivered_at'],
  ['Read', 'read_at'],
  ['Failed', 'failed_at'],
  ['Not sent', 'cancelled_at'],
];

function MessageItem({ message }) {
  const [open, setOpen] = useState(false);
  const label = stepLabel(message);
  const line = messageLine(message);
  // Why it failed, or why it is being tried again -- inline, never elsewhere.
  const failure = message.status === 'FAILED' || message.next_attempt_at ? message.failure_reason : '';
  const moments = MOMENTS.filter(([, field]) => message[field]);
  return (
    <li className="py-2 text-sm">
      <div className="flex items-start justify-between gap-2">
        <span className="font-medium">{label}</span>
        <MessageStateBadge message={message} />
      </div>
      {line ? <p className="text-muted-foreground mt-0.5 text-xs">{line}</p> : null}
      {failure ? (
        <p className="text-destructive mt-0.5 text-xs">
          {failure}
          {message.failure_code ? ` (${message.failure_code})` : ''}
        </p>
      ) : null}
      {message.text || moments.length ? (
        <Button
          variant="ghost"
          size="sm"
          className="mt-1 -ml-2 h-7"
          onClick={() => setOpen((shown) => !shown)}
          aria-expanded={open}
          aria-label={`${open ? 'Hide' : 'Show'} the details of the ${label.toLowerCase()}`}
        >
          {open ? 'Hide details' : 'Show details'}
        </Button>
      ) : null}
      {open ? (
        <div className="mt-1 flex flex-col gap-2 text-xs">
          {/* The text exactly as WhatsApp shows it, as the preview did. */}
          {message.text ? <p className="bg-muted rounded-md p-2 whitespace-pre-wrap">{message.text}</p> : null}
          <dl className="grid grid-cols-[8rem_1fr] gap-x-3 gap-y-0.5">
            {moments.map(([name, field]) => (
              <Fragment key={field}>
                <dt className="text-muted-foreground">{name}</dt>
                <dd>{istMoment(message[field])}</dd>
              </Fragment>
            ))}
            {message.attempt_count ? (
              <>
                <dt className="text-muted-foreground">Attempts</dt>
                <dd>{message.attempt_count}</dd>
              </>
            ) : null}
            {message.created_by ? (
              <>
                <dt className="text-muted-foreground">Requested by</dt>
                <dd>{message.created_by.full_name}</dd>
              </>
            ) : null}
          </dl>
        </div>
      ) : null}
    </li>
  );
}

/**
 * A booking's parent communication (backend communications.overview), in
 * three parts: the parent's confirmation -- asked for and recorded here when
 * the API's `actions` allow it and the caller handles it
 * (`onRequestConfirmation`, `onRecordAnswer`) -- the five steps of PRD 3.11,
 * each with its status and its moment, and the WhatsApp messages with their
 * status and, inline, why one failed. Every moment is in Indian time. Shared
 * by the administrators' booking sheet and the BDE's communication sheet;
 * nothing here changes anything itself.
 */
export function CommunicationDetails({ communication, onRequestConfirmation, onRecordAnswer }) {
  const { booking, parent_confirmation: confirmation, tasks, messages, actions = {} } = communication;
  const canRequest = Boolean(actions.request_confirmation && onRequestConfirmation);
  const canRecord = Boolean(actions.record_confirmation && onRecordAnswer);
  return (
    <div className="flex flex-col gap-3">
      <div>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <Heading>Parent confirmation</Heading>
          {canRequest || canRecord ? (
            <div className="flex flex-wrap gap-2">
              {canRequest ? (
                <Button variant="outline" size="sm" onClick={onRequestConfirmation}>
                  Request confirmation
                </Button>
              ) : null}
              {canRecord ? (
                <Button size="sm" onClick={onRecordAnswer}>
                  Record answer
                </Button>
              ) : null}
            </div>
          ) : null}
        </div>
        <dl className="divide-y">
          <Detail label="Status">
            <ParentConfirmationBadge status={confirmation.status} booked={booking.status === 'BOOKED'} />
          </Detail>
          {confirmation.at ? (
            <Detail label="Recorded">{joined(istMoment(confirmation.at), confirmation.by && `by ${confirmation.by.full_name}`)}</Detail>
          ) : null}
          {confirmation.reason ? <Detail label="Reason">{confirmation.reason.label}</Detail> : null}
        </dl>
      </div>
      {communication.planned ? (
        <>
          <div>
            <Heading>Communication steps</Heading>
            <ol className="divide-y">
              {tasks.map((task) => (
                <li key={task.id} className="py-2 text-sm">
                  <div className="flex items-start justify-between gap-2">
                    <span className="font-medium">{stepLabel(task)}</span>
                    <TaskStateBadge task={task} />
                  </div>
                  {stepLine(task, booking.booking_type) ? (
                    <p className="text-muted-foreground mt-0.5 text-xs">{stepLine(task, booking.booking_type)}</p>
                  ) : null}
                </li>
              ))}
            </ol>
          </div>
          <div>
            <Heading>Message history</Heading>
            {messages.length ? (
              <ol className="divide-y">
                {messages.map((message) => (
                  <MessageItem key={message.id} message={message} />
                ))}
              </ol>
            ) : (
              <p className="text-muted-foreground py-2 text-sm">No messages yet.</p>
            )}
          </div>
        </>
      ) : communication.redemo ? (
        // A Re-Demo (backend bookings.redemos) has no plan: nothing is ever sent to its parent.
        <p className="text-muted-foreground text-sm">
          No messages are sent for a Re-Demo: the BDE contacts the parent directly with its date, time and tutor.
        </p>
      ) : (
        <p className="text-muted-foreground text-sm">
          No messages were planned for this booking: it was made before parent communication began.
        </p>
      )}
    </div>
  );
}

/** CommunicationDetails once read (useBookingCommunication), or why it could not be. */
export function CommunicationBody({ communication, failure, retry, onRequestConfirmation, onRecordAnswer }) {
  if (failure && (failure.status === 403 || failure.status === 404)) {
    return (
      <p className="text-muted-foreground py-2 text-sm">
        {failure.status === 404
          ? 'No communication found for this booking.'
          : "You don't have access to this booking's communication."}
      </p>
    );
  }
  if (failure) {
    return (
      <div className="flex flex-wrap items-center gap-3 pt-2">
        <p className="text-destructive text-sm">{failure.message}</p>
        <Button variant="outline" size="sm" onClick={retry}>
          Try again
        </Button>
      </div>
    );
  }
  if (!communication) return <Skeleton className="mt-2 h-40" aria-busy="true" />;
  return (
    <CommunicationDetails
      communication={communication}
      onRequestConfirmation={onRequestConfirmation}
      onRecordAnswer={onRecordAnswer}
    />
  );
}
