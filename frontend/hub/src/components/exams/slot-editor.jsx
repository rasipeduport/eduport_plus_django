import { useState } from 'react';
import { format } from 'date-fns';
import { ChevronDownIcon } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { ButtonGroup } from '@/components/ui/button-group';
import { Calendar } from '@/components/ui/calendar';
import { Label } from '@/components/ui/label';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { TimeSelect } from '@/components/sessions/time-select';
import { utcToZonedWallTime } from '@/lib/timezone';

// Date / time / duration controls for one exam slot -- the same trio the New
// Session sheet uses for a class, so an exam is scheduled the way a class is.
const HOURS = Array.from({ length: 12 }, (_, i) => i + 1);
const MINUTES = Array.from({ length: 12 }, (_, i) => (i * 5).toString().padStart(2, '0'));
export const DURATIONS = [0.5, 1, 1.5, 2];

const HOUR_OPTIONS = HOURS.map((h) => ({ value: String(h), label: String(h) }));
const MINUTE_OPTIONS = MINUTES.map((m) => ({ value: m, label: m }));

export const emptySlot = () => ({ date: undefined, hour: '', minute: '', meridiem: '', duration: 1 });

function to24Hour(hour12, meridiem) {
  if (meridiem === 'AM') return hour12 === 12 ? 0 : hour12;
  return hour12 === 12 ? 12 : hour12 + 12;
}

function toLocalDateString(d) {
  const pad = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** A completed slot as the student's wall clock reads it. Null while incomplete. */
export function wallTimeFor(slot) {
  if (!slot.date || slot.hour === '' || slot.minute === '' || slot.meridiem === '') return null;
  const hour24 = to24Hour(Number(slot.hour), slot.meridiem);
  return { date: toLocalDateString(slot.date), time: `${String(hour24).padStart(2, '0')}:${slot.minute}` };
}

/** The slot an existing exam occupies, read back in `zone` (for rescheduling). */
export function slotFromExam(exam, zone) {
  const wall = utcToZonedWallTime(exam.start_time, zone);
  const [y, m, d] = wall.date.split('-').map(Number);
  const [hour24, minute] = wall.time.split(':').map(Number);
  const meridiem = hour24 >= 12 ? 'PM' : 'AM';
  const hour12 = hour24 % 12 === 0 ? 12 : hour24 % 12;
  const minutes = Math.round(minute / 5) * 5;
  const hours = (new Date(exam.end_time) - new Date(exam.start_time)) / 3600000;
  return {
    date: new Date(y, m - 1, d),
    hour: String(hour12),
    minute: String(minutes >= 60 ? 55 : minutes).padStart(2, '0'),
    meridiem,
    duration: DURATIONS.includes(hours) ? hours : 1,
  };
}

export function SlotEditor({ slot, onChange, disabled = false }) {
  const [calendarOpen, setCalendarOpen] = useState(false);
  const set = (key, value) => onChange({ ...slot, [key]: value });

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-end gap-3">
        <div className="flex flex-col gap-1.5">
          <span className="text-muted-foreground text-xs">Date</span>
          <Popover modal open={calendarOpen} onOpenChange={setCalendarOpen}>
            <PopoverTrigger asChild>
              <Button type="button" variant="outline" className="w-48 justify-between font-normal" disabled={disabled}>
                <span className="truncate">{slot.date ? format(slot.date, 'PPP') : 'Select date'}</span>
                <ChevronDownIcon className="shrink-0" />
              </Button>
            </PopoverTrigger>
            <PopoverContent className="w-auto overflow-hidden p-0" align="start">
              <Calendar
                mode="single"
                selected={slot.date}
                captionLayout="dropdown"
                defaultMonth={slot.date}
                onSelect={(date) => {
                  set('date', date);
                  setCalendarOpen(false);
                }}
              />
            </PopoverContent>
          </Popover>
        </div>

        <div className="flex flex-col gap-1.5">
          <span className="text-muted-foreground text-xs">Time</span>
          <div className="flex items-center gap-1.5">
            <TimeSelect ariaLabel="Hour" value={slot.hour} onValueChange={(v) => set('hour', v)} options={HOUR_OPTIONS} placeholder="HH" className="w-20" disabled={disabled} />
            <span className="text-muted-foreground">:</span>
            <TimeSelect ariaLabel="Minute" value={slot.minute} onValueChange={(v) => set('minute', v)} options={MINUTE_OPTIONS} placeholder="MM" className="w-20" disabled={disabled} />
            <ButtonGroup className="ml-1">
              <Button type="button" size="sm" variant={slot.meridiem === 'AM' ? 'default' : 'outline'} onClick={() => set('meridiem', 'AM')} disabled={disabled}>
                AM
              </Button>
              <Button type="button" size="sm" variant={slot.meridiem === 'PM' ? 'default' : 'outline'} onClick={() => set('meridiem', 'PM')} disabled={disabled}>
                PM
              </Button>
            </ButtonGroup>
          </div>
        </div>
      </div>

      <div className="flex flex-col gap-2">
        <Label>Duration</Label>
        <ButtonGroup>
          {DURATIONS.map((d) => (
            <Button key={d} type="button" size="sm" variant={slot.duration === d ? 'default' : 'outline'} onClick={() => set('duration', d)} disabled={disabled}>
              {d === 1 ? '1 hour' : `${d} hours`}
            </Button>
          ))}
        </ButtonGroup>
      </div>
    </div>
  );
}
