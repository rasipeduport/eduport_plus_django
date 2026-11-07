import { useEffect, useState } from 'react';

import api from '@/lib/api';
import { FormDialog } from '@/components/form-dialog';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { Skeleton } from '@/components/ui/skeleton';
import { Textarea } from '@/components/ui/textarea';
import {
  REDEMO_REMARKS_MAX_LENGTH,
  bookingError,
  redemoScheduleUrl,
  redemoSlotsUrl,
  redemoTutorsUrl,
  shownDayOf,
} from '@/lib/bookings';
import { slotLabel } from '@/lib/enquiries';
import { cn } from '@/lib/utils';
import { AvailabilityBadge } from './booking-badges';
import { MeetLink } from './meet-link';
import { SlotPicker } from './slot-picker';

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

/**
 * Scheduling a Re-Demo (the administrators' step): the tutor -- every active
 * one from GET /api/bookings/redemos/<id>/tutors/, with how many Demo slots
 * they are free for; the one who taught the Demo being repeated is listed
 * but never selectable (the API's `eligible`), and with no other tutor free
 * the dialog says so and books nothing -- then a date and a
 * time from that tutor's slots (GET …/slots/?tutor_id=, the reschedule
 * picker's, a time they are not free refused), their Meet link as the
 * booking will keep it, and remarks for them. Confirming (POST …/schedule/)
 * books the Re-Demo at once: nothing is sent to the parent, and the BDE
 * tells them the time. The API checks it all again, and its refusal is
 * shown as it comes, with the slots read again.
 */
export function RedemoScheduleDialog({ redemo, open, onOpenChange, onScheduled }) {
  const [data, setData] = useState(null);
  const [failure, setFailure] = useState(null);
  const [tutorId, setTutorId] = useState('');
  const [slots, setSlots] = useState(null);
  const [slotsFailure, setSlotsFailure] = useState(null);
  const [day, setDay] = useState('');
  const [time, setTime] = useState('');
  const [remarks, setRemarks] = useState('');
  const [error, setError] = useState(null);
  const [pending, setPending] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const redemoId = redemo?.id;

  // A fresh dialog on every open.
  const [prevOpen, setPrevOpen] = useState(open);
  if (open !== prevOpen) {
    setPrevOpen(open);
    if (open) {
      setData(null);
      setFailure(null);
      setTutorId('');
      setSlots(null);
      setDay('');
      setTime('');
      setRemarks(redemo?.admin_remarks ?? '');
      setError(null);
    }
  }

  useEffect(() => {
    if (!open || !redemoId) return undefined;
    let active = true;
    setFailure(null);
    api
      .get(redemoTutorsUrl(redemoId))
      .then((response) => {
        if (active) setData(response.data);
      })
      .catch((err) => {
        if (active) setFailure(bookingError(err, 'Could not load the tutors.'));
      });
    return () => {
      active = false;
    };
  }, [open, redemoId]);

  useEffect(() => {
    if (!open || !redemoId || !tutorId) return undefined;
    let active = true;
    setSlots(null);
    setSlotsFailure(null);
    api
      .get(redemoSlotsUrl(redemoId), { params: { tutor_id: tutorId } })
      .then((response) => {
        if (active) setSlots(response.data);
      })
      .catch((err) => {
        if (active) setSlotsFailure(bookingError(err, "Could not load the tutor's slots."));
      });
    return () => {
      active = false;
    };
  }, [open, redemoId, tutorId, reloadKey]);

  const tutors = data?.tutors ?? [];
  const selectable = (option) => option.status === 'AVAILABLE' && option.eligible !== false;
  const tutor = tutors.find((option) => option.id === tutorId);
  const dates = slots?.dates ?? [];
  const shownDay = shownDayOf(dates, day);
  const chosen = dates.find((entry) => entry.date === shownDay)?.slots.find((slot) => slot.time === time && slot.bookable);
  const trimmed = remarks.trim();
  const tooLong = trimmed.length > REDEMO_REMARKS_MAX_LENGTH;
  const canSubmit = Boolean(data?.schedulable && tutor && chosen && !tooLong);

  async function schedule() {
    if (!canSubmit) return;
    setPending(true);
    setError(null);
    try {
      const response = await api.post(redemoScheduleUrl(redemoId), {
        tutor_id: tutorId,
        date: shownDay,
        time: chosen.time,
        remarks: trimmed,
      });
      onScheduled?.(response.data);
      onOpenChange(false);
    } catch (err) {
      const refusal = bookingError(err, 'Could not schedule the Re-Demo.');
      setError(refusal.conflict?.message ? `${refusal.message} ${refusal.conflict.message}` : refusal.message);
      // What was free a moment ago may not be any more: show the slots as they are now.
      setTime('');
      setReloadKey((key) => key + 1);
    } finally {
      setPending(false);
    }
  }

  let body;
  if (failure) {
    body = <p className="text-destructive text-sm">{failure.message}</p>;
  } else if (!data) {
    body = <Rows />;
  } else if (!data.schedulable) {
    body = <p className="text-muted-foreground text-sm">{data.refusal?.message}</p>;
  } else if (tutors.length === 0) {
    body = <p className="text-muted-foreground text-sm">There are no active tutors to choose from.</p>;
  } else {
    body = (
      <div className="flex flex-col gap-4">
        {tutors.some(selectable) ? null : (
          <p role="alert" className="bg-warning/10 text-warning rounded-md px-3 py-2 text-sm">
            No other tutor can teach this Re-Demo: the tutor who taught the Demo being repeated is not eligible, and no
            other tutor is free in the booking window. Free a tutor&apos;s time, or add a tutor, then schedule it.
          </p>
        )}
        <fieldset className="flex max-h-[30vh] flex-col gap-2 overflow-y-auto pr-1" disabled={pending}>
          <legend className="mb-1 text-sm font-medium">Tutor</legend>
          {tutors.map((option) => {
            const unavailable = !selectable(option);
            const ineligible = option.eligible === false;
            return (
              <label
                key={option.id}
                aria-disabled={unavailable || undefined}
                className={cn(
                  'flex items-start gap-3 rounded-md border p-3 text-sm transition-colors',
                  unavailable ? 'bg-muted/30 cursor-not-allowed opacity-60' : 'hover:bg-muted/40 cursor-pointer',
                  tutorId === option.id && 'border-primary bg-muted/40'
                )}
              >
                <input
                  type="radio"
                  name="redemo-tutor"
                  value={option.id}
                  checked={tutorId === option.id}
                  onChange={() => {
                    setTutorId(option.id);
                    setDay('');
                    setTime('');
                    setError(null);
                  }}
                  disabled={unavailable}
                  className="mt-1"
                />
                <span className="min-w-0 flex-1">
                  <span className="flex flex-wrap items-center gap-2">
                    <span className="font-medium">{option.full_name}</span>
                    {ineligible ? (
                      <Badge variant="outline">Original tutor · Not eligible</Badge>
                    ) : (
                      <AvailabilityBadge status={option.status} />
                    )}
                  </span>
                  <span className="text-muted-foreground mt-1 block text-xs">
                    {option.reason ? option.reason.message : slotsText(option.free_slots)}
                  </span>
                </span>
              </label>
            );
          })}
        </fieldset>

        {tutor ? (
          <div className="flex flex-col gap-2">
            <p className="text-sm font-medium">Date and time (IST)</p>
            {slotsFailure ? (
              <div className="flex flex-wrap items-center gap-3">
                <p className="text-destructive text-sm">{slotsFailure.message}</p>
                <Button variant="outline" size="sm" onClick={() => setReloadKey((key) => key + 1)}>
                  Try again
                </Button>
              </div>
            ) : !slots ? (
              <Rows count={2} />
            ) : (
              <SlotPicker
                dates={dates}
                day={shownDay}
                time={time}
                onDayChange={(value) => {
                  setDay(value);
                  setTime('');
                }}
                onTimeChange={setTime}
                tutor={tutor}
                tutorBadges={false}
                disabled={pending}
                name="redemo-time"
              />
            )}
            <div className="text-sm">
              <span className="text-muted-foreground">Meet link: </span>
              <MeetLink link={tutor.tutor_meet_link} label={`${tutor.full_name}'s Meet link`} />
              <p className="text-muted-foreground mt-1 text-xs">
                {tutor.tutor_meet_link
                  ? "The tutor's own Google Meet room, kept on the booking."
                  : "Add the tutor's Meet link from the booking once it is scheduled, or on the Team page."}
              </p>
            </div>
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
            {trimmed.length}/{REDEMO_REMARKS_MAX_LENGTH} characters · shown to the tutor, not the BDE
          </p>
        </div>

        {chosen ? (
          <p role="note" className="bg-muted/40 rounded-md border px-3 py-2 text-sm">
            Books the Re-Demo with <span className="font-medium">{tutor.full_name}</span> on{' '}
            <span className="font-medium">{slotLabel({ date: shownDay, time: chosen.time })}</span>. Nothing is sent to
            the parent: the BDE tells them the time.
          </p>
        ) : null}
      </div>
    );
  }

  return (
    <FormDialog
      open={open}
      onOpenChange={onOpenChange}
      title="Schedule the Re-Demo"
      description={redemo ? `${redemo.student_name} · Re-Demo of the Demo on ${slotLabel(redemo.original?.slot)}` : null}
      error={error}
      onConfirm={schedule}
      confirmLabel="Schedule Re-Demo"
      pendingLabel="Scheduling…"
      confirmDisabled={!canSubmit}
      pending={pending}
      size="lg"
      contentClassName="max-h-[90vh] overflow-y-auto"
    >
      {body}
    </FormDialog>
  );
}
