import { useEffect, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  AlertCircleIcon,
  ArrowLeftIcon,
  CheckCircle2Icon,
  EyeIcon,
  InfoIcon,
  Loader2Icon,
  SearchXIcon,
  XIcon,
} from 'lucide-react';

import api from '@/lib/api';
import { FormDialog } from '@/components/form-dialog';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { ReportStateBadge } from '@/components/bookings/booking-badges';
import { StartBookingButton } from '@/components/bookings/start-booking-button';
import { BookingTypeBadge } from '@/components/enquiries/enquiry-badges';
import { DemoReportForm } from '@/components/reports/demo-report-form';
import { DiagnosticReportForm } from '@/components/reports/diagnostic-report-form';
import { PdfDownloadButton } from '@/components/reports/pdf-download-button';
import { ReportPreviewDialog } from '@/components/reports/report-preview-dialog';
import { ReportVersions } from '@/components/reports/report-versions';
import { useLeaveGuard } from '@/hooks/use-leave-guard';
import { tutorBookingUrl } from '@/lib/bookings';
import { slotLabel } from '@/lib/enquiries';
import {
  DIAGNOSTIC_ASSESSMENT_TYPE,
  REPORT_FIELDS,
  REPORT_SUBJECT,
  emptyReportForm,
  isListField,
  reportActions,
  reportChanged,
  reportError,
  reportFieldId,
  reportForm,
  reportPayload,
  reportPdfError,
  reportPdfFallbackName,
  reportPdfUrl,
  reportState,
  reportTypeFromPath,
  tutorReportPreviewUrl,
  tutorReportUrl,
  validateReport,
  withJsonBody,
} from '@/lib/reports';
import { cn } from '@/lib/utils';

const TITLES = { DIAGNOSTIC: 'Diagnostic report', DEMO: 'Demo report' };

// Why a booking without its report offers no form (lib/reports reportState):
// the report follows the tutor's own Start, never the scheduled time.
const CLOSED = {
  upcoming: 'You can write the report once you start the class.',
  ready: 'Start the class to write its report.',
  late: 'The scheduled time has passed. Start the class to write its report.',
  not_started: 'The slot ended without the class being started, so no report can be written.',
  cancelled: 'This booking was cancelled, so there is no report to write.',
  rescheduled: 'This booking was moved to another slot. Write the report on the new booking.',
};

// What the API's refusals of a save mean here (reports.services).
const REFUSALS = {
  NOT_STARTED: 'The class has not been started. Start it before writing its report.',
  BOOKING_CANCELLED: 'This booking was cancelled, so the report cannot be saved.',
  BOOKING_RESCHEDULED: 'This booking was moved to another slot, so the report cannot be saved here.',
  NOT_FOUND: 'This booking is no longer assigned to you, so the report cannot be saved.',
  REPORT_BUSY: 'The report is being saved somewhere else right now. Try again in a moment.',
};
const CHECK_FIELDS = 'Some fields need attention. They are marked below.';

const TONES = {
  success: { className: 'bg-success/10 text-success', Icon: CheckCircle2Icon, role: 'status' },
  info: { className: 'bg-info/10 text-info', Icon: InfoIcon, role: 'status' },
  error: { className: 'bg-destructive/10 text-destructive', Icon: AlertCircleIcon, role: 'alert' },
};

function Notice({ notice, onDismiss }) {
  if (!notice) return null;
  const { className, Icon, role } = TONES[notice.tone];
  return (
    <div role={role} className={cn('flex items-start gap-2 rounded-md px-3 py-2 text-sm', className)}>
      <Icon className="mt-0.5 size-4 shrink-0" />
      <div className="flex flex-1 flex-col items-start gap-1">
        <p>{notice.text}</p>
        {notice.action ? (
          <Button type="button" variant="link" className="h-auto p-0" onClick={notice.action.onClick}>
            {notice.action.label}
          </Button>
        ) : null}
      </div>
      <button type="button" onClick={onDismiss} className="shrink-0" aria-label="Dismiss">
        <XIcon className="size-4" />
      </button>
    </div>
  );
}

function Detail({ label, children }) {
  return (
    <div className="grid grid-cols-[8rem_1fr] gap-3 py-1.5 text-sm">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="min-w-0 font-medium break-words">{children || <span className="text-muted-foreground">—</span>}</dd>
    </div>
  );
}

/** What the report prints that the tutor does not type: filled in from the booking and the tutor's account. */
function PrintedDetails({ type, booking, tutorName }) {
  return (
    <section className="rounded-lg border p-4">
      <h2 className="text-sm font-semibold">Printed on the report</h2>
      <dl className="mt-1 grid gap-x-8 sm:grid-cols-2">
        <Detail label="Student name">{booking.student_name}</Detail>
        <Detail label="Class">{booking.grade}</Detail>
        <Detail label="Subject">{REPORT_SUBJECT}</Detail>
        {type === 'DIAGNOSTIC' ? <Detail label="Assessment type">{DIAGNOSTIC_ASSESSMENT_TYPE}</Detail> : null}
        <Detail label="Tutor name">{tutorName}</Detail>
        <Detail label="When">{slotLabel(booking.slot)}</Detail>
      </dl>
      <p className="text-muted-foreground mt-2 text-xs">
        Filled in for you from the booking and your account, as they stand when you save.
      </p>
    </section>
  );
}

function NotFound({ onBack }) {
  return (
    <div className="flex flex-col items-center gap-2 rounded-md border px-6 py-12 text-center">
      <SearchXIcon className="text-muted-foreground size-8" />
      <p className="font-medium">Booking not found</p>
      <p className="text-muted-foreground text-sm">It may no longer be assigned to you, or the link may be mistyped.</p>
      <Button variant="outline" size="sm" className="mt-2" onClick={onBack}>
        Back to My Bookings
      </Button>
    </div>
  );
}

/**
 * The tutor's report on one assigned booking (/my-bookings/<demo|diagnostic>/<id>/report):
 * the Diagnostic or Demo form (P6 fields and limits, lib/reports), a PDF
 * preview drawn by the same renderer as every saved version (P8 Step 2), a
 * confirm step before the first submit -- which completes the booking -- and
 * once there is a report, edits saved as new versions, the version history
 * and each version's PDF (P7).
 *
 * The API decides everything: only the booking's assigned tutor reaches it
 * (anyone else is told it does not exist), and it refuses a save it would not
 * keep, with the reason shown here. What the tutor types stays in memory only
 * -- never in browser storage: reloading or closing the tab warns while there
 * are unsaved changes, and Cancel, Back, a link to another page of the Hub,
 * the browser's Back and Forward or logging out ask before discarding them.
 * Nothing of the parent or the BDE is read or shown.
 */
export default function TutorReportPage({ user }) {
  const { bookingType: segment, bookingId } = useParams();
  const type = reportTypeFromPath(segment);
  const navigate = useNavigate();

  const [booking, setBooking] = useState(null);
  const [report, setReport] = useState(null);
  const [loaded, setLoaded] = useState(false);
  const [failure, setFailure] = useState(null);
  const [loadKey, setLoadKey] = useState(0);
  const [values, setValues] = useState(null);
  const [baseline, setBaseline] = useState(null);
  const [attempted, setAttempted] = useState(false);
  const [serverErrors, setServerErrors] = useState({});
  const [notice, setNotice] = useState(null);
  const [pending, setPending] = useState(null); // 'submit' | 'save' | 'preview'
  const [confirming, setConfirming] = useState(false);
  const [discarding, setDiscarding] = useState(null); // 'leave' | 'reload'
  const leaving = useRef(null); // a held way out (link, Back/Forward, log out), to go on with once discarding is confirmed
  const [previewUrl, setPreviewUrl] = useState(null);
  const [versionsKey, setVersionsKey] = useState(0);
  const [gone, setGone] = useState(false);
  const [focusRequest, setFocusRequest] = useState(null); // the field to focus once nothing is in the way

  // The booking, then its report if it has one. A report that is not there is answered 404
  // (NO_REPORT), which the browser logs as an error, so it is asked for only when the booking
  // says there is one; a NO_REPORT all the same reads as no report yet.
  useEffect(() => {
    if (!type) return undefined;
    let active = true;
    setLoaded(false);
    setFailure(null);
    const readReport = () =>
      api.get(tutorReportUrl(type, bookingId)).then(
        (response) => response.data,
        (err) => {
          if (err?.response?.status === 404 && err.response.data?.error === 'NO_REPORT') return null;
          throw err;
        }
      );
    api
      .get(tutorBookingUrl(type, bookingId))
      .then((response) => Promise.all([response, response.data.has_report ? readReport() : null]))
      .then(([response, savedReport]) => {
        if (!active) return;
        const form = savedReport ? reportForm(type, savedReport.fields) : emptyReportForm(type);
        setBooking(response.data);
        setReport(savedReport);
        setValues(form);
        setBaseline(form);
        setAttempted(false);
        setServerErrors({});
        setGone(false);
        setLoaded(true);
      })
      .catch((err) => {
        if (active) setFailure(reportError(err, 'Could not load this report.'));
      });
    return () => {
      active = false;
    };
  }, [type, bookingId, loadKey]);

  const dirty = Boolean(loaded && values && baseline && reportChanged(type, values, baseline));

  // Unsaved changes are kept in memory only: leaving the page by reload or close asks first.
  useEffect(() => {
    if (!dirty) return undefined;
    const warn = (event) => {
      event.preventDefault();
      event.returnValue = '';
    };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [dirty]);

  // Leaving by a link to another page, the browser's Back or Forward, or logging out asks too, as Cancel does.
  useLeaveGuard(dirty, (proceed) => {
    leaving.current = proceed;
    setDiscarding('leave');
  });

  // A field with a problem gets the focus once the form is enabled again and no dialog is open
  // (a refusal arrives while the form is disabled, and the confirm step may still be closing).
  useEffect(() => {
    if (!focusRequest || pending || confirming) return undefined;
    const timer = setTimeout(() => {
      const element = document.getElementById(reportFieldId(focusRequest));
      (isListField(focusRequest) ? element?.querySelector('input') : element)?.focus();
      setFocusRequest(null);
    }, 0);
    return () => clearTimeout(timer);
  }, [focusRequest, pending, confirming]);

  // A preview's PDF lives in memory as an object URL until the preview closes.
  useEffect(
    () => () => {
      if (previewUrl) URL.revokeObjectURL(previewUrl);
    },
    [previewUrl]
  );

  const leave = () => navigate(`/my-bookings?booking=${bookingId}&booking_type=${type}`);
  const back = () => {
    leaving.current = null;
    if (dirty) setDiscarding('leave');
    else leave();
  };

  if (!type || (failure && failure.status === 404)) {
    return (
      <div className="container mx-auto max-w-4xl px-4 py-16">
        <NotFound onBack={leave} />
      </div>
    );
  }
  if (failure) {
    return (
      <div className="container mx-auto max-w-4xl px-4 py-16">
        <div className="flex flex-wrap items-center gap-3">
          <p className="text-destructive text-sm">{failure.message}</p>
          <Button variant="outline" size="sm" onClick={() => setLoadKey((key) => key + 1)}>
            Try again
          </Button>
        </div>
      </div>
    );
  }
  if (!loaded) {
    return (
      <div className="container mx-auto flex max-w-4xl flex-col gap-4 px-4 py-16" aria-busy="true">
        <Skeleton className="h-10 w-64" />
        <Skeleton className="h-32" />
        <Skeleton className="h-96" />
      </div>
    );
  }

  const state = reportState(booking);
  const writable = Boolean(report) || reportActions(booking).write;
  const errors = { ...(attempted ? validateReport(type, values) : {}), ...serverErrors };
  const busy = Boolean(pending);

  const change = (field, value) => {
    setValues((current) => ({ ...current, [field]: value }));
    setServerErrors((current) => {
      if (!(field in current)) return current;
      const { [field]: _dropped, ...rest } = current;
      return rest;
    });
    if (notice?.tone === 'success') setNotice(null);
  };

  const focusFirst = (problems) => {
    const field = REPORT_FIELDS[type].find((name) => problems[name]);
    if (field) setFocusRequest(field);
  };

  // The form's own check, before anything is sent: the API's rules, in its words.
  const checked = () => {
    setAttempted(true);
    const problems = validateReport(type, values);
    if (!Object.keys(problems).length) return true;
    setNotice({ tone: 'error', text: CHECK_FIELDS });
    focusFirst(problems);
    return false;
  };

  const saved = (data, text) => {
    const form = reportForm(type, data.report.fields);
    setReport(data.report);
    setValues(form);
    setBaseline(form);
    setAttempted(false);
    setServerErrors({});
    setBooking((current) => ({
      ...current,
      status: data.booking.status,
      has_report: true,
      report_version: data.report.version,
      report_due: false,
    }));
    setVersionsKey((key) => key + 1);
    setNotice({ tone: 'success', text });
  };

  const refused = (err) => {
    const problem = reportError(err, 'Could not save the report.');
    setServerErrors(problem.code === 'VALIDATION_ERROR' ? problem.fields : {});
    switch (problem.code) {
      case 'VALIDATION_ERROR':
        setAttempted(true);
        setNotice({ tone: 'error', text: problem.fields.non_field_errors || CHECK_FIELDS });
        focusFirst(problem.fields);
        return;
      case 'REPORT_EXISTS':
        // Submitted elsewhere (another tab): take it as the saved report, and keep what was typed here.
        api
          .get(tutorReportUrl(type, bookingId))
          .then((response) => {
            setReport(response.data);
            setBaseline(reportForm(type, response.data.fields));
            setBooking((current) => ({ ...current, status: 'COMPLETED', has_report: true,
              report_version: response.data.version, report_due: false }));
            setVersionsKey((key) => key + 1);
            setNotice({
              tone: 'info',
              text: `This report was already submitted (version ${response.data.version}). Your text is still below: review it and save it as an edit.`,
            });
          })
          .catch((reload) => setNotice({ tone: 'error', text: reportError(reload, problem.message).message }));
        return;
      case 'REPORT_VERSION_CONFLICT':
        setNotice({
          tone: 'error',
          text: `This report was saved somewhere else and is now version ${problem.version}. Reload to see that version — your unsaved text here will be replaced.`,
          action: { label: 'Reload the latest version', onClick: () => setDiscarding('reload') },
        });
        return;
      case 'NOT_STARTED':
      case 'BOOKING_CANCELLED':
      case 'BOOKING_RESCHEDULED':
        setNotice({ tone: 'error', text: REFUSALS[problem.code] });
        api.get(tutorBookingUrl(type, bookingId)).then((response) => setBooking(response.data), () => {});
        return;
      case 'NOT_FOUND':
        setGone(true);
        setNotice({ tone: 'error', text: REFUSALS.NOT_FOUND });
        return;
      default:
        setNotice({ tone: 'error', text: REFUSALS[problem.code] ?? problem.message });
    }
  };

  const submit = () => {
    setPending('submit');
    api
      .post(tutorReportUrl(type, bookingId), reportPayload(type, values))
      .then((response) =>
        saved(response.data, 'Report submitted. The booking is now completed, and you can still edit the report.')
      )
      .catch(refused)
      .finally(() => {
        setPending(null);
        setConfirming(false);
      });
  };

  const save = () => {
    setPending('save');
    api
      .put(tutorReportUrl(type, bookingId), { version: report.version, ...reportPayload(type, values) })
      .then((response) =>
        saved(
          response.data,
          response.data.changed
            ? `Changes saved as version ${response.data.report.version}.`
            : 'Nothing had changed, so no new version was saved.'
        )
      )
      .catch(refused)
      .finally(() => setPending(null));
  };

  const onSubmit = (event) => {
    event.preventDefault();
    if (busy || gone || !checked()) return;
    if (report) save();
    else setConfirming(true);
  };

  const preview = () => {
    if (busy || gone || !checked()) return;
    setPending('preview');
    api
      .post(tutorReportPreviewUrl(type, bookingId), reportPayload(type, values), { responseType: 'blob' })
      .then((response) => setPreviewUrl(URL.createObjectURL(response.data)))
      .catch(async (err) => {
        const problem = reportError(await withJsonBody(err), 'Could not make the preview.');
        if (problem.code === 'VALIDATION_ERROR') {
          setServerErrors(problem.fields);
          setNotice({ tone: 'error', text: CHECK_FIELDS });
          focusFirst(problem.fields);
        } else {
          setNotice({ tone: 'error', text: REFUSALS[problem.code] ?? (await reportPdfError(err)) });
        }
      })
      .finally(() => setPending(null));
  };

  const discard = () => {
    const reason = discarding;
    const proceed = leaving.current;
    leaving.current = null;
    setDiscarding(null);
    if (reason === 'leave') {
      // Thrown away now, not when the page goes: a Back or Forward that comes before the next page has
      // rendered keeps this page on screen, and must not bring the text back.
      setValues(baseline);
      setAttempted(false);
      setServerErrors({});
      setNotice(null);
      (proceed ?? leave)();
    } else {
      setNotice(null);
      setLoadKey((key) => key + 1);
    }
  };

  const Form = type === 'DIAGNOSTIC' ? DiagnosticReportForm : DemoReportForm;
  const tutorName = user?.full_name || user?.email || '';

  return (
    <div className="container mx-auto flex max-w-4xl flex-col gap-6 px-4 py-16">
      <div className="flex flex-col items-start gap-2">
        <Button variant="ghost" size="sm" className="-ml-2" onClick={back}>
          <ArrowLeftIcon />
          My Bookings
        </Button>
        <h1 className="text-2xl font-semibold">{TITLES[type]}</h1>
        <div className="flex flex-wrap items-center gap-2">
          <p className="text-muted-foreground text-sm">
            {booking.student_name} · {slotLabel(booking.slot)}
          </p>
          <BookingTypeBadge type={booking.booking_type} />
          <ReportStateBadge booking={booking} />
        </div>
      </div>

      <Notice notice={notice} onDismiss={() => setNotice(null)} />

      <PrintedDetails type={type} booking={booking} tutorName={tutorName} />

      {writable ? (
        <form id="report-form" noValidate onSubmit={onSubmit} className="rounded-lg border p-4 sm:p-6">
          <fieldset disabled={busy || gone} className="min-w-0">
            <legend className="sr-only">{TITLES[type]}</legend>
            <Form values={values} errors={errors} onChange={change} disabled={busy || gone} />
          </fieldset>
          <div className="mt-6 flex flex-col-reverse gap-2 border-t pt-4 sm:flex-row sm:items-center sm:justify-between">
            <Button type="button" variant="outline" onClick={preview} disabled={busy || gone}>
              {pending === 'preview' ? <Loader2Icon className="animate-spin" /> : <EyeIcon />}
              {pending === 'preview' ? 'Making the preview…' : 'Preview PDF'}
            </Button>
            <div className="flex flex-col-reverse items-stretch gap-2 sm:flex-row sm:items-center">
              {dirty ? (
                <span className="text-muted-foreground text-center text-xs sm:mr-2">Unsaved changes</span>
              ) : null}
              <Button type="button" variant="ghost" onClick={back} disabled={busy}>
                Cancel
              </Button>
              <Button type="submit" disabled={busy || gone || (Boolean(report) && !dirty)}>
                {report ? (pending === 'save' ? 'Saving…' : 'Save changes') : 'Submit report'}
              </Button>
            </div>
          </div>
        </form>
      ) : (
        <div className="bg-muted text-muted-foreground flex flex-col items-start gap-3 rounded-md px-3 py-2 text-sm">
          <p>{CLOSED[state.key]}</p>
          {/* Started here, the form opens at once: the booking as the API answered now has its start. */}
          <StartBookingButton
            booking={booking}
            onStarted={setBooking}
            onRefresh={() => setLoadKey((key) => key + 1)}
          />
        </div>
      )}

      {report ? (
        <section className="flex flex-col gap-6 rounded-lg border p-4 sm:p-6">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-base font-semibold">Saved report</h2>
              <p className="text-muted-foreground text-sm">Version {report.version} is the current one.</p>
            </div>
            <PdfDownloadButton
              url={reportPdfUrl(tutorReportUrl(type, bookingId))}
              fallbackName={reportPdfFallbackName(type)}
            />
          </div>
          <ReportVersions type={type} reportUrl={tutorReportUrl(type, bookingId)} reloadKey={versionsKey} />
        </section>
      ) : null}

      <FormDialog
        open={confirming}
        onOpenChange={(open) => {
          if (!busy) setConfirming(open);
        }}
        title="Submit this report?"
        description="Submitting completes this booking. You can still edit the report later; each edit is kept as a new version."
        confirmLabel="Submit report"
        pendingLabel="Submitting…"
        pending={pending === 'submit'}
        onConfirm={submit}
        onCloseAutoFocus={(event) => {
          if (focusRequest) event.preventDefault();
        }}
      />

      <FormDialog
        open={Boolean(discarding)}
        onOpenChange={(open) => {
          if (open) return;
          leaving.current = null;
          setDiscarding(null);
        }}
        title={discarding === 'reload' ? 'Reload the latest version?' : 'Discard your changes?'}
        description={
          discarding === 'reload'
            ? 'Your unsaved text in this form will be replaced by the version saved most recently.'
            : 'Your changes to this report have not been saved. They will be lost.'
        }
        confirmLabel={discarding === 'reload' ? 'Reload' : 'Discard changes'}
        confirmVariant="destructive"
        cancelLabel="Keep editing"
        onConfirm={discard}
      />

      <ReportPreviewDialog
        url={previewUrl}
        onOpenChange={(open) => {
          if (!open) setPreviewUrl(null);
        }}
      />
    </div>
  );
}
