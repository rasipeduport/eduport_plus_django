import { ArrowRightLeftIcon, CalendarClockIcon, CalendarX2Icon } from 'lucide-react';

import { Avatar, AvatarFallback } from '@/components/ui/avatar';
import { BookingTypeBadge } from '@/components/enquiries/enquiry-badges';
import { FeedbackBadge, RedemoBadge, ReportStateBadge } from '@/components/bookings/booking-badges';
import { JoinMeetButton } from '@/components/bookings/meet-link';
import { StartBookingButton } from '@/components/bookings/start-booking-button';
import { TutorReportLink } from '@/components/reports/tutor-report-link';
import { isJoinable } from '@/lib/bookings';
import { slotLabel } from '@/lib/enquiries';
import { reportWords } from '@/lib/reports';
import { getInitials } from '@/lib/utils';

/** A booking's id as the other workspaces show it: its first eight characters, upper-cased -- the whole id on hover. */
const shortId = (id) => String(id).slice(0, 8).toUpperCase();

function Detail({ label, children }) {
  return (
    <div className="flex min-w-0 items-center gap-1.5">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="min-w-0 font-medium break-words">{children}</dd>
    </div>
  );
}

/**
 * The booking a tutor is assigned, as its workspace heads it: the student by
 * name, the booking's type (a Re-Demo marked as one) and where it stands as a
 * class; under it the class, syllabus and school, the slot in Indian time,
 * the Booking ID and where its feedback or results stand. On the right what
 * the class needs now: Join Meet (the booking's Google Meet room as the API
 * gives it) while it has a class, to come or taught, or plainly No Meet link
 * without one; Start Demo / Start Diagnostic while the API offers it (which
 * opens Meet too and records the start the report needs); and Submit Feedback /
 * Enter Results, or Edit, once the report can be written (`reportState`, the
 * report page's way back). Nothing of the parent: the tutor's API carries
 * none.
 */
export function TutorBookingHeader({ booking, onStarted, onRefresh, reportState }) {
  const words = reportWords(booking.booking_type);
  const canJoin = isJoinable(booking);
  // A booked or completed booking has a class (to come, or taught); a cancelled or moved one has none.
  const hasClass = booking.status === 'BOOKED' || booking.status === 'COMPLETED';
  // The one primary action: Start while it is offered, else the report, else joining the class.
  const startOffered = Boolean(booking.actions?.start);
  const writeOffered = booking.status === 'BOOKED' && Boolean(booking.started_at) && !booking.has_report;

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
              {booking.redemo ? <RedemoBadge number={booking.redemo.number} /> : <BookingTypeBadge type={booking.booking_type} />}
              <ReportStateBadge booking={booking} />
            </div>
            <p className="text-muted-foreground mt-1 flex flex-wrap gap-x-3 gap-y-1 text-sm">
              {booking.grade ? <span>{booking.grade}</span> : null}
              {booking.syllabus ? <span>{booking.syllabus}</span> : null}
              {booking.school_name ? <span>{booking.school_name}</span> : null}
            </p>
            <p className="mt-1.5 flex items-center gap-1.5 text-sm font-medium">
              <CalendarClockIcon className="text-muted-foreground size-4 shrink-0" aria-hidden="true" />
              {slotLabel(booking.slot)}
            </p>
            <dl className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 text-sm">
              <Detail label="Booking ID">
                <span className="font-mono" title={booking.id}>
                  {shortId(booking.id)}
                </span>
              </Detail>
              <Detail label={words.tab}>
                <FeedbackBadge booking={booking} />
              </Detail>
            </dl>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2 lg:justify-end">
          {hasClass ? (
            <JoinMeetButton
              link={booking.tutor_meet_link}
              label={`Join the Google Meet for ${booking.student_name}`}
              variant={canJoin && !startOffered && !writeOffered ? 'default' : 'outline'}
            />
          ) : null}
          <StartBookingButton booking={booking} onStarted={onStarted} onRefresh={onRefresh} />
          <TutorReportLink booking={booking} state={reportState} />
        </div>
      </div>
      {booking.status === 'CANCELLED' || booking.status === 'RESCHEDULED' ? (
        <p className="bg-muted text-muted-foreground flex items-start gap-2 rounded-lg px-3 py-2 text-sm">
          {booking.status === 'CANCELLED' ? (
            <CalendarX2Icon className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
          ) : (
            <ArrowRightLeftIcon className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
          )}
          {booking.status === 'CANCELLED'
            ? 'This booking was cancelled. There is no class to teach.'
            : 'This booking was moved to another slot. If you teach the new one, it is listed separately.'}
        </p>
      ) : null}
    </div>
  );
}
