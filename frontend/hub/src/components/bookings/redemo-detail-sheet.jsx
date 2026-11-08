import { useEffect, useState } from 'react';
import {
  CalendarClockIcon,
  CalendarX2Icon,
  CheckIcon,
  ChevronDownIcon,
  MessageCircleIcon,
  RotateCcwIcon,
  SearchXIcon,
  UserRoundCogIcon,
} from 'lucide-react';

import api from '@/lib/api';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { Skeleton } from '@/components/ui/skeleton';
import { Textarea } from '@/components/ui/textarea';
import { REDEMO_REMARKS_MAX_LENGTH, bookingError, redemoRemarksUrl, redemoUrl } from '@/lib/bookings';
import { istMoment } from '@/lib/communications';
import { formatDay, slotLabel, whatsAppUrl } from '@/lib/enquiries';
import { bookingReportUrl, reportPdfUrl } from '@/lib/reports';
import { savedTimezoneLabel } from '@/lib/timezone';
import { cn } from '@/lib/utils';
import { ParentConfirmationBadge } from '@/components/communications/communication-badges';
import { ReportFieldsView } from '@/components/reports/report-fields-view';
import { ViewPdfButton } from '@/components/reports/view-pdf-button';
import { BookingStateBadge, RedemoStatusBadge } from './booking-badges';
import { MeetLink } from './meet-link';
import { StudentTimeLine } from './student-time';

function Section({ title, action, children, className }) {
  return (
    <section className={cn('rounded-lg border p-4', className)}>
      <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold">{title}</h3>
        {action}
      </div>
      {children}
    </section>
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

const who = (person) => (person ? [person.full_name, person.role_label].filter(Boolean).join(' · ') : '—');
const reportText = (booking) => (booking.has_report ? `Version ${booking.report_version}` : 'Not submitted yet');

/** Where the request has got to (the API's `progress`): each step done, with when, or still to come. */
function Progress({ steps }) {
  return (
    <ol className="grid grid-cols-3 gap-x-2 gap-y-3 sm:grid-cols-6" aria-label="Progress">
      {steps.map((step) => (
        <li key={step.key} className="flex min-w-0 flex-col items-center gap-1 text-center">
          <span
            className={cn(
              'flex size-6 items-center justify-center rounded-full border text-xs',
              step.done ? 'bg-primary text-primary-foreground border-primary' : 'text-muted-foreground'
            )}
            aria-hidden="true"
          >
            {step.done ? <CheckIcon className="size-3.5" /> : null}
          </span>
          <span className={cn('text-xs leading-tight', step.done ? 'font-medium' : 'text-muted-foreground')}>
            {step.label}
            <span className="sr-only">{step.done ? ', done' : ', not yet'}</span>
          </span>
          {step.at ? <span className="text-muted-foreground text-[11px] leading-tight">{formatDay(step.at)}</span> : null}
        </li>
      ))}
    </ol>
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

  if (!booking.has_report) return <p className="text-muted-foreground py-2 text-sm">No report on the original Demo.</p>;
  const changed = versionAtRequest && booking.report_version !== versionAtRequest;
  return (
    <div className="flex flex-col gap-2 py-2">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="font-medium">Version {booking.report_version}</span>
        {versionAtRequest ? (
          <span className="text-muted-foreground text-xs">
            {changed ? `· version ${versionAtRequest} when the Re-Demo was requested` : '· as it was when requested'}
          </span>
        ) : null}
        <Button variant="ghost" size="sm" className="ml-auto" onClick={() => setOpen((value) => !value)} aria-expanded={open}>
          {open ? 'Hide report' : 'Show report'}
          <ChevronDownIcon className={cn('transition-transform', open && 'rotate-180')} />
        </Button>
        <ViewPdfButton url={reportPdfUrl(bookingReportUrl('DEMO', booking.id))} title="Original Demo report" size="sm" />
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

function RemarksEditor({ redemo, onSaved }) {
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

  async function save() {
    setPending(true);
    setError(null);
    setSaved(false);
    try {
      const response = await api.put(redemoRemarksUrl(redemo.id), { remarks: value.trim() });
      setSaved(true);
      onSaved?.(response.data);
    } catch (err) {
      setError(bookingError(err, 'Could not save the remarks.').message);
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="flex flex-col gap-2 pt-2">
      <Textarea
        value={value}
        onChange={(event) => {
          setValue(event.target.value);
          setSaved(false);
        }}
        rows={3}
        aria-label="Remarks for the tutor"
        aria-invalid={tooLong || undefined}
        placeholder="What the tutor should know before teaching this Re-Demo. The BDE never sees them."
        disabled={pending}
      />
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className={tooLong ? 'text-destructive text-xs' : 'text-muted-foreground text-xs'}>
          {redemo.remarks_updated_at
            ? `Last saved ${formatDay(redemo.remarks_updated_at)} by ${redemo.remarks_updated_by?.full_name ?? '—'}`
            : 'Shown to the Re-Demo tutor, not the BDE. Locked once the Re-Demo starts.'}
        </p>
        <Button size="sm" onClick={save} disabled={pending || unchanged || tooLong}>
          {pending ? 'Saving…' : 'Save remarks'}
        </Button>
      </div>
      {error ? <p className="text-destructive text-sm">{error}</p> : null}
      {saved ? (
        <p role="status" className="text-success text-xs">
          Remarks saved.
        </p>
      ) : null}
    </div>
  );
}

/** The parent messages for the scheduled Re-Demo, filled in to send on WhatsApp by hand (the API's parent_messages). */
function ParentMessages({ redemo }) {
  const messages = redemo.parent_messages;
  const lead = redemo.lead ?? {};
  if (!messages) return null;
  const confirmed = redemo.booking?.parent_confirmation === 'CONFIRMED';
  const message = confirmed ? messages.confirmed : messages.confirmation_request;
  const url = message?.text ? whatsAppUrl(lead.phone_dial_code, lead.phone_number, message.text) : null;
  return (
    <div className="flex flex-col gap-1 py-2 text-sm">
      <p className="text-muted-foreground text-xs">
        {redemo.owner_bde
          ? `${redemo.owner_bde.full_name} tells the parent the time. Nothing is sent automatically.`
          : 'No BDE owns this lead: tell the parent the time yourself. Nothing is sent automatically.'}
      </p>
      {url ? (
        <Button variant="outline" size="sm" className="self-start" asChild>
          <a href={url} target="_blank" rel="noopener noreferrer">
            <MessageCircleIcon />
            {confirmed ? 'WhatsApp the class details' : 'WhatsApp the parent to confirm'}
          </a>
        </Button>
      ) : message ? (
        <p className="text-muted-foreground text-xs">The message needs: {message.missing.join(', ').replace(/_/g, ' ')}.</p>
      ) : null}
    </div>
  );
}

function DetailSkeleton() {
  return (
    <div className="flex flex-col gap-4" aria-busy="true">
      <Skeleton className="h-16" />
      <Skeleton className="h-32" />
      <Skeleton className="h-40" />
    </div>
  );
}

/**
 * One Re-Demo request in full (GET /api/bookings/redemos/<id>/), laid out by
 * what an administrator does with it: where it has got to (Progress), the
 * request -- why, by whom, when -- then the Re-Demo booked for it with its
 * student's time, tutor, Meet link and the parent's answer, and what may be
 * done with it in place (`onBookingAction(action, bookingId)`: reschedule,
 * change_tutor, cancel; the API's booking_actions) or in its own workspace
 * (`onOpenBooking`), the earlier attempts, the original Demo with its report,
 * the student and parent, the remarks for the tutor (locked once it starts),
 * and the lead's chain of Re-Demos (`onOpenRedemo`). One main action heads
 * it, as the API allows: Schedule (`onSchedule`) or Reopen (`onReopen`);
 * Close (`onClose`) sits at its foot. `refresh` is the detail as the page read
 * it after a change.
 */
export function RedemoDetailSheet({
  redemoId,
  open,
  onOpenChange,
  reloadKey,
  onSchedule,
  onClose,
  onReopen,
  onBookingAction,
  onOpenBooking,
  onOpenRedemo,
}) {
  const [redemo, setRedemo] = useState(null);
  const [failure, setFailure] = useState(null);
  const [retryKey, setRetryKey] = useState(0);

  useEffect(() => {
    if (!open || !redemoId) return undefined;
    let active = true;
    setFailure(null);
    api
      .get(redemoUrl(redemoId))
      .then((response) => {
        if (active) setRedemo(response.data);
      })
      .catch((err) => {
        if (active) setFailure(bookingError(err, 'Could not load this Re-Demo request.'));
      });
    return () => {
      active = false;
    };
  }, [open, redemoId, reloadKey, retryKey]);

  // Nothing of another request shows while this one loads.
  const shown = redemo && redemo.id === redemoId ? redemo : null;
  const actions = shown?.actions ?? {};
  const bookingActions = shown?.booking_actions ?? null;

  let primary = null;
  if (actions.schedule) {
    primary = (
      <Button size="sm" onClick={() => onSchedule?.(shown)}>
        <CalendarClockIcon />
        Schedule Re-Demo
      </Button>
    );
  } else if (actions.reopen) {
    primary = (
      <Button size="sm" onClick={() => onReopen?.(shown)}>
        <RotateCcwIcon />
        Reopen request
      </Button>
    );
  }

  let body;
  if (failure && failure.status === 404) {
    body = (
      <div className="flex flex-col items-center gap-2 rounded-md border px-6 py-12 text-center">
        <SearchXIcon className="text-muted-foreground size-8" />
        <p className="font-medium">Re-Demo request not found</p>
        <p className="text-muted-foreground text-sm">It may be a mistyped link.</p>
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
    body = <DetailSkeleton />;
  } else {
    const lead = shown.lead ?? {};
    const booking = shown.booking;
    const live = booking && (booking.status === 'BOOKED' || booking.status === 'COMPLETED' || booking.status === 'REDEMO_REQUIRED');
    const earlier = (shown.bookings ?? []).slice(0, live ? -1 : undefined);
    body = (
      <div className="flex flex-col gap-4">
        <Section title="Progress">
          <div className="pt-2">
            <Progress steps={shown.progress ?? []} />
          </div>
          {shown.closed ? (
            <p className="bg-muted/40 mt-3 rounded-md px-3 py-2 text-sm">
              Closed {istMoment(shown.closed.at)} by {who(shown.closed.by)} · {shown.closed.reason?.label}
            </p>
          ) : null}
        </Section>

        <Section title="Request">
          <dl className="divide-y">
            <Detail label="Reason">
              <span className="whitespace-pre-wrap">{shown.reason}</span>
            </Detail>
            <Detail label="Requested by">{who(shown.requested_by)}</Detail>
            <Detail label="Requested on">{istMoment(shown.requested_at)}</Detail>
          </dl>
        </Section>

        <Section title={`Re-Demo ${shown.number ?? ''}`.trim()}>
          {live ? (
            <>
              <dl className="divide-y">
                <Detail label="When">
                  <span className="flex flex-col">
                    <span className="flex flex-wrap items-center gap-2">
                      {slotLabel(booking.slot)}
                      <BookingStateBadge booking={booking} />
                    </span>
                    <StudentTimeLine startsAt={booking.slot?.starts_at} timezone={shown.student_timezone} />
                  </span>
                </Detail>
                <Detail label="Tutor">{booking.tutor?.full_name}</Detail>
                <Detail label="Meet link">
                  <MeetLink link={booking.tutor_meet_link} />
                </Detail>
                {booking.status === 'BOOKED' ? (
                  <Detail label="Parent">
                    <ParentConfirmationBadge status={booking.parent_confirmation} booked />
                  </Detail>
                ) : null}
                <Detail label="Report">{reportText(booking)}</Detail>
              </dl>
              <ParentMessages redemo={shown} />
              <div className="flex flex-wrap gap-2 pt-2">
                {bookingActions?.reschedule ? (
                  <Button variant="outline" size="sm" onClick={() => onBookingAction?.('reschedule', booking.id)}>
                    <CalendarClockIcon />
                    Reschedule
                  </Button>
                ) : null}
                {bookingActions?.change_tutor ? (
                  <Button variant="outline" size="sm" onClick={() => onBookingAction?.('change_tutor', booking.id)}>
                    <UserRoundCogIcon />
                    Change tutor
                  </Button>
                ) : null}
                {bookingActions?.cancel ? (
                  <Button variant="outline" size="sm" onClick={() => onBookingAction?.('cancel', booking.id)}>
                    <CalendarX2Icon />
                    Cancel Re-Demo
                  </Button>
                ) : null}
                <Button variant="link" size="sm" className="h-auto px-0" onClick={() => onOpenBooking?.(booking.id)}>
                  Open booking
                </Button>
              </div>
            </>
          ) : (
            <p className="text-muted-foreground py-2 text-sm">
              {shown.status === 'CLOSED'
                ? 'Closed: nothing is scheduled. Reopen it to schedule the Re-Demo.'
                : actions.schedule
                  ? 'Not scheduled yet. Choose the time and the tutor; the BDE then tells the parent.'
                  : 'Not scheduled yet: an administrator chooses the time and the tutor.'}
            </p>
          )}
          {earlier.length ? (
            <details className="mt-2 text-sm">
              <summary className="text-muted-foreground cursor-pointer text-xs">
                Earlier {earlier.length === 1 ? 'attempt' : `attempts (${earlier.length})`}
              </summary>
              <ul className="mt-2 flex flex-col gap-2">
                {earlier.map((item) => (
                  <li key={item.id} className="flex flex-wrap items-center gap-2">
                    <span>{slotLabel(item.slot)}</span>
                    <BookingStateBadge booking={item} />
                    {item.cancel_reason ? <span className="text-muted-foreground text-xs">{item.cancel_reason.label}</span> : null}
                    <span className="text-muted-foreground text-xs">{item.tutor ? `· ${item.tutor.full_name}` : ''}</span>
                    <Button variant="link" size="sm" className="h-auto p-0" onClick={() => onOpenBooking?.(item.id)}>
                      Open
                    </Button>
                  </li>
                ))}
              </ul>
            </details>
          ) : null}
        </Section>

        <Section
          title="Original Demo"
          action={
            <Button variant="link" size="sm" className="h-auto p-0" onClick={() => onOpenBooking?.(shown.original.id)}>
              Open booking
            </Button>
          }
        >
          <dl className="divide-y">
            <Detail label="When">
              <span className="flex flex-col">
                <span>{slotLabel(shown.original.slot)}</span>
                <StudentTimeLine startsAt={shown.original.slot?.starts_at} timezone={shown.student_timezone} />
              </span>
            </Detail>
            <Detail label="Tutor">{shown.original.tutor?.full_name}</Detail>
          </dl>
          <OriginalReport booking={shown.original} versionAtRequest={shown.original_report?.version_at_request} />
        </Section>

        <Section title="Student and parent">
          <dl className="divide-y">
            <Detail label="Student">{[shown.student_name, lead.grade].filter(Boolean).join(' · ')}</Detail>
            <Detail label="Syllabus">{lead.syllabus}</Detail>
            <Detail label="School">{lead.school_name}</Detail>
            <Detail label="Country">{lead.country}</Detail>
            <Detail label="Time zone">
              <span className={lead.student_timezone ? undefined : 'text-muted-foreground font-normal'}>
                {lead.student_timezone ? savedTimezoneLabel(lead.student_timezone) : 'Not set (times read in IST)'}
              </span>
            </Detail>
            <Detail label="Parent">{shown.parent_name}</Detail>
            <Detail label="Phone">
              <span className="tabular-nums">{shown.phone}</span>
            </Detail>
            <Detail label="Lead BDE">{lead.owner_bde?.full_name ?? 'No BDE'}</Detail>
          </dl>
        </Section>

        <Section title="Remarks for the tutor">
          {actions.edit_remarks ? (
            <RemarksEditor redemo={shown} onSaved={setRedemo} />
          ) : (
            <div className="flex flex-col gap-1 py-2">
              <p className="text-sm whitespace-pre-wrap">
                {shown.admin_remarks || <span className="text-muted-foreground">No remarks.</span>}
              </p>
              {shown.remarks_locked ? (
                <p className="text-muted-foreground text-xs">Locked: the Re-Demo has started, so they stay as the tutor read them.</p>
              ) : null}
            </div>
          )}
        </Section>

        {(shown.chain ?? []).length > 1 ? (
          <Section title="Re-Demo chain">
            <ol className="flex flex-col gap-2 py-2 text-sm" aria-label="Re-Demo chain">
              {shown.chain.map((link, index) => (
                <li key={link.id} className="flex flex-wrap items-center justify-between gap-2">
                  <span className="min-w-0">
                    <span className="font-medium">Re-Demo {index + 1}</span>
                    <span className="text-muted-foreground">
                      {' '}
                      · of {slotLabel(link.original.slot)}
                      {/* A cancelled attempt is not the Re-Demo: it waits to be scheduled again. */}
                      {link.booking && link.booking.status !== 'CANCELLED' ? ` → ${slotLabel(link.booking.slot)}` : ''}
                    </span>
                  </span>
                  <span className="flex items-center gap-2">
                    <RedemoStatusBadge status={link.status} />
                    {link.current ? (
                      <Badge variant="outline">This request</Badge>
                    ) : (
                      <Button variant="link" size="sm" className="h-auto p-0" onClick={() => onOpenRedemo?.(link.id)}>
                        Open
                      </Button>
                    )}
                  </span>
                </li>
              ))}
            </ol>
          </Section>
        ) : null}

        {actions.close ? (
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-dashed p-3">
            <p className="text-muted-foreground text-xs">Parent declined, or no longer needed? Close the request.</p>
            <Button variant="outline" size="sm" onClick={() => onClose?.(shown)}>
              Close request
            </Button>
          </div>
        ) : null}
      </div>
    );
  }

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full sm:max-w-xl">
        <SheetHeader>
          <SheetTitle>{shown ? shown.student_name : 'Re-Demo request'}</SheetTitle>
          <SheetDescription>
            {shown
              ? [shown.lead?.grade, shown.lead?.syllabus, shown.owner_bde ? `BDE: ${shown.owner_bde.full_name}` : 'No BDE']
                  .filter(Boolean)
                  .join(' · ')
              : 'Loading…'}
          </SheetDescription>
          {shown ? (
            <div className="flex flex-wrap items-center gap-2 pt-1">
              <RedemoStatusBadge status={shown.status} />
              {(shown.attention ?? []).map((flag) => (
                <Badge key={flag.code} variant="warning">
                  {flag.label}
                </Badge>
              ))}
              {primary ? <span className="ml-auto">{primary}</span> : null}
            </div>
          ) : null}
        </SheetHeader>
        <div className="min-h-0 flex-1 overflow-y-auto px-4 pb-4">{body}</div>
      </SheetContent>
    </Sheet>
  );
}
