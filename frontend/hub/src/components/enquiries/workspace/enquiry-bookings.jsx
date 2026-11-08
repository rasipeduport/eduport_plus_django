import { CalendarDaysIcon, CalendarOffIcon, MessageCircleIcon } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Panel, PanelEmpty } from '@/components/dashboard/dashboard-primitives';
import { ResponsiveList } from '@/components/page/responsive-list';
import { BookingTypeBadge } from '@/components/enquiries/enquiry-badges';
import { RedemoStatusBadge } from '@/components/bookings/booking-badges';
import { DemoInviteButton } from '@/components/bookings/demo-invite-button';
import { MeetLink } from '@/components/bookings/meet-link';
import { StudentTimeCell, StudentTimeLine } from '@/components/bookings/student-time';
import { ParentConfirmationBadge } from '@/components/communications/communication-badges';
import { bdeDemoInviteUrl, bookingState } from '@/lib/bookings';
import { istMoment } from '@/lib/communications';
import { bookingTypeLabel, formatDay, slotLabel, whatsAppUrl } from '@/lib/enquiries';
import { showsStudentTime } from '@/lib/timezone';
import { cn } from '@/lib/utils';

// The width the table needs with its actions; narrower areas show cards.
const MIN_TABLE_WIDTH = 1150;

/**
 * Who teaches a booking and its Google Meet link, to read and pass on -- the
 * API shows them for a booked or completed booking only, and the BDE changes
 * neither: an administrator sets the tutor and the tutor's link.
 */
export function Teaching({ booking }) {
  if (!booking.tutor) {
    return booking.status === 'BOOKED' && !booking.ended ? (
      <span className="text-muted-foreground">Not assigned yet</span>
    ) : (
      <span className="text-muted-foreground">—</span>
    );
  }
  return (
    <span className="flex flex-col gap-0.5">
      <span className="font-medium">{booking.tutor.full_name}</span>
      <MeetLink link={booking.tutor_meet_link} />
    </span>
  );
}

/** A link-like button inside a line of a booking's status. */
function InlineLink({ onClick, label, children }) {
  return (
    <Button variant="link" size="sm" className="h-auto p-0 text-xs" onClick={onClick} aria-label={label}>
      {children}
    </Button>
  );
}

/**
 * Where a Demo's Re-Demo stands, under its status: the request's own and --
 * once scheduled or taught -- when (with the student's own time, `zone`) and
 * with whom, with a way to the Re-Demo's own row (`onShowBooking`); a Re-Demo
 * cancelled since, waiting to be scheduled again; or, closed, when and why.
 */
function RedemoLine({ redemo, zone, onShowBooking }) {
  const booked = redemo.booking && (redemo.status === 'SCHEDULED' || redemo.status === 'COMPLETED');
  return (
    <span className="flex flex-col items-start gap-0.5">
      <span className="flex flex-wrap items-center gap-1 text-xs">
        <span className="text-muted-foreground">Re-Demo:</span>
        <RedemoStatusBadge status={redemo.status} />
      </span>
      {booked ? (
        <>
          <span className="text-muted-foreground text-xs">
            {slotLabel(redemo.booking)}
            {redemo.tutor ? ` with ${redemo.tutor.full_name}` : ''}
          </span>
          <StudentTimeLine startsAt={redemo.booking.starts_at} timezone={zone} className="text-xs" />
          {onShowBooking ? (
            <InlineLink onClick={() => onShowBooking(redemo.booking)} label={`Show the Re-Demo on ${slotLabel(redemo.booking)}`}>
              Show the Re-Demo
            </InlineLink>
          ) : null}
        </>
      ) : null}
      {redemo.status === 'AWAITING_SCHEDULING' && redemo.booking ? (
        <span className="text-muted-foreground text-xs">The last Re-Demo was cancelled · waiting to be scheduled again</span>
      ) : null}
      {redemo.closed ? (
        <span className="text-muted-foreground text-xs">
          Closed {formatDay(redemo.closed.at)}
          {redemo.closed.reason?.label ? ` · ${redemo.closed.reason.label}` : ''}
        </span>
      ) : null}
    </span>
  );
}

/**
 * Where the booking stands as a class, read-only: only its tutor starts it,
 * never its scheduled time. A Demo sent for a Re-Demo says where that stands
 * (RedemoLine); a Re-Demo leads back to the Demo it repeats. Both ways go to
 * that booking's own row when `onShowBooking` is given.
 */
export function BookingStatus({ booking, onShowBooking }) {
  const state = bookingState(booking);
  return (
    <div className="flex flex-col items-start gap-1">
      <span className="flex flex-wrap gap-1">
        <Badge variant={state.variant}>{state.label}</Badge>
        {booking.redemo_from ? <Badge variant="outline">Re-Demo</Badge> : null}
      </span>
      {booking.started_at ? (
        <span className="text-muted-foreground text-xs whitespace-nowrap">Started {istMoment(booking.started_at)}</span>
      ) : null}
      {booking.redemo ? (
        <RedemoLine redemo={booking.redemo} zone={booking.student_timezone} onShowBooking={onShowBooking} />
      ) : null}
      {booking.redemo_from && onShowBooking ? (
        <InlineLink
          onClick={() => onShowBooking({ id: booking.redemo_from.demo_booking_id })}
          label="Show the Demo this Re-Demo repeats"
        >
          Show the Demo it repeats
        </InlineLink>
      ) : null}
    </div>
  );
}

// What a Re-Demo's parent message still lacks, in the BDE's words (backend communications.redemo_messages).
const MISSING_VALUES = {
  tutor_name: 'a tutor',
  meeting_link: "the tutor's Meet link",
  bde_name: 'your name in Team',
  bde_phone: 'your mobile number in Team',
  template: 'its message template',
};

const missingText = (missing) => [...new Set((missing ?? []).map((name) => MISSING_VALUES[name] ?? name))].join(', ');

/**
 * A Re-Demo's parent messages, sent by hand on WhatsApp (the API's
 * `parent_messages`: the Demo messages' own wording, filled in for this
 * Re-Demo with its time on the student's clock): asking the parent to confirm
 * it until they have, and its class details -- tutor, time, Meet link -- once
 * they have (or when the BDE cannot see the answer). Nothing is sent until
 * the BDE sends it; a message missing a value names what it needs instead.
 */
function RedemoMessages({ booking, recipient }) {
  const messages = booking.parent_messages;
  if (!messages || !recipient) return null;
  const confirmed = booking.parent_confirmation === 'CONFIRMED';
  const unknown = booking.parent_confirmation == null;
  const ask = messages.confirmation_request;
  const details = messages.confirmed;
  const what = `the Re-Demo on ${slotLabel(booking)}`;
  const items = [];
  if (!confirmed && ask?.text) {
    items.push(
      <Button key="ask" variant="outline" size="sm" asChild>
        <a
          href={whatsAppUrl(recipient.dialCode, recipient.number, ask.text)}
          target="_blank"
          rel="noopener noreferrer"
          aria-label={`Ask the parent on WhatsApp to confirm ${what}`}
        >
          <MessageCircleIcon />
          Ask parent to confirm
        </a>
      </Button>
    );
  } else if (!confirmed && ask?.missing?.length) {
    // A request the booking cannot fill says what it needs, as the class details do.
    items.push(
      <span key="ask-missing" className="text-muted-foreground text-xs">
        The confirmation request needs {missingText(ask.missing)}
      </span>
    );
  }
  if (confirmed || unknown) {
    if (details?.text) {
      items.push(
        <Button key="details" variant="outline" size="sm" asChild>
          <a
            href={whatsAppUrl(recipient.dialCode, recipient.number, details.text)}
            target="_blank"
            rel="noopener noreferrer"
            aria-label={`Send the parent the class details of ${what} on WhatsApp`}
          >
            <MessageCircleIcon />
            Send class details
          </a>
        </Button>
      );
    } else if (details?.missing?.length) {
      items.push(
        <span key="details-missing" className="text-muted-foreground text-xs">
          Class details need {missingText(details.missing)}
        </span>
      );
    }
  }
  return items.length ? items : null;
}

/**
 * What the BDE may do with the booking, as the API offers it (`booking.actions`,
 * and for a Demo sent for a Re-Demo `booking.redemo.actions`: closing the
 * request while nothing is booked for it, or reopening it); the API checks
 * again. A Re-Demo still to come also offers its parent messages (RedemoMessages).
 */
function BookingActions({ booking, actions, className }) {
  const { onOpenCommunication, onCancel, recipient, onInviteRefused, onRequestRedemo, onCloseRedemo, onReopenRedemo } =
    actions;
  const what = `${bookingTypeLabel(booking.booking_type).toLowerCase()} on ${slotLabel(booking)}`;
  const redemoActions = booking.redemo?.actions ?? {};
  return (
    <div className={cn('flex flex-wrap items-center justify-end gap-2', className)}>
      {onOpenCommunication ? (
        <Button variant="ghost" size="sm" onClick={() => onOpenCommunication(booking)} aria-label={`Communication for the ${what}`}>
          Communication
        </Button>
      ) : null}
      {booking.actions?.cancel ? (
        <Button variant="outline" size="sm" onClick={() => onCancel(booking)} aria-label={`Cancel the ${what}`}>
          Cancel
        </Button>
      ) : null}
      {booking.actions?.demo_invite ? (
        <DemoInviteButton
          inviteUrl={bdeDemoInviteUrl(booking.booking_type, booking.id)}
          recipient={recipient}
          onRefused={onInviteRefused}
        />
      ) : null}
      {booking.actions?.request_redemo ? (
        <Button
          variant="outline"
          size="sm"
          onClick={() => onRequestRedemo(booking)}
          aria-label={`Request a Re-Demo of the demo on ${slotLabel(booking)}`}
        >
          Request Re-Demo
        </Button>
      ) : null}
      {redemoActions.close && onCloseRedemo ? (
        <Button
          variant="outline"
          size="sm"
          onClick={() => onCloseRedemo(booking)}
          aria-label={`Close the Re-Demo request for the demo on ${slotLabel(booking)}`}
        >
          Close request
        </Button>
      ) : null}
      {redemoActions.reopen && onReopenRedemo ? (
        <Button
          variant="outline"
          size="sm"
          onClick={() => onReopenRedemo(booking)}
          aria-label={`Reopen the Re-Demo request for the demo on ${slotLabel(booking)}`}
        >
          Reopen request
        </Button>
      ) : null}
      <RedemoMessages booking={booking} recipient={recipient} />
    </div>
  );
}

/** A booking's Student Time, from its own instant and its student's zone (the API's `student_timezone`). */
function StudentTime({ booking }) {
  return <StudentTimeCell startsAt={booking.starts_at} timezone={booking.student_timezone} />;
}

function columnsFor(actions, showStudentTime) {
  const communication = Boolean(actions.onOpenCommunication);
  return [
    { key: 'when', header: 'When (IST)', className: 'font-medium whitespace-nowrap', cell: (booking) => slotLabel(booking) },
    // A cell of its own: the When cell's text is the slot alone.
    ...(showStudentTime
      ? [{ key: 'student_time', header: 'Student Time', className: 'whitespace-nowrap', cell: (booking) => <StudentTime booking={booking} /> }]
      : []),
    { key: 'type', header: 'Type', cell: (booking) => <BookingTypeBadge type={booking.booking_type} /> },
    {
      key: 'status',
      header: 'Status',
      cell: (booking) => <BookingStatus booking={booking} onShowBooking={actions.onShowBooking} />,
    },
    ...(communication
      ? [
          {
            key: 'confirmation',
            header: 'Confirmation',
            cell: (booking) => (
              <ParentConfirmationBadge status={booking.parent_confirmation} booked={booking.status === 'BOOKED'} />
            ),
          },
        ]
      : []),
    { key: 'tutor', header: 'Tutor', className: 'min-w-40 whitespace-normal', cell: (booking) => <Teaching booking={booking} /> },
    {
      key: 'booked',
      header: 'Booked on',
      className: 'text-muted-foreground whitespace-nowrap',
      cell: (booking) => formatDay(booking.booked_at),
    },
    {
      key: 'actions',
      header: { srOnly: 'Actions' },
      headerClassName: 'w-px',
      cell: (booking) => <BookingActions booking={booking} actions={actions} />,
    },
  ];
}

/** One booking as a card, where the table would not fit: the same facts and actions. */
function BookingCard({ booking, actions, showStudentTime }) {
  return (
    <article className="bg-card flex h-full flex-col gap-3 rounded-xl border p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="font-medium">{slotLabel(booking)}</p>
          <p className="text-muted-foreground text-xs">Booked on {formatDay(booking.booked_at)}</p>
        </div>
        <BookingTypeBadge type={booking.booking_type} />
      </div>
      <BookingStatus booking={booking} onShowBooking={actions.onShowBooking} />
      <div className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
        {showStudentTime ? (
          <div className="col-span-2 min-w-0">
            <p className="text-muted-foreground text-xs">Student Time</p>
            <p className="truncate">
              <StudentTime booking={booking} />
            </p>
          </div>
        ) : null}
        {actions.onOpenCommunication ? (
          <div className="min-w-0">
            <p className="text-muted-foreground text-xs">Confirmation</p>
            <ParentConfirmationBadge status={booking.parent_confirmation} booked={booking.status === 'BOOKED'} />
          </div>
        ) : null}
        <div className="min-w-0">
          <p className="text-muted-foreground text-xs">Tutor</p>
          <Teaching booking={booking} />
        </div>
      </div>
      <BookingActions booking={booking} actions={actions} className="mt-auto flex-wrap justify-start" />
    </article>
  );
}

/**
 * The enquiry's bookings. Its owner BDE may cancel one that is still booked
 * (Q22) -- the API says which in each booking's `actions` and checks again,
 * that the lead is theirs, on every request -- and, from a Diagnostic whose
 * report is in, send the parent (`recipient`) a Demo invitation; a refusal
 * reads the enquiry again (`onInviteRefused`). A completed Demo may be sent
 * for a Re-Demo (`onRequestRedemo`): it then says where the Re-Demo stands
 * and, once an administrator has scheduled it, when and with whom; while
 * nothing is booked for it the request may be closed (`onCloseRedemo`), and a
 * closed one reopened (`onReopenRedemo`). A Re-Demo still to come offers the
 * parent's messages to send by hand on WhatsApp. A Demo and its Re-Demo lead
 * to each other's rows (`onShowBooking`). With the lead's communication to
 * see (`onOpenCommunication`), each shows the parent's answer to the
 * confirmation request and opens its communication. Beside each booking's
 * Indian time, the student's own (Student Time) while any booking reads
 * differently. `highlight` is the booking a link opened the workspace for.
 */
export function EnquiryBookings({
  bookings,
  highlight,
  onOpenCommunication,
  onCancel,
  recipient,
  onInviteRefused,
  onRequestRedemo,
  onCloseRedemo,
  onReopenRedemo,
  onShowBooking,
}) {
  const actions = {
    onOpenCommunication,
    onCancel,
    recipient,
    onInviteRefused,
    onRequestRedemo,
    onCloseRedemo,
    onReopenRedemo,
    onShowBooking,
  };
  const showStudentTime = showsStudentTime(bookings, (booking) => booking.starts_at, (booking) => booking.student_timezone);
  return (
    <Panel icon={CalendarDaysIcon} title="Bookings" subtitle="Demo classes and diagnostic tests, in Indian time (IST)">
      {bookings.length === 0 ? (
        <PanelEmpty
          icon={CalendarOffIcon}
          message="No bookings yet"
          hint="Bookings made through the booking pages for this child appear here."
        />
      ) : (
        <ResponsiveList
          label="Bookings"
          columns={columnsFor(actions, showStudentTime)}
          rows={bookings}
          highlightedKey={highlight}
          minTableWidth={MIN_TABLE_WIDTH}
          renderCard={(booking) => <BookingCard booking={booking} actions={actions} showStudentTime={showStudentTime} />}
        />
      )}
    </Panel>
  );
}
