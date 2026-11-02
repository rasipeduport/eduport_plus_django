import { useEffect, useMemo, useState } from 'react';
import { EyeIcon, FileClockIcon, FileTextIcon, MessageCircleIcon } from 'lucide-react';

import api from '@/lib/api';
import { bookingTypeLabel, formatDay, slotLabel, whatsAppUrl } from '@/lib/enquiries';
import {
  bdeReportPdfUrl,
  bdeReportsUrl,
  canSharePdf,
  reportError,
  reportPdfFallbackName,
  reportWhatsAppMessage,
} from '@/lib/reports';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Skeleton } from '@/components/ui/skeleton';
import { Panel, PanelEmpty } from '@/components/dashboard/dashboard-primitives';
import { BookingTypeBadge } from '@/components/enquiries/enquiry-badges';
import { PdfDownloadButton } from './pdf-download-button';
import { ReportFieldsView } from './report-fields-view';
import { SharePdfButton } from './share-pdf-button';

/** One report as it prints, in a dialog, with its PDF. */
function ReportDialog({ row, onOpenChange }) {
  return (
    <Dialog open={Boolean(row)} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[calc(100dvh-2rem)] flex-col sm:max-w-2xl">
        {row ? (
          <>
            <DialogHeader>
              <DialogTitle>{bookingTypeLabel(row.booking.booking_type)} report</DialogTitle>
              <DialogDescription>
                {slotLabel(row.booking)} · Version {row.report.version} · As it prints
              </DialogDescription>
            </DialogHeader>
            <div className="min-h-0 overflow-y-auto text-sm">
              <ReportFieldsView type={row.booking.booking_type} report={row.report} />
            </div>
            <DialogFooter>
              <PdfDownloadButton
                url={bdeReportPdfUrl(row.booking.booking_type, row.booking.id)}
                fallbackName={reportPdfFallbackName(row.booking.booking_type)}
              />
              <Button type="button" onClick={() => onOpenChange(false)}>
                Close
              </Button>
            </DialogFooter>
          </>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}

function ReportRow({ row, enquiry, shareable, onView }) {
  const { booking, report } = row;
  const kind = bookingTypeLabel(booking.booking_type).toLowerCase();
  const pdfUrl = bdeReportPdfUrl(booking.booking_type, booking.id);
  const fallbackName = reportPdfFallbackName(booking.booking_type);
  const student = report.student_name || enquiry.student_name;
  const whatsApp = whatsAppUrl(
    enquiry.phone_dial_code,
    enquiry.phone_number,
    reportWhatsAppMessage(booking.booking_type, enquiry.parent_name, student)
  );
  return (
    <li className="flex flex-col gap-3 p-4">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <BookingTypeBadge type={booking.booking_type} />
        <span className="text-sm font-medium">{slotLabel(booking)}</span>
        <Badge variant="secondary">Version {report.version}</Badge>
        <span className="text-muted-foreground text-xs">Last saved {formatDay(report.updated_at)}</span>
      </div>
      <div className="flex flex-wrap items-start gap-2">
        <Button type="button" variant="outline" size="sm" onClick={onView} aria-label={`View the ${kind} report`}>
          <EyeIcon className="size-4" />
          View report
        </Button>
        <PdfDownloadButton url={pdfUrl} fallbackName={fallbackName} label={`Download the ${kind} report as a PDF`} />
        {whatsApp ? (
          <Button size="sm" asChild>
            <a href={whatsApp} target="_blank" rel="noopener noreferrer" aria-label={`Send the ${kind} report via WhatsApp`}>
              <MessageCircleIcon className="size-4" />
              Send via WhatsApp
            </a>
          </Button>
        ) : null}
        {shareable ? (
          <SharePdfButton
            url={pdfUrl}
            fallbackName={fallbackName}
            title={`${bookingTypeLabel(booking.booking_type)} report: ${student}`}
            label={`Share the ${kind} report PDF`}
          />
        ) : null}
      </div>
    </li>
  );
}

/** How a report reaches the parent: by the BDE, outside the Hub. */
function SendingNote({ shareable }) {
  return (
    <div className="text-muted-foreground flex flex-col gap-1 text-xs">
      <p>
        <span className="text-foreground font-medium">Send via WhatsApp</span> opens the parent’s chat with the message
        ready, but it can’t attach the PDF. Download the PDF, attach it in the chat, then send.
      </p>
      {shareable ? (
        <p>
          <span className="text-foreground font-medium">Share PDF</span> hands the PDF to WhatsApp or another app on this
          device. Pick the parent’s chat there.
        </p>
      ) : null}
    </div>
  );
}

/**
 * The reports on one of the BDE's own enquiries (P9, design F.4): each
 * Diagnostic or Demo report its tutor has submitted, at its current version,
 * to view as it prints, download as its PDF and send to the parent. The API
 * answers only the lead's owner BDE (GET /api/bde/enquiries/<id>/reports/).
 *
 * Sending happens outside the Hub. Send via WhatsApp opens the parent's chat
 * (their registered number) with the message filled in (design A11); a link
 * carries no file, so the BDE attaches the downloaded PDF there. Where the
 * browser can share files, Share PDF hands the PDF to the share sheet
 * instead. Nothing here records a send, or says a report was sent.
 */
export function LeadReportsPanel({ enquiry }) {
  const [reports, setReports] = useState(null);
  const [failure, setFailure] = useState(null);
  const [retryKey, setRetryKey] = useState(0);
  const [viewing, setViewing] = useState(null);
  const shareable = useMemo(() => canSharePdf(), []);

  useEffect(() => {
    let active = true;
    setReports(null);
    setFailure(null);
    api
      .get(bdeReportsUrl(enquiry.id))
      .then((response) => {
        if (active) setReports(response.data?.results ?? []);
      })
      .catch((err) => {
        if (active) setFailure(reportError(err, 'Could not load the reports.'));
      });
    return () => {
      active = false;
    };
  }, [enquiry.id, retryKey]);

  let content;
  if (failure) {
    content = (
      <div className="flex flex-wrap items-center gap-3">
        <p className="text-destructive text-sm">{failure.message}</p>
        <Button variant="outline" size="sm" onClick={() => setRetryKey((key) => key + 1)}>
          Try again
        </Button>
      </div>
    );
  } else if (!reports) {
    content = <Skeleton className="h-24" aria-busy="true" />;
  } else if (reports.length === 0) {
    content = (
      <PanelEmpty
        icon={FileClockIcon}
        message="No reports yet"
        hint="A Diagnostic or Demo report appears here once its tutor submits it after the class."
      />
    );
  } else {
    content = (
      <div className="flex flex-col gap-3">
        <ul aria-label="Reports" className="divide-y rounded-md border">
          {reports.map((row) => (
            <ReportRow
              key={`${row.booking.id}-${row.report.version}`}
              row={row}
              enquiry={enquiry}
              shareable={shareable}
              onView={() => setViewing(row)}
            />
          ))}
        </ul>
        <SendingNote shareable={shareable} />
      </div>
    );
  }

  return (
    <Panel icon={FileTextIcon} title="Reports" subtitle="Submitted reports as they print, to send to the parent">
      {content}
      <ReportDialog
        row={viewing}
        onOpenChange={(open) => {
          if (!open) setViewing(null);
        }}
      />
    </Panel>
  );
}
