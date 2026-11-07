import { useState } from 'react';
import { CalendarIcon, ChevronDownIcon } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Calendar } from '@/components/ui/calendar';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { fromPickerDate, rangeLabel, toPickerDate } from '@/lib/date-range';
import { cn } from '@/lib/utils';

/**
 * A date range filter: a calendar where two clicks pick the first and the last
 * day, in either order (the same day twice for one day), opened by a button
 * naming the range -- or by `children`, a trigger of the caller's own. `from`
 * and `to` are YYYY-MM-DD or ''; `onChange({ from, to })` gets the picked
 * range, or both null for `anyLabel` ("Any date").
 */
export function DateRangeFilter({
  from,
  to,
  onChange,
  label = 'Filter by date range',
  anyLabel = 'Any date',
  className,
  children,
}) {
  const [open, setOpen] = useState(false);
  // The first day picked, while the last is still to be picked.
  const [first, setFirst] = useState(null);

  const openRange = (next) => {
    setOpen(next);
    if (next) setFirst(null);
  };
  const selected = first ? { from: first, to: first } : { from: toPickerDate(from), to: toPickerDate(to) };

  return (
    <Popover open={open} onOpenChange={openRange}>
      <PopoverTrigger asChild>
        {children ?? (
          <Button
            variant="outline"
            aria-label={label}
            className={cn('min-w-0 flex-1 basis-44 justify-between font-normal sm:flex-none sm:basis-auto', className)}
          >
            <CalendarIcon />
            <span className="truncate">{rangeLabel(from, to, anyLabel)}</span>
            <ChevronDownIcon className="shrink-0" />
          </Button>
        )}
      </PopoverTrigger>
      <PopoverContent className="w-auto overflow-hidden p-0" align="start" collisionPadding={16}>
        {/* Weeks run Monday to Sunday, as This Week does. */}
        <Calendar
          mode="range"
          weekStartsOn={1}
          selected={selected}
          defaultMonth={first ?? selected.from}
          onSelect={(_range, day) => {
            if (!first) {
              setFirst(day);
              return;
            }
            const [start, end] = day < first ? [day, first] : [first, day];
            onChange({ from: fromPickerDate(start), to: fromPickerDate(end) });
            setOpen(false);
          }}
        />
        <div className="flex items-center justify-between gap-2 border-t p-2">
          <p className="text-muted-foreground px-1 text-xs" role="status">
            {first ? 'Now pick the last day.' : 'Pick the first day.'}
          </p>
          {from || to ? (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                onChange({ from: null, to: null });
                setOpen(false);
              }}
            >
              {anyLabel}
            </Button>
          ) : null}
        </div>
      </PopoverContent>
    </Popover>
  );
}
