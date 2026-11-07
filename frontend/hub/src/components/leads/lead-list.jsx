import { Link } from 'react-router-dom';
import { ChevronRightIcon, InboxIcon, SearchXIcon, XIcon } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { EmptyState } from '@/components/page/page';
import { DateRangeFilter } from '@/components/page/date-range-filter';
import { FilterSelect, SearchField } from '@/components/page/list-toolbar';
import { Pagination } from '@/components/page/pagination';
import { ResponsiveList } from '@/components/page/responsive-list';
import { EnquiryStatusBadge } from '@/components/enquiries/enquiry-badges';
import { LEAD_STATUSES, SOURCE_FILTERS, formatDay, slotLabel } from '@/lib/enquiries';

/**
 * The Leads page's filters: search, status, source, owner (`owners`, its
 * options) and the dates a lead came in on, and Clear all filters while any
 * is set. `filters` are the page's URL values ('' for none); `onChange(updates)`
 * takes URL values (null to drop one) and `onClear()` drops them all.
 */
export function LeadFilters({ filters, owners, onChange, onClear }) {
  const filtered = Boolean(filters.q || filters.status || filters.source || filters.owner || filters.from || filters.to);
  return (
    <div className="flex flex-wrap items-center gap-2">
      <SearchField
        value={filters.q}
        onSearch={(text) => onChange({ q: text || null })}
        label="Search leads"
        placeholder="Search parent, student or phone…"
      />
      <FilterSelect
        label="Filter by status"
        placeholder="All statuses"
        value={filters.status}
        onChange={(value) => onChange({ status: value || null })}
        options={LEAD_STATUSES}
      />
      <FilterSelect
        label="Filter by source"
        placeholder="All sources"
        value={filters.source}
        onChange={(value) => onChange({ source: value || null })}
        options={SOURCE_FILTERS}
      />
      <FilterSelect
        label="Filter by owner"
        placeholder="All owners"
        value={filters.owner}
        onChange={(value) => onChange({ owner: value || null })}
        options={owners}
      />
      <DateRangeFilter
        from={filters.from}
        to={filters.to}
        label="Filter by received date"
        anyLabel="Received any day"
        onChange={(range) => onChange(range)}
      />
      {filtered ? (
        <Button variant="ghost" className="text-muted-foreground" onClick={onClear}>
          <XIcon className="size-4" />
          Clear all filters
        </Button>
      ) : null}
    </div>
  );
}

function Owner({ lead, onAssign }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      {lead.owner ? (
        <span className="font-medium">{lead.owner.full_name}</span>
      ) : (
        <span className="text-muted-foreground">Unassigned</span>
      )}
      {onAssign ? (
        <Button
          variant={lead.owner ? 'ghost' : 'outline'}
          size="sm"
          onClick={() => onAssign(lead)}
          aria-label={`${lead.owner ? 'Reassign' : 'Assign'} the lead for ${lead.student_name}`}
        >
          {lead.owner ? 'Reassign' : 'Assign'}
        </Button>
      ) : null}
    </div>
  );
}

/**
 * Every lead, as administrators work through them: when it came in, the
 * child and parent, where it came from, where it stands, its next booking and
 * the BDE who owns it -- with, given `onAssign`, giving it to a BDE -- each
 * opening the lead's page. A table where it fits, a card per lead on a phone
 * or a narrow screen; empty, it says why and offers the way on. The API pages
 * it; `onChange` receives what changed in the URL.
 */
export function LeadList({ rows, total, page, pageSize, filtered, pending, onAssign, onChange, onClear }) {
  const columns = [
    {
      key: 'received',
      header: 'Received',
      className: 'text-muted-foreground whitespace-nowrap',
      cell: (lead) => formatDay(lead.created_at),
    },
    {
      key: 'student',
      header: 'Student',
      className: 'min-w-28 whitespace-normal',
      cell: (lead) => (
        <>
          <Link to={`/leads/${lead.id}`} className="font-medium hover:underline">
            {lead.student_name}
          </Link>
          {lead.grade ? <p className="text-muted-foreground text-xs">{lead.grade}</p> : null}
        </>
      ),
    },
    {
      key: 'parent',
      header: 'Parent',
      className: 'min-w-32 whitespace-normal',
      cell: (lead) => (
        <>
          <p className="break-words">{lead.parent_name}</p>
          <p className="text-muted-foreground text-xs whitespace-nowrap tabular-nums">{lead.phone}</p>
        </>
      ),
    },
    { key: 'source', header: 'Source', cell: (lead) => lead.source_label },
    { key: 'status', header: 'Status', cell: (lead) => <EnquiryStatusBadge enquiry={lead} /> },
    {
      key: 'next',
      header: 'Next booking',
      className: 'text-muted-foreground whitespace-nowrap',
      cell: (lead) => (lead.next_booking ? slotLabel(lead.next_booking) : '—'),
    },
    { key: 'owner', header: 'Owner', className: 'whitespace-normal', cell: (lead) => <Owner lead={lead} onAssign={onAssign} /> },
    {
      key: 'open',
      header: { srOnly: 'Open' },
      headerClassName: 'w-10',
      cell: (lead) => (
        <Button variant="ghost" size="icon" className="size-8" asChild>
          <Link to={`/leads/${lead.id}`} aria-label={`Open the lead for ${lead.student_name}`}>
            <ChevronRightIcon className="size-4" />
          </Link>
        </Button>
      ),
    },
  ];

  const renderCard = (lead) => (
    <article className="bg-card flex h-full flex-col gap-3 rounded-xl border p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="truncate font-medium">
            <Link to={`/leads/${lead.id}`} className="hover:underline">
              {lead.student_name}
            </Link>
          </h2>
          <p className="text-muted-foreground truncate text-sm">{[lead.grade, lead.parent_name].filter(Boolean).join(' · ')}</p>
        </div>
        <EnquiryStatusBadge enquiry={lead} />
      </div>
      <div className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
        <div className="min-w-0">
          <p className="text-muted-foreground text-xs">Phone</p>
          <p className="truncate tabular-nums">{lead.phone}</p>
        </div>
        <div className="min-w-0">
          <p className="text-muted-foreground text-xs">Source</p>
          <p className="truncate">{lead.source_label}</p>
        </div>
        <div className="min-w-0">
          <p className="text-muted-foreground text-xs">Received</p>
          <p className="truncate">{formatDay(lead.created_at)}</p>
        </div>
        <div className="min-w-0">
          <p className="text-muted-foreground text-xs">Next booking</p>
          <p className="truncate">{lead.next_booking ? slotLabel(lead.next_booking) : '—'}</p>
        </div>
      </div>
      <div className="mt-auto flex items-center justify-between gap-2 border-t pt-3 text-sm">
        <Owner lead={lead} onAssign={onAssign} />
        <Button variant="outline" size="sm" asChild>
          <Link to={`/leads/${lead.id}`} aria-label={`Open the lead for ${lead.student_name}`}>
            Open
            <ChevronRightIcon />
          </Link>
        </Button>
      </div>
    </article>
  );

  let body;
  if (rows.length) {
    body = (
      <ResponsiveList label="Leads" columns={columns} rows={rows} pending={pending} minTableWidth={1080} renderCard={renderCard} />
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
        title="No leads match these filters"
        description="Try another search, status, source, owner or dates, or clear the filters."
        action={
          <Button variant="outline" onClick={onClear}>
            Clear all filters
          </Button>
        }
      />
    );
  } else {
    body = (
      <EmptyState
        icon={InboxIcon}
        title="No leads yet"
        description="Leads from the booking pages, the website, the landing page and manual entry appear here."
      />
    );
  }

  return (
    <>
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
    </>
  );
}
