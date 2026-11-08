import { ClipboardListIcon, GraduationCapIcon, RouteIcon, UserRoundIcon } from 'lucide-react';

import { Panel } from '@/components/dashboard/dashboard-primitives';
import { redemoStatus } from '@/lib/bookings';
import { istMoment } from '@/lib/communications';
import { bookingTypeLabel, formatDay, slotLabel } from '@/lib/enquiries';
import { cn } from '@/lib/utils';

function Field({ label, children }) {
  return (
    <div className="grid grid-cols-[8rem_1fr] gap-3 py-2 text-sm first:pt-0 last:pb-0">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="min-w-0 font-medium break-words">{children || <span className="text-muted-foreground">—</span>}</dd>
    </div>
  );
}

const TYPE_TONE = { DEMO: 'demo', DIAGNOSTIC: 'diagnostic' };
const CONDUCTED = new Set(['COMPLETED', 'REDEMO_REQUIRED']);

/**
 * How the enquiry has moved, oldest first, from what the enquiry already
 * carries: when it reached Eduport Plus and when it became the BDE's, then
 * each booking -- booked, started, completed, cancelled or moved, and any
 * Re-Demo asked for -- and the booking still to come. A step the API gives no
 * moment for (a completion, a move) is shown without one. `ownerTitle` names
 * the step where a BDE took it ("Became yours", for that BDE). The
 * administrators' booking workspace draws the same steps on its own timeline.
 */
export function enquiryJourney(enquiry, ownerTitle = 'Became yours') {
  const steps = [{ key: 'received', at: enquiry.created_at, title: 'Enquiry received', detail: `Original enquiry source: ${enquiry.source_label}` }];
  const received = new Date(enquiry.created_at).getTime();
  if (enquiry.added_at && Math.abs(new Date(enquiry.added_at).getTime() - received) > 60_000) {
    steps.push({ key: 'yours', at: enquiry.added_at, title: ownerTitle });
  }
  const bookings = [...(enquiry.bookings ?? [])].sort((a, b) => new Date(a.booked_at) - new Date(b.booked_at));
  for (const booking of bookings) {
    const type = bookingTypeLabel(booking.booking_type);
    const tone = TYPE_TONE[booking.booking_type];
    steps.push({
      key: `${booking.id}-booked`,
      at: booking.booked_at,
      title: booking.redemo_from ? `${type} booked (Re-Demo)` : `${type} booked`,
      detail: `For ${slotLabel(booking)}`,
      tone,
    });
    if (booking.started_at) steps.push({ key: `${booking.id}-started`, at: booking.started_at, title: `${type} started`, tone });
    if (CONDUCTED.has(booking.status)) {
      steps.push({
        key: `${booking.id}-completed`,
        title: `${type} completed`,
        detail: booking.tutor ? `With ${booking.tutor.full_name}` : null,
        tone: 'success',
      });
    }
    if (booking.redemo) {
      steps.push({ key: `${booking.id}-redemo`, title: 'Re-Demo asked for', detail: redemoStatus(booking.redemo.status).label, tone: 'warning' });
    }
    if (booking.status === 'CANCELLED') {
      steps.push({ key: `${booking.id}-cancelled`, at: booking.cancelled_at, title: `${type} cancelled`, tone: 'muted' });
    }
    if (booking.status === 'RESCHEDULED') {
      steps.push({ key: `${booking.id}-moved`, title: `${type} moved to another slot`, tone: 'muted' });
    }
  }
  if (enquiry.next_booking) {
    const next = enquiry.next_booking;
    steps.push({
      key: 'next',
      title: `Next: ${bookingTypeLabel(next.booking_type)}`,
      detail: slotLabel(next),
      tone: TYPE_TONE[next.booking_type],
      upcoming: true,
    });
  }
  return steps;
}

const DOT = {
  demo: 'bg-demo',
  diagnostic: 'bg-diagnostic',
  success: 'bg-success',
  warning: 'bg-warning',
  muted: 'bg-border',
};
const RING = { demo: 'ring-demo', diagnostic: 'ring-diagnostic' };

function Journey({ enquiry, className }) {
  const steps = enquiryJourney(enquiry);
  return (
    <Panel icon={RouteIcon} title="Enquiry journey" subtitle="From the first contact to the next booking, in Indian time (IST)" className={className}>
      <ol aria-label="Enquiry journey">
        {steps.map((step) => (
          <li key={step.key} className="group flex gap-3">
            <span className="flex flex-col items-center" aria-hidden="true">
              <span
                className={cn(
                  'mt-1.5 size-2.5 shrink-0 rounded-full',
                  step.upcoming ? cn('bg-background ring-2', RING[step.tone] ?? 'ring-muted-foreground') : DOT[step.tone] ?? 'bg-muted-foreground'
                )}
              />
              <span className="bg-border mt-1.5 w-px flex-1 group-last:hidden" />
            </span>
            <div className="min-w-0 flex-1 pb-4 group-last:pb-0">
              <p className={cn('text-sm font-medium', step.upcoming && 'text-muted-foreground')}>{step.title}</p>
              <p className="text-muted-foreground text-xs">
                {[step.detail, step.at ? istMoment(step.at) : null].filter(Boolean).join(' · ')}
              </p>
            </div>
          </li>
        ))}
      </ol>
    </Panel>
  );
}

/**
 * The enquiry at a glance: the parent, the student, where the enquiry stands
 * and how it got there. `onShowBooking(booking)` opens a booking in the
 * Bookings tab -- the next one, from here.
 */
export function EnquiryOverview({ enquiry, onShowBooking }) {
  const next = enquiry.next_booking;
  return (
    <div className="grid min-w-0 gap-4 lg:grid-cols-3">
      <Panel icon={UserRoundIcon} title="Parent">
        <dl className="divide-y">
          <Field label="Name">{enquiry.parent_name}</Field>
          <Field label="Phone">
            <span className="tabular-nums">{enquiry.phone}</span>
          </Field>
          <Field label="Email">{enquiry.parent_email}</Field>
          <Field label="Country">{enquiry.country}</Field>
        </dl>
      </Panel>
      <Panel icon={GraduationCapIcon} title="Student">
        <dl className="divide-y">
          <Field label="Name">{enquiry.student_name}</Field>
          <Field label="Class">{enquiry.grade}</Field>
          <Field label="School">{enquiry.school_name}</Field>
          <Field label="Syllabus">{enquiry.syllabus}</Field>
        </dl>
      </Panel>
      <Panel icon={ClipboardListIcon} title="Enquiry">
        <dl className="divide-y">
          <Field label="Original enquiry source">{enquiry.source_label}</Field>
          <Field label="Status">{enquiry.status_label}</Field>
          <Field label="Next booking">
            {next ? (
              <button type="button" className="text-link text-left font-medium hover:underline" onClick={() => onShowBooking(next)}>
                {slotLabel(next)}
              </button>
            ) : null}
          </Field>
          <Field label="Yours since">{formatDay(enquiry.added_at)}</Field>
          <Field label="First received">{formatDay(enquiry.created_at)}</Field>
        </dl>
      </Panel>
      <Journey enquiry={enquiry} className="lg:col-span-3" />
    </div>
  );
}
