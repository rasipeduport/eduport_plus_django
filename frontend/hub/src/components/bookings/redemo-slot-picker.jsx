import { slotLabel, slotParts } from '@/lib/enquiries';
import { byStudentDate, studentSlotTime } from '@/lib/redemo-slots';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';

// Why a slot cannot take the Re-Demo (backend coordination.slot_options and bookings.redemos).
const UNAVAILABLE = {
  FULL: 'Fully booked',
  CLOSED: 'Closed',
  NO_TUTOR_FREE: 'No tutor who may teach it is free',
};

/**
 * The Re-Demo's dates and times, on the student's own clock first: the dates
 * as the student's calendar has them (byStudentDate), each slot's time in the
 * student's zone with the same slot in Indian time beside it -- the one
 * instant either way -- with its seats, how many tutors are free then (by
 * time), or why it is out of reach. A slot is picked by its instant
 * (`starts_at`), so the slot booked is the one shown. `day` is the student's
 * date shown, `selected` the picked slot's starts_at.
 */
export function RedemoSlotPicker({ dates, day, selected, onDayChange, onSelect, showTutorCount = false, disabled, name }) {
  const days = byStudentDate(dates);
  const shownDay = day || days.find((entry) => entry.slots.some((slot) => slot.bookable))?.date || days[0]?.date || '';
  const slots = days.find((entry) => entry.date === shownDay)?.slots ?? [];
  return (
    <>
      <div className="flex flex-wrap gap-2" role="group" aria-label="Student's dates">
        {days.map((entry) => {
          const openCount = entry.slots.filter((slot) => slot.bookable).length;
          return (
            <Button
              key={entry.date}
              type="button"
              size="sm"
              variant={entry.date === shownDay ? 'default' : 'outline'}
              aria-pressed={entry.date === shownDay}
              onClick={() => onDayChange(entry.date)}
              disabled={disabled}
            >
              {slotParts(entry.date, '00:00').day}
              {/* Out of reach is not only full: no tutor free (by time), or the chosen tutor busy. */}
              <span className="text-xs opacity-70">{openCount ? `(${openCount})` : '(none open)'}</span>
            </Button>
          );
        })}
      </div>

      <fieldset className="flex max-h-[40vh] flex-col gap-2 overflow-y-auto pr-1" disabled={disabled}>
        <legend className="sr-only">Times</legend>
        {slots.map((slot) => {
          const why =
            slot.lead_conflict?.message ??
            (slot.unavailable_reason === 'TUTOR_BUSY' ? slot.tutor_reason?.message : UNAVAILABLE[slot.unavailable_reason]);
          const otherDay = slot.student_date && slot.student_date !== slot.date;
          return (
            <label
              key={slot.starts_at}
              className={cn(
                'flex items-start gap-3 rounded-md border p-3 text-sm',
                slot.bookable ? 'hover:bg-muted/40 cursor-pointer' : 'cursor-not-allowed opacity-60',
                selected === slot.starts_at && slot.bookable && 'border-primary bg-muted/40'
              )}
            >
              <input
                type="radio"
                name={name}
                value={slot.starts_at}
                checked={selected === slot.starts_at}
                onChange={() => onSelect(slot)}
                disabled={!slot.bookable}
                className="mt-0.5"
              />
              <span className="min-w-0 flex-1">
                <span className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
                  <span className="font-medium">{studentSlotTime(slot)}</span>
                  <span className="text-muted-foreground text-xs">
                    {otherDay ? slotLabel(slot) : `${slotParts(slot.date, slot.time).time} IST`}
                  </span>
                </span>
                {slot.bookable ? (
                  <span className="text-muted-foreground block text-xs">
                    {slot.seats_left} {slot.seats_left === 1 ? 'seat' : 'seats'} left
                    {showTutorCount
                      ? ` · ${slot.free_tutors} ${slot.free_tutors === 1 ? 'tutor' : 'tutors'} free`
                      : ''}
                  </span>
                ) : why ? (
                  <span className="text-muted-foreground block text-xs">{why}</span>
                ) : null}
              </span>
            </label>
          );
        })}
        {slots.length === 0 ? <p className="text-muted-foreground text-sm">No Demo slots in the booking window.</p> : null}
      </fieldset>
    </>
  );
}
