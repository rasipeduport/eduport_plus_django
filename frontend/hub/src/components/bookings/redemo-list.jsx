import { RotateCcw, SearchXIcon, XIcon } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { EmptyState } from '@/components/page/page';
import { DateRangeFilter } from '@/components/page/date-range-filter';
import { FilterSelect, SearchField } from '@/components/page/list-toolbar';
import { Pagination } from '@/components/page/pagination';
import { ResponsiveList } from '@/components/page/responsive-list';
import { ParentConfirmationBadge } from '@/components/communications/communication-badges';
import { REDEMO_STATUS_FILTERS } from '@/lib/bookings';
import { formatDay, slotLabel, slotParts } from '@/lib/enquiries';
import { cn } from '@/lib/utils';
import { RedemoStatusBadge } from './booking-badges';
import { StudentTimeLine } from './student-time';

// "No BDE": the requests of leads nobody owns (the API's owner=none).
const NO_OWNER = 'none';

/** Whether a Re-Demo is booked or taught for the request: a waiting or closed one's last booking was cancelled. */
const booked = (redemo) => redemo.status === 'SCHEDULED' || redemo.status === 'COMPLETED';

function When({ slot, timezone }) {
  if (!slot) return <span className="text-muted-foreground">—</span>;
  const when = slotParts(slot.date, slot.time);
  return (
    <>
      <p className="font-medium">{when.day}</p>
      <p className="text-muted-foreground text-xs">{when.time} IST</p>
      <StudentTimeLine startsAt={slot.starts_at} timezone={timezone} className="text-xs" />
    </>
  );
}

/** The one thing to do with a request from the list, by where it stands: schedule it, or open it. */
function RowAction({ redemo, canSchedule, onOpen, onSchedule, className }) {
  if (canSchedule && redemo.status === 'AWAITING_SCHEDULING') {
    return (
      <Button size="sm" className={className} onClick={() => onSchedule(redemo)} aria-label={`Schedule ${redemo.student_name}'s Re-Demo`}>
        Schedule
      </Button>
    );
  }
  return (
    <Button
      variant={redemo.needs_action ? 'default' : 'outline'}
      size="sm"
      className={className}
      onClick={() => onOpen(redemo.id)}
      aria-label={`Open the Re-Demo request for ${redemo.student_name}`}
    >
      Open
    </Button>
  );
}

function Status({ redemo }) {
  return (
    <span className="flex flex-col items-start gap-1">
      <RedemoStatusBadge status={redemo.status} />
      {(redemo.attention ?? []).map((flag) => (
        <Badge key={flag.code} variant="warning" className="text-[11px]">
          {flag.label}
        </Badge>
      ))}
      {redemo.closed?.reason ? <span className="text-muted-foreground text-xs">{redemo.closed.reason.label}</span> : null}
    </span>
  );
}

const ownerLine = (redemo) =>
  [redemo.grade, redemo.syllabus, redemo.owner_bde ? `BDE: ${redemo.owner_bde.full_name}` : 'No BDE']
    .filter(Boolean)
    .join(' · ');

const requester = (redemo) =>
  redemo.requested_by
    ? `by ${redemo.requested_by.full_name}${redemo.requested_by.role_label ? ` (${redemo.requested_by.role_label})` : ''}`
    : '';

/**
 * The Re-Demo requests, as administrators work through them (Demo Bookings'
 * Re-Demo tab): status chips with how many stand at each (`counts`), then
 * search, the lead's BDE and the dates requested -- every filter in the URL
 * (`onChange` receives what changed) -- and the rows in the API's order, an
 * administrator's steps first. Each row: the student, who asked and when,
 * the original Demo and the Re-Demo booked for it (Indian time with the
 * student's beside it, the tutor and the parent's answer), where it stands
 * with anything to look at, and its one action -- Schedule while it waits
 * (`onSchedule`, with accounts.assign_booking_tutor), else Open (`onOpen`,
 * the side sheet). `highlightedId` marks the request a link opened. A table
 * where it fits, a card per request on a phone or a narrow screen.
 */
export function RedemoList({
  rows,
  total,
  page,
  pageSize,
  filters,
  counts,
  owners,
  pending,
  canSchedule,
  highlightedId,
  onChange,
  onOpen,
  onSchedule,
}) {
  const filtered = Boolean(filters.q || filters.status || filters.owner || filters.from || filters.to || filters.lead);
  const clear = () => onChange({ q: null, status: null, owner: null, from: null, to: null, lead: null });

  const columns = [
    {
      key: 'student',
      header: 'Student',
      className: 'min-w-36 whitespace-normal',
      cell: (redemo) => (
        <>
          <p className="font-medium break-words">{redemo.student_name}</p>
          <p className="text-muted-foreground text-xs">{ownerLine(redemo)}</p>
        </>
      ),
    },
    {
      key: 'requested',
      header: 'Requested',
      className: 'whitespace-nowrap',
      cell: (redemo) => (
        <>
          <p className="font-medium">{formatDay(redemo.requested_at)}</p>
          <p className="text-muted-foreground max-w-44 truncate text-xs">{requester(redemo)}</p>
        </>
      ),
    },
    {
      key: 'original',
      header: 'Original Demo',
      className: 'whitespace-nowrap',
      cell: (redemo) => (
        <>
          <When slot={redemo.original?.slot} />
          <p className="text-muted-foreground text-xs">{redemo.original?.tutor?.full_name ?? 'No tutor'}</p>
        </>
      ),
    },
    {
      key: 'redemo',
      header: 'Re-Demo',
      className: 'whitespace-nowrap',
      cell: (redemo) =>
        booked(redemo) && redemo.booking ? (
          <>
            <When slot={redemo.booking.slot} timezone={redemo.student_timezone} />
            <p className="text-muted-foreground text-xs">{redemo.tutor?.full_name ?? 'No tutor'}</p>
            {redemo.booking.status === 'BOOKED' ? (
              <span className="mt-1 inline-block">
                <ParentConfirmationBadge status={redemo.booking.parent_confirmation} booked />
              </span>
            ) : null}
          </>
        ) : (
          <span className="text-muted-foreground">—</span>
        ),
    },
    { key: 'status', header: 'Status', cell: (redemo) => <Status redemo={redemo} /> },
    {
      key: 'actions',
      header: { srOnly: 'Actions' },
      headerClassName: 'w-px',
      cell: (redemo) => (
        <div className="flex justify-end">
          <RowAction redemo={redemo} canSchedule={canSchedule} onOpen={onOpen} onSchedule={onSchedule} />
        </div>
      ),
    },
  ];

  const renderCard = (redemo) => (
    <article className="bg-card flex h-full flex-col gap-3 rounded-xl border p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="truncate font-medium">{redemo.student_name}</h2>
          <p className="text-muted-foreground truncate text-sm">{ownerLine(redemo)}</p>
        </div>
        <Status redemo={redemo} />
      </div>
      <div className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
        <div className="min-w-0">
          <p className="text-muted-foreground text-xs">Requested</p>
          <p className="truncate">{formatDay(redemo.requested_at)}</p>
        </div>
        <div className="min-w-0">
          <p className="text-muted-foreground text-xs">Re-Demo tutor</p>
          <p className="truncate">{(booked(redemo) && redemo.tutor?.full_name) || '—'}</p>
        </div>
        <div className="col-span-2 min-w-0">
          <p className="text-muted-foreground text-xs">Original Demo</p>
          <p className="truncate">{redemo.original?.slot ? slotLabel(redemo.original.slot) : '—'}</p>
        </div>
        {booked(redemo) && redemo.booking?.slot ? (
          <div className="col-span-2 min-w-0">
            <p className="text-muted-foreground text-xs">Re-Demo</p>
            <p className="truncate">{slotLabel(redemo.booking.slot)}</p>
            <StudentTimeLine startsAt={redemo.booking.slot.starts_at} timezone={redemo.student_timezone} className="text-xs" />
          </div>
        ) : null}
      </div>
      <div className="mt-auto border-t pt-3">
        <RowAction redemo={redemo} canSchedule={canSchedule} onOpen={onOpen} onSchedule={onSchedule} />
      </div>
    </article>
  );

  let body;
  if (rows.length) {
    body = (
      <ResponsiveList
        label="Re-Demo requests"
        columns={columns}
        rows={rows}
        pending={pending}
        minTableWidth={980}
        renderCard={renderCard}
        highlightedKey={highlightedId || null}
      />
    );
  } else if (total > 0) {
    body = (
      <EmptyState
        icon={SearchXIcon}
        title="Nothing on this page"
        description="This page is past the last one."
        action={
          <Button variant="outline" onClick={() => onChange({ page: null })}>
            Go to the first page
          </Button>
        }
      />
    );
  } else if (filtered) {
    body = (
      <EmptyState
        icon={SearchXIcon}
        title="No Re-Demo requests match these filters"
        description="Try another search, status, BDE or date, or clear the filters."
        action={
          <Button variant="outline" onClick={clear}>
            Clear all filters
          </Button>
        }
      />
    );
  } else {
    body = (
      <EmptyState
        icon={RotateCcw}
        title="No Re-Demo requests yet"
        description="A completed demo sent for a Re-Demo, from its booking, appears here to be scheduled."
      />
    );
  }

  const ownerOptions = [
    ...(owners ?? []).map((owner) => ({ value: owner.id, label: owner.full_name })),
    { value: NO_OWNER, label: 'No BDE' },
  ];

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap gap-2" role="group" aria-label="Filter by Re-Demo status">
        {REDEMO_STATUS_FILTERS.map((option) => {
          const active = (filters.status || '') === option.value;
          const count = counts ? counts[option.value || 'ALL'] : null;
          return (
            <Button
              key={option.value || 'all'}
              size="sm"
              variant={active ? 'default' : 'outline'}
              aria-pressed={active}
              onClick={() => onChange({ status: option.value || null })}
            >
              {option.label}
              {count != null ? (
                <span className={cn('rounded-full px-1.5 text-xs tabular-nums', active ? 'bg-primary-foreground/20' : 'bg-muted')}>
                  {count}
                </span>
              ) : null}
            </Button>
          );
        })}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <SearchField
          value={filters.q}
          onSearch={(text) => onChange({ q: text || null })}
          label="Search Re-Demo requests"
          placeholder="Search student, parent or phone…"
        />
        <FilterSelect
          label="Filter by the lead's BDE"
          placeholder="All BDEs"
          value={filters.owner}
          onChange={(value) => onChange({ owner: value || null })}
          options={ownerOptions}
          className="sm:w-48"
        />
        <DateRangeFilter
          from={filters.from}
          to={filters.to}
          onChange={({ from, to }) => onChange({ from: from || null, to: to || null })}
          label="Filter by the date requested"
          anyLabel="Any request date"
        />
        {filtered ? (
          <Button variant="ghost" className="text-muted-foreground" onClick={clear}>
            <XIcon className="size-4" />
            Clear all filters
          </Button>
        ) : null}
      </div>
      {filters.lead ? (
        <p className="text-muted-foreground flex flex-wrap items-center gap-2 text-sm">
          {filters.leadLabel ? `Showing ${filters.leadLabel}'s requests only.` : "Showing one student's requests only."}
          <Button variant="link" size="sm" className="h-auto p-0" onClick={() => onChange({ lead: null })}>
            Show every request
          </Button>
        </p>
      ) : null}
      {body}
      {total > 0 ? (
        <Pagination
          page={page}
          pageSize={pageSize}
          total={total}
          pending={pending}
          onPageChange={(next) => onChange({ page: String(next) })}
        />
      ) : null}
    </div>
  );
}
