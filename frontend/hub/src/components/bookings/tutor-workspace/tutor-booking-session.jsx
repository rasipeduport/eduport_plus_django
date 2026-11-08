import { useId } from 'react';
import { Link } from 'react-router-dom';
import { CalendarDaysIcon, FilePenLineIcon, FilePlus2Icon, PlayIcon } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Panel } from '@/components/dashboard/dashboard-primitives';
import { BookingTypeBadge } from '@/components/enquiries/enquiry-badges';
import { FeedbackBadge, RedemoBadge, ReportStateBadge } from '@/components/bookings/booking-badges';
import { JoinMeetButton } from '@/components/bookings/meet-link';
import { StartBookingButton } from '@/components/bookings/start-booking-button';
import { ResponsiveList } from '@/components/page/responsive-list';
import { startLabel } from '@/lib/bookings';
import { istMoment, istParts } from '@/lib/communications';
import { slotLabel } from '@/lib/enquiries';
import { reportActions, reportWords, tutorReportPagePath } from '@/lib/reports';

// The width the table needs; narrower areas show the card.
const MIN_TABLE_WIDTH = 760;

// A booked or completed booking has a class (to come, or taught); a cancelled or moved one has none.
const hasClass = (booking) => booking.status === 'BOOKED' || booking.status === 'COMPLETED';

function When({ booking }) {
  const ends = istParts(booking.slot.ends_at);
  return (
    <span className="flex flex-col">
      <span className="font-medium">{slotLabel(booking.slot)}</span>
      {ends ? <span className="text-muted-foreground text-xs">Ends {ends.time}</span> : null}
    </span>
  );
}

function Type({ booking }) {
  return (
    <span className="flex flex-wrap items-center gap-1.5">
      <BookingTypeBadge type={booking.booking_type} />
      {booking.redemo ? <RedemoBadge number={booking.redemo.number} /> : null}
    </span>
  );
}

function Status({ booking }) {
  return (
    <span className="flex flex-col items-start gap-1">
      <ReportStateBadge booking={booking} />
      {booking.started_at ? (
        <span className="text-muted-foreground text-xs">Started {istMoment(booking.started_at)}</span>
      ) : null}
    </span>
  );
}

function Meeting({ booking }) {
  if (!hasClass(booking)) return <span className="text-muted-foreground">—</span>;
  return <JoinMeetButton link={booking.tutor_meet_link} label={`Join the Google Meet for ${booking.student_name}`} />;
}

/** A Start that is not open yet: shown, disabled, with when the API says it opens. */
function StartNotYet({ booking }) {
  const hintId = useId();
  const opens = istMoment(booking.start_opens_at);
  return (
    <span className="flex flex-col items-start gap-1">
      <Button size="sm" disabled aria-describedby={hintId}>
        <PlayIcon className="size-4" />
        {startLabel(booking.booking_type)}
      </Button>
      <span id={hintId} className="text-muted-foreground text-xs">
        {opens ? `Opens ${opens}` : booking.start_refusal.message}
      </span>
    </span>
  );
}

/**
 * What the tutor can do with the class now, every rule the API's: Start Demo /
 * Start Diagnostic while it offers the start (`actions.start`, from five
 * minutes before the class until its slot ends), shown disabled until then;
 * once started, Submit Feedback / Enter Results on the report page; once the
 * report is in, where it stands and Edit -- never a second start. Otherwise
 * why nothing can be done (the API's `start_refusal`).
 */
function SessionAction({ booking, onStarted, onRefresh, reportState }) {
  const report = reportActions(booking);
  const words = reportWords(booking.booking_type);
  const reportPath = tutorReportPagePath(booking.booking_type, booking.id);

  if (booking.actions?.start) return <StartBookingButton booking={booking} onStarted={onStarted} onRefresh={onRefresh} />;
  if (report.write) {
    const label = words.write;
    return (
      <Button size="sm" asChild>
        <Link to={reportPath} state={reportState} aria-label={`${label} for ${booking.student_name}`}>
          <FilePlus2Icon className="size-4" />
          {label}
        </Link>
      </Button>
    );
  }
  if (report.edit) {
    return (
      <span className="flex flex-wrap items-center gap-2">
        <FeedbackBadge booking={booking} />
        <Button size="sm" variant="outline" asChild>
          <Link to={reportPath} state={reportState} aria-label={`${words.edit} for ${booking.student_name}`}>
            <FilePenLineIcon className="size-4" />
            {words.edit}
          </Link>
        </Button>
      </span>
    );
  }
  if (booking.start_refusal?.code === 'START_TOO_EARLY') return <StartNotYet booking={booking} />;
  return <span className="text-muted-foreground text-sm">{booking.start_refusal?.message ?? '—'}</span>;
}

/**
 * The booking's session, for its tutor to join and teach (the workspace's
 * Session tab), laid out as the other workspaces' Bookings tab lays out
 * theirs: when (IST) and until when, its type, where it stands (and when it
 * was started), its Google Meet room (Join Meet, the API's link, or plainly
 * No Meet link) and what to do now (SessionAction). A table where it fits, a
 * card on a phone or a narrow screen. `onStarted` gets the booking as the
 * Start answers it; `reportState` is the report page's way back.
 */
export function TutorBookingSession({ booking, onStarted, onRefresh, reportState }) {
  const action = (entry) => <SessionAction booking={entry} onStarted={onStarted} onRefresh={onRefresh} reportState={reportState} />;
  const columns = [
    { key: 'when', header: 'Date & Time (IST)', className: 'whitespace-nowrap', cell: (entry) => <When booking={entry} /> },
    { key: 'type', header: 'Booking Type', cell: (entry) => <Type booking={entry} /> },
    { key: 'status', header: 'Status', cell: (entry) => <Status booking={entry} /> },
    { key: 'meeting', header: 'Meeting', cell: (entry) => <Meeting booking={entry} /> },
    { key: 'action', header: 'Action', className: 'min-w-48 whitespace-normal', cell: action },
  ];

  const renderCard = (entry) => (
    <article className="bg-card flex h-full flex-col gap-3 rounded-xl border p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <When booking={entry} />
        <Type booking={entry} />
      </div>
      <Status booking={entry} />
      <div className="grid gap-3 text-sm sm:grid-cols-2">
        <div className="min-w-0">
          <p className="text-muted-foreground mb-1 text-xs">Meeting</p>
          <Meeting booking={entry} />
        </div>
        <div className="min-w-0">
          <p className="text-muted-foreground mb-1 text-xs">Action</p>
          {action(entry)}
        </div>
      </div>
    </article>
  );

  return (
    <Panel icon={CalendarDaysIcon} title="Bookings" subtitle="Demo classes and diagnostic tests, in Indian time (IST)">
      <ResponsiveList label="Bookings" columns={columns} rows={[booking]} minTableWidth={MIN_TABLE_WIDTH} renderCard={renderCard} />
    </Panel>
  );
}
