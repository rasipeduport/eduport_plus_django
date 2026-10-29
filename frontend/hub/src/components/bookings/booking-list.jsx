import { useState } from 'react';
import { CalendarIcon, ChevronDownIcon, XIcon } from 'lucide-react';
import { format } from 'date-fns';

import { Button } from '@/components/ui/button';
import { Calendar } from '@/components/ui/calendar';
import { Input } from '@/components/ui/input';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { BookingTypeBadge } from '@/components/enquiries/enquiry-badges';
import {
  ASSIGNMENT_FILTERS,
  BOOKING_STATUSES,
  BOOKING_TYPES,
  DEFAULT_WHEN,
  WHEN_FILTERS,
  tutorChangeable,
} from '@/lib/bookings';
import { slotParts } from '@/lib/enquiries';
import { BookingStateBadge, TutorName } from './booking-badges';

const ALL = '__all__';
const pad = (value) => String(value).padStart(2, '0');

// The calendar works in this device's dates; the filter in the slots' Indian dates (YYYY-MM-DD).
function toPickerDate(iso) {
  if (!iso) return undefined;
  const [year, month, day] = iso.split('-').map(Number);
  return new Date(year, month - 1, day);
}

function fromPickerDate(date) {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

function rangeLabel(from, to) {
  if (!from && !to) return 'Any date';
  const label = (iso) => format(toPickerDate(iso), 'd MMM yyyy');
  if (from && to) return from === to ? label(from) : `${label(from)} – ${label(to)}`;
  return from ? `From ${label(from)}` : `Until ${label(to)}`;
}

/**
 * Every Demo and Diagnostic booking, as administrators manage them: the type
 * tabs, search, status / tutor / date filters and paging the API applies
 * (lib/bookings), and per row a way to open the booking and, for holders of
 * accounts.assign_booking_tutor, to assign or change its tutor. The page keeps
 * the filters in the URL; `onChange` receives what changed.
 */
export function BookingList({ rows, total, page, pageSize, filters, pending, canAssign, onChange, onOpen, onAssign }) {
  const [q, setQ] = useState(filters.q);
  const [rangeOpen, setRangeOpen] = useState(false);
  const [range, setRange] = useState(undefined);

  // Keep the box in step when the URL changes underneath it (Clear, back).
  const [prevQ, setPrevQ] = useState(filters.q);
  if (filters.q !== prevQ) {
    setPrevQ(filters.q);
    setQ(filters.q);
  }

  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const startRow = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const endRow = Math.min(page * pageSize, total);
  const filtered = Boolean(
    filters.q || filters.status || filters.assigned || filters.from || filters.to || filters.when !== DEFAULT_WHEN
  );

  const openRange = (open) => {
    setRangeOpen(open);
    if (open) setRange({ from: toPickerDate(filters.from), to: toPickerDate(filters.to) });
  };

  return (
    <div className="flex flex-col gap-3">
      <Tabs value={filters.type || ALL} onValueChange={(value) => onChange({ type: value === ALL ? null : value })}>
        <TabsList>
          <TabsTrigger value={ALL}>All</TabsTrigger>
          {BOOKING_TYPES.map((type) => (
            <TabsTrigger key={type.value} value={type.value}>
              {type.label}
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>

      <div className="flex flex-wrap items-center gap-2">
        <form
          className="min-w-0 flex-1 basis-full sm:flex-none sm:basis-auto"
          onSubmit={(event) => {
            event.preventDefault();
            onChange({ q: q.trim() || null });
          }}
        >
          <Input
            placeholder="Search student, parent or phone…"
            value={q}
            onChange={(event) => setQ(event.target.value)}
            className="w-full sm:w-72"
            aria-label="Search bookings"
          />
        </form>
        <FilterSelect
          label="Filter by status"
          placeholder="All statuses"
          value={filters.status || ALL}
          onChange={(value) => onChange({ status: value === ALL ? null : value })}
          options={BOOKING_STATUSES}
        />
        <FilterSelect
          label="Filter by tutor assignment"
          placeholder="All tutors"
          value={filters.assigned || ALL}
          onChange={(value) => onChange({ assigned: value === ALL ? null : value })}
          options={ASSIGNMENT_FILTERS}
        />
        <Select
          value={filters.when}
          onValueChange={(value) => onChange({ when: value === DEFAULT_WHEN ? null : value })}
        >
          <SelectTrigger
            size="sm"
            aria-label="Filter by when"
            className="min-w-0 flex-1 basis-32 sm:w-[140px] sm:flex-none sm:basis-auto"
          >
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {WHEN_FILTERS.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Popover open={rangeOpen} onOpenChange={openRange}>
          <PopoverTrigger asChild>
            <Button
              variant="outline"
              size="sm"
              className="min-w-0 flex-1 basis-44 justify-between font-normal sm:flex-none sm:basis-auto"
              aria-label="Filter by date range"
            >
              <CalendarIcon />
              <span className="truncate">{rangeLabel(filters.from, filters.to)}</span>
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
                  setRangeOpen(false);
                }
              }}
            />
            {filters.from || filters.to ? (
              <div className="border-t p-2">
                <Button
                  variant="ghost"
                  size="sm"
                  className="w-full"
                  onClick={() => {
                    onChange({ from: null, to: null });
                    setRangeOpen(false);
                  }}
                >
                  Any date
                </Button>
              </div>
            ) : null}
          </PopoverContent>
        </Popover>
        {filtered ? (
          <Button
            variant="ghost"
            size="sm"
            className="text-muted-foreground"
            onClick={() => onChange({ q: null, status: null, assigned: null, from: null, to: null, when: null })}
          >
            <XIcon className="size-4" />
            Clear
          </Button>
        ) : null}
      </div>

      <div className="overflow-hidden rounded-md border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>When (IST)</TableHead>
              <TableHead>Type</TableHead>
              <TableHead>Student</TableHead>
              <TableHead className="hidden md:table-cell">Parent</TableHead>
              <TableHead>Tutor</TableHead>
              <TableHead>Status</TableHead>
              <TableHead className="w-px">
                <span className="sr-only">Actions</span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody className={pending ? 'opacity-60' : undefined}>
            {rows.length === 0 ? (
              <TableRow>
                <TableCell colSpan={7} className="h-24 text-center">
                  {filtered || filters.type ? 'No bookings match these filters.' : 'No upcoming bookings.'}
                </TableCell>
              </TableRow>
            ) : (
              rows.map((booking) => {
                const when = slotParts(booking.slot.date, booking.slot.time);
                return (
                  <TableRow key={booking.id}>
                    <TableCell className="whitespace-nowrap">
                      <p className="font-medium">{when.day}</p>
                      <p className="text-muted-foreground text-xs">{when.time}</p>
                    </TableCell>
                    <TableCell>
                      <BookingTypeBadge type={booking.booking_type} />
                    </TableCell>
                    <TableCell>
                      <p className="font-medium">{booking.student_name}</p>
                      {booking.grade ? <p className="text-muted-foreground text-xs">{booking.grade}</p> : null}
                    </TableCell>
                    <TableCell className="hidden md:table-cell">
                      <p>{booking.parent_name}</p>
                      <p className="text-muted-foreground text-xs tabular-nums">{booking.phone}</p>
                    </TableCell>
                    <TableCell>
                      <TutorName booking={booking} />
                    </TableCell>
                    <TableCell>
                      <BookingStateBadge booking={booking} />
                    </TableCell>
                    <TableCell>
                      <div className="flex justify-end gap-1">
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => onOpen(booking.id)}
                          aria-label={`View the booking for ${booking.student_name}`}
                        >
                          View
                        </Button>
                        {canAssign && tutorChangeable(booking) ? (
                          <Button
                            variant={booking.tutor ? 'ghost' : 'default'}
                            size="sm"
                            onClick={() => onAssign(booking)}
                            aria-label={`${booking.tutor ? 'Change' : 'Assign'} the tutor for ${booking.student_name}`}
                          >
                            {booking.tutor ? 'Change' : 'Assign'}
                          </Button>
                        ) : null}
                      </div>
                    </TableCell>
                  </TableRow>
                );
              })
            )}
          </TableBody>
        </Table>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-muted-foreground text-sm whitespace-nowrap">
          {total === 0 ? 'No results' : `Showing ${startRow}–${endRow} of ${total}`}
        </p>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            disabled={page <= 1 || pending}
            onClick={() => onChange({ page: String(page - 1) })}
          >
            Previous
          </Button>
          <span className="text-sm whitespace-nowrap">
            Page {page} of {totalPages}
          </span>
          <Button
            variant="outline"
            size="sm"
            disabled={page >= totalPages || pending}
            onClick={() => onChange({ page: String(page + 1) })}
          >
            Next
          </Button>
        </div>
      </div>
    </div>
  );
}

function FilterSelect({ label, placeholder, value, onChange, options }) {
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger
        size="sm"
        aria-label={label}
        className="min-w-0 flex-1 basis-36 sm:w-[160px] sm:flex-none sm:basis-auto"
      >
        <SelectValue placeholder={placeholder} />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={ALL}>{placeholder}</SelectItem>
        {options.map((option) => (
          <SelectItem key={option.value} value={option.value}>
            {option.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
