import { ArrowRightLeftIcon, CalendarClockIcon, CalendarX2Icon, MessageCircleIcon, RotateCcwIcon } from 'lucide-react';

import { Avatar, AvatarFallback } from '@/components/ui/avatar';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { BookingTypeBadge } from '@/components/enquiries/enquiry-badges';
import { BookingStateBadge, RedemoBadge, RedemoStatusBadge } from '@/components/bookings/booking-badges';
import { StudentTimeLine } from '@/components/bookings/student-time';
import { formatDay, phoneLinks, slotLabel } from '@/lib/enquiries';
import { cn, getInitials } from '@/lib/utils';

/** A booking's id as the BDE's booking sheet shows it: its first eight characters, upper-cased -- the whole id on hover. */
const shortId = (id) => String(id).slice(0, 8).toUpperCase();

/** Whether the booking has its tutor: who, or that a booking still to come needs one. */
function TutorStatus({ booking }) {
  if (booking.tutor) return <Badge variant="outline">Tutor: {booking.tutor.full_name}</Badge>;
  if (booking.status === 'BOOKED' && !booking.slot?.ended) return <Badge variant="warning">Needs a tutor</Badge>;
  return null;
}

/** One detail of the booking, its label muted beside its value: "Booking ID 7F4D83DF". */
function Detail({ label, children }) {
  return (
    <div className="flex min-w-0 items-baseline gap-1.5">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="min-w-0 font-medium break-words">
        {children || <span className="text-muted-foreground font-normal">—</span>}
      </dd>
    </div>
  );
}

/**
 * The booking's details, compact, under its slot: its own reference (Booking
 * ID, every booking its own) and, for a Demo booked with a Demo invitation,
 * who sent the invitation and the Diagnostic it came from. Nothing else: how
 * the enquiry first came in is the Enquiry card's, when the booking was made
 * is on All Bookings and its timeline, its start on Tutor & Assignment.
 */
function BookingDetails({ booking }) {
  // A Demo invitation's booking: a BDE handoff that is not a Re-Demo an administrator scheduled.
  const invited = booking.channel === 'BDE_HANDOFF' && !booking.redemo_from;
  return (
    <dl className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 text-sm">
      <Detail label="Booking ID">
        <span className="font-mono" title={booking.id}>
          {shortId(booking.id)}
        </span>
      </Detail>
      {invited ? <Detail label="Invited by">{booking.created_by?.full_name}</Detail> : null}
      {booking.invited_from ? <Detail label="From Diagnostic">{slotLabel(booking.invited_from.slot)}</Detail> : null}
    </dl>
  );
}

/** A link-like button inside a line of text. */
function InlineLink({ onClick, label, children }) {
  return (
    <Button variant="link" size="sm" className="h-auto p-0" onClick={onClick} aria-label={label}>
      {children}
    </Button>
  );
}

/** A line about what happened to the booking -- moved, cancelled, sent for a Re-Demo -- with its icon. */
function Note({ icon: Icon, children }) {
  return (
    <li className="flex items-start gap-2">
      <Icon className="text-muted-foreground mt-0.5 size-4 shrink-0" aria-hidden="true" />
      <span className="flex min-w-0 flex-wrap items-center gap-x-1.5 gap-y-1">{children}</span>
    </li>
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
  // The Re-Demo this Demo was sent for: its report and history stay, the new Demo is booked separately --
  // reached from here, as is the request (a closed one too: its Demo reads Completed again).
  if (booking.redemo_request) {
    const redemoBooking = booking.redemo_request.booking;
    notes.push(
      <Note key="redemo" icon={RotateCcwIcon}>
        <span>Re-Demo</span>
        <RedemoStatusBadge status={booking.redemo_request.status} />
        <span>
          requested on {formatDay(booking.redemo_request.requested_at)} by{' '}
          {booking.redemo_request.requested_by?.full_name ?? '—'}
        </span>
        {redemoBooking && redemoBooking.status !== 'CANCELLED' ? (
          <>
            <span className="text-muted-foreground">·</span>
            <span>Booked for {slotLabel(redemoBooking.slot)}</span>
            <InlineLink onClick={() => onOpenBooking(redemoBooking.id)} label="Open the Re-Demo booking">
              Open Re-Demo
            </InlineLink>
          </>
        ) : null}
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
  return notes.length ? <ul className="flex flex-col gap-1.5 text-sm sm:pl-18">{notes}</ul> : null;
}

/**
 * Who the booking is for and how to reach them, as the BDE's enquiry
 * workspace heads an enquiry: by the student's name, the booking's type,
 * where it stands and its tutor; under it the class and syllabus, the parent
 * and their number, the booking's slot (IST) -- with the student's own time
 * under it where that reads differently -- and its details
 * (BookingDetails); WhatsApp and `actions` (the booking's own, which the
 * workspace offers only as its state and the caller's permissions allow) on
 * the right; then what has happened to the booking (Notes). A booking of its
 * chain opens in its own workspace (`onOpenBooking(id)`), and so does a
 * Re-Demo request (`onOpenRedemo(id)`).
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
            <p className="mt-1.5 flex items-center gap-1.5 text-sm font-medium">
              <CalendarClockIcon className="text-muted-foreground size-4 shrink-0" aria-hidden="true" />
              {slotLabel(booking.slot)}
            </p>
            {/* Under the slot's text, past its icon. */}
            <StudentTimeLine startsAt={booking.slot?.starts_at} timezone={booking.student_timezone} className="mt-0.5 pl-5.5" />
            <BookingDetails booking={booking} />
          </div>
        </div>
        <div className={cn('flex flex-wrap items-center gap-2 lg:justify-end', !links && !actions && 'hidden')}>
          {links ? (
            <Button variant="outline" size="sm" asChild>
              <a href={links.whatsapp} target="_blank" rel="noopener noreferrer">
                <MessageCircleIcon />
                WhatsApp
              </a>
            </Button>
          ) : null}
          {actions}
        </div>
      </div>
      <Notes booking={booking} onOpenBooking={onOpenBooking} onOpenRedemo={onOpenRedemo} />
    </div>
  );
}
