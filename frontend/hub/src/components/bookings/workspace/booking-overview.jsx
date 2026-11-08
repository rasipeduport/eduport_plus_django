import { Link } from 'react-router-dom';
import {
  CalendarDaysIcon,
  CheckIcon,
  ClipboardListIcon,
  GraduationCapIcon,
  MinusIcon,
  RotateCcwIcon,
  RouteIcon,
  UserRoundIcon,
} from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { Panel, PanelEmpty } from '@/components/dashboard/dashboard-primitives';
import { BookingTypeBadge, EnquiryStatusBadge } from '@/components/enquiries/enquiry-badges';
import { enquiryJourney } from '@/components/enquiries/workspace/enquiry-overview';
import { ErrorState } from '@/components/page/states';
import { bookingState } from '@/lib/bookings';
import { formatDay, slotLabel, sourceLabel } from '@/lib/enquiries';
import { istMoment } from '@/lib/communications';
import { cn } from '@/lib/utils';
import { RedemoBadge } from '../booking-badges';

function Field({ label, children }) {
  return (
    <div className="grid grid-cols-[7.5rem_1fr] gap-3 py-2 text-sm first:pt-0 last:pb-0">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="min-w-0 font-medium break-words">{children || <span className="text-muted-foreground">—</span>}</dd>
    </div>
  );
}

/** A value the enquiry's own record holds: a placeholder while it loads, a dash when it has none. */
function FromLead({ loading, children }) {
  if (loading) return <Skeleton className="h-4 w-28" aria-hidden="true" />;
  return children || <span className="text-muted-foreground">—</span>;
}

/**
 * Where the enquiry stands and who has it: from the lead in full (`lead`, GET
 * /api/leads/<id>/) for holders of accounts.view_all_leads -- its original
 * source (how the parent first reached Eduport Plus, a BDE's link named as
 * such: the lead's own source_label, which a BDE's enquiry shows too; how this
 * booking came in is the header's Came in), status, owner BDE (and since when,
 * when they took it later than it came in) and when it first came in, with the
 * lead to open -- each a placeholder until the lead arrives. Without the lead
 * to read, what the booking itself says of its enquiry (its source and BDE).
 */
function EnquiryCard({ booking, lead, loading, showLead }) {
  const brief = booking.lead ?? {};
  const owner = lead ? lead.owner : brief.owner_bde;
  const ownedLater =
    lead?.owner && lead.added_at && Math.abs(new Date(lead.added_at) - new Date(lead.created_at)) > 60_000;
  return (
    <Panel
      icon={ClipboardListIcon}
      title="Enquiry"
      action={
        showLead ? (
          <Button variant="outline" size="sm" asChild>
            <Link to={`/leads/${brief.id}`}>Open lead</Link>
          </Button>
        ) : null
      }
    >
      <dl className="divide-y">
        {/* How the parent first reached Eduport Plus -- never how this booking came in (the header's Came in). */}
        <Field label="Original enquiry source">
          <FromLead loading={loading}>{lead ? lead.source_label : showLead ? null : sourceLabel(brief.source)}</FromLead>
        </Field>
        <Field label="Status">
          <FromLead loading={loading}>{lead ? <EnquiryStatusBadge enquiry={lead} /> : null}</FromLead>
        </Field>
        <Field label="Owner">
          {owner ? (
            <span className="flex flex-col">
              <span>{owner.full_name}</span>
              {ownedLater ? (
                <span className="text-muted-foreground text-xs font-normal">Since {formatDay(lead.added_at)}</span>
              ) : null}
            </span>
          ) : (
            <span className="text-muted-foreground">Unassigned</span>
          )}
        </Field>
        <Field label="First received">
          <FromLead loading={loading}>{lead ? formatDay(lead.created_at) : null}</FromLead>
        </Field>
      </dl>
    </Panel>
  );
}

// A step's mark on the timeline, by what it was: a cancellation or a move, a
// Re-Demo asked for, or anything else that has happened. The step to come is
// an open ring in its booking type's colour.
const RINGS = { demo: 'border-demo', diagnostic: 'border-diagnostic' };

function StepMark({ step, latest }) {
  if (step.upcoming) {
    return <span className={cn('size-5 shrink-0 rounded-full border-2 bg-background', RINGS[step.tone] ?? 'border-primary')} />;
  }
  let Icon = CheckIcon;
  let fill = latest ? 'bg-primary text-primary-foreground' : 'bg-success text-success-foreground';
  if (step.tone === 'muted') {
    Icon = MinusIcon;
    fill = 'bg-muted-foreground text-background';
  } else if (step.tone === 'warning') {
    Icon = RotateCcwIcon;
    fill = 'bg-warning text-warning-foreground';
  }
  return (
    <span
      className={cn(
        'flex size-5 shrink-0 items-center justify-center rounded-full',
        fill,
        latest && 'ring-primary/20 ring-4'
      )}
    >
      <Icon className="size-3" strokeWidth={3} />
    </span>
  );
}

/**
 * How the enquiry has moved, on one timeline: the steps a BDE's enquiry
 * workspace shows (enquiryJourney -- from the first contact, through each
 * booking made, started, completed, cancelled, moved or sent for a Re-Demo, to
 * the booking still to come), each with what it was and when (IST) where the
 * API gives a moment. What has happened is checked off, the latest of it
 * marked; the booking to come is an open ring.
 */
function JourneyCard({ lead }) {
  const owner = lead.owner;
  const steps = enquiryJourney(lead, owner ? `Assigned to ${owner.full_name}` : 'Assigned to a BDE');
  // The last step that has happened (the booking to come, if any, follows it).
  const latest = steps.reduce((last, step, index) => (step.upcoming ? last : index), -1);
  return (
    <Panel icon={RouteIcon} title="Enquiry Journey" subtitle="From the first contact to the next booking, in Indian time (IST)">
      <ol aria-label="Enquiry journey">
        {steps.map((step, index) => {
          const isLatest = index === latest;
          return (
            <li key={step.key} className="group flex gap-3" aria-current={isLatest ? 'step' : undefined}>
              <span className="flex flex-col items-center pt-0.5" aria-hidden="true">
                <StepMark step={step} latest={isLatest} />
                <span className="bg-border mt-1 w-px flex-1 group-last:hidden" />
              </span>
              <div className="min-w-0 flex-1 pb-5 group-last:pb-0">
                <p className="flex flex-wrap items-center gap-2">
                  <span className={cn('text-sm font-medium', step.upcoming && 'text-muted-foreground')}>{step.title}</span>
                  {isLatest ? <Badge variant="secondary">Latest</Badge> : null}
                  {step.upcoming ? <Badge variant="outline">Upcoming</Badge> : null}
                </p>
                <p className="text-muted-foreground text-xs">
                  {[step.detail, step.at ? istMoment(step.at) : null].filter(Boolean).join(' · ')}
                </p>
              </div>
            </li>
          );
        })}
      </ol>
    </Panel>
  );
}

/** Who teaches a booking of the list, or that a booking still to come has nobody yet. */
function tutorText(entry) {
  if (entry.tutor) return `Tutor: ${entry.tutor.full_name}`;
  return entry.status === 'BOOKED' && !entry.ended ? 'Unassigned' : 'No tutor';
}

/**
 * Every Demo and Diagnostic booking made for the child (the lead's bookings,
 * latest slot first, as the API lists them): its type, slot (IST), where it
 * stands, who teaches it and when it was booked, each opening in its own
 * workspace (`onOpenBooking(entry)`) -- this one marked instead.
 */
function AllBookingsCard({ lead, bookingId, onOpenBooking }) {
  const bookings = lead.bookings ?? [];
  return (
    <Panel icon={CalendarDaysIcon} title="All Bookings" subtitle="Every booking made for this child, in Indian time (IST)">
      {bookings.length === 0 ? (
        <PanelEmpty icon={CalendarDaysIcon} message="No bookings yet" />
      ) : (
        <ol aria-label="All bookings" className="flex flex-col gap-1">
          {bookings.map((entry) => {
            const state = bookingState(entry);
            const current = entry.id === bookingId;
            const tutor = tutorText(entry);
            return (
              <li
                key={entry.id}
                aria-current={current ? 'true' : undefined}
                className={cn(
                  '-mx-2 flex flex-wrap items-center gap-x-3 gap-y-1.5 rounded-lg px-2 py-2 md:grid md:grid-cols-[8.5rem_13rem_minmax(0,10rem)_minmax(0,1fr)_auto]',
                  current && 'bg-muted/60'
                )}
              >
                <span>
                  <BookingTypeBadge type={entry.booking_type} />
                </span>
                <span className="text-sm font-medium whitespace-nowrap">{slotLabel(entry)}</span>
                <span className="flex flex-wrap gap-1">
                  <Badge variant={state.variant}>{state.label}</Badge>
                  {entry.redemo_from ? <RedemoBadge /> : null}
                </span>
                <span className="text-muted-foreground min-w-0 text-xs">
                  <span className={cn(tutor === 'Unassigned' && 'text-warning font-medium')}>{tutor}</span>
                  {' · '}Booked {formatDay(entry.booked_at)}
                </span>
                <span className="ml-auto md:ml-0 md:justify-self-end">
                  {current ? (
                    <Badge variant="outline">This booking</Badge>
                  ) : (
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => onOpenBooking(entry)}
                      aria-label={`Open the ${entry.booking_type === 'DIAGNOSTIC' ? 'diagnostic test' : 'demo class'} on ${slotLabel(entry)}`}
                    >
                      Open
                    </Button>
                  )}
                </span>
              </li>
            );
          })}
        </ol>
      )}
    </Panel>
  );
}

/**
 * The booking at a glance (the administrators' booking workspace, laid out as
 * a BDE's enquiry workspace is): the parent, the student and the enquiry side
 * by side, then -- from the lead in full (`lead`, for holders of
 * accounts.view_all_leads, `showLead`) -- how the enquiry has moved and every
 * booking made for the child, each opening in its own workspace
 * (`onOpenBooking(id, type)`). The booking's own facts (its slot, seat, start,
 * how it came in, any move, cancellation or Re-Demo) head the workspace
 * (BookingHeader).
 */
export function BookingOverview({ booking, lead, leadFailure, onRetryLead, showLead, onOpenBooking }) {
  const brief = booking.lead ?? {};
  const loading = showLead && !lead && !leadFailure;

  let enquiry = null;
  if (showLead) {
    if (leadFailure && !lead) {
      enquiry = <ErrorState message={leadFailure.message} onRetry={onRetryLead} />;
    } else if (!lead) {
      enquiry = (
        <>
          <Skeleton className="h-64 rounded-xl" aria-busy="true" />
          <Skeleton className="h-32 rounded-xl" aria-busy="true" />
        </>
      );
    } else {
      enquiry = (
        <>
          <JourneyCard lead={lead} />
          <AllBookingsCard
            lead={lead}
            bookingId={booking.id}
            onOpenBooking={(entry) => onOpenBooking(entry.id, entry.booking_type)}
          />
        </>
      );
    }
  }

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <div className="grid min-w-0 gap-4 lg:grid-cols-3 lg:items-stretch">
        <Panel icon={UserRoundIcon} title="Parent">
          <dl className="divide-y">
            <Field label="Name">{booking.parent_name}</Field>
            <Field label="Phone">
              <span className="tabular-nums">{booking.phone}</span>
            </Field>
            <Field label="Email">
              <FromLead loading={loading}>{lead?.parent_email}</FromLead>
            </Field>
            <Field label="Country">{brief.country}</Field>
          </dl>
        </Panel>

        <Panel icon={GraduationCapIcon} title="Student">
          <dl className="divide-y">
            <Field label="Name">{booking.student_name}</Field>
            <Field label="Class">{booking.grade}</Field>
            <Field label="School">{brief.school_name}</Field>
            <Field label="Syllabus">{brief.syllabus}</Field>
          </dl>
        </Panel>

        <EnquiryCard booking={booking} lead={lead} loading={loading} showLead={showLead} />
      </div>

      {enquiry}
    </div>
  );
}
