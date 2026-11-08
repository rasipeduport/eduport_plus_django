import { Fragment, useId, useState } from 'react';
import {
  CheckCheckIcon,
  CheckIcon,
  ChevronDownIcon,
  CircleAlertIcon,
  CircleDotIcon,
  ClipboardCheckIcon,
  ClockIcon,
  MinusIcon,
  PhoneCallIcon,
  SendIcon,
  TimerOffIcon,
  TriangleAlertIcon,
} from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { Tabs, TabsContent, TabsCount, TabsList, TabsTrigger } from '@/components/ui/tabs';
import {
  CALL_OUTCOMES,
  MESSAGE_MOMENTS,
  callReminder,
  istMoment,
  joined,
  latestMessages,
  messageLine,
  messageState,
  stepLabel,
  stepLine,
  workflowState,
} from '@/lib/communications';
import { cn } from '@/lib/utils';
import { MessageStateBadge, ParentConfirmationBadge, TaskStateBadge } from './communication-badges';
import { CommunicationBody } from './communication-details';

// Who acts on a task (backend communications.models.OwnerRole).
const OWNER_ROLES = { BDE: 'BDE', ADMIN: 'Admin' };

/** Label and value pairs as a definition list; pairs without a value are left out unless `keepEmpty`, then shown as "—". */
function Facts({ rows, keepEmpty = false, className }) {
  const shown = keepEmpty ? rows : rows.filter(([, value]) => value);
  if (!shown.length) return null;
  return (
    <dl className={cn('grid grid-cols-[minmax(0,8rem)_minmax(0,1fr)] gap-x-3 gap-y-1 text-xs', className)}>
      {shown.map(([label, value]) => (
        <Fragment key={label}>
          <dt className="text-muted-foreground">{label}</dt>
          <dd className="min-w-0 break-words">{value || <span className="text-muted-foreground">—</span>}</dd>
        </Fragment>
      ))}
    </dl>
  );
}

function DetailHeading({ children }) {
  return <h4 className="mb-1.5 text-xs font-semibold">{children}</h4>;
}

export function Empty({ children }) {
  return <p className="text-muted-foreground rounded-lg border border-dashed px-4 py-6 text-center text-sm">{children}</p>;
}

/**
 * The parent's answer to the confirmation request, first in the sheet: where
 * it stands, who recorded it and why not, and asking for it and recording it
 * where the API's `actions` allow -- with what the last of those did.
 */
export function ParentConfirmationCard({ communication, notice, onRequestConfirmation, onRecordAnswer }) {
  const headingId = useId();
  const { booking, parent_confirmation: confirmation, actions = {} } = communication;
  const canRequest = Boolean(actions.request_confirmation && onRequestConfirmation);
  const canRecord = Boolean(actions.record_confirmation && onRecordAnswer);
  return (
    <section aria-labelledby={headingId} className="bg-card rounded-xl border p-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0">
          <h3 id={headingId} className="text-sm font-semibold">
            Parent confirmation
          </h3>
          <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1">
            <ParentConfirmationBadge status={confirmation.status} booked={booking.status === 'BOOKED'} />
            {confirmation.at ? (
              <span className="text-muted-foreground text-xs">
                Recorded {istMoment(confirmation.at)}
                {confirmation.by ? ` by ${confirmation.by.full_name}` : ''}
              </span>
            ) : null}
            {confirmation.reason ? <span className="text-xs">Reason: {confirmation.reason.label}</span> : null}
          </div>
        </div>
        {canRequest || canRecord ? (
          <div className="flex flex-wrap gap-2 *:flex-1 sm:shrink-0 sm:*:flex-none">
            {canRequest ? (
              <Button variant="outline" size="sm" onClick={onRequestConfirmation}>
                <SendIcon />
                Request confirmation
              </Button>
            ) : null}
            {canRecord ? (
              <Button size="sm" onClick={onRecordAnswer}>
                <ClipboardCheckIcon />
                Record parent answer
              </Button>
            ) : null}
          </div>
        ) : null}
      </div>
      {notice ? (
        <p role="status" className="bg-success/10 text-success mt-3 rounded-md px-3 py-2 text-sm">
          {notice}
        </p>
      ) : null}
    </section>
  );
}

// Each workflow state's badge and dot on the timeline (lib/communications workflowState): green once done,
// red when it failed or ran out, amber while it is open or late, grey until its time comes.
const STEP_LOOKS = {
  completed: { label: 'Completed', variant: 'success', icon: CheckIcon, dot: 'bg-success/15 text-success' },
  sent: { label: 'Sent', variant: 'success', icon: CheckCheckIcon, dot: 'bg-success/15 text-success' },
  failed: { label: 'Failed', variant: 'destructive', icon: CircleAlertIcon, dot: 'bg-destructive/15 text-destructive' },
  missed: { label: 'Missed', variant: 'destructive', icon: TimerOffIcon, dot: 'bg-destructive/15 text-destructive' },
  cancelled: { label: 'Cancelled', variant: 'outline', icon: MinusIcon, dot: 'bg-muted text-muted-foreground' },
  overdue: { label: 'Overdue', variant: 'warning', icon: TriangleAlertIcon, dot: 'bg-warning/15 text-warning' },
  pending: { label: 'Pending', variant: 'warning', icon: CircleDotIcon, dot: 'bg-warning/15 text-warning' },
  scheduled: { label: 'Scheduled', variant: 'outline', icon: ClockIcon, dot: 'bg-muted text-muted-foreground' },
};

/** What a step's message adds under its line: that it failed, what it waits for, or that the parent has it. */
function stepNote(state, message) {
  if (!message || state === 'cancelled') return null;
  if (state === 'failed') return { text: joined('Message failed', istMoment(message.failed_at)), tone: 'text-destructive' };
  if (state === 'sent' || state === 'completed') {
    return message.status === 'DELIVERED' || message.status === 'READ'
      ? { text: joined(messageState(message).label, messageLine(message)), tone: 'text-muted-foreground' }
      : null;
  }
  const line = message.status === 'WAITING' || message.status === 'PENDING' ? messageLine(message) : null;
  return line ? { text: line, tone: 'text-muted-foreground' } : null;
}

/**
 * The five steps of PRD 3.11 as a vertical timeline: each with its state, its
 * moment and what its message adds, the first still open highlighted as the
 * current step. Nothing to act on here.
 */
export function WorkflowTimeline({ communication }) {
  const { booking, tasks, messages } = communication;
  const latest = latestMessages(messages);
  const current = tasks.find((task) => task.status === 'OPEN');
  return (
    <ol className="flex flex-col">
      {tasks.map((task, index) => {
        const message = latest[task.step];
        const state = workflowState(task, message);
        const look = STEP_LOOKS[state];
        const line = stepLine(task, booking.booking_type);
        const note = stepNote(state, message);
        const isCurrent = task === current;
        return (
          <li key={task.id} className="relative flex gap-3 pb-3 last:pb-0" aria-current={isCurrent ? 'step' : undefined}>
            {index < tasks.length - 1 ? (
              <span aria-hidden="true" className="bg-border absolute top-9 -bottom-0.5 left-[11.5px] w-px" />
            ) : null}
            <span
              aria-hidden="true"
              className={cn(
                'mt-2 grid size-6 shrink-0 place-items-center rounded-full',
                look.dot,
                isCurrent && 'ring-foreground/25 ring-offset-background ring-2 ring-offset-2'
              )}
            >
              <look.icon className="size-3.5" />
            </span>
            <div className={cn('min-w-0 flex-1 rounded-lg px-3 py-2', isCurrent && 'bg-muted')}>
              {isCurrent ? (
                <p aria-hidden="true" className="text-muted-foreground text-[11px] font-semibold tracking-wide uppercase">
                  Current step
                </p>
              ) : null}
              <div className="flex items-start justify-between gap-2">
                <p className="text-sm font-medium">{stepLabel(task)}</p>
                <Badge variant={look.variant}>{look.label}</Badge>
              </div>
              {line ? <p className="text-muted-foreground mt-0.5 text-xs">{line}</p> : null}
              {note ? <p className={cn('mt-0.5 text-xs', note.tone)}>{note.text}</p> : null}
            </div>
          </li>
        );
      })}
    </ol>
  );
}

/** Everything the API has on one message: its text, its moments, its attempts and the provider's reports. */
function MessageDetails({ id, message }) {
  const moments = MESSAGE_MOMENTS.filter(([, field]) => message[field]).map(([name, field]) => [name, istMoment(message[field])]);
  const facts = [
    ['Problem', message.problem?.label],
    ['Failure', message.failure_reason && joined(message.failure_reason, message.failure_code && `code ${message.failure_code}`)],
    ['Not sent because', message.cancel_reason?.label],
    ['Waiting for', (message.waiting_for ?? []).map((item) => item.label).join(', ')],
    ['Scheduled for', istMoment(message.scheduled_for)],
    ['Send by', istMoment(message.send_before)],
    ['Next attempt', istMoment(message.next_attempt_at)],
    ['Attempts', message.attempt_count ? String(message.attempt_count) : null],
    ['Channel', message.channel_label],
    ['Requested by', message.created_by?.full_name],
    ['Added', istMoment(message.created_at)],
  ];
  const attempts = message.attempts ?? [];
  const events = message.events ?? [];
  return (
    <div id={id} className="mt-3 flex flex-col gap-3 border-t pt-3">
      {/* The text exactly as WhatsApp shows it, as the preview did. */}
      {message.text ? (
        <div>
          <DetailHeading>Message</DetailHeading>
          <p className="bg-muted rounded-md p-2.5 text-xs break-words whitespace-pre-wrap">{message.text}</p>
        </div>
      ) : null}
      {moments.length ? (
        <div>
          <DetailHeading>Timestamps</DetailHeading>
          <Facts rows={moments} />
        </div>
      ) : null}
      <div>
        <DetailHeading>Details</DetailHeading>
        <Facts rows={facts} />
      </div>
      {attempts.length ? (
        <div>
          <DetailHeading>Attempts</DetailHeading>
          <ul className="flex flex-col gap-1.5">
            {attempts.map((attempt) => (
              <li key={attempt.number} className="bg-muted/60 rounded-md px-2.5 py-2 text-xs">
                <p className="font-medium">
                  Attempt {attempt.number} · {attempt.outcome_label || attempt.outcome}
                </p>
                <p className="text-muted-foreground">
                  {joined(istMoment(attempt.started_at), attempt.triggered_by && `by ${attempt.triggered_by.full_name}`)}
                </p>
                {attempt.error_message || attempt.error_code ? (
                  <p className="text-destructive break-words">
                    {joined(attempt.error_message, attempt.error_code && `code ${attempt.error_code}`, attempt.retryable && 'can be retried')}
                  </p>
                ) : null}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {events.length ? (
        <div>
          <DetailHeading>{message.channel_label || 'Provider'} events</DetailHeading>
          <ul className="flex flex-col gap-1">
            {events.map((event, index) => (
              <li key={`${event.status}-${event.occurred_at}-${index}`} className="text-xs">
                <div className="flex flex-wrap justify-between gap-x-3">
                  <span className="font-medium">{event.status_label || event.provider_status}</span>
                  <span className="text-muted-foreground">{istMoment(event.occurred_at)}</span>
                </div>
                {event.error_message || event.error_code ? (
                  <p className="text-destructive break-words">
                    {joined(event.error_message, event.error_code && `code ${event.error_code}`)}
                  </p>
                ) : null}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

/** One WhatsApp message: its step, a preview, its state and moment, why it failed (in the row), and its details on demand. */
export function MessageRow({ message }) {
  const [open, setOpen] = useState(false);
  const detailsId = useId();
  const label = stepLabel(message);
  const failed = message.status === 'FAILED';
  // Why it failed, or why it is being tried again -- in the row itself.
  const failure = failed || message.next_attempt_at ? message.failure_reason || (failed ? message.problem?.label : '') : '';
  const when = messageLine(message) ?? (message.scheduled_for ? `Scheduled for ${istMoment(message.scheduled_for)}` : null);
  const meta = joined(message.channel_label, when);
  return (
    <li className={cn('bg-card rounded-lg border p-3', failed && 'border-destructive/40 bg-destructive/5')}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm font-medium">{label}</p>
          {message.text ? <p className="text-muted-foreground mt-0.5 line-clamp-2 text-sm break-words">{message.text}</p> : null}
        </div>
        <MessageStateBadge message={message} />
      </div>
      {failure ? (
        <p className="text-destructive mt-2 flex items-start gap-1.5 text-xs font-medium">
          <CircleAlertIcon className="mt-px size-3.5 shrink-0" aria-hidden="true" />
          <span className="min-w-0 break-words">
            {failure}
            {message.failure_code ? ` (${message.failure_code})` : ''}
          </span>
        </p>
      ) : null}
      <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1">
        {meta ? <p className="text-muted-foreground text-xs">{meta}</p> : null}
        <Button
          variant="ghost"
          size="sm"
          className="-mr-2 ml-auto h-7 text-xs"
          onClick={() => setOpen((shown) => !shown)}
          aria-expanded={open}
          aria-controls={open ? detailsId : undefined}
          aria-label={`${open ? 'Hide' : 'Show'} the details of the ${label.toLowerCase()}`}
        >
          {open ? 'Hide details' : 'Show details'}
          <ChevronDownIcon className={cn('transition-transform', open && 'rotate-180')} />
        </Button>
      </div>
      {open ? <MessageDetails id={detailsId} message={message} /> : null}
    </li>
  );
}

/**
 * The 15-minute call before the class: its reminder while it is on, its time,
 * and the outcome the BDE recorded for it -- the call's task shows the latest
 * (backend communications.services.record_call_outcome) -- or that there is none.
 */
export function CallOutcomes({ communication }) {
  const { booking, tasks } = communication;
  const calls = tasks.filter((task) => task.step === 'PRE_ACTIVITY_CALL');
  if (!calls.length) return <Empty>No call is planned for this booking.</Empty>;
  return (
    <ul className="flex flex-col gap-2">
      {calls.map((task) => {
        const reminder = callReminder(task, booking.booking_type);
        const outcome = CALL_OUTCOMES.has(task.resolution) ? task.resolution_label : null;
        const closed = task.status !== 'OPEN' && !outcome;
        // In the timeline's words, as the call reads there.
        const look = STEP_LOOKS[workflowState(task)];
        return (
          <li key={task.id} className="bg-card rounded-lg border p-3">
            <div className="flex items-start justify-between gap-2">
              <p className="text-sm font-medium">{stepLabel(task)}</p>
              <Badge variant={look.variant}>{look.label}</Badge>
            </div>
            {reminder ? (
              <p className="bg-warning/10 text-warning mt-2 flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium">
                <PhoneCallIcon className="size-4 shrink-0" aria-hidden="true" />
                {reminder}
              </p>
            ) : null}
            <Facts
              className="mt-2"
              keepEmpty
              rows={[
                ['Reminder from', istMoment(task.active_from)],
                ['Due', istMoment(task.due_at)],
                ['Outcome', outcome ? joined(outcome, istMoment(task.resolved_at)) : 'No outcome recorded'],
                ...(outcome ? [['Recorded by', task.resolved_by?.full_name]] : []),
                ...(closed ? [['Closed', joined(task.resolution_label || task.status_label, istMoment(task.resolved_at))]] : []),
              ]}
            />
            <p className="text-muted-foreground mt-2 text-xs">A reminder to phone the parent shortly before the class starts.</p>
          </li>
        );
      })}
    </ul>
  );
}

/** Each step's task in full: who acts on it, from when, by when, until when, and how it closed. */
export function TaskDetails({ communication }) {
  const { tasks } = communication;
  if (!tasks.length) return <Empty>No tasks for this booking.</Empty>;
  return (
    <ul className="flex flex-col gap-2">
      {tasks.map((task) => (
        <li key={task.id} className="bg-card rounded-lg border p-3">
          <div className="flex items-start justify-between gap-2">
            <p className="text-sm font-medium">{stepLabel(task)}</p>
            <TaskStateBadge task={task} />
          </div>
          <Facts
            className="mt-2"
            keepEmpty
            rows={[
              ['Owner', joined(OWNER_ROLES[task.owner_role] ?? task.owner_role, task.owner?.full_name)],
              ['Active from', istMoment(task.active_from)],
              ['Due', istMoment(task.due_at)],
              ['Window closes', istMoment(task.expires_at)],
              ...(task.status === 'OPEN'
                ? []
                : [
                    ['Resolution', task.resolution_label || task.status_label],
                    ['Resolved', joined(istMoment(task.resolved_at), task.resolved_by && `by ${task.resolved_by.full_name}`)],
                  ]),
            ]}
          />
        </li>
      ))}
    </ul>
  );
}

/** The messages, the call and the tasks, a tab each, the tab bar kept in view as they scroll. */
function CommunicationTabs({ communication }) {
  const { tasks, messages } = communication;
  return (
    <section
      aria-label="Messages, call outcomes and task details"
      className="min-w-0 border-t px-4 pb-4 sm:px-6 lg:overflow-y-auto lg:border-t-0"
    >
      <Tabs defaultValue="messages" className="gap-4">
        <TabsList className="bg-background sticky top-0 z-10 pt-3">
          <TabsTrigger value="messages">
            Messages
            <TabsCount value={messages.length} />
          </TabsTrigger>
          <TabsTrigger value="calls">Call Outcomes</TabsTrigger>
          <TabsTrigger value="tasks">
            Task Details
            <TabsCount value={tasks.length} />
          </TabsTrigger>
        </TabsList>
        <TabsContent value="messages">
          {messages.length ? (
            <ol className="flex flex-col gap-2">
              {messages.map((message) => (
                <MessageRow key={message.id} message={message} />
              ))}
            </ol>
          ) : (
            <Empty>No messages yet.</Empty>
          )}
        </TabsContent>
        <TabsContent value="calls">
          <CallOutcomes communication={communication} />
        </TabsContent>
        <TabsContent value="tasks">
          <TaskDetails communication={communication} />
        </TabsContent>
      </Tabs>
    </section>
  );
}

function WorkspaceSkeleton() {
  return (
    <div className="flex flex-col gap-4 px-4 py-4 sm:px-6" aria-busy="true">
      <Skeleton className="h-20 rounded-xl" />
      <div className="grid gap-6 lg:grid-cols-[22rem_minmax(0,1fr)]">
        <div className="flex flex-col gap-3">
          {[0, 1, 2, 3, 4].map((key) => (
            <Skeleton key={key} className="h-12" />
          ))}
        </div>
        <div className="flex flex-col gap-3">
          <Skeleton className="h-9 w-72 max-w-full" />
          <Skeleton className="h-24" />
          <Skeleton className="h-24" />
        </div>
      </div>
    </div>
  );
}

/**
 * The body of the BDE's communication sheet, laid out from what
 * CommunicationPanel hands it (`communication`, `failure`, `retry`, the two
 * actions and the last action's `notice`): the parent's confirmation first,
 * then the workflow timeline beside the Messages, Call Outcomes and Task
 * Details tabs on a wide screen, one under the other on a narrow one. The
 * columns scroll on their own on a wide screen; the whole body on a narrow one.
 */
export function CommunicationWorkspace({ communication, failure, retry, notice, onRequestConfirmation, onRecordAnswer }) {
  const workflowHeadingId = useId();
  if (failure) {
    return (
      <div className="px-4 py-4 sm:px-6">
        <CommunicationBody communication={null} failure={failure} retry={retry} />
      </div>
    );
  }
  if (!communication) return <WorkspaceSkeleton />;

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto lg:overflow-hidden">
      <div className="shrink-0 px-4 pt-4 sm:px-6">
        <ParentConfirmationCard
          communication={communication}
          notice={notice}
          onRequestConfirmation={onRequestConfirmation}
          onRecordAnswer={onRecordAnswer}
        />
      </div>
      {communication.planned ? (
        <div className="grid lg:min-h-0 lg:flex-1 lg:grid-cols-[22rem_minmax(0,1fr)] lg:grid-rows-[minmax(0,1fr)]">
          <section aria-labelledby={workflowHeadingId} className="min-w-0 px-4 py-4 sm:px-6 lg:overflow-y-auto lg:border-r">
            <h3 id={workflowHeadingId} className="mb-3 text-sm font-semibold">
              Communication workflow
            </h3>
            <WorkflowTimeline communication={communication} />
          </section>
          <CommunicationTabs communication={communication} />
        </div>
      ) : (
        <p className="text-muted-foreground px-4 py-4 text-sm sm:px-6">
          {communication.redemo
            ? // A Re-Demo (backend bookings.redemos) has no plan: nothing is ever sent to its parent.
              'No messages are sent for a Re-Demo: the BDE contacts the parent directly with its date, time and tutor.'
            : 'No messages were planned for this booking: it was made before parent communication began.'}
        </p>
      )}
    </div>
  );
}
