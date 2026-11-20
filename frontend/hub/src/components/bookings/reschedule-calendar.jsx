import { useState } from 'react';
import { CalendarDaysIcon } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Calendar } from '@/components/ui/calendar';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { calendarDay, isoDay } from '@/lib/bookings';
import { slotParts } from '@/lib/enquiries';

/**
 * The reschedule picker's last date option, "More dates": a calendar of every
 * date a booking may be moved to, as the API's `range` names them
 * (reschedule-options `window`: `today`, `first` -- today while one of its
 * times can still be chosen, else tomorrow -- and `last`, 30 days on). All are
 * Indian dates and come from the server, never from this device's clock, so a
 * device in another zone shows the same days; earlier and later ones are
 * disabled. A picked date is handed on as "YYYY-MM-DD" (`onSelect`). While the
 * date shown is one the date buttons do not hold (`active`), the button names
 * it (`selected`).
 */
export function RescheduleCalendar({ range, selected, active, onSelect, disabled }) {
  const [open, setOpen] = useState(false);
  const today = calendarDay(range.today);
  const first = calendarDay(range.first);
  const last = calendarDay(range.last);
  const chosen = calendarDay(selected);
  const shown = chosen && chosen >= first && chosen <= last ? chosen : undefined;
  return (
    <Popover modal open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          type="button"
          size="sm"
          variant={active ? 'default' : 'outline'}
          disabled={disabled}
          className={active ? undefined : 'border-primary/40 text-primary'}
        >
          <CalendarDaysIcon aria-hidden="true" />
          {active && selected ? slotParts(selected, '00:00').day : 'More dates'}
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-auto overflow-hidden p-0" align="start" collisionPadding={16}>
        <Calendar
          mode="single"
          required
          selected={shown}
          today={today}
          defaultMonth={shown ?? first}
          startMonth={today}
          endMonth={last}
          disabled={[{ before: first }, { after: last }]}
          onSelect={(date) => {
            if (!date) return;
            setOpen(false);
            onSelect(isoDay(date));
          }}
        />
        <div className="text-muted-foreground flex flex-wrap items-center gap-x-4 gap-y-1 border-t px-3 py-2 text-xs">
          <span className="flex items-center gap-1.5">
            <span className="bg-accent size-2.5 rounded-full" aria-hidden="true" />
            Today (IST)
          </span>
          <span className="flex items-center gap-1.5">
            <span className="bg-muted-foreground/30 size-2.5 rounded-full" aria-hidden="true" />
            Not available
          </span>
        </div>
      </PopoverContent>
    </Popover>
  );
}
