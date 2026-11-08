import { useEffect, useState } from 'react';
import { format } from 'date-fns';

import api from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { bookingReportUrl, reportError, reportPdfFallbackName, reportPdfUrl } from '@/lib/reports';
import { PdfDownloadButton } from './pdf-download-button';
import { ReportFieldsView } from './report-fields-view';
import { ReportVersions } from './report-versions';

const when = (value) => (value ? format(new Date(value), 'd MMM yyyy, h:mm a') : null);

/**
 * Why a booked booking has no report yet, by its tutor's own start (the API's
 * activity_state), never the slot's clock: due after a class the tutor started
 * (report_due), started now, not started though its time has passed, never
 * started at all, or still to come.
 */
function waiting(booking) {
  if (booking.report_due) return 'Report due. The class is over and the tutor has not written the report yet.';
  switch (booking.activity_state) {
    case 'IN_PROGRESS':
      return 'The tutor has started the class. They can write the report now.';
    case 'LATE':
      return 'The scheduled time has passed and the tutor has not started the class yet.';
    case 'NOT_STARTED':
      return 'The slot ended without the tutor starting the class, so no report can be written.';
    default:
      return 'The tutor can write the report once they start the class.';
  }
}

function Detail({ label, children }) {
  return (
    <div className="grid grid-cols-[8rem_1fr] gap-3 py-2 text-sm">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="min-w-0 font-medium break-words">{children || <span className="text-muted-foreground">—</span>}</dd>
    </div>
  );
}

/**
 * A booking's report, for the Admin, read-only (P6 design E.1, D17): which
 * version is current, who submitted it and when it was last saved (the
 * booking detail's ``report``), the report as it prints (GET
 * /api/bookings/<type>/<id>/report/), its PDF, and every version on request
 * with each one's PDF (P7). No report yet: why. Only the booking's tutor
 * writes or edits a report, so nothing here does.
 */
export function AdminReportSection({ booking, reloadKey }) {
  const url = bookingReportUrl(booking.booking_type, booking.id);
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
        if (active) setFailure(reportError(err, 'Could not load the report.'));
      });
    return () => {
      active = false;
    };
  }, [url, hasReport, reloadKey, retryKey]);

  // Nothing of another booking's report shows while this one loads.
  const shown = report && report.booking_id === booking.id ? report : null;
  const brief = booking.report;

  let content = null;
  if (hasReport) {
    if (failure) {
      content = (
        <div className="flex flex-wrap items-center gap-3 pt-2">
          <p className="text-destructive text-sm">{failure.message}</p>
          <Button variant="outline" size="sm" onClick={() => setRetryKey((key) => key + 1)}>
            Try again
          </Button>
        </div>
      );
    } else if (!shown) {
      content = <Skeleton className="mt-2 h-32" aria-busy="true" />;
    } else {
      content = (
        <div className="mt-2 border-t pt-3">
          <ReportFieldsView type={booking.booking_type} report={shown} />
        </div>
      );
    }
  }

  return (
    <section className="bg-card rounded-xl border p-4">
      <div className="mb-1 flex items-center justify-between gap-2">
        <h3 className="text-sm font-semibold">Report</h3>
        {hasReport ? (
          <PdfDownloadButton url={reportPdfUrl(url)} fallbackName={reportPdfFallbackName(booking.booking_type)} />
        ) : null}
      </div>
      {hasReport ? (
        <>
          <dl className="divide-y">
            <Detail label="Version">{`Version ${booking.report_version}`}</Detail>
            <Detail label="Submitted">
              {brief
                ? [when(brief.submitted_at), brief.submitted_by?.full_name && `by ${brief.submitted_by.full_name}`]
                    .filter(Boolean)
                    .join(' ')
                : null}
            </Detail>
            <Detail label="Last saved">{brief ? when(brief.updated_at) : null}</Detail>
          </dl>
          <p className="text-muted-foreground text-xs">Read-only. Only the booking’s tutor writes or edits its report.</p>
          {content}
          <div className="mt-3 flex flex-col gap-3 border-t pt-3">
            <Button
              variant="ghost"
              size="sm"
              className="self-start"
              onClick={() => setVersionsOpen((open) => !open)}
              aria-expanded={versionsOpen}
            >
              {versionsOpen ? 'Hide versions' : 'Show versions'}
            </Button>
            {versionsOpen ? (
              <ReportVersions type={booking.booking_type} reportUrl={url} reloadKey={reloadKey} headingAs="h4" />
            ) : null}
          </div>
        </>
      ) : (
        <p className="text-muted-foreground py-2 text-sm">{waiting(booking)}</p>
      )}
    </section>
  );
}
