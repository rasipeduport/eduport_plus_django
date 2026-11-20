import { useEffect, useState } from 'react';

import api from '@/lib/api';
import { FormDialog } from '@/components/form-dialog';
import { useRefusalRefresh } from '@/hooks/use-refusal-refresh';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import {
  RESCHEDULE_REASONS,
  SAME_DAY_NOTICE,
  bookingError,
  bookingRescheduleOptionsUrl,
  bookingRescheduleUrl,
  shownDayOf,
} from '@/lib/bookings';
import { bookingTypeLabel, slotLabel } from '@/lib/enquiries';
import { cn } from '@/lib/utils';
import { RescheduleCalendar } from './reschedule-calendar';
import { SlotPicker } from './slot-picker';

function OptionsSkeleton() {
  return (
    <div className="flex flex-col gap-2" aria-busy="true">
      <Skeleton className="h-9" />
      {[0, 1, 2].map((key) => (
        <Skeleton key={key} className="h-12" />
      ))}
    </div>
  );
}

/**
 * Moving a booking to another slot (Admin only, until its slot starts). The
 * slots come from the API (GET /api/bookings/<type>/<id>/reschedule-options/):
 * the public pages' window with the seats left, why a slot is out of reach --
 * full, closed, its own, or the child already booked then -- and whether the
 * assigned tutor is free there: they move with the booking only if so (Q24),
 * which the dialog says before anything is sent. The reason is picked from
 * the list, never typed. POST /api/bookings/<type>/<id>/reschedule/ checks it
 * all again and answers the replacement booking.
 *
 * The date buttons are the public pages' seven dates; "More dates" (the API's
 * `window`) reaches every date from today through 30 days on, a time at least
 * 30 minutes away. A calendar date the buttons do not hold is read on its own
 * (the same API, `?date=`), and the button then names it. A time today brings
 * SAME_DAY_NOTICE: nobody is told of the move by itself.
 */
export function RescheduleBookingDialog({ booking, open, onOpenChange, onRescheduled, onRefused }) {
  // Refused as out of date (404/409): once closed, `onRefused` lets the page read it again.
  const refusal = useRefusalRefresh(onOpenChange, onRefused);
  const [data, setData] = useState(null);
  const [failure, setFailure] = useState(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [day, setDay] = useState('');
  const [time, setTime] = useState('');
  const [reason, setReason] = useState('');
  const [error, setError] = useState(null);
  const [pending, setPending] = useState(false);
  // The calendar date outside the date buttons, if one was picked, and what the API said of it.
  const [calendarDate, setCalendarDate] = useState('');
  const [calendarAnswer, setCalendarAnswer] = useState(null);
  const bookingId = booking?.id;
  const bookingType = booking?.booking_type;

  // A fresh dialog on every open.
  const [prevOpen, setPrevOpen] = useState(open);
  if (open !== prevOpen) {
    setPrevOpen(open);
    if (open) {
      setData(null);
      setFailure(null);
      setDay('');
      setTime('');
      setReason('');
      setError(null);
      setCalendarDate('');
      setCalendarAnswer(null);
    }
  }

  useEffect(() => {
    if (!open || !bookingId || !bookingType) return undefined;
    let active = true;
    setFailure(null);
    api
      .get(bookingRescheduleOptionsUrl(bookingType, bookingId))
      .then((response) => {
        if (active) setData(response.data);
      })
      .catch((err) => {
        if (active) setFailure(bookingError(err, 'Could not load the open slots.'));
      });
    return () => {
      active = false;
    };
  }, [open, bookingType, bookingId, reloadKey]);

  // A calendar date's own times, read again with the rest (reloadKey). Only the
  // latest date picked is kept: an earlier answer arriving late is dropped.
  useEffect(() => {
    if (!open || !bookingId || !bookingType || !calendarDate) return undefined;
    let active = true;
    setCalendarAnswer(null);
    api
      .get(bookingRescheduleOptionsUrl(bookingType, bookingId), { params: { date: calendarDate } })
      .then((response) => {
        if (!active) return;
        const entry = response.data.dates?.find((item) => item.date === calendarDate) ?? { date: calendarDate, slots: [] };
        setCalendarAnswer({ date: calendarDate, slots: entry.slots });
        // Moved or started meanwhile: say so, as the dates' own answer would.
        if (!response.data.reschedulable) {
          setData((current) => current && { ...current, reschedulable: false, refusal: response.data.refusal });
        }
      })
      .catch((err) => {
        if (active) setCalendarAnswer({ date: calendarDate, failure: bookingError(err, 'Could not load the times for that date.') });
      });
    return () => {
      active = false;
    };
  }, [open, bookingType, bookingId, calendarDate, reloadKey]);

  const dates = data?.dates ?? [];
  const range = data?.window;
  const shownDay = shownDayOf(dates, day);
  // A day the buttons do not hold came from the calendar: its times are its own answer's.
  const fromCalendar = Boolean(shownDay) && !dates.some((entry) => entry.date === shownDay);
  const answer = fromCalendar && calendarAnswer?.date === shownDay ? calendarAnswer : null;
  const slots = fromCalendar ? (answer?.slots ?? []) : (dates.find((entry) => entry.date === shownDay)?.slots ?? []);
  const chosen = slots.find((slot) => slot.time === time && slot.bookable);
  const tutor = data?.tutor;
  const sameDay = Boolean(chosen && range?.today && shownDay === range.today);
  const canSubmit = Boolean(data?.reschedulable && chosen && reason);

  const pickCalendarDate = (value) => {
    setDay(value);
    setTime('');
    setCalendarDate(dates.some((entry) => entry.date === value) ? '' : value);
  };

  let emptyDay = null;
  if (answer?.failure) {
    emptyDay = (
      <span className="flex flex-wrap items-center gap-3">
        <span className="text-destructive">{answer.failure.message}</span>
        <Button variant="outline" size="sm" onClick={() => setReloadKey((key) => key + 1)}>
          Try again
        </Button>
      </span>
    );
  } else if (fromCalendar) {
    emptyDay = 'No time can be chosen on this date.';
  }

  async function reschedule() {
    if (!canSubmit) return;
    setPending(true);
    setError(null);
    try {
      const response = await api.post(bookingRescheduleUrl(bookingType, bookingId), {
        date: shownDay,
        time: chosen.time,
        reason,
      });
      refusal.accepted();
      onRescheduled?.(response.data);
      onOpenChange(false);
    } catch (err) {
      const failure = bookingError(err, 'Could not move the booking.');
      setError(failure.conflict?.message ? `${failure.message} ${failure.conflict.message}` : failure.message);
      refusal.refused(failure);
      // What was open a moment ago may not be any more: show the slots as they are now.
      setTime('');
      setReloadKey((key) => key + 1);
    } finally {
      setPending(false);
    }
  }

  let body;
  if (failure) {
    body = (
      <div className="flex flex-wrap items-center gap-3">
        <p className="text-destructive text-sm">{failure.message}</p>
        <Button variant="outline" size="sm" onClick={() => setReloadKey((key) => key + 1)}>
          Try again
        </Button>
      </div>
    );
  } else if (!data) {
    body = <OptionsSkeleton />;
  } else if (!data.reschedulable) {
    body = <p className="text-muted-foreground text-sm">{data.refusal?.message}</p>;
  } else {
    body = (
      <div className="flex flex-col gap-4">
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
          disabled={pending}
          name="reschedule-time"
          moreDates={
            range ? (
              <RescheduleCalendar
                range={range}
                selected={shownDay}
                active={fromCalendar}
                onSelect={pickCalendarDate}
                disabled={pending}
              />
            ) : null
          }
          slots={fromCalendar ? slots : undefined}
          loading={fromCalendar && !answer}
          empty={emptyDay}
        />

        {chosen && tutor && !chosen.tutor_free ? (
          <p role="note" className="bg-warning/10 text-warning rounded-md px-3 py-2 text-sm">
            {tutor.full_name} isn&apos;t free then, so the moved booking will need a tutor.
          </p>
        ) : null}

        {sameDay ? (
          <p role="note" className="bg-warning/10 text-warning rounded-md px-3 py-2 text-sm">
            {SAME_DAY_NOTICE}
          </p>
        ) : null}

        <fieldset className="flex flex-col gap-2" disabled={pending}>
          <legend className="mb-1 text-sm font-medium">Why is it moved?</legend>
          <div className="flex flex-wrap gap-2">
            {RESCHEDULE_REASONS.map((option) => (
              <label
                key={option.value}
                className={cn(
                  'hover:bg-muted/40 flex cursor-pointer items-center gap-2 rounded-md border px-3 py-2 text-sm',
                  reason === option.value && 'border-primary bg-muted/40'
                )}
              >
                <input
                  type="radio"
                  name="reschedule-reason"
                  value={option.value}
                  checked={reason === option.value}
                  onChange={() => setReason(option.value)}
                />
                {option.label}
              </label>
            ))}
          </div>
        </fieldset>
      </div>
    );
  }

  return (
    <FormDialog
      open={open}
      onOpenChange={refusal.onOpenChange}
      title="Reschedule booking"
      description={
        booking ? `${booking.student_name} · ${bookingTypeLabel(booking.booking_type)} · now ${slotLabel(booking.slot)}` : null
      }
      error={error}
      onConfirm={reschedule}
      confirmLabel="Move booking"
      pendingLabel="Moving…"
      confirmDisabled={!canSubmit}
      pending={pending}
      size="lg"
    >
      {body}
    </FormDialog>
  );
}
