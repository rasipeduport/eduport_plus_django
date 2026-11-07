import { useId } from 'react';
import { CalendarRangeIcon, ChevronDownIcon, XIcon } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { DateRangeFilter } from '@/components/page/date-range-filter';
import { FilterSelect, SearchField } from '@/components/page/list-toolbar';
import { CLASS_DATE_OPTIONS, DEFAULT_CLASS_DATES, SCHEDULE_OPTIONS } from '@/lib/bde-booking-filters';
import { DEFAULT_WHEN } from '@/lib/bookings';
import { rangeLabel } from '@/lib/date-range';
import { cn } from '@/lib/utils';

// The schedule select offers its default, Upcoming, as its empty value.
const OTHER_SCHEDULES = SCHEDULE_OPTIONS.filter((option) => option.value !== DEFAULT_WHEN);

/** One class-date option: pressed while it is the list's. */
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
 * The Demo and Diagnostic Bookings filters: the class date in a section of its
 * own -- Today, This Week, This Month, All Time or a Custom range picked on a
 * calendar, with the Indian dates it covers spelt out -- then search, booking
 * status (`statuses`) and schedule, and Clear all filters while any is off its
 * default. `filters` are readBdeBookingFilters'; `onChange(updates)` takes URL
 * values (null for a default) and `onClear()` puts every one back.
 */
export function BdeBookingFilters({ filters, statuses, onChange, onClear }) {
  const labelId = useId();
  const pick = (preset) => onChange({ dates: preset === DEFAULT_CLASS_DATES ? null : preset, from: null, to: null });

  return (
    <div className="flex flex-col gap-3">
      <section
        aria-labelledby={labelId}
        className="flex flex-col gap-2 rounded-lg border p-3 sm:flex-row sm:flex-wrap sm:items-center sm:gap-x-4"
      >
        <span id={labelId} className="flex items-center gap-2 text-sm font-medium">
          <CalendarRangeIcon className="text-muted-foreground size-4" aria-hidden="true" />
          Class date
        </span>
        <div role="group" aria-labelledby={labelId} className="bg-muted grid grid-cols-6 gap-1 rounded-lg p-1 sm:flex">
          {CLASS_DATE_OPTIONS.map((option, index) => {
            // On a phone the five are three over two, each row its full width.
            const span = index < 3 ? 'col-span-2' : 'col-span-3';
            return option.value === 'custom' ? (
              <DateRangeFilter
                key={option.value}
                from={filters.from}
                to={filters.to}
                anyLabel="All Time"
                onChange={(range) => (range.from ? onChange({ dates: 'custom', ...range }) : pick(DEFAULT_CLASS_DATES))}
              >
                <DateOption pressed={filters.dates === 'custom'} className={span}>
                  {option.label}
                  <ChevronDownIcon className="size-3.5" aria-hidden="true" />
                </DateOption>
              </DateRangeFilter>
            ) : (
              <DateOption
                key={option.value}
                pressed={filters.dates === option.value}
                className={span}
                onClick={() => pick(option.value)}
              >
                {option.label}
              </DateOption>
            );
          })}
        </div>
        <p className="text-muted-foreground text-xs sm:ml-auto" aria-live="polite">
          {filters.from || filters.to
            ? `Classes on ${rangeLabel(filters.from, filters.to)} (IST)`
            : 'Classes on any date'}
        </p>
      </section>
      <div className="flex flex-wrap items-center gap-2">
        <SearchField
          value={filters.q}
          onSearch={(text) => onChange({ q: text || null })}
          label="Search bookings"
          placeholder="Search student, parent or phone…"
        />
        <FilterSelect
          label="Filter by booking status"
          placeholder="All statuses"
          value={filters.status}
          onChange={(value) => onChange({ status: value || null })}
          options={statuses}
        />
        <FilterSelect
          label="Filter by schedule"
          placeholder="Upcoming"
          value={filters.when === DEFAULT_WHEN ? '' : filters.when}
          onChange={(value) => onChange({ when: value || null })}
          options={OTHER_SCHEDULES}
        />
        {filters.filtered ? (
          <Button variant="ghost" className="text-muted-foreground" onClick={onClear}>
            <XIcon className="size-4" />
            Clear all filters
          </Button>
        ) : null}
      </div>
    </div>
  );
}
