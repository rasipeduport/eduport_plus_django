import { XIcon } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { FilterSelect, SearchField } from '@/components/page/list-toolbar';
import { FEEDBACK_FILTERS, TUTOR_STATUSES } from '@/lib/tutor-booking-filters';
import { reportWords } from '@/lib/reports';
import { ClassDateFilter } from './class-date-filter';

/**
 * A tutor's Demo or Diagnostic Bookings filters (`type`): the class date in a
 * section of its own, as every booking list has it (ClassDateFilter), then
 * the student's name, the booking status (Upcoming and All) and whether the
 * feedback or results are in (Completed and All), and Clear all filters while
 * any is set. `filters` are lib/tutor-booking-filters'; `onChange(updates)`
 * takes URL values (null for a default) and `onClear()` puts every one back.
 */
export function TutorBookingFilters({ type, filters, onChange, onClear }) {
  const words = reportWords(type);
  return (
    <div className="flex flex-col gap-3">
      <ClassDateFilter filters={filters} onChange={onChange} />
      <div className="flex flex-wrap items-center gap-2">
        <SearchField
          value={filters.q}
          onSearch={(text) => onChange({ q: text || null })}
          label="Search bookings by student name"
          placeholder="Search student name…"
        />
        {filters.view !== 'completed' ? (
          <FilterSelect
            label="Filter by booking status"
            placeholder="All statuses"
            value={filters.status}
            onChange={(value) => onChange({ status: value || null })}
            options={TUTOR_STATUSES}
          />
        ) : null}
        {filters.view !== 'upcoming' ? (
          <FilterSelect
            label={`Filter by ${words.noun}`}
            placeholder={`All ${words.noun}`}
            value={filters.feedback}
            onChange={(value) => onChange({ feedback: value || null })}
            options={FEEDBACK_FILTERS.map((option) => ({ ...option, label: `${words.tab}: ${option.label}` }))}
          />
        ) : null}
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
