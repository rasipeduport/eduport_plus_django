import { useId } from 'react';
import { CalendarRangeIcon } from 'lucide-react';

import { DatePresets } from '@/components/page/date-presets';
import { CLASS_DATE_OPTIONS, DEFAULT_CLASS_DATES } from '@/lib/bde-booking-filters';
import { rangeLabel } from '@/lib/date-range';

/**
 * The booking lists' class date, in a section of its own: Today, This Week,
 * This Month, All Time or a Custom range picked on a calendar, with the Indian
 * dates it covers spelt out. `filters` holds `dates` (the preset), `from` and
 * `to`; `onChange(updates)` takes URL values (null for the default, All Time).
 * A BDE's Demo and Diagnostic Bookings and the administrators' share it.
 */
export function ClassDateFilter({ filters, onChange }) {
  const labelId = useId();
  const pick = (preset) => onChange({ dates: preset === DEFAULT_CLASS_DATES ? null : preset, from: null, to: null });

  return (
    <section
      aria-labelledby={labelId}
      className="flex flex-col gap-2 rounded-lg border p-3 sm:flex-row sm:flex-wrap sm:items-center sm:gap-x-4"
    >
      <span id={labelId} className="flex items-center gap-2 text-sm font-medium">
        <CalendarRangeIcon className="text-muted-foreground size-4" aria-hidden="true" />
        Class date
      </span>
      <DatePresets
        options={CLASS_DATE_OPTIONS}
        value={filters.dates}
        from={filters.from}
        to={filters.to}
        anyLabel="All Time"
        labelledBy={labelId}
        onPick={pick}
        onCustom={(range) => (range.from ? onChange({ dates: 'custom', ...range }) : pick(DEFAULT_CLASS_DATES))}
      />
      <p className="text-muted-foreground text-xs sm:ml-auto" aria-live="polite">
        {filters.from || filters.to ? `Classes on ${rangeLabel(filters.from, filters.to)} (IST)` : 'Classes on any date'}
      </p>
    </section>
  );
}
