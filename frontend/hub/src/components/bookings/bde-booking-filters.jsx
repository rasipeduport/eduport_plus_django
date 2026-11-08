import { XIcon } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { FilterSelect, SearchField } from '@/components/page/list-toolbar';
import { SCHEDULE_OPTIONS } from '@/lib/bde-booking-filters';
import { DEFAULT_WHEN } from '@/lib/bookings';
import { ClassDateFilter } from './class-date-filter';

// The schedule select offers its default, Upcoming, as its empty value.
const OTHER_SCHEDULES = SCHEDULE_OPTIONS.filter((option) => option.value !== DEFAULT_WHEN);

/**
 * The Demo and Diagnostic Bookings filters: the class date in a section of its
 * own -- Today, This Week, This Month, All Time or a Custom range picked on a
 * calendar, with the Indian dates it covers spelt out (ClassDateFilter) --
 * then search, booking status (`statuses`) and schedule, and Clear all filters
 * while any is off its default. `filters` are readBdeBookingFilters';
 * `onChange(updates)` takes URL values (null for a default) and `onClear()`
 * puts every one back.
 */
export function BdeBookingFilters({ filters, statuses, onChange, onClear }) {
  return (
    <div className="flex flex-col gap-3">
      <ClassDateFilter filters={filters} onChange={onChange} />
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
