import { Link } from 'react-router-dom';
import { BookMarkedIcon, MoreHorizontalIcon, SearchXIcon, XIcon } from 'lucide-react';

import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { EmptyState } from '@/components/page/page';
import { FilterSelect, SearchField } from '@/components/page/list-toolbar';
import { Pagination } from '@/components/page/pagination';
import { ResponsiveList } from '@/components/page/responsive-list';
import { PlanTypeBadges, SyllabusStatusBadge } from '@/components/sales/syllabus-badges';
import { formatDay } from '@/lib/enquiries';
import { BOARDS, GRADES, STRUCTURES, SYLLABUS_STATUSES, structureLabel } from '@/lib/sales';

/**
 * The syllabus list's filters: search by title, status, structure, board and
 * grade, and Clear all filters while any is set. `filters` are the page's URL
 * values ('' for none); `onChange(updates)` takes URL values (null drops one).
 */
export function SyllabusFilters({ filters, onChange, onClear }) {
  const filtered = Object.values(filters).some(Boolean);
  return (
    <div className="flex flex-wrap items-center gap-2">
      <SearchField
        value={filters.q}
        onSearch={(text) => onChange({ q: text || null })}
        label="Search syllabuses"
        placeholder="Search titles…"
      />
      <FilterSelect
        label="Filter by status"
        placeholder="All statuses"
        value={filters.status}
        onChange={(value) => onChange({ status: value || null })}
        options={SYLLABUS_STATUSES}
      />
      <FilterSelect
        label="Filter by structure"
        placeholder="All structures"
        value={filters.structure}
        onChange={(value) => onChange({ structure: value || null })}
        options={STRUCTURES}
      />
      <FilterSelect
        label="Filter by board"
        placeholder="All boards"
        value={filters.board}
        onChange={(value) => onChange({ board: value || null })}
        options={BOARDS}
      />
      <FilterSelect
        label="Filter by grade"
        placeholder="All grades"
        value={filters.grade}
        onChange={(value) => onChange({ grade: value || null })}
        options={GRADES}
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

/** A syllabus's class totals as one line: "38 Regular · 19 Revision", or a Bridge Course's "30 classes". */
function classSummary(row) {
  if (row.structure === 'BRIDGE_COURSE') return `${row.totals.bridge ?? 0} classes`;
  return `${row.totals.regular ?? 0} Regular · ${row.totals.revision ?? 0} Revision`;
}

/**
 * What can be done to a listed syllabus, as `actions` offers: open it, edit
 * its draft (or start one), its PDF, publish its draft, deactivate or
 * reactivate it, duplicate it.
 */
function RowActions({ row, actions, pdfPending, duplicating }) {
  const inactive = row.status === 'INACTIVE';
  const hasDraft = Boolean(row.draft_revision);
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" className="size-8" aria-label={`Actions for ${row.title}`}>
          <MoreHorizontalIcon className="size-4" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuLabel>Actions</DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem asChild>
          <Link to={`/sales-syllabus/${row.id}`}>View</Link>
        </DropdownMenuItem>
        {!inactive ? (
          hasDraft ? (
            <DropdownMenuItem asChild>
              <Link to={`/sales-syllabus/${row.id}/edit`}>Edit draft</Link>
            </DropdownMenuItem>
          ) : (
            <DropdownMenuItem onSelect={() => actions.startDraft(row)}>Edit</DropdownMenuItem>
          )
        ) : null}
        {/* One PDF at a time: the page says while one is being drawn. */}
        <DropdownMenuItem disabled={Boolean(pdfPending)} onSelect={() => actions.previewPdf(row)}>
          Preview PDF
        </DropdownMenuItem>
        <DropdownMenuItem disabled={Boolean(pdfPending)} onSelect={() => actions.downloadPdf(row)}>
          Download PDF
        </DropdownMenuItem>
        {!inactive && hasDraft ? (
          <DropdownMenuItem onSelect={() => actions.publish(row)}>Publish…</DropdownMenuItem>
        ) : null}
        <DropdownMenuItem disabled={Boolean(duplicating)} onSelect={() => actions.duplicate(row)}>
          Duplicate
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        {inactive ? (
          <DropdownMenuItem onSelect={() => actions.reactivate(row)}>Reactivate</DropdownMenuItem>
        ) : (
          <DropdownMenuItem variant="destructive" onSelect={() => actions.deactivate(row)}>
            Deactivate
          </DropdownMenuItem>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

/**
 * Every syllabus, as administrators manage them: its title and version, grade
 * and board, structure, plan types, class totals, status (with a waiting
 * draft) and when it last changed -- the revision it offers, or its draft
 * before the first publication. A table where it fits, a card per syllabus on
 * a narrow screen; empty, it says why and offers the way on.
 */
export function SyllabusList({
  rows,
  total,
  page,
  pageSize,
  filtered,
  pending,
  actions,
  pdfPending,
  duplicating,
  onChange,
  onClear,
  onCreate,
}) {
  const columns = [
    {
      key: 'title',
      header: 'Syllabus',
      className: 'min-w-44 whitespace-normal',
      cell: (row) => (
        <>
          <Link to={`/sales-syllabus/${row.id}`} className="font-medium hover:underline">
            {row.title}
          </Link>
          <p className="text-muted-foreground text-xs">
            {row.chapter_count} {row.structure === 'BRIDGE_COURSE' ? 'days' : 'chapters'}
          </p>
        </>
      ),
    },
    { key: 'grade', header: 'Grade', className: 'whitespace-nowrap', cell: (row) => `Grade ${row.grade}` },
    { key: 'board', header: 'Board', cell: (row) => row.board },
    {
      key: 'version',
      header: 'Version',
      className: 'text-muted-foreground whitespace-nowrap',
      cell: (row) => row.syllabus_version || '—',
    },
    { key: 'structure', header: 'Structure', className: 'whitespace-nowrap', cell: (row) => structureLabel(row.structure) },
    { key: 'plans', header: 'Plan types', className: 'min-w-40 whitespace-normal', cell: (row) => <PlanTypeBadges planTypes={row.plan_types} /> },
    { key: 'classes', header: 'Classes', className: 'whitespace-nowrap tabular-nums', cell: classSummary },
    {
      key: 'status',
      header: 'Status',
      cell: (row) => <SyllabusStatusBadge status={row.status} draftRevision={row.draft_revision} />,
    },
    {
      key: 'updated',
      header: 'Last updated',
      className: 'text-muted-foreground whitespace-nowrap',
      cell: (row) => (
        <>
          {formatDay(row.updated_at)}
          {row.updated_by ? <p className="text-xs">{row.updated_by.name}</p> : null}
        </>
      ),
    },
    {
      key: 'actions',
      header: { srOnly: 'Actions' },
      headerClassName: 'w-10',
      cell: (row) => <RowActions row={row} actions={actions} pdfPending={pdfPending} duplicating={duplicating} />,
    },
  ];

  const renderCard = (row) => (
    <article className="bg-card flex h-full flex-col gap-3 rounded-xl border p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="font-medium">
            <Link to={`/sales-syllabus/${row.id}`} className="hover:underline">
              {row.title}
            </Link>
          </h2>
          <p className="text-muted-foreground text-sm">
            {[`Grade ${row.grade}`, row.board, row.syllabus_version, structureLabel(row.structure)].filter(Boolean).join(' · ')}
          </p>
        </div>
        <RowActions row={row} actions={actions} pdfPending={pdfPending} duplicating={duplicating} />
      </div>
      <PlanTypeBadges planTypes={row.plan_types} />
      <p className="text-muted-foreground text-sm tabular-nums">{classSummary(row)}</p>
      <div className="mt-auto flex flex-wrap items-center justify-between gap-2 border-t pt-3 text-sm">
        <SyllabusStatusBadge status={row.status} draftRevision={row.draft_revision} />
        <span className="text-muted-foreground text-xs">
          Updated {formatDay(row.updated_at)}
          {row.updated_by ? ` · ${row.updated_by.name}` : ''}
        </span>
      </div>
    </article>
  );

  let body;
  if (rows.length) {
    body = <ResponsiveList label="Syllabuses" columns={columns} rows={rows} pending={pending} minTableWidth={1100} renderCard={renderCard} />;
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
        title="No syllabuses match these filters"
        description="Try another search, status, structure, board or grade, or clear the filters."
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
        icon={BookMarkedIcon}
        title="No syllabuses yet"
        description="Create the first syllabus: its chapters, the plans it is sold as and the PDF parents receive."
        action={onCreate ? <Button onClick={onCreate}>New syllabus</Button> : null}
      />
    );
  }

  return (
    <>
      {body}
      {total > 0 ? (
        <Pagination page={page} pageSize={pageSize} total={total} pending={pending} onPageChange={(next) => onChange({ page: String(next) })} />
      ) : null}
    </>
  );
}
