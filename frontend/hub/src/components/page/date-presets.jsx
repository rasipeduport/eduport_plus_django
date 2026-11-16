import { ChevronDownIcon } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { DateRangeFilter } from '@/components/page/date-range-filter';
import { cn } from '@/lib/utils';

/** One preset: pressed while it is the list's. */
function DateOption({ pressed, className, children, ...props }) {
  return (
    <Button
      type="button"
      variant="ghost"
      size="sm"
      aria-pressed={pressed}
      className={cn(
        'h-8 min-w-0 rounded-md px-3 font-normal',
        pressed
          ? 'bg-background text-foreground hover:bg-background font-medium shadow-sm'
          : 'text-muted-foreground hover:text-foreground hover:bg-background/60',
        className
      )}
      {...props}
    >
      {children}
    </Button>
  );
}

/**
 * A row of date presets in a segmented control -- e.g. Today, This Week, This
 * Month, All Time -- whose `custom` option opens a calendar for a range of the
 * reader's own. `options` are `{ value, label }`, `value` the one in force,
 * `from` and `to` the Custom range (YYYY-MM-DD or ''). `onPick(value)` gets a
 * preset; `onCustom({ from, to })` a picked range, or both null when the
 * calendar's `anyLabel` clears it. On a phone five presets sit three over two,
 * each row its full width. `labelledBy` names the group.
 */
export function DatePresets({ options, value, from, to, anyLabel, onPick, onCustom, labelledBy }) {
  return (
    <div role="group" aria-labelledby={labelledBy} className="bg-muted grid grid-cols-6 gap-1 rounded-lg p-1 sm:flex">
      {options.map((option, index) => {
        const span = index < 3 ? 'col-span-2' : 'col-span-3';
        return option.value === 'custom' ? (
          <DateRangeFilter key={option.value} from={from} to={to} anyLabel={anyLabel} onChange={onCustom}>
            <DateOption pressed={value === 'custom'} className={span}>
              {option.label}
              <ChevronDownIcon className="size-3.5" aria-hidden="true" />
            </DateOption>
          </DateRangeFilter>
        ) : (
          <DateOption key={option.value} pressed={value === option.value} className={span} onClick={() => onPick(option.value)}>
            {option.label}
          </DateOption>
        );
      })}
    </div>
  );
}
