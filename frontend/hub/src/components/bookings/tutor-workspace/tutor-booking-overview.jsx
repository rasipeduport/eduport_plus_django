import {
  AlertCircleIcon,
  CircleSlashIcon,
  ClipboardListIcon,
  ClockIcon,
  FileTextIcon,
  GraduationCapIcon,
  LockIcon,
  PlayCircleIcon,
  RotateCcwIcon,
  UserRoundIcon,
} from 'lucide-react';

import { Panel } from '@/components/dashboard/dashboard-primitives';
import { EnquiryStatusBadge } from '@/components/enquiries/enquiry-badges';
import { StartBookingButton } from '@/components/bookings/start-booking-button';
import { JourneyCard } from '@/components/bookings/workspace/booking-overview';
import { TutorReportLink } from '@/components/reports/tutor-report-link';
import { bookingTypeLabel, formatDay, slotLabel } from '@/lib/enquiries';
import { istMoment } from '@/lib/communications';
import { reportState, reportWords } from '@/lib/reports';
import { cn } from '@/lib/utils';

function Field({ label, children }) {
  return (
    <div className="grid grid-cols-[7.5rem_1fr] gap-3 py-2 text-sm first:pt-0 last:pb-0">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="min-w-0 font-medium break-words">{children || <span className="text-muted-foreground">—</span>}</dd>
    </div>
  );
}

// What the tutor's API withholds: the parent's contact stays with the BDE and the administrators.
const NOT_SHARED = <span className="text-muted-foreground font-normal">Not shared with tutors</span>;

const TONES = {
  info: { className: 'border-info/20 bg-info/5', iconClassName: 'text-info' },
  success: { className: 'border-success/20 bg-success/5', iconClassName: 'text-success' },
  warning: { className: 'border-warning/25 bg-warning/5', iconClassName: 'text-warning' },
  muted: { className: 'bg-muted/50', iconClassName: 'text-muted-foreground' },
};

/**
 * What the class needs from the tutor now, by where it stands with its report
 * (lib/reports reportState) -- never by the slot's clock alone: a class
 * counts as taught only once its tutor starts it, and only then can its
 * feedback or results be written.
 */
function nextStep(booking) {
  const words = reportWords(booking.booking_type);
  const kind = bookingTypeLabel(booking.booking_type).toLowerCase();
  switch (reportState(booking).key) {
    case 'upcoming':
      return {
        tone: 'info',
        icon: ClockIcon,
        title: booking.start_opens_at ? `Start opens ${istMoment(booking.start_opens_at)}` : 'Start opens five minutes before the class',
        text: `Start the ${kind} here when it begins: it opens Google Meet and records the start, which the ${words.noun} needs.`,
      };
    case 'ready':
      return {
        tone: 'info',
        icon: PlayCircleIcon,
        title: `You can start the ${kind} now`,
        text: `Starting opens Google Meet and records the start, which the ${words.noun} needs.`,
        start: true,
      };
    case 'late':
      return {
        tone: 'warning',
        icon: AlertCircleIcon,
        title: 'The scheduled time has passed',
        text: `Start the ${kind} now. Without a start before the slot ends, no ${words.noun} can be written.`,
        start: true,
      };
    case 'in_progress':
      return {
        tone: 'info',
        icon: PlayCircleIcon,
        title: `${bookingTypeLabel(booking.booking_type)} in progress`,
        text: `You started it ${istMoment(booking.started_at)}. ${words.write} once you have taught it.`,
        report: true,
      };
    case 'report_due':
      return {
        tone: 'warning',
        icon: FileTextIcon,
        title: `${words.tab} due`,
        text: `The ${kind} is over and its ${words.noun} is not in yet.`,
        report: true,
      };
    case 'completed':
      // Nothing left to do: the feedback or results, their versions and their editing are the Feedback / Results tab's.
      return null;
    case 'not_started':
      return {
        tone: 'muted',
        icon: CircleSlashIcon,
        title: 'Not started',
        text: `The slot ended without the ${kind} being started, so no ${words.noun} can be written. Speak to an administrator if it was taught.`,
      };
    case 'cancelled':
      return { tone: 'muted', icon: CircleSlashIcon, title: 'Cancelled', text: 'There is no class to teach.' };
    default:
      return {
        tone: 'muted',
        icon: CircleSlashIcon,
        title: 'Moved to another slot',
        text: `This booking takes no ${words.noun}: it belongs to the booking that replaced it.`,
      };
  }
}

/** What to do next with the booking (nextStep), with the one action that does it -- nothing once it is completed. */
function NextStep({ booking, onStarted, onRefresh, reportState: linkState }) {
  const step = nextStep(booking);
  if (!step) return null;
  const tone = TONES[step.tone];
  let action = null;
  if (step.start) action = <StartBookingButton booking={booking} onStarted={onStarted} onRefresh={onRefresh} />;
  else if (step.report) action = <TutorReportLink booking={booking} state={linkState} />;
  return (
    <section
      aria-label="Next step"
      className={cn('flex flex-wrap items-center gap-x-4 gap-y-3 rounded-xl border px-4 py-3', tone.className)}
    >
      <step.icon className={cn('size-5 shrink-0', tone.iconClassName)} aria-hidden="true" />
      <div className="min-w-0 flex-1 basis-60">
        <p className="text-sm font-medium">{step.title}</p>
        <p className="text-muted-foreground mt-0.5 text-sm">{step.text}</p>
      </div>
      {action ? <div className="flex shrink-0 flex-wrap gap-2">{action}</div> : null}
    </section>
  );
}

/**
 * Why this Re-Demo is taught (the API's `redemo`, backend bookings.redemos),
 * each labelled by where it comes from: the reason given when it was
 * requested (the BDE's, often the parent's words), the administrators'
 * remarks from scheduling it, and the Demo it follows -- when it was and who
 * taught it.
 */
function RedemoPanel({ redemo }) {
  const which = redemo.number > 1 ? `Re-Demo ${redemo.number}` : 'Re-Demo';
  return (
    <Panel icon={RotateCcwIcon} title={which} subtitle="Why this demo is taught again">
      <dl className="divide-y">
        <Field label="Request reason">
          <span className="flex flex-col">
            <span className="whitespace-pre-wrap">{redemo.reason}</span>
            <span className="text-muted-foreground text-xs font-normal">From the Re-Demo request (BDE / parent)</span>
          </span>
        </Field>
        <Field label="Admin remarks">
          <span className="flex flex-col">
            {redemo.admin_remarks ? (
              <span className="whitespace-pre-wrap">{redemo.admin_remarks}</span>
            ) : (
              <span className="text-muted-foreground">No remarks</span>
            )}
            <span className="text-muted-foreground text-xs font-normal">From the administrator who scheduled it</span>
          </span>
        </Field>
        <Field label="Follows the Demo">
          <span className="flex flex-col">
            <span>{slotLabel(redemo.original.slot)}</span>
            <span className="text-muted-foreground text-xs font-normal">
              {redemo.original.tutor ? `Taught by ${redemo.original.tutor.full_name}` : 'No tutor recorded'}
            </span>
          </span>
        </Field>
      </dl>
    </Panel>
  );
}

/**
 * The booking at a glance, for its tutor, laid out as the administrators' and
 * the BDE's workspaces lay out theirs: what to do next (NextStep), then the
 * parent, the student and the enquiry side by side, and the enquiry's journey
 * under them (the administrators' JourneyCard, from the API's `enquiry`), and
 * for a Re-Demo why it is taught again. Of the parent only the country: the
 * tutor's API carries no contact. The session, its Meet room and its feedback
 * or results are the header's and their own tab's. `reportState` is the report
 * page's way back.
 */
export function TutorBookingOverview({ booking, onStarted, onRefresh, reportState: linkState }) {
  const enquiry = booking.enquiry;
  const next = enquiry?.next_booking;

  return (
    <div className="flex flex-col gap-4">
      <NextStep
        booking={booking}
        onStarted={onStarted}
        onRefresh={onRefresh}
        reportState={linkState}
      />
      <div className="grid min-w-0 gap-4 lg:grid-cols-3">
        <Panel icon={UserRoundIcon} title="Parent">
          <dl className="divide-y">
            <Field label="Name">{NOT_SHARED}</Field>
            <Field label="Phone">{NOT_SHARED}</Field>
            <Field label="Email">{NOT_SHARED}</Field>
            <Field label="Country">{booking.country}</Field>
          </dl>
        </Panel>
        <Panel icon={GraduationCapIcon} title="Student">
          <dl className="divide-y">
            <Field label="Name">{booking.student_name}</Field>
            <Field label="Class">{booking.grade}</Field>
            <Field label="School">{booking.school_name}</Field>
            <Field label="Syllabus">{booking.syllabus}</Field>
          </dl>
        </Panel>
        <Panel icon={ClipboardListIcon} title="Enquiry">
          <dl className="divide-y">
            <Field label="Original enquiry source">{enquiry?.source_label}</Field>
            <Field label="Status">{enquiry ? <EnquiryStatusBadge enquiry={enquiry} /> : null}</Field>
            <Field label="Next booking">{next ? slotLabel(next) : null}</Field>
            <Field label="First received">{enquiry ? formatDay(enquiry.created_at) : null}</Field>
          </dl>
        </Panel>
      </div>
      {enquiry ? <JourneyCard lead={enquiry} /> : null}
      {booking.redemo ? <RedemoPanel redemo={booking.redemo} /> : null}
    </div>
  );
}

/**
 * What the tutor is told about the student to teach them: their name, class,
 * syllabus, school and country -- the child's details from the booking, and
 * all the tutor's API carries. The parent's contact stays with the BDE and the
 * administrators.
 */
export function TutorStudentInfo({ booking }) {
  return (
    <div className="grid min-w-0 gap-4 lg:grid-cols-3">
      <Panel icon={GraduationCapIcon} title="Student" subtitle="As given when the session was booked" className="lg:col-span-2">
        <dl className="divide-y">
          <Field label="Name">{booking.student_name}</Field>
          <Field label="Class">{booking.grade}</Field>
          <Field label="Syllabus">{booking.syllabus}</Field>
          <Field label="School">{booking.school_name}</Field>
          <Field label="Country">{booking.country}</Field>
        </dl>
      </Panel>
      <Panel icon={LockIcon} title="Shared with tutors">
        <p className="text-muted-foreground text-sm">
          Tutors see the student&apos;s academic details only. The parent&apos;s name and phone number stay with the BDE
          and the administrators: ask them if you need the family contacted.
        </p>
      </Panel>
    </div>
  );
}
