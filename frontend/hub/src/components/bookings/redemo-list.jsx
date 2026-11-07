import { useState } from 'react';
import { XIcon } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { REDEMO_STATUSES, REDEMO_TAB } from '@/lib/bookings';
import { formatDay, slotParts } from '@/lib/enquiries';
import { RedemoStatusBadge } from './booking-badges';
import { BookingTabs } from './booking-list';

const ALL = '__all__';

function When({ slot }) {
  if (!slot) return <span className="text-muted-foreground">—</span>;
  const when = slotParts(slot.date, slot.time);
  return (
    <>
      <p className="font-medium">{when.day}</p>
      <p className="text-muted-foreground text-xs">{when.time}</p>
    </>
  );
}

/**
 * The Re-Demo requests, as administrators manage them (the Bookings page's
 * Re-Demo tab): newest first, each with the child, the original Demo and its
 * tutor, who asked, where it stands, and the Re-Demo's tutor and slot once an
 * administrator has scheduled it -- searched, filtered by status and paged by
 * the API. A request opens in a side sheet (`onOpen`); `onChange` receives what
 * changed in the URL.
 */
export function RedemoList({ rows, total, page, pageSize, filters, pending, onChange, onOpen }) {
  const [q, setQ] = useState(filters.q);

  // Keep the box in step when the URL changes underneath it (Clear, back).
  const [prevQ, setPrevQ] = useState(filters.q);
  if (filters.q !== prevQ) {
    setPrevQ(filters.q);
    setQ(filters.q);
  }

  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const startRow = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const endRow = Math.min(page * pageSize, total);
  const filtered = Boolean(filters.q || filters.status);

  return (
    <div className="flex flex-col gap-3">
      <BookingTabs value={REDEMO_TAB} onChange={onChange} />

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
            aria-label="Search Re-Demo requests"
          />
        </form>
        <Select value={filters.status || ALL} onValueChange={(value) => onChange({ status: value === ALL ? null : value })}>
          <SelectTrigger
            size="sm"
            aria-label="Filter by Re-Demo status"
            className="min-w-0 flex-1 basis-40 sm:w-[190px] sm:flex-none sm:basis-auto"
          >
            <SelectValue placeholder="All statuses" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>All statuses</SelectItem>
            {REDEMO_STATUSES.map((option) => (
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
            onClick={() => onChange({ q: null, status: null })}
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
              <TableHead>Requested</TableHead>
              <TableHead>Student</TableHead>
              <TableHead className="hidden lg:table-cell">Original Demo (IST)</TableHead>
              <TableHead>Status</TableHead>
              <TableHead className="hidden md:table-cell">Re-Demo tutor</TableHead>
              <TableHead className="hidden xl:table-cell">Re-Demo (IST)</TableHead>
              <TableHead className="w-px">
                <span className="sr-only">Actions</span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody className={pending ? 'opacity-60' : undefined}>
            {rows.length === 0 ? (
              <TableRow>
                <TableCell colSpan={7} className="h-24 text-center">
                  {filtered ? 'No Re-Demo requests match these filters.' : 'No Re-Demo requests yet.'}
                </TableCell>
              </TableRow>
            ) : (
              rows.map((redemo) => (
                <TableRow key={redemo.id}>
                  <TableCell className="whitespace-nowrap">
                    <p className="font-medium">{formatDay(redemo.requested_at)}</p>
                    <p className="text-muted-foreground max-w-40 truncate text-xs">by {redemo.requested_by?.full_name}</p>
                  </TableCell>
                  <TableCell className="min-w-28 whitespace-normal">
                    <p className="font-medium break-words">{redemo.student_name}</p>
                    <p className="text-muted-foreground text-xs">
                      {[redemo.grade, redemo.owner_bde ? `BDE: ${redemo.owner_bde.full_name}` : 'No BDE']
                        .filter(Boolean)
                        .join(' · ')}
                    </p>
                  </TableCell>
                  <TableCell className="hidden whitespace-nowrap lg:table-cell">
                    <When slot={redemo.original?.slot} />
                    <p className="text-muted-foreground text-xs">{redemo.original?.tutor?.full_name ?? 'No tutor'}</p>
                  </TableCell>
                  <TableCell>
                    <RedemoStatusBadge status={redemo.status} />
                  </TableCell>
                  <TableCell className="hidden whitespace-normal md:table-cell">
                    {redemo.tutor ? (
                      <span className="font-medium">{redemo.tutor.full_name}</span>
                    ) : (
                      <span className="text-muted-foreground">—</span>
                    )}
                  </TableCell>
                  <TableCell className="hidden whitespace-nowrap xl:table-cell">
                    <When slot={redemo.booking?.slot} />
                  </TableCell>
                  <TableCell>
                    <div className="flex justify-end">
                      <Button
                        variant={redemo.status === 'AWAITING_SCHEDULING' ? 'default' : 'outline'}
                        size="sm"
                        onClick={() => onOpen(redemo.id)}
                        aria-label={`View the Re-Demo request for ${redemo.student_name}`}
                      >
                        View
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))
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
