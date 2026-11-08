import { useEffect, useState } from 'react';
import { AlertTriangleIcon, CalendarClockIcon, CalendarSearchIcon } from 'lucide-react';

import api from '@/lib/api';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { Skeleton } from '@/components/ui/skeleton';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Textarea } from '@/components/ui/textarea';
import {
  REDEMO_REMARKS_MAX_LENGTH,
  bookingError,
  redemoScheduleUrl,
  redemoSlotTutorsUrl,
  redemoSlotsUrl,
  redemoTimesUrl,
  redemoTutorsUrl,
} from '@/lib/bookings';
import { slotLabel } from '@/lib/enquiries';
import { studentSlotLabel } from '@/lib/redemo-slots';
import { savedTimezoneLabel } from '@/lib/timezone';
import { cn } from '@/lib/utils';
import { liveBooking } from '@/lib/redemo-workspace';
import { AvailabilityBadge } from '../booking-badges';
import { MeetLink } from '../meet-link';
import { RedemoSlotPicker } from '../redemo-slot-picker';
import { StudentTimeLine } from '../student-time';
import { WorkspaceCard } from './parts';

function Rows({ count = 3 }) {
  return (
    <div className="flex flex-col gap-2" aria-busy="true">
      {Array.from({ length: count }, (_, key) => (
        <Skeleton key={key} className="h-12" />
      ))}
    </div>
  );
}

const slotsText = (count) => (count === 1 ? '1 free Demo slot' : `${count} free Demo slots`);
const BY_TIME = 'time';
const BY_TUTOR = 'tutor';

/** A GET of `url` with `params` while `enabled`, read again on `reloadKey`: `{ data, failure }`. */
function useRead(url, params, enabled, reloadKey) {
  const [data, setData] = useState(null);
  const [failure, setFailure] = useState(null);
  const key = enabled ? `${url}?${new URLSearchParams(params ?? {})}` : null;
  useEffect(() => {
    if (!key) return undefined;
    let active = true;
    setData(null);
    setFailure(null);
    api
      .get(url, { params })
      .then((response) => {
        if (active) setData({ key, ...response.data });
      })
      .catch((err) => {
        if (active) setFailure(bookingError(err, 'Could not load the options.'));
      });
    return () => {
      active = false;
    };
    // `params` is read through `key`.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, reloadKey]);
  return { data: data && data.key === key ? data : null, failure };
}

/** The tutors to choose from, as radios: who is free, and why one may not be picked (busy, or taught the chain). */
function TutorChoices({ tutors, value, onChange, disabled, freeText }) {
  return (
    <fieldset className="flex max-h-[28rem] flex-col gap-2 overflow-y-auto pr-1" disabled={disabled}>
      <legend className="mb-1 text-sm font-medium">Tutor</legend>
      {tutors.map((option) => {
        const unavailable = option.status !== 'AVAILABLE' || option.eligible === false;
        const ineligible = option.eligible === false;
        return (
          <label
            key={option.id}
            aria-disabled={unavailable || undefined}
            className={cn(
              'flex items-start gap-3 rounded-md border p-3 text-sm transition-colors',
              unavailable ? 'bg-muted/30 cursor-not-allowed opacity-60' : 'hover:bg-muted/40 cursor-pointer',
              value === option.id && 'border-primary bg-muted/40'
            )}
          >
            <input
              type="radio"
              name="redemo-tutor"
              value={option.id}
              checked={value === option.id}
              onChange={() => onChange(option.id)}
              disabled={unavailable}
              className="mt-1"
            />
            <span className="min-w-0 flex-1">
              <span className="flex flex-wrap items-center gap-2">
                <span className="font-medium">{option.full_name}</span>
                {ineligible ? (
                  <Badge variant="outline">{option.original ? 'Original tutor' : 'Taught this chain'} · Not eligible</Badge>
                ) : (
                  <AvailabilityBadge status={option.status} />
                )}
                {!ineligible && !option.tutor_meet_link ? <Badge variant="warning">No Meet link</Badge> : null}
              </span>
              <span className="text-muted-foreground mt-1 block text-xs">
                {option.reason ? option.reason.message : freeText(option)}
              </span>
            </span>
          </label>
        );
      })}
    </fieldset>
  );
}

/** What the scheduling works to, in a few lines: the Demo it repeats, its tutor (never eligible), and the student's clock. */
function Context({ redemo, clock }) {
  const zone = clock?.student_timezone_known ? savedTimezoneLabel(clock.student_timezone) : null;
  return (
    <div className="bg-muted/40 flex flex-col gap-1 rounded-md border px-3 py-2 text-sm">
      <p className="text-muted-foreground text-xs">
        Repeats the Demo on {slotLabel(redemo.original?.slot)}
        {redemo.original?.tutor ? ` with ${redemo.original.tutor.full_name} (not eligible)` : ''}. Tutors who taught an
        earlier Demo of this chain are listed but cannot be chosen.
      </p>
      <p className="text-muted-foreground text-xs">
        {zone
          ? `Times are shown on the student's clock (${zone}), with India's time beside them.`
          : "The student's time zone is not set, so times are shown in Indian time (IST)."}
      </p>
    </div>
  );
}

/** Why there is nothing to schedule now, from the request as the API reads it. */
function NothingToSchedule({ redemo }) {
  const booking = liveBooking(redemo);
  let message;
  if (redemo.status === 'CLOSED') message = 'This request is closed, so nothing can be scheduled. Reopen it to schedule the Re-Demo.';
  else if (booking?.status === 'BOOKED')
    message = 'The Re-Demo is scheduled. Reschedule it or change its tutor from the actions below.';
  else if (booking) message = 'The Re-Demo has been taught: there is nothing left to schedule.';
  else message = 'Not scheduled yet: an administrator chooses the time and the tutor.';
  return (
    <WorkspaceCard icon={CalendarClockIcon} title="Scheduling">
      {booking ? (
        <div className="bg-muted/40 flex flex-col gap-0.5 rounded-md border px-3 py-2 text-sm">
          <p className="font-medium">
            {slotLabel(booking.slot)}
            {booking.tutor ? ` with ${booking.tutor.full_name}` : ''}
          </p>
          <StudentTimeLine startsAt={booking.slot?.starts_at} timezone={redemo.student_timezone} />
        </div>
      ) : null}
      <p className="text-muted-foreground text-sm">{message}</p>
    </WorkspaceCard>
  );
}

/**
 * The workspace's Scheduling tab: scheduling a Re-Demo (the administrators'
 * step, `redemo.actions.schedule`), two ways:
 *
 *   By time   a date and a time first -- the Demo slots of the booking window
 *             for the child (GET …/times/), each with how many tutors who may
 *             teach the Re-Demo are free then -- then one of those tutors
 *             (GET …/slot-tutors/?date=&time=)
 *   By tutor  the tutor first (GET …/tutors/: every active tutor and how many
 *             slots they are free for), then that tutor's slots (GET
 *             …/slots/?tutor_id=)
 *
 * Every slot reads on the student's own clock first (their saved zone; India's
 * when it is not set), with the same slot in Indian time beside it: one
 * instant either way, which the request carries (`starts_at`) so the slot
 * booked is the slot shown. Anyone who taught a Demo of the chain is listed
 * but never selectable. Then the tutor's Meet link (a warning when they have
 * none), the remarks for them, and what will be booked, before Schedule
 * Re-Demo (POST …/schedule/) books it at once (`onScheduled`, the request as
 * the API answers). Nothing is sent to the parent: the BDE tells them the
 * time. The API checks it all again, and its refusal is shown as it comes,
 * with the options read again. With nothing to schedule, nothing is read.
 */
export function RedemoScheduler({ redemo, onScheduled }) {
  const enabled = Boolean(redemo.actions?.schedule);
  const redemoId = redemo.id;
  const [mode, setMode] = useState(BY_TIME);
  const [tutorId, setTutorId] = useState('');
  const [slot, setSlot] = useState(null);
  const [day, setDay] = useState('');
  const [remarks, setRemarks] = useState(redemo.admin_remarks ?? '');
  const [error, setError] = useState(null);
  const [pending, setPending] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  // The remarks saved elsewhere (the Overview tab), or another request, start the field again from the API's.
  const remarksKey = `${redemoId}|${redemo.remarks_updated_at}`;
  const [prevRemarksKey, setPrevRemarksKey] = useState(remarksKey);
  if (remarksKey !== prevRemarksKey) {
    setPrevRemarksKey(remarksKey);
    setRemarks(redemo.admin_remarks ?? '');
  }

  const byTime = mode === BY_TIME;
  const tutors = useRead(redemoTutorsUrl(redemoId), null, enabled && !byTime, reloadKey);
  const tutorSlots = useRead(
    redemoSlotsUrl(redemoId),
    { tutor_id: tutorId },
    enabled && !byTime && Boolean(tutorId),
    reloadKey
  );
  const times = useRead(redemoTimesUrl(redemoId), null, enabled && byTime, reloadKey);
  const slotTutors = useRead(
    redemoSlotTutorsUrl(redemoId),
    slot ? { date: slot.date, time: slot.time } : null,
    enabled && byTime && Boolean(slot),
    reloadKey
  );

  if (!enabled) return <NothingToSchedule redemo={redemo} />;

  const switchMode = (next) => {
    setMode(next);
    setTutorId('');
    setSlot(null);
    setDay('');
    setError(null);
  };

  const gate = byTime ? times.data : tutors.data;
  const clock = byTime ? times.data : tutorSlots.data;
  const tutorList = byTime ? (slotTutors.data?.tutors ?? []) : (tutors.data?.tutors ?? []);
  const tutor = tutorList.find((option) => option.id === tutorId);
  const selectable = (option) => option.status === 'AVAILABLE' && option.eligible !== false;
  const dates = byTime ? (times.data?.dates ?? []) : (tutorSlots.data?.dates ?? []);
  // The slot picked, as the API answers it now: still open, or not.
  const chosen = slot
    ? dates.flatMap((entry) => entry.slots.map((item) => ({ ...item, date: entry.date }))).find(
        (item) => item.starts_at === slot.starts_at && item.bookable
      )
    : null;
  const trimmed = remarks.trim();
  const tooLong = trimmed.length > REDEMO_REMARKS_MAX_LENGTH;
  const canSubmit = Boolean(gate?.schedulable && tutor && selectable(tutor) && chosen && !tooLong);

  async function schedule() {
    if (!canSubmit || pending) return;
    setPending(true);
    setError(null);
    try {
      const response = await api.post(redemoScheduleUrl(redemoId), {
        tutor_id: tutorId,
        date: chosen.date,
        time: chosen.time,
        starts_at: chosen.starts_at,
        remarks: trimmed,
      });
      setTutorId('');
      setSlot(null);
      setDay('');
      onScheduled?.(response.data);
    } catch (err) {
      const refusal = bookingError(err, 'Could not schedule the Re-Demo.');
      setError(refusal.conflict?.message ? `${refusal.message} ${refusal.conflict.message}` : refusal.message);
      // What was free a moment ago may not be any more: show the options as they are now.
      setReloadKey((key) => key + 1);
    } finally {
      setPending(false);
    }
  }

  const failure = (byTime ? times.failure : tutors.failure) ?? null;
  if (failure) {
    return (
      <WorkspaceCard icon={CalendarClockIcon} title="Schedule the Re-Demo">
        <div className="flex flex-wrap items-center gap-3">
          <p className="text-destructive text-sm">{failure.message}</p>
          <Button variant="outline" size="sm" onClick={() => setReloadKey((key) => key + 1)}>
            Try again
          </Button>
        </div>
      </WorkspaceCard>
    );
  }
  if (gate && !gate.schedulable) {
    return (
      <WorkspaceCard icon={CalendarClockIcon} title="Schedule the Re-Demo">
        <p className="text-muted-foreground text-sm">{gate.refusal?.message}</p>
      </WorkspaceCard>
    );
  }

  const picker = (
    <div className="flex flex-col gap-2">
      <p className="text-sm font-medium">
        Date and time{' '}
        <span className="text-muted-foreground font-normal">
          ({clock?.student_timezone_known ? `${clock.display_timezone_label} time, IST beside it` : 'IST'})
        </span>
      </p>
      {!byTime && tutorSlots.failure ? (
        <div className="flex flex-wrap items-center gap-3">
          <p className="text-destructive text-sm">{tutorSlots.failure.message}</p>
          <Button variant="outline" size="sm" onClick={() => setReloadKey((key) => key + 1)}>
            Try again
          </Button>
        </div>
      ) : (byTime ? times.data : tutorSlots.data) ? (
        <RedemoSlotPicker
          dates={dates}
          day={day}
          selected={slot?.starts_at}
          onDayChange={(value) => {
            setDay(value);
            setSlot(null);
            if (byTime) setTutorId('');
          }}
          onSelect={(value) => {
            setSlot(value);
            // The day shown stays the picked slot's, however the options read again after a refusal.
            setDay(value.student_date ?? value.date);
            setError(null);
            if (byTime) setTutorId('');
          }}
          showTutorCount={byTime}
          disabled={pending}
          name="redemo-time"
        />
      ) : (
        <Rows count={2} />
      )}
    </div>
  );
  const tutorPicker = (list) =>
    list.length === 0 ? (
      <p className="text-muted-foreground text-sm">There are no active tutors to choose from.</p>
    ) : (
      <>
        {list.some(selectable) ? null : (
          <p role="alert" className="bg-warning/10 text-warning rounded-md px-3 py-2 text-sm">
            {byTime
              ? 'No tutor who may teach this Re-Demo is free at this time. Choose another time.'
              : 'No other tutor can teach this Re-Demo: the tutors who taught its Demos are not eligible, and no other tutor is free in the booking window. Free a tutor’s time, or add a tutor, then schedule it.'}
          </p>
        )}
        <TutorChoices
          tutors={list}
          value={tutorId}
          onChange={(id) => {
            setTutorId(id);
            setError(null);
            if (!byTime) {
              setSlot(null);
              setDay('');
            }
          }}
          disabled={pending}
          freeText={(option) => (byTime ? 'Free at this time' : slotsText(option.free_slots))}
        />
      </>
    );

  let choices;
  if (!gate) choices = <Rows />;
  else if (byTime) {
    choices = (
      <>
        {picker}
        {slot ? (
          slotTutors.failure ? (
            <p className="text-destructive text-sm">{slotTutors.failure.message}</p>
          ) : slotTutors.data ? (
            tutorPicker(tutorList)
          ) : (
            <Rows count={2} />
          )
        ) : null}
      </>
    );
  } else {
    choices = (
      <>
        {tutorPicker(tutorList)}
        {tutorId ? picker : null}
      </>
    );
  }

  return (
    <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1fr)_22rem]">
      <WorkspaceCard
        icon={CalendarSearchIcon}
        title="Schedule the Re-Demo"
        action={
          <Tabs value={mode} onValueChange={switchMode}>
            <TabsList>
              <TabsTrigger value={BY_TIME}>By time</TabsTrigger>
              <TabsTrigger value={BY_TUTOR}>By tutor</TabsTrigger>
            </TabsList>
          </Tabs>
        }
      >
        <Context redemo={redemo} clock={clock ?? gate} />
        <div className="flex flex-col gap-4">{choices}</div>
      </WorkspaceCard>

      <WorkspaceCard icon={CalendarClockIcon} title="Booking" className="lg:sticky lg:top-20">
        {chosen && tutor && selectable(tutor) ? (
          <div role="note" className="bg-muted/40 flex flex-col gap-0.5 rounded-md border px-3 py-2 text-sm">
            <p className="font-medium">Books the Re-Demo with {tutor.full_name}</p>
            <p>
              {clock?.student_timezone_known ? (
                <>
                  {studentSlotLabel(chosen)} <span className="text-muted-foreground">for the student</span> ·{' '}
                </>
              ) : null}
              {slotLabel(chosen)}
            </p>
            <p className="text-muted-foreground text-xs">Nothing is sent to the parent: the BDE tells them the time.</p>
          </div>
        ) : (
          <p className="text-muted-foreground text-sm">
            {byTime ? 'Choose a time, then a tutor free at it.' : 'Choose a tutor, then one of their times.'}
          </p>
        )}

        {tutor ? (
          <div className="text-sm">
            <span className="text-muted-foreground">Meet link: </span>
            <MeetLink link={tutor.tutor_meet_link} label={`${tutor.full_name}'s Meet link`} />
            {tutor.tutor_meet_link ? (
              <p className="text-muted-foreground mt-1 text-xs">The tutor&apos;s own Google Meet room, kept on the booking.</p>
            ) : (
              <p className="text-warning mt-1 flex items-start gap-1.5 text-xs">
                <AlertTriangleIcon className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
                {tutor.full_name} has no Meet link yet. Add it on the Team page before the class, or the parent has no link
                to join.
              </p>
            )}
          </div>
        ) : null}

        <div className="flex flex-col gap-2">
          <Label htmlFor="redemo-remarks">Remarks for the tutor</Label>
          <Textarea
            id="redemo-remarks"
            value={remarks}
            onChange={(event) => setRemarks(event.target.value)}
            rows={3}
            disabled={pending}
            aria-invalid={tooLong || undefined}
            placeholder="What the tutor should know before teaching this Re-Demo."
          />
          <p className={tooLong ? 'text-destructive text-xs' : 'text-muted-foreground text-xs'}>
            {trimmed.length}/{REDEMO_REMARKS_MAX_LENGTH} characters · shown to the tutor, not the BDE · locked once the
            Re-Demo starts
          </p>
        </div>

        {error ? (
          <p role="alert" className="bg-destructive/10 text-destructive rounded-md px-3 py-2 text-sm">
            {error}
          </p>
        ) : null}
        <Button onClick={schedule} disabled={!canSubmit || pending}>
          <CalendarClockIcon />
          {pending ? 'Scheduling…' : 'Schedule Re-Demo'}
        </Button>
      </WorkspaceCard>
    </div>
  );
}
