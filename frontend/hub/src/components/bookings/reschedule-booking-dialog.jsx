import { useEffect, useState } from 'react';

import api from '@/lib/api';
import { FormDialog } from '@/components/form-dialog';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import {
  RESCHEDULE_REASONS,
  bookingError,
  bookingRescheduleOptionsUrl,
  bookingRescheduleUrl,
  shownDayOf,
} from '@/lib/bookings';
import { bookingTypeLabel, slotLabel } from '@/lib/enquiries';
import { cn } from '@/lib/utils';
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
 */
export function RescheduleBookingDialog({ booking, open, onOpenChange, onRescheduled }) {
  const [data, setData] = useState(null);
  const [failure, setFailure] = useState(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [day, setDay] = useState('');
  const [time, setTime] = useState('');
  const [reason, setReason] = useState('');
  const [error, setError] = useState(null);
  const [pending, setPending] = useState(false);
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

  const dates = data?.dates ?? [];
  const shownDay = shownDayOf(dates, day);
  const slots = dates.find((entry) => entry.date === shownDay)?.slots ?? [];
  const chosen = slots.find((slot) => slot.time === time && slot.bookable);
  const tutor = data?.tutor;
  const canSubmit = Boolean(data?.reschedulable && chosen && reason);

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
      onRescheduled?.(response.data);
      onOpenChange(false);
    } catch (err) {
      const refusal = bookingError(err, 'Could not move the booking.');
      setError(refusal.conflict?.message ? `${refusal.message} ${refusal.conflict.message}` : refusal.message);
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
        />

        {chosen && tutor && !chosen.tutor_free ? (
          <p role="note" className="bg-warning/10 text-warning rounded-md px-3 py-2 text-sm">
            {tutor.full_name} isn&apos;t free then, so the moved booking will need a tutor.
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
      onOpenChange={onOpenChange}
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
