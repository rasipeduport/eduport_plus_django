import { useEffect, useState } from 'react';
import { SearchXIcon } from 'lucide-react';

import api from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { Skeleton } from '@/components/ui/skeleton';
import { BookingTypeBadge } from '@/components/enquiries/enquiry-badges';
import { PdfDownloadButton } from '@/components/reports/pdf-download-button';
import { TutorReportLink } from '@/components/reports/tutor-report-link';
import { bookingError, tutorBookingUrl } from '@/lib/bookings';
import { bookingTypeLabel, slotLabel } from '@/lib/enquiries';
import { reportActions, reportPdfFallbackName, reportPdfUrl, reportState, tutorReportUrl } from '@/lib/reports';
import { ReportStateBadge } from './booking-badges';

function Section({ title, footer, children }) {
  return (
    <section className="rounded-lg border p-4">
      <h3 className="mb-1 text-sm font-semibold">{title}</h3>
      <dl className="divide-y">{children}</dl>
      {footer ? <div className="flex flex-wrap items-start gap-2 pt-3">{footer}</div> : null}
    </section>
  );
}

// What a booking without its report is waiting for (lib/reports reportState).
const REPORT_WAITING = {
  upcoming: 'You can write the report once the class starts.',
  in_progress: 'The class has started. You can write the report now.',
  report_due: 'The class is over. The report is due.',
};

/**
 * The booking's report, for its tutor: not written yet and why, or the
 * version saved -- with Write report, or Edit report and its PDF (P7). A
 * cancelled or moved booking has no report to write, so no section.
 */
function ReportSection({ booking }) {
  const actions = reportActions(booking);
  const state = reportState(booking);
  const footer =
    actions.write || actions.edit ? (
      <>
        <TutorReportLink booking={booking} />
        {actions.pdf ? (
          <PdfDownloadButton
            url={reportPdfUrl(tutorReportUrl(booking.booking_type, booking.id))}
            fallbackName={reportPdfFallbackName(booking.booking_type)}
          />
        ) : null}
      </>
    ) : null;
  return (
    <Section title="Report" footer={footer}>
      <Detail label="Report">
        {booking.has_report ? `Submitted — version ${booking.report_version}` : REPORT_WAITING[state.key]}
      </Detail>
    </Section>
  );
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
 * One booking the tutor is assigned to teach (GET /api/tutor/bookings/<type>/<id>/):
 * the slot in Indian time, the child it is for and its report. Only the
 * fields below are read -- nothing of the parent, the BDE or the assignment.
 * A booking no longer assigned to the caller is answered 404, as one that does
 * not exist; a link without a known `bookingType` names no booking, so it is
 * not found without asking the API.
 */
export function TutorBookingSheet({ bookingType, bookingId, open, onOpenChange, reloadKey }) {
  const [booking, setBooking] = useState(null);
  const [failure, setFailure] = useState(null);
  const [retryKey, setRetryKey] = useState(0);

  useEffect(() => {
    if (!open || !bookingId || !bookingType) return undefined;
    let active = true;
    setFailure(null);
    api
      .get(tutorBookingUrl(bookingType, bookingId))
      .then((response) => {
        if (active) setBooking(response.data);
      })
      .catch((err) => {
        if (active) setFailure(bookingError(err, 'Could not load this booking.'));
      });
    return () => {
      active = false;
    };
  }, [open, bookingType, bookingId, reloadKey, retryKey]);

  // Nothing of another booking shows while this one loads.
  const shown = booking && booking.id === bookingId && booking.booking_type === bookingType ? booking : null;

  // A link naming a booking without a known type names none. (While the sheet
  // closes there is no booking at all, and nothing to say about one.)
  const untyped = Boolean(bookingId) && !bookingType;

  let body;
  if (untyped || (failure && failure.status === 404)) {
    body = (
      <div className="flex flex-col items-center gap-2 rounded-md border px-6 py-12 text-center">
        <SearchXIcon className="text-muted-foreground size-8" />
        <p className="font-medium">Booking not found</p>
        <p className="text-muted-foreground text-sm">It may no longer be assigned to you, or the link may be mistyped.</p>
      </div>
    );
  } else if (failure) {
    body = (
      <div className="flex flex-wrap items-center gap-3">
        <p className="text-destructive text-sm">{failure.message}</p>
        <Button variant="outline" size="sm" onClick={() => setRetryKey((key) => key + 1)}>
          Try again
        </Button>
      </div>
    );
  } else if (!shown) {
    body = (
      <div className="flex flex-col gap-4" aria-busy="true">
        <Skeleton className="h-32" />
        <Skeleton className="h-40" />
      </div>
    );
  } else {
    body = (
      <div className="flex flex-col gap-4">
        {shown.status === 'CANCELLED' ? (
          <p className="bg-muted text-muted-foreground rounded-md px-3 py-2 text-sm">
            This booking was cancelled. There is no class to teach.
          </p>
        ) : null}
        <Section title="Booking">
          <Detail label="Type">{bookingTypeLabel(shown.booking_type)}</Detail>
          <Detail label="When">{slotLabel(shown.slot)}</Detail>
          <Detail label="Status">
            <ReportStateBadge booking={shown} />
          </Detail>
        </Section>

        {shown.status === 'BOOKED' || shown.status === 'COMPLETED' ? <ReportSection booking={shown} /> : null}

        <Section title="Student">
          <Detail label="Name">{shown.student_name}</Detail>
          <Detail label="Class">{shown.grade}</Detail>
          <Detail label="Syllabus">{shown.syllabus}</Detail>
          <Detail label="School">{shown.school_name}</Detail>
          <Detail label="Country">{shown.country}</Detail>
        </Section>
      </div>
    );
  }

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full sm:max-w-lg">
        <SheetHeader>
          <SheetTitle>{shown ? shown.student_name : 'Booking'}</SheetTitle>
          <SheetDescription>{shown ? `${slotLabel(shown.slot)} · ${shown.grade || 'Class not given'}` : 'Loading…'}</SheetDescription>
          {shown ? (
            <div className="flex flex-wrap gap-2 pt-1">
              <BookingTypeBadge type={shown.booking_type} />
              <ReportStateBadge booking={shown} />
            </div>
          ) : null}
        </SheetHeader>
        <div className="min-h-0 flex-1 overflow-y-auto px-4 pb-4">{body}</div>
      </SheetContent>
    </Sheet>
  );
}
