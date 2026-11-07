import { useEffect, useState } from 'react';
import { SearchXIcon } from 'lucide-react';

import api from '@/lib/api';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { Skeleton } from '@/components/ui/skeleton';
import { Textarea } from '@/components/ui/textarea';
import { REDEMO_REMARKS_MAX_LENGTH, bookingError, redemoRemarksUrl, redemoUrl } from '@/lib/bookings';
import { formatDay, slotLabel } from '@/lib/enquiries';
import { BookingStateBadge, RedemoStatusBadge } from './booking-badges';
import { MeetLink } from './meet-link';

function Section({ title, action, children }) {
  return (
    <section className="rounded-lg border p-4">
      <div className="mb-1 flex items-center justify-between gap-2">
        <h3 className="text-sm font-semibold">{title}</h3>
        {action}
      </div>
      <dl className="divide-y">{children}</dl>
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

function reportText(booking) {
  return booking.has_report ? `Submitted · version ${booking.report_version}` : 'Not submitted yet';
}

/** A Demo of the chain: when, where it stands, who teaches it and its report, with a way to open it in full. */
function DemoLink({ booking, onOpenBooking, label }) {
  return (
    <div className="flex flex-col gap-1">
      <span className="flex flex-wrap items-center gap-2">
        <span>{slotLabel(booking.slot)}</span>
        <BookingStateBadge booking={booking} />
      </span>
      <span className="text-muted-foreground text-xs font-normal">
        {booking.tutor ? `Tutor: ${booking.tutor.full_name}` : 'No tutor'} · Report: {reportText(booking)}
      </span>
      <Button
        variant="link"
        size="sm"
        className="h-auto self-start p-0"
        onClick={() => onOpenBooking?.(booking.id)}
        aria-label={label}
      >
        Open booking
      </Button>
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
            : 'Shown to the Re-Demo tutor, not the BDE.'}
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

function DetailSkeleton() {
  return (
    <div className="flex flex-col gap-4" aria-busy="true">
      <Skeleton className="h-32" />
      <Skeleton className="h-40" />
      <Skeleton className="h-32" />
    </div>
  );
}

/**
 * One Re-Demo request in full (GET /api/bookings/redemos/<id>/): why and by
 * whom it was asked for, the Re-Demo an administrator scheduled -- its tutor,
 * slot and Meet link, or Schedule Re-Demo when the API's actions.schedule
 * allows (`onSchedule`) -- and the original Demo, each with its own report
 * and a way to open it (`onOpenBooking`: a scheduled Re-Demo is moved,
 * reassigned or cancelled from its booking), the remarks for its tutor
 * (actions.edit_remarks) and the lead's whole chain of Re-Demos
 * (`onOpenRedemo`).
 */
export function RedemoDetailSheet({ redemoId, open, onOpenChange, reloadKey, onSchedule, onOpenBooking, onOpenRedemo }) {
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
    const earlier = (shown.bookings ?? []).slice(0, -1);
    body = (
      <div className="flex flex-col gap-4">
        <Section title="Request">
          <Detail label="Status">
            <RedemoStatusBadge status={shown.status} />
          </Detail>
          <Detail label="Reason">
            <span className="whitespace-pre-wrap">{shown.reason}</span>
          </Detail>
          <Detail label="Requested by">{shown.requested_by?.full_name}</Detail>
          <Detail label="Requested on">{formatDay(shown.requested_at)}</Detail>
        </Section>

        <Section
          title={`Re-Demo ${shown.number ?? ''}`.trim()}
          action={
            shown.actions?.schedule ? (
              <Button size="sm" onClick={() => onSchedule?.(shown)}>
                Schedule Re-Demo
              </Button>
            ) : null
          }
        >
          {shown.booking ? (
            <>
              <Detail label="Booking">
                <DemoLink booking={shown.booking} onOpenBooking={onOpenBooking} label="Open the Re-Demo booking" />
              </Detail>
              <Detail label="Meet link">
                <MeetLink link={shown.booking.tutor_meet_link} />
              </Detail>
            </>
          ) : (
            <p className="text-muted-foreground py-2 text-sm">
              {shown.actions?.schedule
                ? 'Not scheduled yet. Choose the tutor, date and time; the BDE then tells the parent.'
                : 'Not scheduled yet: an administrator chooses the tutor, date and time.'}
            </p>
          )}
          {earlier.map((booking) => (
            <Detail key={booking.id} label="Earlier">
              <DemoLink booking={booking} onOpenBooking={onOpenBooking} label="Open an earlier Re-Demo booking" />
            </Detail>
          ))}
        </Section>

        <Section title="Original Demo">
          <Detail label="Demo">
            <DemoLink booking={shown.original} onOpenBooking={onOpenBooking} label="Open the original Demo" />
          </Detail>
          <Detail label="Report">
            {shown.original_report
              ? `Version ${shown.original_report.version}, by ${shown.original_report.submitted_by?.full_name ?? '—'}`
              : null}
          </Detail>
        </Section>

        <Section title="Student and parent">
          <Detail label="Student">{[shown.student_name, shown.grade].filter(Boolean).join(' · ')}</Detail>
          <Detail label="School">{lead.school_name}</Detail>
          <Detail label="Parent">{shown.parent_name}</Detail>
          <Detail label="Phone">
            <span className="tabular-nums">{shown.phone}</span>
          </Detail>
          <Detail label="Lead BDE">{lead.owner_bde?.full_name}</Detail>
        </Section>

        <Section title="Remarks for the tutor">
          {shown.actions?.edit_remarks ? (
            <RemarksEditor redemo={shown} onSaved={setRedemo} />
          ) : (
            <p className="py-2 text-sm whitespace-pre-wrap">
              {shown.admin_remarks || <span className="text-muted-foreground">No remarks.</span>}
            </p>
          )}
        </Section>

        {(shown.chain ?? []).length > 1 ? (
          <Section title="Re-Demo history">
            <ol className="flex flex-col gap-2 py-2 text-sm" aria-label="Re-Demo history">
              {shown.chain.map((link, index) => (
                <li key={link.id} className="flex flex-wrap items-center justify-between gap-2">
                  <span className="min-w-0">
                    <span className="font-medium">Re-Demo {index + 1}</span>
                    <span className="text-muted-foreground">
                      {' '}
                      · of {slotLabel(link.original.slot)}
                      {link.booking ? ` → ${slotLabel(link.booking.slot)}` : ''}
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
      </div>
    );
  }

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full sm:max-w-lg">
        <SheetHeader>
          <SheetTitle>{shown ? shown.student_name : 'Re-Demo request'}</SheetTitle>
          <SheetDescription>
            {shown ? `Re-Demo of ${slotLabel(shown.original.slot)} · requested ${formatDay(shown.requested_at)}` : 'Loading…'}
          </SheetDescription>
          {shown ? (
            <div className="flex flex-wrap gap-2 pt-1">
              <RedemoStatusBadge status={shown.status} />
            </div>
          ) : null}
        </SheetHeader>
        <div className="min-h-0 flex-1 overflow-y-auto px-4 pb-4">{body}</div>
      </SheetContent>
    </Sheet>
  );
}
