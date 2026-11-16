import { useState } from 'react';
import { Link } from 'react-router-dom';
import {
  ChevronRightIcon,
  ClipboardCheckIcon,
  FileTextIcon,
  MessageCircleIcon,
  PhoneCallIcon,
  PhoneIcon,
  RotateCcwIcon,
  UserPlusIcon,
} from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { ResponsiveList } from '@/components/page/responsive-list';
import { BookingTypeBadge } from '@/components/enquiries/enquiry-badges';
import { RecordOutcomeDialog } from '@/components/enquiries/follow-up-dialogs';
import { ConfirmationRequestDialog } from '@/components/communications/confirmation-request-dialog';
import { ParentAnswerDialog } from '@/components/communications/parent-answer-dialog';
import { confirmationRequestNotice, istMoment, istParts, joined, parentAnswerNotice } from '@/lib/communications';
import { phoneLinks, slotLabel, whatsAppUrl } from '@/lib/enquiries';
import { FOLLOW_UP_STATE_VARIANTS, followUpPath, followUpTask } from '@/lib/follow-ups';

const TYPE_ICONS = {
  NEW_ENQUIRY_CALL: UserPlusIcon,
  PARENT_CONFIRMATION: ClipboardCheckIcon,
  PRE_ACTIVITY_CALL: PhoneCallIcon,
  TUTOR_REPORT: FileTextIcon,
  REDEMO_CONFIRMATION: RotateCcwIcon,
};

const rowKey = (followUp) => `${followUp.type}:${followUp.id}`;

/** A follow-up's booking as the confirmation dialogs read one: the booking, whose it is and its slot. */
const dialogBooking = (followUp) =>
  followUp?.booking
    ? { ...followUp.booking, student_name: followUp.enquiry.student_name, slot: followUp.booking }
    : null;

export function FollowUpStateBadge({ followUp }) {
  return <Badge variant={FOLLOW_UP_STATE_VARIANTS[followUp.state] ?? 'outline'}>{followUp.state_label}</Badge>;
}

function FollowUpName({ followUp }) {
  const Icon = TYPE_ICONS[followUp.type] ?? ClipboardCheckIcon;
  const task = followUpTask(followUp);
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <Icon className="text-muted-foreground size-4 shrink-0" aria-hidden="true" />
        <span className="font-medium">{followUp.type_label}</span>
        <FollowUpStateBadge followUp={followUp} />
      </span>
      {task ? <span className="text-muted-foreground text-xs">{task}</span> : null}
    </div>
  );
}

/** Demo class or diagnostic test -- marked when it is a Re-Demo -- and its slot; a new enquiry has none yet. */
function FollowUpBooking({ booking }) {
  if (!booking) return <span className="text-muted-foreground text-sm">No booking yet</span>;
  return (
    <span className="flex flex-col items-start gap-1">
      <span className="flex flex-wrap items-center gap-1.5">
        <BookingTypeBadge type={booking.booking_type} />
        {booking.redemo ? <Badge variant="outline">Re-Demo</Badge> : null}
      </span>
      <span className="text-muted-foreground text-xs whitespace-nowrap">{slotLabel(booking)}</span>
    </span>
  );
}

/** When a follow-up is due: its Indian date over its time. */
function Due({ value }) {
  const parts = istParts(value);
  if (!parts) return null;
  return (
    <span className="flex flex-col">
      <span>{parts.date}</span>
      <span className="text-muted-foreground text-xs">{parts.time}</span>
    </span>
  );
}

/**
 * What the BDE does on a reminder -- each action offered only when the API
 * says the caller may take it, or the page where it is done: the enquiry, or
 * its tutor feedback, where the report is sent -- with calling or messaging
 * the parent. A Re-Demo's confirmation is the BDE's by hand: WhatsApp opens
 * with the confirmation request's own wording filled in for it (the API's
 * `parent_messages`), its time on the student's clock, for the BDE to send.
 */
function Actions({ followUp, from, inEnquiry, onAct, className }) {
  const { actions, enquiry } = followUp;
  const links = phoneLinks(enquiry.phone_dial_code, enquiry.phone_number);
  const who = enquiry.parent_name;
  const prefilled =
    followUp.type === 'REDEMO_CONFIRMATION' ? followUp.parent_messages?.confirmation_request?.text ?? null : null;
  const whatsapp = prefilled ? whatsAppUrl(enquiry.phone_dial_code, enquiry.phone_number, prefilled) : links?.whatsapp;
  const whatsappLabel = prefilled ? `WhatsApp ${who} the Re-Demo date and time` : `WhatsApp ${who}`;
  const whose = `${enquiry.student_name}’s ${followUp.type_label.toLowerCase()}`;
  const report = followUp.type === 'TUTOR_REPORT';
  const act = (kind) => () => onAct(kind, followUp);

  const buttons = [];
  if (actions.request_confirmation) {
    buttons.push(
      <Button key="request" size="sm" onClick={act('request')} aria-label={`Request confirmation for ${whose}`}>
        Request confirmation
      </Button>
    );
  }
  if (actions.record_answer) {
    buttons.push(
      <Button
        key="answer"
        size="sm"
        variant={actions.request_confirmation ? 'outline' : 'default'}
        onClick={act('answer')}
        aria-label={`Record the parent’s answer for ${whose}`}
      >
        Record answer
      </Button>
    );
  }
  if (actions.record_outcome) {
    buttons.push(
      <Button key="outcome" size="sm" onClick={act('outcome')} aria-label={`Record the outcome of ${whose}`}>
        Record outcome
      </Button>
    );
  }
  if (report) {
    buttons.push(
      <Button key="report" size="sm" asChild>
        <Link
          to={followUpPath(followUp)}
          state={from ? { from } : undefined}
          aria-label={`Open ${enquiry.student_name}’s tutor report to share it`}
        >
          <FileTextIcon />
          Open report
        </Link>
      </Button>
    );
  }
  // A new enquiry opens its own page -- already in view inside it.
  if (followUp.type === 'NEW_ENQUIRY_CALL' && !inEnquiry) {
    buttons.push(
      <Button key="enquiry" size="sm" asChild>
        <Link
          to={followUpPath(followUp)}
          state={from ? { from } : undefined}
          aria-label={`Open ${enquiry.student_name}’s enquiry`}
        >
          Open enquiry
        </Link>
      </Button>
    );
  }
  // A booking's reminder also opens its communication.
  const openable = Boolean(followUp.booking) && !report;
  const openLabel = `Open the communication for ${whose}`;

  return (
    <div className={className ?? 'flex flex-wrap items-center justify-end gap-2'}>
      {buttons}
      <div className="ml-auto flex items-center gap-1">
        {links ? (
          <>
            <Button variant="ghost" size="icon" className="size-8" asChild>
              <a href={links.tel} aria-label={`Call ${who}`} title={`Call ${who}`}>
                <PhoneIcon className="size-4" />
              </a>
            </Button>
            <Button variant="ghost" size="icon" className="size-8" asChild>
              <a href={whatsapp} target="_blank" rel="noopener noreferrer" aria-label={whatsappLabel}
                title={whatsappLabel}>
                <MessageCircleIcon className="size-4" />
              </a>
            </Button>
          </>
        ) : null}
        {openable ? (
          <Button variant="ghost" size="icon" className="size-8" asChild>
            <Link to={followUpPath(followUp)} state={from ? { from } : undefined} aria-label={openLabel} title={openLabel}>
              <ChevronRightIcon className="size-4" />
            </Link>
          </Button>
        ) : null}
      </div>
    </div>
  );
}

/**
 * Reminders as a list: a table where it fits, cards elsewhere. Each says what
 * is to be done and by when, for which booking and (unless `inEnquiry`, inside
 * the enquiry's own workspace) whose, with the action that does it -- asking
 * for or recording the parent's confirmation, or recording the call before a
 * class, in a dialog here; opening the enquiry, or its report to send it to
 * the parent. `onChanged` hears of each action taken here, with what to tell
 * the BDE; `from` is the way back from where one opens.
 */
export function FollowUpList({ rows, pending, inEnquiry = false, from = null, onChanged }) {
  // The dialog open now, and the follow-up it is for -- kept while it closes.
  const [dialog, setDialog] = useState({ kind: null, followUp: null });
  const onAct = (kind, followUp) => setDialog({ kind, followUp });
  const dialogProps = (kind) => ({
    open: dialog.kind === kind,
    onOpenChange: (open) => setDialog((current) => ({ ...current, kind: open ? kind : null })),
  });
  const changed = (message) => onChanged?.(message);

  const columns = [
    {
      key: 'follow-up',
      header: 'Follow-up',
      className: 'min-w-60 whitespace-normal',
      cell: (followUp) => <FollowUpName followUp={followUp} />,
    },
    ...(inEnquiry
      ? []
      : [
          {
            key: 'enquiry',
            header: 'Student & parent',
            className: 'whitespace-normal',
            cell: (followUp) => (
              <>
                <p className="font-medium">{followUp.enquiry.student_name}</p>
                <p className="text-muted-foreground text-xs">{followUp.enquiry.parent_name}</p>
                <p className="text-muted-foreground text-xs whitespace-nowrap">{followUp.enquiry.phone}</p>
              </>
            ),
          },
        ]),
    { key: 'booking', header: 'Booking', cell: (followUp) => <FollowUpBooking booking={followUp.booking} /> },
    { key: 'due', header: 'Due (IST)', cell: (followUp) => <Due value={followUp.due_at} /> },
    {
      key: 'actions',
      header: { srOnly: 'Actions' },
      className: 'whitespace-normal',
      cell: (followUp) => <Actions followUp={followUp} from={from} inEnquiry={inEnquiry} onAct={onAct} />,
    },
  ];

  const renderCard = (followUp) => (
    <article className="bg-card flex h-full flex-col gap-3 rounded-xl border p-4">
      <FollowUpName followUp={followUp} />
      {inEnquiry ? null : (
        <p className="text-sm">
          <span className="font-medium">{followUp.enquiry.student_name}</span>
          <span className="text-muted-foreground"> · {joined(followUp.enquiry.parent_name, followUp.enquiry.phone)}</span>
        </p>
      )}
      <div className="flex flex-wrap items-end justify-between gap-2">
        <FollowUpBooking booking={followUp.booking} />
        <p className="text-muted-foreground text-xs">Due {istMoment(followUp.due_at)}</p>
      </div>
      <Actions
        followUp={followUp}
        from={from}
        inEnquiry={inEnquiry}
        onAct={onAct}
        className="mt-auto flex flex-wrap items-center gap-2"
      />
    </article>
  );

  return (
    <>
      <ResponsiveList
        label="Follow-ups"
        columns={columns}
        rows={rows}
        rowKey={rowKey}
        pending={pending}
        minTableWidth={inEnquiry ? 820 : 1080}
        renderCard={renderCard}
      />
      <RecordOutcomeDialog followUp={dialog.followUp} onRecorded={changed} {...dialogProps('outcome')} />
      <ConfirmationRequestDialog
        booking={dialogBooking(dialog.followUp)}
        onRequested={(data) => changed(confirmationRequestNotice(data))}
        {...dialogProps('request')}
      />
      <ParentAnswerDialog
        booking={dialogBooking(dialog.followUp)}
        onRecorded={(data, outcome) => changed(parentAnswerNotice(data, outcome))}
        {...dialogProps('answer')}
      />
    </>
  );
}
