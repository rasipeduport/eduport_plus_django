import { useEffect, useState } from 'react';
import { CalendarCheckIcon, ChevronDownIcon, ClipboardListIcon, HistoryIcon, LockIcon, MessageSquareTextIcon } from 'lucide-react';

import api from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { Textarea } from '@/components/ui/textarea';
import { REDEMO_REMARKS_MAX_LENGTH, bookingError, redemoRemarksUrl } from '@/lib/bookings';
import { istMoment } from '@/lib/communications';
import { formatDay, slotLabel } from '@/lib/enquiries';
import { bookingReportUrl, reportPdfUrl } from '@/lib/reports';
import { liveBooking, reportText, who } from '@/lib/redemo-workspace';
import { cn } from '@/lib/utils';
import { ParentConfirmationBadge } from '@/components/communications/communication-badges';
import { ReportFieldsView } from '@/components/reports/report-fields-view';
import { ViewPdfButton } from '@/components/reports/view-pdf-button';
import { BookingStateBadge, RedemoStatusBadge } from '../booking-badges';
import { MeetLink } from '../meet-link';
import { StudentTimeLine } from '../student-time';
import { Field, Fields, WorkspaceCard } from './parts';

/** A slot in IST with the student's own time under it. */
function When({ slot, zone, children }) {
  return (
    <span className="flex flex-col">
      <span className="flex flex-wrap items-center gap-2">
        {slotLabel(slot)}
        {children}
      </span>
      <StudentTimeLine startsAt={slot?.starts_at} timezone={zone} />
    </span>
  );
}

/** The original Demo's report, as it prints, read on demand from its booking's report route. */
function OriginalReport({ booking, versionAtRequest }) {
  const [open, setOpen] = useState(false);
  const [report, setReport] = useState(null);
  const [failure, setFailure] = useState(null);
  useEffect(() => {
    if (!open || !booking.has_report || report) return undefined;
    let active = true;
    setFailure(null);
    api
      .get(bookingReportUrl('DEMO', booking.id))
      .then((response) => {
        if (!active) return;
        setReport(response.data);
        setFailure(null);
      })
      .catch((err) => {
        if (active) setFailure(bookingError(err, 'Could not load the report.').message);
      });
    return () => {
      active = false;
    };
  }, [open, booking.id, booking.has_report, report]);

  if (!booking.has_report) return <p className="text-muted-foreground text-sm">No report on the original Demo.</p>;
  const changed = versionAtRequest && booking.report_version !== versionAtRequest;
  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="font-medium">Report · version {booking.report_version}</span>
        {versionAtRequest ? (
          <span className="text-muted-foreground text-xs">
            {changed ? `· version ${versionAtRequest} when the Re-Demo was requested` : '· as it was when requested'}
          </span>
        ) : null}
        <span className="ml-auto flex flex-wrap gap-2">
          <Button variant="ghost" size="sm" onClick={() => setOpen((value) => !value)} aria-expanded={open}>
            {open ? 'Hide preview' : 'Preview'}
            <ChevronDownIcon className={cn('transition-transform', open && 'rotate-180')} />
          </Button>
          <ViewPdfButton url={reportPdfUrl(bookingReportUrl('DEMO', booking.id))} title="Original Demo report" size="sm" />
        </span>
      </div>
      {open ? (
        failure ? (
          <p className="text-destructive text-sm">{failure}</p>
        ) : report ? (
          <div className="bg-muted/20 rounded-md border p-3">
            <ReportFieldsView type="DEMO" report={report} />
          </div>
        ) : (
          <Skeleton className="h-24" />
        )
      ) : null}
    </div>
  );
}

/** The remarks for the Re-Demo tutor, edited in place (PUT …/remarks/) until the Re-Demo starts. */
function RemarksEditor({ redemo, onSaved }) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(redemo.admin_remarks ?? '');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState(null);
  const [saved, setSaved] = useState(false);

  // Another request, or the same one read again, starts from what the API holds.
  const [prevKey, setPrevKey] = useState(`${redemo.id}|${redemo.remarks_updated_at}`);
  const key = `${redemo.id}|${redemo.remarks_updated_at}`;
  if (key !== prevKey) {
    setPrevKey(key);
    setValue(redemo.admin_remarks ?? '');
  }

  const tooLong = value.trim().length > REDEMO_REMARKS_MAX_LENGTH;
  const unchanged = value.trim() === (redemo.admin_remarks ?? '');
  const lastSaved = redemo.remarks_updated_at
    ? `Last saved ${formatDay(redemo.remarks_updated_at)} by ${redemo.remarks_updated_by?.full_name ?? '—'}`
    : 'Shown to the Re-Demo tutor, not the BDE. Locked once the Re-Demo starts.';

  async function save() {
    setPending(true);
    setError(null);
    setSaved(false);
    try {
      const response = await api.put(redemoRemarksUrl(redemo.id), { remarks: value.trim() });
      setSaved(true);
      setEditing(false);
      onSaved?.(response.data);
    } catch (err) {
      setError(bookingError(err, 'Could not save the remarks.').message);
    } finally {
      setPending(false);
    }
  }

  if (!editing) {
    return (
      <div className="flex flex-col gap-2">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <p className="min-w-0 flex-1 text-sm whitespace-pre-wrap">
            {redemo.admin_remarks || <span className="text-muted-foreground">No remarks yet.</span>}
          </p>
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              setEditing(true);
              setSaved(false);
            }}
          >
            {redemo.admin_remarks ? 'Edit remarks' : 'Add remarks'}
          </Button>
        </div>
        <p className="text-muted-foreground text-xs">{lastSaved}</p>
        {saved ? (
          <p role="status" className="text-success text-xs">
            Remarks saved.
          </p>
        ) : null}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      <Textarea
        value={value}
        onChange={(event) => setValue(event.target.value)}
        rows={4}
        aria-label="Remarks for the tutor"
        aria-invalid={tooLong || undefined}
        placeholder="What the tutor should know before teaching this Re-Demo. The BDE never sees them."
        disabled={pending}
        autoFocus
      />
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className={tooLong ? 'text-destructive text-xs' : 'text-muted-foreground text-xs'}>
          {value.trim().length}/{REDEMO_REMARKS_MAX_LENGTH} characters · {lastSaved}
        </p>
        <span className="flex gap-2">
          <Button
            variant="ghost"
            size="sm"
            disabled={pending}
            onClick={() => {
              setEditing(false);
              setValue(redemo.admin_remarks ?? '');
              setError(null);
            }}
          >
            Cancel
          </Button>
          <Button size="sm" onClick={save} disabled={pending || unchanged || tooLong}>
            {pending ? 'Saving…' : 'Save remarks'}
          </Button>
        </span>
      </div>
      {error ? <p className="text-destructive text-sm">{error}</p> : null}
    </div>
  );
}

/**
 * The workspace's Overview tab: the request (why, by whom, when, and how it
 * was closed), the Demo it repeats with its tutor and report (previewed in
 * place or read as a PDF), the Re-Demo as it stands now -- booked, with its
 * student's time, tutor, Meet link and the parent's answer, or why nothing
 * is booked -- and the remarks for its tutor: added or edited while the API
 * allows (`actions.edit_remarks`), read-only once locked. `onSaved` is the
 * request as the API answered a save; `onOpenBooking(id)` opens a Demo in
 * its own workspace.
 */
export function RedemoOverview({ redemo, onSaved, onOpenBooking }) {
  const actions = redemo.actions ?? {};
  const original = redemo.original;
  const booking = liveBooking(redemo);
  const zone = redemo.student_timezone;

  return (
    <div className="flex flex-col gap-4">
      <div className="grid gap-4 xl:grid-cols-2">
        <WorkspaceCard icon={ClipboardListIcon} title="Request details">
          <Fields>
            <Field label="Request">Re-Demo {redemo.number ?? 1}</Field>
            <Field label="Requested by">{who(redemo.requested_by)}</Field>
            <Field label="Requested on">{istMoment(redemo.requested_at)}</Field>
            <Field label="Reason">
              <span className="whitespace-pre-wrap">{redemo.reason}</span>
            </Field>
            {redemo.closed ? (
              <Field label="Closed">
                {istMoment(redemo.closed.at)} by {who(redemo.closed.by)}
                <span className="text-muted-foreground block font-normal">{redemo.closed.reason?.label}</span>
              </Field>
            ) : null}
          </Fields>
        </WorkspaceCard>

        <WorkspaceCard
          icon={HistoryIcon}
          title="Original Demo"
          action={
            <Button variant="link" size="sm" className="h-auto p-0" onClick={() => onOpenBooking(original.id)}>
              Open booking
            </Button>
          }
        >
          <Fields>
            <Field label="When">
              <When slot={original.slot} zone={zone}>
                <BookingStateBadge booking={original} />
              </When>
            </Field>
            <Field label="Tutor">{original.tutor?.full_name}</Field>
          </Fields>
          <div className="border-t pt-3">
            <OriginalReport booking={original} versionAtRequest={redemo.original_report?.version_at_request} />
          </div>
        </WorkspaceCard>
      </div>

      <WorkspaceCard
        icon={CalendarCheckIcon}
        title={`Re-Demo ${redemo.number ?? ''}`.trim()}
        action={
          <span className="flex items-center gap-3">
            <RedemoStatusBadge status={redemo.status} />
            {booking ? (
              <Button variant="link" size="sm" className="h-auto p-0" onClick={() => onOpenBooking(booking.id)}>
                Open booking
              </Button>
            ) : null}
          </span>
        }
      >
        {booking ? (
          <Fields>
            <Field label="When">
              <When slot={booking.slot} zone={zone}>
                <BookingStateBadge booking={booking} />
              </When>
            </Field>
            <Field label="Tutor">{booking.tutor?.full_name}</Field>
            <Field label="Meet link">
              <MeetLink link={booking.tutor_meet_link} />
            </Field>
            {booking.status === 'BOOKED' ? (
              <Field label="Parent">
                <ParentConfirmationBadge status={booking.parent_confirmation} booked />
              </Field>
            ) : null}
            <Field label="Report">
              {reportText(booking)}
              {booking.has_report && booking.report_shared ? (
                <span className="text-muted-foreground font-normal"> · shared</span>
              ) : null}
            </Field>
          </Fields>
        ) : (
          <p className="text-muted-foreground text-sm">
            {redemo.status === 'CLOSED'
              ? 'Closed: nothing is scheduled. Reopen it to schedule the Re-Demo.'
              : actions.schedule
                ? 'Not scheduled yet. Choose the time and the tutor on the Scheduling tab; the BDE then tells the parent.'
                : 'Not scheduled yet: an administrator chooses the time and the tutor.'}
          </p>
        )}
      </WorkspaceCard>

      <WorkspaceCard
        icon={MessageSquareTextIcon}
        title="Remarks for the tutor"
        action={
          redemo.remarks_locked ? (
            <span className="text-muted-foreground flex items-center gap-1.5 text-xs">
              <LockIcon className="size-3.5" aria-hidden="true" />
              Locked
            </span>
          ) : null
        }
      >
        {actions.edit_remarks ? (
          <RemarksEditor redemo={redemo} onSaved={onSaved} />
        ) : (
          <div className="flex flex-col gap-1">
            <p className="text-sm whitespace-pre-wrap">
              {redemo.admin_remarks || <span className="text-muted-foreground">No remarks.</span>}
            </p>
            {redemo.remarks_locked ? (
              <p className="text-muted-foreground text-xs">Locked: the Re-Demo has started, so they stay as the tutor read them.</p>
            ) : null}
          </div>
        )}
      </WorkspaceCard>
    </div>
  );
}
