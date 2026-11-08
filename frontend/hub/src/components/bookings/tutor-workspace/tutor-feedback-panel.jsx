import { useEffect, useState } from 'react';
import { FileTextIcon, HistoryIcon } from 'lucide-react';

import api from '@/lib/api';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { Panel, ToneIcon } from '@/components/dashboard/dashboard-primitives';
import { FeedbackBadge } from '@/components/bookings/booking-badges';
import { StartBookingButton } from '@/components/bookings/start-booking-button';
import { EmptyState } from '@/components/page/page';
import { ErrorState } from '@/components/page/states';
import { PdfDownloadButton } from '@/components/reports/pdf-download-button';
import { ReportDocument } from '@/components/reports/report-document';
import { ReportVersions } from '@/components/reports/report-versions';
import { TutorReportLink } from '@/components/reports/tutor-report-link';
import { ViewPdfButton } from '@/components/reports/view-pdf-button';
import { istMoment } from '@/lib/communications';
import {
  reportError,
  reportPdfFallbackName,
  reportPdfUrl,
  reportState,
  reportWords,
  tutorReportUrl,
} from '@/lib/reports';

// What the tab heads a booking's report with.
const REPORT_TITLES = { DEMO: 'Demo Feedback', DIAGNOSTIC: 'Diagnostic Results' };

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
 * once in, the report -- read from GET /api/tutor/bookings/<type>/<id>/report/
 * -- headed by where it stands, its version and when it was submitted and last
 * edited, with Edit (the report page), View PDF (the very PDF a download
 * saves, shown in the page) and Download PDF together, then the report as a
 * document (ReportDocument), and every version on request; before that, why
 * it cannot be written yet, with Start or Submit Feedback / Enter Results
 * where the booking allows. Writing and editing happen on the report page
 * (TutorReportLink, `reportState` its way back), which guards unsaved text.
 * A cancelled or moved booking takes no report.
 */
export function TutorFeedbackPanel({ booking, reloadKey, onStarted, onRefresh, reportState: linkState }) {
  const type = booking.booking_type;
  const words = reportWords(type);
  const title = REPORT_TITLES[type] ?? REPORT_TITLES.DEMO;
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
      <Panel icon={FileTextIcon} title={title} action={<FeedbackBadge booking={booking} />}>
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

  const version = shown?.version ?? booking.report_version;
  const pdfUrl = reportPdfUrl(url);
  const edited = shown && shown.updated_at !== shown.submitted_at;

  return (
    <div className="flex flex-col gap-4">
      <Card className="gap-0 overflow-hidden py-0">
        <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3 border-b px-4 py-4 sm:px-5">
          <div className="flex min-w-0 items-start gap-3">
            <ToneIcon icon={FileTextIcon} tone={type === 'DIAGNOSTIC' ? 'diagnostic' : 'demo'} />
            <div className="min-w-0">
              <h3 className="text-lg leading-tight font-semibold">{title}</h3>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <Badge variant="success">Submitted</Badge>
                {version ? (
                  <Badge variant="outline" className="tabular-nums">
                    Version {version}
                  </Badge>
                ) : null}
              </div>
              {shown ? (
                <p className="text-muted-foreground mt-2 flex flex-wrap gap-x-2 gap-y-0.5 text-xs">
                  <span>Submitted {istMoment(shown.submitted_at)}</span>
                  {edited ? (
                    <>
                      <span aria-hidden="true">·</span>
                      <span>Last edited {istMoment(shown.updated_at)}</span>
                    </>
                  ) : null}
                </p>
              ) : null}
            </div>
          </div>
          <div className="flex flex-wrap items-start gap-2 sm:justify-end">
            <TutorReportLink booking={booking} state={linkState} />
            <ViewPdfButton
              url={pdfUrl}
              title={`${title} PDF`}
              description={version ? `Version ${version}, exactly as it downloads.` : 'Exactly as it downloads.'}
              label={`View the ${words.noun} PDF`}
            />
            <PdfDownloadButton url={pdfUrl} fallbackName={reportPdfFallbackName(type)} label={`Download the ${words.noun} PDF`} />
          </div>
        </div>
        <div className="p-4 sm:p-5">
          {failure ? (
            <ErrorState message={failure.message} onRetry={() => setRetryKey((key) => key + 1)} />
          ) : shown ? (
            <ReportDocument type={type} report={shown} />
          ) : (
            <Skeleton className="h-64" aria-busy="true" />
          )}
        </div>
      </Card>

      {/* Every version, on request, under this card's own heading. */}
      <Card className="gap-0 py-0">
        <section aria-labelledby="tutor-version-history">
          <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-4 sm:px-5">
            <div className="flex min-w-0 items-center gap-3">
              <span className="bg-muted text-muted-foreground flex size-10 shrink-0 items-center justify-center rounded-lg">
                <HistoryIcon className="size-5" aria-hidden="true" />
              </span>
              <div className="min-w-0">
                <h3 id="tutor-version-history" className="text-sm font-semibold">
                  Version History
                </h3>
                <p className="text-muted-foreground text-xs">
                  {booking.report_version > 1
                    ? `${booking.report_version} versions saved. Show them to read each one and download its PDF.`
                    : 'One version saved so far. Each edit is kept as a new version.'}
                </p>
              </div>
            </div>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setVersionsOpen((open) => !open)}
              aria-expanded={versionsOpen}
              aria-controls="tutor-version-list"
            >
              {versionsOpen ? 'Hide versions' : 'Show versions'}
            </Button>
          </div>
          {versionsOpen ? (
            <div id="tutor-version-list" className="border-t px-4 py-4 sm:px-5">
              <ReportVersions type={type} reportUrl={url} reloadKey={reloadKey} showHeading={false} />
            </div>
          ) : null}
        </section>
      </Card>
    </div>
  );
}
