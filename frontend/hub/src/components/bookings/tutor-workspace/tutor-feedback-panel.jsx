import { useEffect, useState } from 'react';
import { FileTextIcon, HistoryIcon } from 'lucide-react';

import api from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { Panel } from '@/components/dashboard/dashboard-primitives';
import { FeedbackBadge } from '@/components/bookings/booking-badges';
import { StartBookingButton } from '@/components/bookings/start-booking-button';
import { EmptyState } from '@/components/page/page';
import { ErrorState } from '@/components/page/states';
import { PdfDownloadButton } from '@/components/reports/pdf-download-button';
import { ReportFieldsView } from '@/components/reports/report-fields-view';
import { ReportVersions } from '@/components/reports/report-versions';
import { TutorReportLink } from '@/components/reports/tutor-report-link';
import { istMoment } from '@/lib/communications';
import {
  reportError,
  reportPdfFallbackName,
  reportPdfUrl,
  reportState,
  reportWords,
  tutorReportUrl,
} from '@/lib/reports';

// What a booking without its report is waiting for (lib/reports reportState):
// the report follows the tutor's own Start, never the scheduled time.
function waiting(booking) {
  const { noun } = reportWords(booking.booking_type);
  switch (reportState(booking).key) {
    case 'in_progress':
      return `You have started the class. You can write the ${noun} now.`;
    case 'report_due':
      return `The class is over and its ${noun} is due.`;
    case 'ready':
      return `Start the class to write its ${noun}.`;
    case 'late':
      return `The scheduled time has passed. Start the class to write its ${noun}.`;
    case 'not_started':
      return `The slot ended without the class being started, so no ${noun} can be written.`;
    default:
      return `You can write the ${noun} once you start the class.`;
  }
}

/**
 * A booking's feedback (a Demo's) or results (a Diagnostic's), for its tutor:
 * once in, the report as it prints -- read from GET
 * /api/tutor/bookings/<type>/<id>/report/ -- with its PDF, when it was
 * submitted and last saved, and every version on request; before that, why
 * it cannot be written yet, with Start or Write feedback / Enter results
 * where the booking allows. Writing and editing happen on the report page
 * (TutorReportLink, `reportState` its way back), which guards unsaved text.
 * A cancelled or moved booking takes no report.
 */
export function TutorFeedbackPanel({ booking, reloadKey, onStarted, onRefresh, reportState: linkState }) {
  const type = booking.booking_type;
  const words = reportWords(type);
  const url = tutorReportUrl(type, booking.id);
  const hasReport = Boolean(booking.has_report);
  const [report, setReport] = useState(null);
  const [failure, setFailure] = useState(null);
  const [retryKey, setRetryKey] = useState(0);
  const [versionsOpen, setVersionsOpen] = useState(false);

  useEffect(() => {
    if (!hasReport) return undefined;
    let active = true;
    setFailure(null);
    api
      .get(url)
      .then((response) => {
        if (active) setReport(response.data);
      })
      .catch((err) => {
        if (active) setFailure(reportError(err, `Could not load the ${words.noun}.`));
      });
    return () => {
      active = false;
    };
  }, [url, hasReport, reloadKey, retryKey, words.noun]);

  if (booking.status === 'CANCELLED' || booking.status === 'RESCHEDULED') {
    return (
      <EmptyState
        icon={FileTextIcon}
        title={`No ${words.noun} for this booking`}
        description={
          booking.status === 'RESCHEDULED'
            ? 'It was moved to another slot: the report belongs to the booking that replaced it.'
            : 'It was cancelled, so no class was taught and no report is written.'
        }
      />
    );
  }

  // Nothing of another booking's report shows while this one loads.
  const shown = report && report.booking_id === booking.id ? report : null;

  if (!hasReport) {
    return (
      <Panel icon={FileTextIcon} title={words.page} action={<FeedbackBadge booking={booking} />}>
        <div className="flex flex-col items-start gap-3">
          <p className="text-muted-foreground text-sm">{waiting(booking)}</p>
          <div className="flex flex-wrap gap-2">
            <StartBookingButton booking={booking} onStarted={onStarted} onRefresh={onRefresh} />
            <TutorReportLink booking={booking} state={linkState} />
          </div>
          <p className="text-muted-foreground text-xs">
            The {words.noun} is saved when you submit it: there are no drafts, so write it in one sitting. You can
            preview its PDF before submitting, and edit it afterwards.
          </p>
        </div>
      </Panel>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <Panel
        icon={FileTextIcon}
        title={words.page}
        subtitle={
          shown
            ? `Version ${shown.version} · submitted ${istMoment(shown.submitted_at)}${
                shown.updated_at !== shown.submitted_at ? ` · last saved ${istMoment(shown.updated_at)}` : ''
              }`
            : `Version ${booking.report_version}`
        }
        action={
          <div className="flex flex-wrap justify-end gap-2">
            <TutorReportLink booking={booking} state={linkState} />
            <PdfDownloadButton url={reportPdfUrl(url)} fallbackName={reportPdfFallbackName(type)} />
          </div>
        }
      >
        {failure ? (
          <ErrorState message={failure.message} onRetry={() => setRetryKey((key) => key + 1)} />
        ) : shown ? (
          // The report as it prints, on a page of its own.
          <div className="bg-background rounded-lg border p-4 sm:p-6">
            <ReportFieldsView type={type} report={shown} />
          </div>
        ) : (
          <Skeleton className="h-48" aria-busy="true" />
        )}
      </Panel>

      {/* Every version, on request: ReportVersions heads itself. */}
      <section className="bg-card relative rounded-xl border p-4">
        <Button
          variant="outline"
          size="sm"
          className={versionsOpen ? 'absolute top-3 right-4' : 'float-right'}
          onClick={() => setVersionsOpen((open) => !open)}
          aria-expanded={versionsOpen}
        >
          {versionsOpen ? 'Hide versions' : 'Show versions'}
        </Button>
        {versionsOpen ? (
          <ReportVersions type={type} reportUrl={url} reloadKey={reloadKey} headingAs="h3" />
        ) : (
          <div className="flex min-w-0 items-center gap-2">
            <span className="bg-muted text-muted-foreground flex size-7 shrink-0 items-center justify-center rounded-md">
              <HistoryIcon className="size-4" aria-hidden="true" />
            </span>
            <div className="min-w-0">
              <h3 className="text-sm font-semibold">Versions</h3>
              <p className="text-muted-foreground text-xs">
                {booking.report_version > 1
                  ? `${booking.report_version} versions saved. Show them to read each one and download its PDF.`
                  : 'One version saved so far. Each edit is kept as a new version.'}
              </p>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}
