import { RotateCcw, SearchXIcon, XIcon } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { EmptyState } from '@/components/page/page';
import { FilterSelect, SearchField } from '@/components/page/list-toolbar';
import { Pagination } from '@/components/page/pagination';
import { ResponsiveList } from '@/components/page/responsive-list';
import { REDEMO_STATUSES } from '@/lib/bookings';
import { formatDay, slotLabel, slotParts } from '@/lib/enquiries';
import { RedemoStatusBadge } from './booking-badges';

function When({ slot }) {
  if (!slot) return <span className="text-muted-foreground">—</span>;
  const when = slotParts(slot.date, slot.time);
  return (
    <>
      <p className="font-medium">{when.day}</p>
      <p className="text-muted-foreground text-xs">{when.time} IST</p>
    </>
  );
}

function ViewButton({ redemo, onOpen, className }) {
  return (
    <Button
      variant={redemo.status === 'AWAITING_SCHEDULING' ? 'default' : 'outline'}
      size="sm"
      className={className}
      onClick={() => onOpen(redemo.id)}
      aria-label={`View the Re-Demo request for ${redemo.student_name}`}
    >
      View
    </Button>
  );
}

const ownerLine = (redemo) =>
  [redemo.grade, redemo.owner_bde ? `BDE: ${redemo.owner_bde.full_name}` : 'No BDE'].filter(Boolean).join(' · ');

/**
 * The Re-Demo requests, as administrators manage them (Demo Bookings' Re-Demo
 * tab): newest first, each with the child, the original Demo and its tutor,
 * who asked, where it stands, and the Re-Demo's tutor and slot once an
 * administrator has scheduled it -- searched, filtered by status and paged by
 * the API; a table where it fits, a card per request on a phone or a narrow
 * screen. A request opens in a side sheet (`onOpen`); `onChange` receives what
 * changed in the URL.
 */
export function RedemoList({ rows, total, page, pageSize, filters, pending, onChange, onOpen }) {
  const filtered = Boolean(filters.q || filters.status);
  const clear = () => onChange({ q: null, status: null });

  const columns = [
    {
      key: 'requested',
      header: 'Requested',
      className: 'whitespace-nowrap',
      cell: (redemo) => (
        <>
          <p className="font-medium">{formatDay(redemo.requested_at)}</p>
          <p className="text-muted-foreground max-w-40 truncate text-xs">by {redemo.requested_by?.full_name}</p>
        </>
      ),
    },
    {
      key: 'student',
      header: 'Student',
      className: 'min-w-28 whitespace-normal',
      cell: (redemo) => (
        <>
          <p className="font-medium break-words">{redemo.student_name}</p>
          <p className="text-muted-foreground text-xs">{ownerLine(redemo)}</p>
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
    { key: 'status', header: 'Status', cell: (redemo) => <RedemoStatusBadge status={redemo.status} /> },
    {
      key: 'tutor',
      header: 'Re-Demo tutor',
      className: 'whitespace-normal',
      cell: (redemo) =>
        redemo.tutor ? <span className="font-medium">{redemo.tutor.full_name}</span> : <span className="text-muted-foreground">—</span>,
    },
    { key: 'redemo', header: 'Re-Demo', className: 'whitespace-nowrap', cell: (redemo) => <When slot={redemo.booking?.slot} /> },
    {
      key: 'actions',
      header: { srOnly: 'Actions' },
      headerClassName: 'w-px',
      cell: (redemo) => (
        <div className="flex justify-end">
          <ViewButton redemo={redemo} onOpen={onOpen} />
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
        <RedemoStatusBadge status={redemo.status} />
      </div>
      <div className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
        <div className="min-w-0">
          <p className="text-muted-foreground text-xs">Requested</p>
          <p className="truncate">{formatDay(redemo.requested_at)}</p>
        </div>
        <div className="min-w-0">
          <p className="text-muted-foreground text-xs">Re-Demo tutor</p>
          <p className="truncate">{redemo.tutor?.full_name ?? '—'}</p>
        </div>
        <div className="col-span-2 min-w-0">
          <p className="text-muted-foreground text-xs">Original Demo</p>
          <p className="truncate">{redemo.original?.slot ? slotLabel(redemo.original.slot) : '—'}</p>
        </div>
        {redemo.booking?.slot ? (
          <div className="col-span-2 min-w-0">
            <p className="text-muted-foreground text-xs">Re-Demo</p>
            <p className="truncate">{slotLabel(redemo.booking.slot)}</p>
          </div>
        ) : null}
      </div>
      <div className="mt-auto border-t pt-3">
        <ViewButton redemo={redemo} onOpen={onOpen} />
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
        minTableWidth={900}
        renderCard={renderCard}
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
        description="Try another search or status, or clear the filters."
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

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <SearchField
          value={filters.q}
          onSearch={(text) => onChange({ q: text || null })}
          label="Search Re-Demo requests"
          placeholder="Search student, parent or phone…"
        />
        <FilterSelect
          label="Filter by Re-Demo status"
          placeholder="All statuses"
          value={filters.status}
          onChange={(value) => onChange({ status: value || null })}
          options={REDEMO_STATUSES}
          className="sm:w-52"
        />
        {filtered ? (
          <Button variant="ghost" className="text-muted-foreground" onClick={clear}>
            <XIcon className="size-4" />
            Clear all filters
          </Button>
        ) : null}
      </div>
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
