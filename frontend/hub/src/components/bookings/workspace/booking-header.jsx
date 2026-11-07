import { ArrowRightLeftIcon, CalendarX2Icon, MessageCircleIcon, PhoneIcon, RotateCcwIcon } from 'lucide-react';

import { Avatar, AvatarFallback } from '@/components/ui/avatar';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { BookingTypeBadge } from '@/components/enquiries/enquiry-badges';
import { BookingStateBadge, RedemoBadge, RedemoStatusBadge, StartInfo } from '@/components/bookings/booking-badges';
import { cameInLabel } from '@/lib/bookings';
import { formatDay, phoneLinks, slotLabel } from '@/lib/enquiries';
import { getInitials } from '@/lib/utils';

/** Whether the booking has its tutor: who, or that a booking still to come needs one. */
function TutorStatus({ booking }) {
  if (booking.tutor) return <Badge variant="outline">Tutor: {booking.tutor.full_name}</Badge>;
  if (booking.status === 'BOOKED' && !booking.slot?.ended) return <Badge variant="warning">Needs a tutor</Badge>;
  return null;
}

/** One fact of the booking, its label muted: "Seat 1". */
function Fact({ label, children }) {
  return (
    <div className="flex min-w-0 flex-wrap items-center gap-x-1.5">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="min-w-0 font-medium break-words">{children || <span className="text-muted-foreground">—</span>}</dd>
    </div>
  );
}

/** A link-like button inside a line of text. */
function InlineLink({ onClick, label, children }) {
  return (
    <Button variant="link" size="sm" className="h-auto p-0 text-xs" onClick={onClick} aria-label={label}>
      {children}
    </Button>
  );
}

/** A line about what happened to the booking -- moved, cancelled, sent for a Re-Demo -- with its icon. */
function Note({ icon: Icon, children }) {
  return (
    <li className="flex items-start gap-2">
      <Icon className="text-muted-foreground mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
      <span className="flex min-w-0 flex-wrap items-center gap-x-1.5 gap-y-1">{children}</span>
    </li>
  );
}

/**
 * The booking's own facts, under its name: its seat, when it was booked, how
 * it came in and who it came through -- a BDE credited by their link, the
 * administrator who scheduled a Re-Demo, or whoever sent the Demo invitation
 * and from which Diagnostic -- and whether its tutor started it (read-only:
 * only the tutor starts a booking).
 */
function Facts({ booking }) {
  let origin;
  if (booking.channel === 'BDE_HANDOFF' && booking.redemo_from) {
    origin = <Fact label="Scheduled by">{booking.created_by?.full_name}</Fact>;
  } else if (booking.channel === 'BDE_HANDOFF') {
    origin = (
      <>
        <Fact label="Invited by">{booking.created_by?.full_name}</Fact>
        <Fact label="From Diagnostic">{booking.invited_from ? slotLabel(booking.invited_from.slot) : null}</Fact>
      </>
    );
  } else {
    origin = <Fact label="Credited BDE">{booking.bde?.full_name}</Fact>;
  }
  return (
    <dl className="flex flex-wrap gap-x-5 gap-y-1 text-xs">
      <Fact label="Seat">{booking.seat ? String(booking.seat) : null}</Fact>
      <Fact label="Booked on">{formatDay(booking.booked_at)}</Fact>
      <Fact label="Came in">{cameInLabel(booking)}</Fact>
      {origin}
      {booking.status !== 'RESCHEDULED' ? (
        <Fact label="Started">
          <StartInfo booking={booking} showBy />
        </Fact>
      ) : null}
    </dl>
  );
}

/**
 * What has happened to the booking beyond its status, each with its way on:
 * the booking it replaced and the one that replaced it (`onOpenBooking(id)`),
 * the Demo a Re-Demo teaches again and its request, the Re-Demo a completed
 * Demo was sent for (`onOpenRedemo(id)`), and a cancellation, with who did it,
 * when and why. Nothing when none applies.
 */
function Notes({ booking, onOpenBooking, onOpenRedemo }) {
  const notes = [];
  if (booking.rescheduled_from) {
    notes.push(
      <Note key="moved-from" icon={ArrowRightLeftIcon}>
        <span>Moved from {slotLabel(booking.rescheduled_from.slot)}</span>
        <InlineLink onClick={() => onOpenBooking(booking.rescheduled_from.id)} label="Open the booking it replaced">
          Open
        </InlineLink>
      </Note>
    );
  }
  if (booking.channel === 'BDE_HANDOFF' && booking.redemo_from) {
    notes.push(
      <Note key="redemo-of" icon={RotateCcwIcon}>
        <span>Re-Demo of the Demo on {slotLabel(booking.redemo_from.original.slot)}</span>
        <InlineLink onClick={() => onOpenBooking(booking.redemo_from.original.id)} label="Open the Demo this one teaches again">
          Open
        </InlineLink>
        <span className="text-muted-foreground">·</span>
        <span>Request</span>
        <RedemoStatusBadge status={booking.redemo_from.status} />
        <InlineLink onClick={() => onOpenRedemo(booking.redemo_from.id)}>Open request</InlineLink>
      </Note>
    );
  }
  // The Re-Demo this Demo was sent for: its report and history stay, the new Demo is booked separately.
  if (booking.redemo_request) {
    notes.push(
      <Note key="redemo" icon={RotateCcwIcon}>
        <span>Re-Demo</span>
        <RedemoStatusBadge status={booking.redemo_request.status} />
        <span>
          requested on {formatDay(booking.redemo_request.requested_at)} by{' '}
          {booking.redemo_request.requested_by?.full_name ?? '—'}
        </span>
        <InlineLink onClick={() => onOpenRedemo(booking.redemo_request.id)}>Open request</InlineLink>
      </Note>
    );
  }
  if (booking.status === 'CANCELLED') {
    notes.push(
      <Note key="cancelled" icon={CalendarX2Icon}>
        <span>
          Cancelled on {formatDay(booking.cancelled_at)} by {booking.cancelled_by?.full_name ?? '—'}
        </span>
        <span className="text-muted-foreground">·</span>
        <span>{booking.cancel_reason || 'No reason given'}</span>
      </Note>
    );
  }
  if (booking.status === 'RESCHEDULED') {
    notes.push(
      <Note key="moved" icon={ArrowRightLeftIcon}>
        <span>
          Moved on {formatDay(booking.rescheduled_at)} by {booking.rescheduled_by?.full_name ?? '—'}
        </span>
        <span className="text-muted-foreground">·</span>
        <span>{booking.reschedule_reason || 'No reason given'}</span>
        {booking.rescheduled_to ? (
          <>
            <span className="text-muted-foreground">·</span>
            <span>Moved to {slotLabel(booking.rescheduled_to.slot)}</span>
            <InlineLink onClick={() => onOpenBooking(booking.rescheduled_to.id)} label="Open the new booking">
              Open
            </InlineLink>
          </>
        ) : null}
      </Note>
    );
  }
  return notes.length ? <ul className="flex flex-col gap-1.5 text-xs">{notes}</ul> : null;
}

/**
 * Who the booking is for and how to reach them, as the BDE's enquiry
 * workspace heads an enquiry -- compact, the actions on one row: the student,
 * the booking's type, where it stands and its tutor; the class and syllabus,
 * the parent and their number; the booking's reference (its id's first eight
 * characters: a lead has no student id) and its slot (IST); then the
 * booking's own facts (Facts) and what has happened to it (Notes). Call and
 * WhatsApp come first among `actions`, the booking's own (the workspace offers
 * only those its state and the caller's permissions allow). A booking of its
 * chain opens in its own workspace (`onOpenBooking(id)`), a Re-Demo request
 * on Demo Bookings' Re-Demo tab (`onOpenRedemo(id)`).
 */
export function BookingHeader({ booking, actions, onOpenBooking, onOpenRedemo }) {
  const lead = booking.lead ?? {};
  const links = phoneLinks(lead.phone_dial_code, lead.phone_number);
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-4">
        <div className="flex min-w-0 items-start gap-4">
          <Avatar className="size-14 rounded-full" aria-hidden="true">
            <AvatarFallback className="size-14 rounded-full text-lg">{getInitials(booking.student_name, null)}</AvatarFallback>
          </Avatar>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="truncate text-2xl font-semibold tracking-tight">{booking.student_name}</h1>
              <BookingTypeBadge type={booking.booking_type} />
              {booking.redemo_from ? <RedemoBadge /> : null}
              <BookingStateBadge booking={booking} />
              <TutorStatus booking={booking} />
            </div>
            <p className="text-muted-foreground mt-1 flex flex-wrap gap-x-3 gap-y-1 text-sm">
              {booking.grade ? <span>{booking.grade}</span> : null}
              {lead.syllabus ? <span>{lead.syllabus}</span> : null}
              <span>Parent: {booking.parent_name}</span>
              <span className="tabular-nums">{booking.phone}</span>
            </p>
            <p className="mt-0.5 flex flex-wrap gap-x-3 gap-y-1 text-sm">
              <span className="text-muted-foreground">
                Booking ID: <span className="font-mono">{booking.id.slice(0, 8)}</span>
              </span>
              <span className="font-medium">{slotLabel(booking.slot)}</span>
            </p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2 lg:justify-end">
          {links ? (
            <>
              <Button variant="outline" size="sm" asChild>
                <a href={links.tel}>
                  <PhoneIcon />
                  Call
                </a>
              </Button>
              <Button variant="outline" size="sm" asChild>
                <a href={links.whatsapp} target="_blank" rel="noopener noreferrer">
                  <MessageCircleIcon />
                  WhatsApp
                </a>
              </Button>
            </>
          ) : null}
          {actions}
        </div>
      </div>
      <div className="flex flex-col gap-2 sm:pl-18">
        <Facts booking={booking} />
        <Notes booking={booking} onOpenBooking={onOpenBooking} onOpenRedemo={onOpenRedemo} />
      </div>
    </div>
  );
}
