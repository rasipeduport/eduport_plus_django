import { useState } from 'react';
import { format } from 'date-fns';
import { CalendarIcon, ChevronDownIcon } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Calendar } from '@/components/ui/calendar';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { cn } from '@/lib/utils';

const pad = (value) => String(value).padStart(2, '0');

// The calendar works in this device's dates; the filter in plain YYYY-MM-DD dates (a slot's Indian date, say).
function toPickerDate(iso) {
  if (!iso) return undefined;
  const [year, month, day] = iso.split('-').map(Number);
  return new Date(year, month - 1, day);
}

function fromPickerDate(date) {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

function rangeLabel(from, to, anyLabel) {
  if (!from && !to) return anyLabel;
  const label = (iso) => format(toPickerDate(iso), 'd MMM yyyy');
  if (from && to) return from === to ? label(from) : `${label(from)} – ${label(to)}`;
  return from ? `From ${label(from)}` : `Until ${label(to)}`;
}

/**
 * A date range filter for a list's toolbar: a button naming the range that
 * opens a calendar, where two clicks pick the first and last day. `from` and
 * `to` are YYYY-MM-DD or ''; `onChange({ from, to })` gets the picked range,
 * or both null for `anyLabel` ("Any date").
 */
export function DateRangeFilter({ from, to, onChange, label = 'Filter by date range', anyLabel = 'Any date', className }) {
  const [open, setOpen] = useState(false);
  const [range, setRange] = useState(undefined);

  const openRange = (next) => {
    setOpen(next);
    if (next) setRange({ from: toPickerDate(from), to: toPickerDate(to) });
  };

  return (
    <Popover open={open} onOpenChange={openRange}>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          aria-label={label}
          className={cn('min-w-0 flex-1 basis-44 justify-between font-normal sm:flex-none sm:basis-auto', className)}
        >
          <CalendarIcon />
          <span className="truncate">{rangeLabel(from, to, anyLabel)}</span>
          <ChevronDownIcon className="shrink-0" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-auto overflow-hidden p-0" align="start">
        <Calendar
          mode="range"
          selected={range}
          defaultMonth={range?.from}
          onSelect={(picked) => {
            setRange(picked);
            if (picked?.from && picked?.to) {
              onChange({ from: fromPickerDate(picked.from), to: fromPickerDate(picked.to) });
              setOpen(false);
            }
          }}
        />
        {from || to ? (
          <div className="border-t p-2">
            <Button
              variant="ghost"
              size="sm"
              className="w-full"
              onClick={() => {
                onChange({ from: null, to: null });
                setOpen(false);
              }}
            >
              {anyLabel}
            </Button>
          </div>
        ) : null}
      </PopoverContent>
    </Popover>
  );
}
