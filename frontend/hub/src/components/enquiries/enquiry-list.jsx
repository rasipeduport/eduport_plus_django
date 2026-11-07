import { useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { ChevronRightIcon, XIcon } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { LEAD_STATUSES, SOURCE_FILTERS, formatDay, slotLabel } from '@/lib/enquiries';
import { EnquiryStatusBadge } from './enquiry-badges';

const ALL = '__all__';

/**
 * A list of leads: search, status and source filters, and paging, all kept in
 * the URL (like the team directory) and applied by the API. Each row opens
 * the lead's page (`basePath`/:id). Given `owners` (the owner filter's
 * options) it is the administrators' list: when each lead came in, who owns
 * it, an owner filter and, with `onAssign`, giving a lead to a BDE. The
 * administrators' Leads page (/leads) is its one user now: a BDE's My
 * Enquiries is built on the shared page kit (my-enquiries-list.jsx).
 */
export function EnquiryList({
  rows,
  total,
  page,
  pageSize,
  filters,
  pending,
  basePath = '/enquiries',
  owners = null,
  onAssign = null,
  emptyMessage = 'No leads yet. Share your booking links, or add a lead that reached you another way.',
}) {
  const [searchParams, setSearchParams] = useSearchParams();
  const [q, setQ] = useState(filters.q);

  // Keep the box in step when the URL changes underneath it (Clear, back).
  const [prevQ, setPrevQ] = useState(filters.q);
  if (filters.q !== prevQ) {
    setPrevQ(filters.q);
    setQ(filters.q);
  }

  const navigate = (updates) => {
    const params = new URLSearchParams(searchParams);
    for (const [key, value] of Object.entries(updates)) {
      if (value === null || value === '') params.delete(key);
      else params.set(key, value);
    }
    // Any filter change (anything but paging) resets to the first page.
    if (!('page' in updates)) params.delete('page');
    setSearchParams(params);
  };

  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const startRow = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const endRow = Math.min(page * pageSize, total);
  const hasFilters = Boolean(filters.q || filters.status || filters.source || filters.owner);
  const admin = Boolean(owners);
  const columns = 8 + (admin ? 2 : 0) + (onAssign ? 1 : 0);

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <form
          className="min-w-0 flex-1 basis-full sm:flex-none sm:basis-auto"
          onSubmit={(event) => {
            event.preventDefault();
            navigate({ q: q.trim() || null });
          }}
        >
          <Input
            placeholder="Search parent, student or phone…"
            value={q}
            onChange={(event) => setQ(event.target.value)}
            className="w-full sm:w-72"
            aria-label="Search leads"
          />
        </form>
        <FilterSelect
          placeholder="All statuses"
          label="Filter by status"
          value={filters.status || ALL}
          onChange={(value) => navigate({ status: value === ALL ? null : value })}
          options={LEAD_STATUSES}
        />
        <FilterSelect
          placeholder="All sources"
          label="Filter by source"
          value={filters.source || ALL}
          onChange={(value) => navigate({ source: value === ALL ? null : value })}
          options={SOURCE_FILTERS}
        />
        {admin ? (
          <FilterSelect
            placeholder="All owners"
            label="Filter by owner"
            value={filters.owner || ALL}
            onChange={(value) => navigate({ owner: value === ALL ? null : value })}
            options={owners}
          />
        ) : null}
        {hasFilters ? (
          <Button
            variant="ghost"
            size="sm"
            className="text-muted-foreground"
            onClick={() => setSearchParams(new URLSearchParams())}
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
              {admin ? <TableHead>Received</TableHead> : null}
              <TableHead>Parent</TableHead>
              <TableHead>Phone</TableHead>
              <TableHead>Student</TableHead>
              <TableHead>Class</TableHead>
              <TableHead>Source</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Next booking</TableHead>
              {admin ? <TableHead>Owner</TableHead> : null}
              {onAssign ? (
                <TableHead className="w-px">
                  <span className="sr-only">Assign</span>
                </TableHead>
              ) : null}
              <TableHead className="w-10">
                <span className="sr-only">Open</span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody className={pending ? 'opacity-60' : undefined}>
            {rows.length === 0 ? (
              <TableRow>
                <TableCell colSpan={columns} className="h-24 text-center">
                  {hasFilters ? 'No leads match these filters.' : emptyMessage}
                </TableCell>
              </TableRow>
            ) : (
              rows.map((enquiry) => (
                <TableRow key={enquiry.id}>
                  {admin ? (
                    <TableCell className="text-muted-foreground whitespace-nowrap">{formatDay(enquiry.created_at)}</TableCell>
                  ) : null}
                  <TableCell>
                    <Link to={`${basePath}/${enquiry.id}`} className="font-medium hover:underline">
                      {enquiry.parent_name}
                    </Link>
                  </TableCell>
                  <TableCell className="text-muted-foreground tabular-nums">{enquiry.phone}</TableCell>
                  <TableCell>{enquiry.student_name}</TableCell>
                  <TableCell>{enquiry.grade || '—'}</TableCell>
                  <TableCell>{enquiry.source_label}</TableCell>
                  <TableCell>
                    <EnquiryStatusBadge enquiry={enquiry} />
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {enquiry.next_booking ? slotLabel(enquiry.next_booking) : '—'}
                  </TableCell>
                  {admin ? (
                    <TableCell>
                      {enquiry.owner ? enquiry.owner.full_name : <span className="text-muted-foreground">Unassigned</span>}
                    </TableCell>
                  ) : null}
                  {onAssign ? (
                    <TableCell>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => onAssign(enquiry)}
                        aria-label={`${enquiry.owner ? 'Reassign' : 'Assign'} the lead for ${enquiry.student_name}`}
                      >
                        {enquiry.owner ? 'Reassign' : 'Assign'}
                      </Button>
                    </TableCell>
                  ) : null}
                  <TableCell>
                    <Button variant="ghost" size="icon" className="size-8" asChild>
                      <Link to={`${basePath}/${enquiry.id}`} aria-label={`Open the lead for ${enquiry.student_name}`}>
                        <ChevronRightIcon className="size-4" />
                      </Link>
                    </Button>
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
            onClick={() => navigate({ page: String(page - 1) })}
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
            onClick={() => navigate({ page: String(page + 1) })}
          >
            Next
          </Button>
        </div>
      </div>
    </div>
  );
}

function FilterSelect({ placeholder, label, value, onChange, options }) {
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
