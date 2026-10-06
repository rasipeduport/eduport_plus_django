import { Fragment, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { format } from 'date-fns';
import { CalendarIcon, ChevronDown, XIcon } from 'lucide-react';

import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { Calendar } from '@/components/ui/calendar';
import { ACTION_LABELS, actionLabel, describeActivity } from '@/lib/activity-format';
import { cn } from '@/lib/utils';
import { ChangesTable } from './changes-table';

const ALL = '__all__';

const ENTITY_TYPES = [
  { value: 'student', label: 'Student' },
  { value: 'student_note', label: 'Student note' },
  { value: 'session', label: 'Session' },
  { value: 'exam', label: 'Exam' },
  { value: 'additional_exam', label: 'Additional exam' },
  { value: 'homework', label: 'Homework' },
  { value: 'invitation', label: 'Invitation' },
  { value: 'profile', label: 'User' },
];

const ENTITY_NOUN = {
  student: 'Student',
  student_note: 'Note on',
  session: 'Session',
  exam: 'Exam',
  additional_exam: 'Additional exam',
  homework: 'Homework',
  invitation: 'Invitation',
  profile: 'User',
};

export function ActivityFeed({ rows, total, page, pageSize, actorOptions, filters, pending = false, role = 'ADMIN' }) {
  // Mentors and tutors are pinned to their own entries by the API, so the
  // actor filter would have nothing to offer them.
  const showActorFilter = role === 'ADMIN';
  const [searchParams, setSearchParams] = useSearchParams();
  const [expanded, setExpanded] = useState(null);
  const [q, setQ] = useState(filters.q);

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

  const fromDate = filters.from ? new Date(filters.from) : undefined;
  const toDate = filters.to ? new Date(filters.to) : undefined;

  const dateLabel = (() => {
    if (fromDate && toDate) return `${format(fromDate, 'MMM d')} – ${format(toDate, 'MMM d, yyyy')}`;
    if (fromDate) return `From ${format(fromDate, 'MMM d, yyyy')}`;
    if (toDate) return `Until ${format(toDate, 'MMM d, yyyy')}`;
    return 'Date range';
  })();

  const setDateRange = (range) => {
    if (!range || (!range.from && !range.to)) {
      navigate({ from: null, to: null });
      return;
    }
    // Stretch the end of the range to the end of that day so it is inclusive.
    const end = range.to
      ? new Date(range.to.getFullYear(), range.to.getMonth(), range.to.getDate(), 23, 59, 59, 999)
      : undefined;
    navigate({
      from: range.from ? range.from.toISOString() : null,
      to: end ? end.toISOString() : null,
    });
  };

  const hasFilters = Boolean(
    filters.q || filters.action || filters.entity || filters.actor || filters.from || filters.to
  );

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <form
          className="min-w-0 flex-1 basis-full sm:flex-none sm:basis-auto"
          onSubmit={(event) => {
            event.preventDefault();
            navigate({ q: q || null });
          }}
        >
          <Input
            placeholder="Search actor or target…"
            value={q}
            onChange={(event) => setQ(event.target.value)}
            className="w-full sm:max-w-xs"
          />
        </form>

        <FilterSelect
          placeholder="All actions"
          value={filters.action || ALL}
          onChange={(value) => navigate({ action: value === ALL ? null : value })}
          options={Object.keys(ACTION_LABELS).map((action) => ({ value: action, label: ACTION_LABELS[action] }))}
        />
        <FilterSelect
          placeholder="All types"
          value={filters.entity || ALL}
          onChange={(value) => navigate({ entity: value === ALL ? null : value })}
          options={ENTITY_TYPES}
        />
        {showActorFilter ? (
          <FilterSelect
            placeholder="All actors"
            value={filters.actor || ALL}
            onChange={(value) => navigate({ actor: value === ALL ? null : value })}
            options={actorOptions.map((actor) => ({ value: actor.id, label: actor.name }))}
          />
        ) : null}

        <Popover>
          <PopoverTrigger asChild>
            <Button variant="outline" size="sm">
              <CalendarIcon className="size-4" />
              {dateLabel}
            </Button>
          </PopoverTrigger>
          <PopoverContent className="w-auto p-0" align="start">
            <Calendar
              mode="range"
              selected={fromDate || toDate ? { from: fromDate, to: toDate } : undefined}
              onSelect={setDateRange}
              numberOfMonths={2}
            />
          </PopoverContent>
        </Popover>

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
              <TableHead className="w-[170px]">When</TableHead>
              <TableHead>Who</TableHead>
              <TableHead>Action</TableHead>
              <TableHead>Details</TableHead>
              <TableHead className="w-10" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.length === 0 ? (
              <TableRow>
                <TableCell colSpan={5} className="h-24 text-center">
                  No activity found.
                </TableCell>
              </TableRow>
            ) : (
              rows.map((row) => {
                const hasChanges = Object.keys(row.changes ?? {}).length > 0;
                const isOpen = expanded === row.id;
                return (
                  <Fragment key={row.id}>
                    <TableRow
                      className={cn(hasChanges && 'cursor-pointer')}
                      onClick={() => hasChanges && setExpanded(isOpen ? null : row.id)}
                    >
                      <TableCell className="text-muted-foreground text-xs whitespace-nowrap">
                        {format(new Date(row.created_at), 'd MMM yyyy, h:mm a')}
                      </TableCell>
                      <TableCell>
                        <div className="font-medium">{row.actor_name ?? row.actor_email ?? 'Unknown'}</div>
                        {row.actor_role ? (
                          <div className="text-muted-foreground text-xs capitalize">{row.actor_role.toLowerCase()}</div>
                        ) : null}
                      </TableCell>
                      <TableCell>
                        <Badge variant="secondary">{actionLabel(row.action)}</Badge>
                      </TableCell>
                      <TableCell>
                        <div>{describeActivity(row)}</div>
                        {row.entity_label ? (
                          <div className="text-muted-foreground text-xs">
                            {ENTITY_NOUN[row.entity_type] ?? 'Item'}: {row.entity_label}
                          </div>
                        ) : null}
                      </TableCell>
                      <TableCell>
                        {hasChanges ? (
                          <ChevronDown className={cn('size-4 transition-transform', isOpen && 'rotate-180')} />
                        ) : null}
                      </TableCell>
                    </TableRow>
                    {isOpen && hasChanges ? (
                      <TableRow>
                        <TableCell colSpan={5} className="bg-muted/30">
                          <ChangesTable changes={row.changes} />
                        </TableCell>
                      </TableRow>
                    ) : null}
                  </Fragment>
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

function FilterSelect({ placeholder, value, onChange, options }) {
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger size="sm" className="min-w-0 flex-1 basis-36 sm:w-[160px] sm:flex-none sm:basis-auto">
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
