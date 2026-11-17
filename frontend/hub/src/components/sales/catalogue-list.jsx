import { Link } from 'react-router-dom';
import { BadgePercentIcon, SearchXIcon, XIcon } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { EmptyState } from '@/components/page/page';
import { FilterSelect, SearchField } from '@/components/page/list-toolbar';
import { Pagination } from '@/components/page/pagination';
import { ResponsiveList } from '@/components/page/responsive-list';
import { PlanTypeBadges } from '@/components/sales/syllabus-badges';
import { SyllabusActions } from '@/components/sales/syllabus-actions';
import { CatalogueSyllabusCard } from '@/components/sales/catalogue-syllabus-card';
import { BOARDS, GRADES, STRUCTURES, SUBTITLES, structureLabel } from '@/lib/sales';

/**
 * The catalogue's filters: search by title, structure, board and grade, and
 * Clear all filters while any is set. `filters` are the page's URL values
 * ('' for none); `onChange(updates)` takes URL values (null drops one).
 */
export function CatalogueFilters({ filters, onChange, onClear, selecting = false }) {
  const filtered = Object.values(filters).some(Boolean);
  return (
    <div className={selecting ? 'flex flex-wrap items-center gap-3' : 'flex flex-wrap items-center gap-2'}>
      <SearchField
        value={filters.q}
        onSearch={(text) => onChange({ q: text || null })}
        label="Search plans"
        placeholder={selecting ? 'Search syllabuses…' : 'Search titles…'}
        className={selecting ? 'sm:max-w-md sm:flex-1 sm:basis-72' : undefined}
      />
      <FilterSelect
        label="Filter by structure"
        placeholder="All structures"
        value={filters.structure}
        onChange={(value) => onChange({ structure: value || null })}
        options={STRUCTURES}
        className={selecting ? 'sm:w-36' : undefined}
      />
      <FilterSelect
        label="Filter by board"
        placeholder="All boards"
        value={filters.board}
        onChange={(value) => onChange({ board: value || null })}
        options={BOARDS}
        className={selecting ? 'sm:w-36' : undefined}
      />
      <FilterSelect
        label="Filter by grade"
        placeholder="All grades"
        value={filters.grade}
        onChange={(value) => onChange({ grade: value || null })}
        options={GRADES}
        className={selecting ? 'sm:w-36' : undefined}
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

/** A plan's classes as one line: "38 Regular · 19 Revision", or a Bridge Course's "30 classes over 30 days". */
function classSummary(row) {
  if (row.structure === 'BRIDGE_COURSE') return `${row.totals.bridge ?? 0} classes over ${row.chapter_count} days`;
  return `${row.totals.regular ?? 0} Regular · ${row.totals.revision ?? 0} Revision`;
}

/**
 * The plans on sale, as a BDE quotes them (the catalogue): each syllabus's
 * title and version, grade and board, structure, plan types and classes --
 * the revision it sells. A table where it fits, a card per plan on a narrow
 * screen; empty, it says why.
 */
export function CatalogueList({ rows, total, page, pageSize, filtered, pending, onChange, onClear, onSelect, enquiry }) {
  const open = (row) => `/plans/${row.id}`;
  const columns = [
    {
      key: 'title',
      header: 'Plan',
      className: 'min-w-44 whitespace-normal',
      cell: (row) => (
        <>
          <Link to={open(row)} className="font-medium hover:underline">
            {row.title}
          </Link>
          <p className="text-muted-foreground mt-1 text-xs">{row.subtitle ?? SUBTITLES[row.structure]}</p>
        </>
      ),
    },
    { key: 'grade', header: 'Grade', className: 'whitespace-nowrap', cell: (row) => `Grade ${row.grade}` },
    { key: 'board', header: 'Board', cell: (row) => row.board },
    { key: 'version', header: 'Version', className: 'text-muted-foreground whitespace-nowrap', cell: (row) => row.syllabus_version || '—' },
    { key: 'structure', header: 'Structure', className: 'whitespace-nowrap', cell: (row) => structureLabel(row.structure) },
    { key: 'plans', header: 'Sold as', className: 'min-w-40 whitespace-normal', cell: (row) => <PlanTypeBadges planTypes={row.plan_types} /> },
    { key: 'classes', header: 'Classes', className: 'whitespace-nowrap tabular-nums', cell: classSummary },
    {
      key: 'pdf',
      header: 'Syllabus PDF',
      className: 'min-w-64 whitespace-normal',
      cell: (row) => <SyllabusActions syllabus={row} enquiry={enquiry} />,
    },
    {
      key: 'open',
      header: { srOnly: 'Open' },
      headerClassName: 'w-24',
      cell: (row) =>
        onSelect ? (
          <Button size="sm" onClick={() => onSelect(row)} disabled={pending} aria-label={`Select ${row.title}`}>
            Select syllabus
          </Button>
        ) : (
          <Button variant="outline" size="sm" asChild>
            <Link to={open(row)} aria-label={`Open ${row.title}`}>
              Open
            </Link>
          </Button>
        ),
    },
  ];

  const renderCard = (row) => (
    <article className="bg-card flex h-full flex-col gap-3 rounded-xl border p-4">
      <div className="min-w-0">
        <h2 className="font-medium">
          <Link to={open(row)} className="hover:underline">
            {row.title}
          </Link>
        </h2>
        <p className="text-muted-foreground mt-1 text-sm">{row.subtitle ?? SUBTITLES[row.structure]}</p>
        <p className="text-muted-foreground text-sm">
          {[`Grade ${row.grade}`, row.board, row.syllabus_version, structureLabel(row.structure)].filter(Boolean).join(' · ')}
        </p>
      </div>
      <PlanTypeBadges planTypes={row.plan_types} />
      <SyllabusActions syllabus={row} enquiry={enquiry} />
      <div className="mt-auto flex flex-wrap items-center justify-between gap-2 border-t pt-3 text-sm">
        <span className="text-muted-foreground tabular-nums">{classSummary(row)}</span>
        {onSelect ? (
          <Button size="sm" onClick={() => onSelect(row)} disabled={pending} aria-label={`Select ${row.title}`}>
            Select syllabus
          </Button>
        ) : (
          <Button variant="outline" size="sm" asChild>
            <Link to={open(row)} aria-label={`Open ${row.title}`}>
              Open
            </Link>
          </Button>
        )}
      </div>
    </article>
  );

  let body;
  if (rows.length) {
    body = onSelect ? (
      <ul aria-label="Plans on sale" aria-busy={pending || undefined} className="@container flex min-w-0 flex-col gap-4">
        {rows.map((row) => (
          <li key={`${row.id}:${row.revision}`} className="min-w-0">
            <CatalogueSyllabusCard syllabus={row} enquiry={enquiry} pending={pending} onSelect={onSelect} />
          </li>
        ))}
      </ul>
    ) : (
      <ResponsiveList label="Plans on sale" columns={columns} rows={rows} pending={pending} minTableWidth={900} renderCard={renderCard} />
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
        title="No plans match these filters"
        description="Try another search, structure, board or grade, or clear the filters."
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
        icon={BadgePercentIcon}
        title="No plans on sale yet"
        description="Plans appear here once an administrator publishes them in Syllabus & Plans."
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
