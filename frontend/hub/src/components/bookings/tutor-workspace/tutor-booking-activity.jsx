import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { CheckIcon, HistoryIcon, MinusIcon } from 'lucide-react';

import api from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { Panel } from '@/components/dashboard/dashboard-primitives';
import { ErrorState } from '@/components/page/states';
import { istMoment } from '@/lib/communications';
import { bookingTypeLabel, slotLabel } from '@/lib/enquiries';
import { reportError, reportFieldsText, reportWords, tutorReportUrl } from '@/lib/reports';
import { cn } from '@/lib/utils';

/**
 * What has happened to the booking as its tutor's API tells it, oldest first:
 * the class at its slot, when the tutor started it (or that the slot ended
 * without a start), each saved version of its feedback or results
 * (`revisions`: the first completed the booking), and a cancellation or move
 * -- the API gives no moment for those, so they come last. While the class is
 * still to come, when Start opens and the class itself are the steps ahead.
 * Who assigned the tutor, cancelled or moved the booking, and why, stay with
 * the administrators.
 */
function tutorTimeline(booking, revisions = []) {
  const words = reportWords(booking.booking_type);
  const kind = bookingTypeLabel(booking.booking_type);
  const toCome = booking.status === 'BOOKED' && !booking.started_at && !booking.slot.ended;
  const steps = [];
  if (toCome && !booking.slot.started) {
    steps.push({ key: 'opens', at: booking.start_opens_at, title: 'Start opens', detail: istMoment(booking.start_opens_at), ahead: true });
  }
  steps.push({
    key: 'slot',
    at: booking.slot.starts_at,
    title: booking.slot.started ? `${kind} time` : `${kind} scheduled`,
    detail: slotLabel(booking.slot),
    ahead: !booking.slot.started && booking.status === 'BOOKED',
  });
  if (booking.started_at) {
    steps.push({ key: 'started', at: booking.started_at, title: 'You started the class', detail: istMoment(booking.started_at) });
  } else if (booking.status === 'BOOKED' && booking.activity_state === 'NOT_STARTED') {
    steps.push({
      key: 'ended',
      at: booking.slot.ends_at,
      title: 'The slot ended without a start',
      detail: `No ${words.noun} can be written`,
      muted: true,
    });
  }
  for (const revision of revisions) {
    steps.push({
      key: `version-${revision.version}`,
      at: revision.edited_at,
      title: revision.version === 1 ? `${words.tab} submitted · booking completed` : `${words.tab} edited · version ${revision.version}`,
      detail: [
        istMoment(revision.edited_at),
        revision.version === 1 ? null : `Changed: ${reportFieldsText(revision.changed_fields)}`,
      ]
        .filter(Boolean)
        .join(' · '),
    });
  }
  if (booking.status === 'CANCELLED') steps.push({ key: 'cancelled', at: null, title: 'Booking cancelled', muted: true });
  if (booking.status === 'RESCHEDULED') steps.push({ key: 'moved', at: null, title: 'Moved to another slot', muted: true });
  // In time order; what has no moment of its own last, as given.
  return steps
    .map((step, index) => ({ step, index }))
    .sort((a, b) => {
      if (a.step.at && b.step.at) return new Date(a.step.at) - new Date(b.step.at) || a.index - b.index;
      if (a.step.at || b.step.at) return a.step.at ? -1 : 1;
      return a.index - b.index;
    })
    .map(({ step }) => step);
}

function StepMark({ step }) {
  if (step.ahead) return <span className="border-primary bg-background size-5 shrink-0 rounded-full border-2" />;
  const Icon = step.muted ? MinusIcon : CheckIcon;
  return (
    <span
      className={cn(
        'flex size-5 shrink-0 items-center justify-center rounded-full',
        step.muted ? 'bg-muted-foreground text-background' : 'bg-success text-success-foreground'
      )}
    >
      <Icon className="size-3" strokeWidth={3} />
    </span>
  );
}

/**
 * The booking's timeline for its tutor (tutorTimeline), its report's versions
 * read from GET …/report/revisions/ once it has one; the tutor's own full
 * activity is on the Activity page.
 */
export function TutorBookingActivity({ booking, reloadKey }) {
  const hasReport = Boolean(booking.has_report);
  const [revisions, setRevisions] = useState(null);
  const [failure, setFailure] = useState(null);
  const [retryKey, setRetryKey] = useState(0);

  useEffect(() => {
    if (!hasReport) return undefined;
    let active = true;
    setFailure(null);
    api
      .get(`${tutorReportUrl(booking.booking_type, booking.id)}revisions/`)
      .then((response) => {
        if (active) setRevisions({ bookingId: booking.id, rows: response.data.results ?? [] });
      })
      .catch((err) => {
        if (active) setFailure(reportError(err, 'Could not load the report versions.'));
      });
    return () => {
      active = false;
    };
  }, [booking.booking_type, booking.id, hasReport, reloadKey, retryKey]);

  const loaded = !hasReport || (revisions && revisions.bookingId === booking.id);
  const steps = tutorTimeline(booking, hasReport && loaded ? revisions.rows : []);

  return (
    <Panel
      icon={HistoryIcon}
      title="Activity"
      subtitle="This booking as it has gone so far, in Indian time (IST)"
      action={
        <Button variant="outline" size="sm" asChild>
          <Link to="/activity">All your activity</Link>
        </Button>
      }
    >
      {failure ? <ErrorState className="mb-4" message={failure.message} onRetry={() => setRetryKey((key) => key + 1)} /> : null}
      {!loaded && !failure ? (
        <Skeleton className="h-40" aria-busy="true" />
      ) : (
        <ol aria-label="Booking timeline">
          {steps.map((step) => (
            <li key={step.key} className="group flex gap-3">
              <span className="flex flex-col items-center pt-0.5" aria-hidden="true">
                <StepMark step={step} />
                <span className="bg-border mt-1 w-px flex-1 group-last:hidden" />
              </span>
              <div className="min-w-0 flex-1 pb-5 group-last:pb-0">
                <p className={cn('text-sm font-medium', step.ahead && 'text-muted-foreground')}>
                  {step.title}
                  {step.ahead ? <span className="sr-only"> (still to come)</span> : null}
                </p>
                {step.detail ? <p className="text-muted-foreground mt-0.5 text-xs">{step.detail}</p> : null}
              </div>
            </li>
          ))}
        </ol>
      )}
      <p className="text-muted-foreground mt-4 text-xs">
        Who assigned, moved or cancelled a booking, and why, stays with the administrators.
      </p>
    </Panel>
  );
}
