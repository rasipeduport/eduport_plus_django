import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { BadgePercentIcon, ReceiptTextIcon, SearchXIcon, XIcon } from 'lucide-react';

import api from '@/lib/api';
import { PERMISSIONS, can, canOpenPage } from '@/lib/access';
import { LEAD_BDES_URL } from '@/lib/leads';
import { QUOTES_URL, QUOTE_STATUSES, enquiryLabel, formatAmount, quotePlanLabel, salesError } from '@/lib/sales';
import { formatDate } from '@/lib/utils';
import { useListParams } from '@/hooks/use-list-params';
import { Button } from '@/components/ui/button';
import { TableSkeleton } from '@/components/table-skeleton';
import { EmptyState, Page, PageHeader } from '@/components/page/page';
import { FilterSelect, SearchField } from '@/components/page/list-toolbar';
import { Pagination } from '@/components/page/pagination';
import { ResponsiveList } from '@/components/page/responsive-list';
import { AccessDeniedState, ErrorState } from '@/components/page/states';
import { QuoteStatusBadge } from '@/components/sales/quote-parts';

const PAGE_SIZE = 25;
const valid = (options, value) => (options.some((option) => option.value === value) ? value : '');

/**
 * Quotes, BDE and Admin alike: a BDE's own (My Quotes), newest first -- every
 * BDE's for whoever manages quotes (`user`), who may narrow them to one BDE's.
 * Searched by reference or plan and filtered by status in the URL; each opens
 * on the quote as it was issued. The API answers each caller with only what
 * they may see, whatever the URL asks.
 */
export default function QuotesPage({ user }) {
  const manager = can(user, PERMISSIONS.manageSalesQuotes);
  const { searchParams, update, clear } = useListParams();
  const [data, setData] = useState(null);
  const [failure, setFailure] = useState(null);
  const [pending, setPending] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  // The BDEs to filter by (a manager's); without them the filter is not offered.
  const [bdes, setBdes] = useState(null);

  const page = Math.max(1, parseInt(searchParams.get('page') || '1', 10) || 1);
  const q = (searchParams.get('q') ?? '').trim();
  const status = valid(QUOTE_STATUSES, searchParams.get('status'));
  const owner = manager ? (searchParams.get('created_by') ?? '').trim() : '';
  const filters = { q, status, owner };
  const filtered = Object.values(filters).some(Boolean);

  useEffect(() => {
    let active = true;
    setPending(true);
    const params = { page, page_size: PAGE_SIZE };
    if (q) params.q = q;
    if (status) params.status = status;
    if (owner) params.created_by = owner;
    api
      .get(QUOTES_URL, { params })
      .then((response) => {
        if (!active) return;
        setData(response.data);
        setFailure(null);
      })
      .catch((err) => {
        if (active) setFailure(salesError(err, 'Could not load the quotes.'));
      })
      .finally(() => {
        if (active) setPending(false);
      });
    return () => {
      active = false;
    };
  }, [page, q, status, owner, reloadKey]);

  useEffect(() => {
    if (!manager) return undefined;
    let active = true;
    api
      .get(LEAD_BDES_URL)
      .then((response) => {
        if (active) setBdes(response.data?.results ?? []);
      })
      .catch(() => {});
    return () => {
      active = false;
    };
  }, [manager]);

  const retry = () => setReloadKey((key) => key + 1);
  const open = (row) => `/quotes/${row.id}`;
  const bdeOptions = (bdes ?? []).map((bde) => ({ value: bde.id, label: bde.assignable ? bde.full_name : `${bde.full_name} (inactive)` }));

  const columns = [
    {
      key: 'reference',
      header: 'Quote',
      className: 'whitespace-nowrap',
      cell: (row) => (
        <Link to={open(row)} className="font-medium tabular-nums hover:underline">
          {row.reference}
        </Link>
      ),
    },
    { key: 'date', header: 'Date', className: 'text-muted-foreground whitespace-nowrap', cell: (row) => formatDate(row.created_at) },
    {
      key: 'plan',
      header: 'Plan',
      className: 'min-w-48 whitespace-normal',
      cell: (row) => (
        <>
          <span className="block">{row.syllabus.title}</span>
          <span className="text-muted-foreground block text-xs">{quotePlanLabel(row)}</span>
        </>
      ),
    },
    { key: 'enquiry', header: 'Enquiry', className: 'min-w-36 whitespace-normal', cell: (row) => enquiryLabel(row.lead) || '—' },
    ...(manager ? [{ key: 'bde', header: 'BDE', className: 'whitespace-nowrap', cell: (row) => row.created_by?.name ?? '—' }] : []),
    {
      key: 'payable',
      header: 'Payable at once',
      className: 'whitespace-nowrap text-right tabular-nums',
      headerClassName: 'text-right',
      cell: (row) => formatAmount(row.payable_amount, row.currency),
    },
    { key: 'status', header: 'Status', cell: (row) => <QuoteStatusBadge status={row.status} /> },
    {
      key: 'open',
      header: { srOnly: 'Open' },
      headerClassName: 'w-24',
      cell: (row) => (
        <Button variant="outline" size="sm" asChild>
          <Link to={open(row)} aria-label={`Open quote ${row.reference}`}>
            Open
          </Link>
        </Button>
      ),
    },
  ];

  const renderCard = (row) => (
    <article className="bg-card flex h-full flex-col gap-3 rounded-xl border p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="font-medium tabular-nums">
            <Link to={open(row)} className="hover:underline">
              {row.reference}
            </Link>
          </h2>
          <p className="text-muted-foreground text-sm">
            {[formatDate(row.created_at), manager ? row.created_by?.name : null].filter(Boolean).join(' · ')}
          </p>
        </div>
        <QuoteStatusBadge status={row.status} />
      </div>
      <div className="text-sm">
        <p>{row.syllabus.title}</p>
        <p className="text-muted-foreground text-xs">{quotePlanLabel(row)}</p>
        {row.lead ? <p className="text-muted-foreground mt-1 text-xs">For {enquiryLabel(row.lead)}</p> : null}
      </div>
      <div className="mt-auto flex flex-wrap items-center justify-between gap-2 border-t pt-3 text-sm">
        <span className="font-semibold tabular-nums">{formatAmount(row.payable_amount, row.currency)}</span>
        <Button variant="outline" size="sm" asChild>
          <Link to={open(row)} aria-label={`Open quote ${row.reference}`}>
            Open
          </Link>
        </Button>
      </div>
    </article>
  );

  let content;
  if (failure?.status === 403) {
    content = <AccessDeniedState title="You don't have access to quotes." message={failure.message} />;
  } else {
    let list;
    const rows = data?.results ?? [];
    const total = data?.count ?? 0;
    if (!data && !failure) {
      list = <TableSkeleton toolbar={false} />;
    } else if (!data) {
      list = <ErrorState message={failure.message} onRetry={retry} pending={pending} />;
    } else {
      let body;
      if (rows.length) {
        body = (
          <ResponsiveList
            label="Quotes"
            columns={columns}
            rows={rows}
            pending={pending}
            minTableWidth={manager ? 980 : 860}
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
              <Button variant="outline" onClick={() => update({ page: null })}>
                Go to the first page
              </Button>
            }
          />
        );
      } else if (filtered) {
        body = (
          <EmptyState
            icon={SearchXIcon}
            title="No quotes match these filters"
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
            icon={ReceiptTextIcon}
            title="No quotes yet"
            description={
              manager
                ? 'Quotes appear here as BDEs issue them from an enquiry’s Plan Choosing tab.'
                : 'Open a student’s enquiry → Plan Choosing to select a syllabus and create a quote.'
            }
            action={
              canOpenPage(user, '/enquiries') ? (
                <Button variant="outline" asChild>
                  <Link to="/enquiries">
                    <BadgePercentIcon />
                    My Enquiries
                  </Link>
                </Button>
              ) : null
            }
          />
        );
      }
      list = (
        <>
          {failure ? <ErrorState message={failure.message} onRetry={retry} pending={pending} /> : null}
          {body}
          {total > 0 ? (
            <Pagination page={page} pageSize={PAGE_SIZE} total={total} pending={pending} onPageChange={(next) => update({ page: String(next) })} />
          ) : null}
        </>
      );
    }
    content = (
      <div className="flex flex-col gap-4">
        <div className="flex flex-wrap items-center gap-2">
          <SearchField value={q} onSearch={(text) => update({ q: text || null })} label="Search quotes" placeholder="Search reference or plan…" />
          <FilterSelect
            label="Filter by status"
            placeholder="All statuses"
            value={status}
            onChange={(value) => update({ status: value || null })}
            options={QUOTE_STATUSES}
          />
          {manager && bdes ? (
            <FilterSelect
              label="Filter by BDE"
              placeholder="All BDEs"
              value={owner}
              onChange={(value) => update({ created_by: value || null })}
              options={bdeOptions}
            />
          ) : null}
          {filtered ? (
            <Button variant="ghost" className="text-muted-foreground" onClick={clear}>
              <XIcon className="size-4" />
              Clear all filters
            </Button>
          ) : null}
        </div>
        {list}
      </div>
    );
  }

  return (
    <Page>
      <PageHeader
        title={manager ? 'Quotes' : 'My Quotes'}
        description={
          manager
            ? 'Every quote the BDEs have issued, kept exactly as the parent was told. Open one for its PDF, or to cancel it.'
            : 'The quotes you have issued, kept exactly as the parent was told. Open one for its PDF.'
        }
        actions={
          !manager && canOpenPage(user, '/plans') ? (
            <Button asChild>
              <Link to="/plans">
                <ReceiptTextIcon />
                New quote
              </Link>
            </Button>
          ) : null
        }
      />
      {content}
    </Page>
  );
}
