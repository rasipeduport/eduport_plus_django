import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { slotParts } from '@/lib/enquiries';
import { cn } from '@/lib/utils';

// Why a slot cannot take the booking (backend coordination.slot_options, bookings.redemos.slot_options).
const UNAVAILABLE = {
  CURRENT: 'Its current slot',
  FULL: 'Fully booked',
  CLOSED: 'Closed',
};

/**
 * A staff picker's dates and times, as the API answers them
 * (coordination.slot_options): a button per date with how many slots are
 * open, then that date's times, each with its seats left or why it is out
 * of reach -- full, closed, its own slot, the child booked then, or the
 * tutor not free (TUTOR_BUSY). With `tutorBadges` and a `tutor`, an open
 * time also says whether that tutor is free there. `day` is the date shown
 * (lib/bookings shownDayOf), `time` the one picked.
 *
 * `moreDates` closes the row of dates (the reschedule's calendar). For a day
 * the buttons do not hold, `slots` gives its times, `loading` stands in for
 * them while they are read, and `empty` is said when there are none.
 */
export function SlotPicker({
  dates, day, time, onDayChange, onTimeChange, tutor, tutorBadges = true, disabled, name,
  moreDates = null, slots: daySlots, loading = false, empty = null,
}) {
  const slots = daySlots ?? dates.find((entry) => entry.date === day)?.slots ?? [];
  return (
    <>
      <div className="flex flex-wrap gap-2" role="group" aria-label="Dates">
        {dates.map((entry) => {
          const openCount = entry.slots.filter((slot) => slot.bookable).length;
          return (
            <Button
              key={entry.date}
              type="button"
              size="sm"
              variant={entry.date === day ? 'default' : 'outline'}
              aria-pressed={entry.date === day}
              onClick={() => onDayChange(entry.date)}
            >
              {slotParts(entry.date, '00:00').day}
              <span className="text-xs opacity-70">{openCount ? `(${openCount})` : '(full)'}</span>
            </Button>
          );
        })}
        {moreDates}
      </div>

      <fieldset className="flex max-h-[40vh] flex-col gap-2 overflow-y-auto pr-1" disabled={disabled} aria-busy={loading || undefined}>
        <legend className="sr-only">Times</legend>
        {loading ? [0, 1, 2].map((key) => <Skeleton key={key} className="h-12" />) : null}
        {!loading && !slots.length && empty ? <div className="text-muted-foreground text-sm">{empty}</div> : null}
        {(loading ? [] : slots).map((slot) => {
          const why =
            slot.lead_conflict?.message ??
            (slot.unavailable_reason === 'TUTOR_BUSY' ? slot.tutor_reason?.message : UNAVAILABLE[slot.unavailable_reason]);
          return (
            <label
              key={slot.time}
              className={cn(
                'flex items-start gap-3 rounded-md border p-3 text-sm',
                slot.bookable ? 'hover:bg-muted/40 cursor-pointer' : 'cursor-not-allowed opacity-60',
                time === slot.time && slot.bookable && 'border-primary bg-muted/40'
              )}
            >
              <input
                type="radio"
                name={name}
                value={slot.time}
                checked={time === slot.time}
                onChange={() => onTimeChange(slot.time)}
                disabled={!slot.bookable}
                className="mt-0.5"
              />
              <span className="min-w-0 flex-1">
                <span className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">{slotParts(day, slot.time).time}</span>
                  {slot.bookable ? (
                    <span className="text-muted-foreground text-xs">
                      {slot.seats_left} {slot.seats_left === 1 ? 'seat' : 'seats'} left
                    </span>
                  ) : null}
                  {slot.bookable && tutor && tutorBadges ? (
                    slot.tutor_free ? (
                      <Badge variant="success">Tutor free</Badge>
                    ) : (
                      <Badge variant="warning">Tutor busy</Badge>
                    )
                  ) : null}
                </span>
                {!slot.bookable && why ? <span className="text-muted-foreground block text-xs">{why}</span> : null}
                {slot.bookable && tutor && tutorBadges && !slot.tutor_free && slot.tutor_reason ? (
                  <span className="text-muted-foreground block text-xs">{slot.tutor_reason.message}</span>
                ) : null}
              </span>
            </label>
          );
        })}
      </fieldset>
    </>
  );
}
