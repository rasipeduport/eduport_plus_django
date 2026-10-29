import { XIcon } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { BookingTypeBadge } from '@/components/enquiries/enquiry-badges';
import { BOOKING_TYPES, DEFAULT_WHEN, WHEN_FILTERS } from '@/lib/bookings';
import { slotParts } from '@/lib/enquiries';
import { BookingStateBadge } from './booking-badges';

const ALL = '__all__';

/**
 * The bookings a tutor is assigned to teach (GET /api/tutor/bookings/): the
 * type tabs, the Upcoming / Past / All filter and paging the API applies
 * (lib/bookings), and per row a way to open the booking. Read-only: a tutor
 * never assigns or changes a tutor. Each row shows the slot in Indian time and
 * the child it is for -- nothing of the parent, the BDE or the assignment is
 * read here. The page keeps the filters in the URL; `onChange` receives what
 * changed.
 */
export function TutorBookingList({ rows, total, page, pageSize, filters, pending, onChange, onOpen }) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const startRow = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const endRow = Math.min(page * pageSize, total);
  const filtered = Boolean(filters.type || filters.when !== DEFAULT_WHEN);

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
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
        <Select
          value={filters.when}
          onValueChange={(value) => onChange({ when: value === DEFAULT_WHEN ? null : value })}
        >
          <SelectTrigger size="sm" aria-label="Filter by when" className="w-[140px]">
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
        {filtered ? (
          <Button
            variant="ghost"
            size="sm"
            className="text-muted-foreground"
            onClick={() => onChange({ type: null, when: null })}
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
              <TableHead className="hidden md:table-cell">Syllabus</TableHead>
              <TableHead className="hidden lg:table-cell">School</TableHead>
              <TableHead className="hidden lg:table-cell">Country</TableHead>
              <TableHead>Status</TableHead>
              <TableHead className="w-px">
                <span className="sr-only">Actions</span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody className={pending ? 'opacity-60' : undefined}>
            {rows.length === 0 ? (
              <TableRow>
                <TableCell colSpan={8} className="h-24 text-center">
                  {filtered ? 'No bookings match these filters.' : 'No upcoming bookings assigned to you.'}
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
                    <TableCell className="hidden md:table-cell">{booking.syllabus || '—'}</TableCell>
                    <TableCell className="hidden lg:table-cell">{booking.school_name || '—'}</TableCell>
                    <TableCell className="hidden lg:table-cell">{booking.country || '—'}</TableCell>
                    <TableCell>
                      <BookingStateBadge booking={booking} />
                    </TableCell>
                    <TableCell>
                      <div className="flex justify-end">
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => onOpen(booking.id)}
                          aria-label={`View the booking for ${booking.student_name}`}
                        >
                          View
                        </Button>
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
