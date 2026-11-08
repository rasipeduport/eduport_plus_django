import { CalendarDaysIcon, CalendarOffIcon } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Panel, PanelEmpty } from '@/components/dashboard/dashboard-primitives';
import { ResponsiveList } from '@/components/page/responsive-list';
import { BookingTypeBadge } from '@/components/enquiries/enquiry-badges';
import { RedemoStatusBadge } from '@/components/bookings/booking-badges';
import { DemoInviteButton } from '@/components/bookings/demo-invite-button';
import { MeetLink } from '@/components/bookings/meet-link';
import { ParentConfirmationBadge } from '@/components/communications/communication-badges';
import { bdeDemoInviteUrl, bookingState } from '@/lib/bookings';
import { istMoment } from '@/lib/communications';
import { bookingTypeLabel, formatDay, slotLabel } from '@/lib/enquiries';
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

/** Where a Demo's Re-Demo stands, under its status: the request's own and, once scheduled, when and with whom. */
function RedemoLine({ redemo }) {
  return (
    <span className="flex flex-col items-start gap-0.5">
      <span className="flex flex-wrap items-center gap-1 text-xs">
        <span className="text-muted-foreground">Re-Demo:</span>
        <RedemoStatusBadge status={redemo.status} />
      </span>
      {redemo.booking ? (
        <span className="text-muted-foreground text-xs">
          {slotLabel(redemo.booking)}
          {redemo.tutor ? ` with ${redemo.tutor.full_name}` : ''}
        </span>
      ) : null}
    </span>
  );
}

/** Where the booking stands as a class, read-only: only its tutor starts it, never its scheduled time. */
export function BookingStatus({ booking }) {
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
      {booking.redemo ? <RedemoLine redemo={booking.redemo} /> : null}
    </div>
  );
}

/** What the BDE may do with the booking, as the API offers it (`booking.actions`); the API checks again. */
function BookingActions({ booking, actions, className }) {
  const { onOpenCommunication, onCancel, recipient, onInviteRefused, onRequestRedemo } = actions;
  const what = `${bookingTypeLabel(booking.booking_type).toLowerCase()} on ${slotLabel(booking)}`;
  return (
    <div className={cn('flex justify-end gap-2', className)}>
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
    </div>
  );
}

function columnsFor(actions) {
  const communication = Boolean(actions.onOpenCommunication);
  return [
    { key: 'when', header: 'When (IST)', className: 'font-medium whitespace-nowrap', cell: (booking) => slotLabel(booking) },
    { key: 'type', header: 'Type', cell: (booking) => <BookingTypeBadge type={booking.booking_type} /> },
    { key: 'status', header: 'Status', cell: (booking) => <BookingStatus booking={booking} /> },
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
function BookingCard({ booking, actions }) {
  return (
    <article className="bg-card flex h-full flex-col gap-3 rounded-xl border p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="font-medium">{slotLabel(booking)}</p>
          <p className="text-muted-foreground text-xs">Booked on {formatDay(booking.booked_at)}</p>
        </div>
        <BookingTypeBadge type={booking.booking_type} />
      </div>
      <BookingStatus booking={booking} />
      <div className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
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
 * and, once an administrator has scheduled it, when and with whom. With the
 * lead's communication to see (`onOpenCommunication`), each shows the
 * parent's answer to the confirmation request and opens its communication.
 * `highlight` is the booking a link opened the workspace for.
 */
export function EnquiryBookings({ bookings, highlight, onOpenCommunication, onCancel, recipient, onInviteRefused, onRequestRedemo }) {
  const actions = { onOpenCommunication, onCancel, recipient, onInviteRefused, onRequestRedemo };
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
          columns={columnsFor(actions)}
          rows={bookings}
          highlightedKey={highlight}
          minTableWidth={MIN_TABLE_WIDTH}
          renderCard={(booking) => <BookingCard booking={booking} actions={actions} />}
        />
      )}
    </Panel>
  );
}
