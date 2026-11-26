import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { ClockPlusIcon, SearchXIcon, XIcon } from 'lucide-react';

import api from '@/lib/api';
import { salesError } from '@/lib/sales';
import { wholeAed } from '@/lib/payments';
import { ADDITIONAL_HOURS_URL, LIST_VIEWS, allocationPath, chapterLabel, dueLabel, hours, listQuery } from '@/lib/additional-hours';
import { formatDate } from '@/lib/utils';
import { useListParams } from '@/hooks/use-list-params';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { TableSkeleton } from '@/components/table-skeleton';
import { EmptyState, Page, PageHeader } from '@/components/page/page';
import { FilterSelect } from '@/components/page/list-toolbar';
import { Pagination } from '@/components/page/pagination';
import { ResponsiveList } from '@/components/page/responsive-list';
import { AccessDeniedState, ErrorState } from '@/components/page/states';
import { AllocationBadges } from '@/components/sales/additional-hours';

const PAGE_SIZE = 25;
// The default view is what is still owed (pending or partly paid); the select's first option names it.
const DEFAULT_VIEW = 'OPEN';
const VIEW_OPTIONS = LIST_VIEWS.filter((view) => view.value !== DEFAULT_VIEW);
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
const validDate = (value) => (DATE_RE.test(value ?? '') ? value : '');

function Tile({ label, value, tone }) {
  return <div className="bg-card min-w-0 rounded-xl border px-4 py-3">
    <dt className="text-muted-foreground text-xs">{label}</dt>
    <dd className={`truncate text-xl font-semibold tabular-nums ${tone ?? ''}`}>{value}</dd>
  </div>;
}

/**
 * Additional hours across students (backend sales.additional_hours register):
 * every student's for an administrator, a mentor's own students' only -- the
 * API decides, whatever the URL asks. Opens on what is still owed, soonest due
 * first; filtered by status (Overdue among them) and due dates in the URL, with
 * the totals of what is shown. Each opens on its student's Finance tab, where
 * payments are recorded. Never part of the tuition figures.
 */
export default function AdditionalHoursPage() {
  const { searchParams, update, clear } = useListParams();
  const [data, setData] = useState(null);
  const [failure, setFailure] = useState(null);
  const [pending, setPending] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  const page = Math.max(1, parseInt(searchParams.get('page') || '1', 10) || 1);
  const view = VIEW_OPTIONS.some((option) => option.value === searchParams.get('view')) ? searchParams.get('view') : '';
  const dueFrom = validDate(searchParams.get('due_from'));
  const dueTo = validDate(searchParams.get('due_to'));
  const filtered = Boolean(view || dueFrom || dueTo);

  useEffect(() => {
    let active = true;
    setPending(true);
    const params = { page, page_size: PAGE_SIZE, ...listQuery(view || DEFAULT_VIEW) };
    if (dueFrom) params.due_from = dueFrom;
    if (dueTo) params.due_to = dueTo;
    api.get(ADDITIONAL_HOURS_URL, { params })
      .then((response) => { if (active) { setData(response.data); setFailure(null); } })
      .catch((err) => { if (active) setFailure(salesError(err, 'Could not load the additional hours.')); })
      .finally(() => { if (active) setPending(false); });
    return () => { active = false; };
  }, [page, view, dueFrom, dueTo, reloadKey]);

  const retry = () => setReloadKey((key) => key + 1);
  const open = (row) => (
    <Button variant="outline" size="sm" asChild>
      <Link to={allocationPath(row)} aria-label={`Open ${row.reference} for ${row.student.full_name}`}>Open</Link>
    </Button>
  );
  const columns = [
    { key: 'student', header: 'Student', className: 'min-w-40 whitespace-normal', cell: (row) => <span>
      <Link to={allocationPath(row)} className="font-medium hover:underline">{row.student.full_name}</Link>
      <span className="text-muted-foreground block text-xs">{row.student.student_code}</span></span> },
    { key: 'reference', header: 'Reference', cell: (row) => <span className="tabular-nums">{row.reference}</span> },
    { key: 'plan', header: 'Plan / chapter', className: 'min-w-44 whitespace-normal', cell: (row) => <span>{row.plan.quote_reference} · {row.plan.syllabus}
      <span className="text-muted-foreground block text-xs">{chapterLabel(row.chapter)}</span></span> },
    { key: 'hours', header: 'Hours', cell: (row) => hours(row.hours) },
    { key: 'amount', header: 'Amount', headerClassName: 'text-right', className: 'text-right tabular-nums', cell: (row) => wholeAed(row.amount) },
    { key: 'paid', header: 'Paid', headerClassName: 'text-right', className: 'text-right tabular-nums', cell: (row) => wholeAed(row.paid_amount) },
    { key: 'outstanding', header: 'Still due', headerClassName: 'text-right', className: 'text-right tabular-nums font-medium', cell: (row) => wholeAed(row.outstanding_amount) },
    { key: 'due', header: 'Due date', className: 'whitespace-normal', cell: (row) => <span className={row.overdue ? 'text-destructive' : ''}>{dueLabel(row, formatDate)}</span> },
    { key: 'last', header: 'Last payment', className: 'text-muted-foreground whitespace-nowrap', cell: (row) => (row.last_payment_date ? formatDate(row.last_payment_date) : '—') },
    { key: 'status', header: 'Status', cell: (row) => <AllocationBadges row={row} /> },
    { key: 'open', header: { srOnly: 'Open' }, headerClassName: 'w-24', cell: open },
  ];
  const renderCard = (row) => <article className="bg-card flex h-full flex-col gap-3 rounded-xl border p-4">
    <div className="flex items-start justify-between gap-3">
      <div className="min-w-0"><h2 className="font-medium"><Link to={allocationPath(row)} className="hover:underline">{row.student.full_name}</Link></h2>
        <p className="text-muted-foreground text-sm">{row.student.student_code} · {row.reference}</p></div>
      <AllocationBadges row={row} />
    </div>
    <p className="text-sm">{hours(row.hours)} · {row.plan.quote_reference} · {chapterLabel(row.chapter)}</p>
    <div className="mt-auto flex flex-wrap items-center justify-between gap-2 border-t pt-3 text-sm">
      <span><span className="font-semibold tabular-nums">{wholeAed(row.outstanding_amount)}</span> still due · <span className={row.overdue ? 'text-destructive' : 'text-muted-foreground'}>{dueLabel(row, formatDate)}</span></span>
      {open(row)}
    </div>
  </article>;

  let content;
  if (failure?.status === 403) {
    content = <AccessDeniedState title="You don't have access to additional hours." message={failure.message} />;
  } else {
    let list;
    const rows = data?.results ?? [];
    const total = data?.count ?? 0;
    if (!data && !failure) list = <TableSkeleton toolbar={false} />;
    else if (!data) list = <ErrorState message={failure.message} onRetry={retry} pending={pending} />;
    else {
      let body;
      if (rows.length) {
        body = <ResponsiveList label="Additional hours" columns={columns} rows={rows} pending={pending} minTableWidth={1080} renderCard={renderCard} />;
      } else if (total > 0) {
        body = <EmptyState icon={SearchXIcon} title="Nothing on this page" description="This page is past the last one."
          action={<Button variant="outline" onClick={() => update({ page: null })}>Go to the first page</Button>} />;
      } else if (filtered) {
        body = <EmptyState icon={SearchXIcon} title="No additional hours match these filters" description="Try another status or due date, or clear the filters."
          action={<Button variant="outline" onClick={clear}>Clear all filters</Button>} />;
      } else {
        body = <EmptyState icon={ClockPlusIcon} title="Nothing is owed for additional hours"
          description="Hours an administrator adds on a student’s Finance tab appear here until they are paid." />;
      }
      const summary = data.summary;
      list = <>
        {failure ? <ErrorState message={failure.message} onRetry={retry} pending={pending} /> : null}
        {/* The API's totals: every allocation matching these filters, across all pages -- not this page alone. */}
        <dl aria-label="Totals for all additional hours matching these filters, across every page" className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <Tile label="Still due" value={wholeAed(summary.outstanding)} tone={Number(summary.outstanding) > 0 ? 'text-warning' : ''} />
          <Tile label="Overdue" value={summary.overdue_count ? `${summary.overdue_count} · ${wholeAed(summary.overdue_amount)}` : 'None'}
            tone={summary.overdue_count ? 'text-destructive' : ''} />
          <Tile label="Hours with payment pending" value={hours(summary.payment_pending_hours)} />
          <Tile label="Received" value={wholeAed(summary.received)} tone="text-success" />
        </dl>
        {body}
        {total > 0 ? <Pagination page={page} pageSize={PAGE_SIZE} total={total} pending={pending} onPageChange={(next) => update({ page: String(next) })} /> : null}
      </>;
    }
    content = <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end gap-2">
        <FilterSelect label="Filter by status" placeholder="Pending and partly paid" value={view}
          onChange={(value) => update({ view: value || null })} options={VIEW_OPTIONS} />
        <div className="flex flex-col gap-1"><Label htmlFor="hours-due-from" className="text-muted-foreground text-xs">Due from</Label>
          <Input id="hours-due-from" type="date" className="w-40" value={dueFrom} onChange={(event) => update({ due_from: event.target.value || null })} /></div>
        <div className="flex flex-col gap-1"><Label htmlFor="hours-due-to" className="text-muted-foreground text-xs">Due to</Label>
          <Input id="hours-due-to" type="date" className="w-40" value={dueTo} onChange={(event) => update({ due_to: event.target.value || null })} /></div>
        {filtered ? <Button variant="ghost" className="text-muted-foreground" onClick={clear}><XIcon className="size-4" />Clear all filters</Button> : null}
      </div>
      {list}
    </div>;
  }

  return <Page>
    <PageHeader title="Additional Hours"
      description="Hours added on top of students’ plans and the payments still owed for them, kept apart from tuition. Record payments from each student’s Finance tab." />
    {content}
  </Page>;
}
