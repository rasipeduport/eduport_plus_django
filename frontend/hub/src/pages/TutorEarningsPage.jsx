import { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import {
  AlertTriangleIcon,
  ChevronRightIcon,
  HandCoinsIcon,
  HourglassIcon,
  InfoIcon,
  ListChecksIcon,
  SlidersHorizontalIcon,
  WalletIcon,
  XIcon,
} from 'lucide-react';

import api from '@/lib/api';
import { PERMISSIONS, can } from '@/lib/access';
import {
  EARNINGS_API,
  NOT_COUNTED_REASONS,
  countsLine,
  dayLabel,
  earningsError,
  formatInr,
  monthLabel,
  trimUnits,
} from '@/lib/earnings';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { Tile } from '@/components/dashboard/kpi-cards';
import { EmptyState, Page, PageHeader } from '@/components/page/page';
import { FilterSelect, SearchField } from '@/components/page/list-toolbar';
import { ResponsiveList } from '@/components/page/responsive-list';
import { AccessDeniedState, ErrorState } from '@/components/page/states';
import { BalanceBadge, DemoConversionCard, MonthFilter, RateSourceBadge, SyncNote } from '@/components/earnings/parts';
import { RatesSheet } from '@/components/earnings/rates-sheet';
import { ReviewSheet } from '@/components/earnings/review-sheet';

const BALANCES = [
  { value: 'pending', label: 'Pending payment' },
  { value: 'paid', label: 'Paid in full' },
  { value: 'overpaid', label: 'Overpaid' },
  { value: 'none', label: 'Nothing earned yet' },
];
const RATES = [
  { value: 'tutor', label: 'Tutor-specific rate' },
  { value: 'global', label: 'Global rate only' },
];

/** "6 notes due, 1 report due, 2 being added": what is not counted yet across every tutor, or null. */
function notCountedLine(counts) {
  const parts = Object.entries(counts || {})
    .filter(([, count]) => count > 0)
    .map(([reason, count]) => `${count} ${(NOT_COUNTED_REASONS[reason]?.label || reason).toLowerCase()}`);
  return parts.length ? parts.join(', ') : null;
}

/**
 * Tutor Earnings, for administrators (Sales & Finance): every tutor's
 * eligible classes, earnings, payments and balance for the period (all time,
 * or a month), with the global rates, what needs review, and each tutor's
 * own page. In Indian rupees. The API (accounts.view_tutor_earnings) serves
 * the figures; this page only reads -- the sync adds earnings every 10 minutes.
 */
export default function TutorEarningsPage({ user }) {
  const [params, setParams] = useSearchParams();
  const month = params.get('month') || '';
  const q = params.get('q') || '';
  const balance = params.get('balance') || '';
  const rate = params.get('rate') || '';
  const [data, setData] = useState(null);
  const [failure, setFailure] = useState(null);
  const [pending, setPending] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const [ratesOpen, setRatesOpen] = useState(false);
  const [reviewOpen, setReviewOpen] = useState(false);

  const canRates = can(user, PERMISSIONS.manageTutorRates);
  const canCorrect = can(user, PERMISSIONS.correctTutorEarnings);

  useEffect(() => {
    let active = true;
    setPending(true);
    api
      .get(`${EARNINGS_API}/overview/`, { params: month ? { month } : {} })
      .then((response) => {
        if (!active) return;
        setData(response.data);
        setFailure(null);
      })
      .catch((err) => {
        if (active) setFailure(earningsError(err, 'Could not load Tutor Earnings.'));
      })
      .finally(() => {
        if (active) setPending(false);
      });
    return () => {
      active = false;
    };
  }, [month, reloadKey]);

  const update = (changes) => {
    const next = new URLSearchParams(params);
    for (const [key, value] of Object.entries(changes)) {
      if (value) next.set(key, value);
      else next.delete(key);
    }
    setParams(next, { replace: true });
  };
  const reload = () => setReloadKey((key) => key + 1);

  const term = q.toLowerCase();
  const rows = (data?.tutors || []).filter(
    (row) =>
      (!term || (row.name || '').toLowerCase().includes(term) || (row.email || '').toLowerCase().includes(term)) &&
      (!balance || row.balance_state === balance) &&
      (!rate || row.own_rates === (rate === 'tutor'))
  );
  const filtered = Boolean(q || balance || rate);

  let content;
  if (failure?.status === 403) {
    content = <AccessDeniedState title="You don't have access to Tutor Earnings." message={failure.message} />;
  } else if (failure && !data) {
    content = <ErrorState message={failure.message} onRetry={reload} />;
  } else if (!data) {
    content = (
      <div className="flex flex-col gap-4" aria-busy="true">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-24 rounded-xl" />
          ))}
        </div>
        <Skeleton className="h-72 rounded-xl" />
      </div>
    );
  } else {
    const totals = data.totals;
    const period = month ? monthLabel(month) : 'All time';
    const waiting = notCountedLine(data.not_counted);
    const columns = [
      {
        key: 'tutor',
        header: 'Tutor',
        cell: (row) => (
          <Link to={`/tutor-earnings/${row.id}`} className="flex flex-col underline-offset-4 hover:underline">
            <span className="font-medium">
              {row.name}
              {row.active ? null : (
                <Badge variant="secondary" className="ml-2">
                  Inactive
                </Badge>
              )}
            </span>
            <span className="text-muted-foreground text-xs">{row.email}</span>
          </Link>
        ),
      },
      { key: 'diagnostic', header: 'Diagnostic', cell: (row) => row.diagnostic, className: 'text-right tabular-nums', headerClassName: 'text-right' },
      { key: 'demo', header: 'Demo', cell: (row) => row.demo, className: 'text-right tabular-nums', headerClassName: 'text-right' },
      {
        key: 'conversions',
        header: 'Converted',
        cell: (row) => row.conversions ?? 0,
        className: 'text-right tabular-nums',
        headerClassName: 'text-right',
      },
      { key: 'sessions', header: 'Sessions', cell: (row) => row.sessions, className: 'text-right tabular-nums', headerClassName: 'text-right' },
      {
        key: 'hours',
        header: 'Session hours',
        cell: (row) => `${trimUnits(row.session_hours)} h`,
        className: 'text-right tabular-nums',
        headerClassName: 'text-right',
      },
      { key: 'classes', header: 'Classes', cell: (row) => row.classes, className: 'text-right font-medium tabular-nums', headerClassName: 'text-right' },
      { key: 'earned', header: 'Total earned', cell: (row) => formatInr(row.earned), className: 'text-right font-medium tabular-nums', headerClassName: 'text-right' },
      { key: 'paid', header: 'Paid', cell: (row) => formatInr(row.paid), className: 'text-right tabular-nums', headerClassName: 'text-right' },
      {
        key: 'pending',
        header: 'Pending',
        cell: (row) => <BalanceBadge state={row.balance_state} outstanding={row.outstanding} />,
        className: 'text-right',
        headerClassName: 'text-right',
      },
      { key: 'rates', header: 'Rates', cell: (row) => <RateSourceBadge source={row.own_rates ? 'TUTOR' : 'GLOBAL'} /> },
      {
        key: 'open',
        header: { srOnly: 'Open' },
        cell: (row) => (
          <Button variant="ghost" size="icon" asChild>
            <Link to={`/tutor-earnings/${row.id}`} aria-label={`Open ${row.name}`}>
              <ChevronRightIcon />
            </Link>
          </Button>
        ),
        className: 'text-right',
      },
    ];

    content = (
      <div className="flex flex-col gap-4">
        {!data.activated_at ? (
          <EmptyState icon={HourglassIcon} title="Tutor Earnings is not activated" description="Nothing counts until it is." />
        ) : null}
        {data.activated_at && !data.pricing ? (
          <div role="alert" className="border-warning/40 bg-warning/10 flex flex-wrap items-center gap-3 rounded-xl border px-4 py-3 text-sm">
            <AlertTriangleIcon className="text-warning size-4 shrink-0" aria-hidden="true" />
            <p className="min-w-0 flex-1">
              <strong>Set the initial rates to start pricing.</strong> Eligible classes since {dayLabel(data.activated_at)} are
              counted but not priced yet; the initial rates price every one of them.
            </p>
            {canRates ? (
              <Button size="sm" onClick={() => setRatesOpen(true)}>
                Set initial rates
              </Button>
            ) : null}
          </div>
        ) : null}

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <Tile icon={WalletIcon} tone="info" label="Total Earnings" value={formatInr(totals.earned)} hint={`${period} · ${totals.tutors} tutors`} />
          <Tile
            icon={HandCoinsIcon}
            tone="success"
            label="Total Paid"
            value={formatInr(totals.paid)}
            hint={`${totals.payments} ${totals.payments === 1 ? 'payment' : 'payments'} · ${period}`}
          />
          <Tile
            icon={HourglassIcon}
            tone="warning"
            label="Pending Payments"
            value={formatInr(totals.pending)}
            hint={`Outstanding today · ${totals.tutors_with_balance} ${totals.tutors_with_balance === 1 ? 'tutor' : 'tutors'}${
              Number(totals.overpaid) > 0 ? ` · ${formatInr(totals.overpaid)} overpaid` : ''
            }`}
          />
          <Tile icon={ListChecksIcon} label="Eligible classes" value={totals.classes} hint={countsLine(totals)} />
        </div>

        <DemoConversionCard counts={totals} total={totals.earned} period={period} />

        <div className="flex flex-wrap items-center gap-2">
          <SearchField value={q} onSearch={(text) => update({ q: text })} label="Search tutors" placeholder="Tutor name or email…" />
          <MonthFilter months={data.months} value={month} onChange={(value) => update({ month: value })} />
          <FilterSelect label="Balance" placeholder="All tutors" value={balance} onChange={(value) => update({ balance: value })} options={BALANCES} />
          <FilterSelect label="Rates" placeholder="Any rate" value={rate} onChange={(value) => update({ rate: value })} options={RATES} />
          {filtered ? (
            <Button variant="ghost" className="text-muted-foreground" onClick={() => update({ q: '', balance: '', rate: '' })}>
              <XIcon className="size-4" />
              Clear filters
            </Button>
          ) : null}
        </div>

        {failure ? <ErrorState message={failure.message} onRetry={reload} pending={pending} /> : null}
        {data.tutors.length === 0 ? (
          <EmptyState icon={WalletIcon} title="No tutors yet" description="Tutors appear here as soon as they have an account." />
        ) : rows.length === 0 ? (
          <EmptyState
            icon={WalletIcon}
            title="No tutors match these filters"
            action={
              <Button variant="outline" onClick={() => update({ q: '', balance: '', rate: '' })}>
                Clear filters
              </Button>
            }
          />
        ) : (
          <ResponsiveList
            label="Tutor earnings"
            columns={columns}
            rows={rows}
            pending={pending}
            minTableWidth={1160}
            renderCard={(row) => (
              <Link to={`/tutor-earnings/${row.id}`} className="bg-card flex flex-col gap-2 rounded-xl border p-4">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="truncate font-medium">{row.name}</p>
                    <p className="text-muted-foreground truncate text-xs">{row.email}</p>
                  </div>
                  <BalanceBadge state={row.balance_state} outstanding={row.outstanding} />
                </div>
                <p className="text-muted-foreground text-xs">{countsLine(row)}</p>
                <p className="text-sm">
                  Earned <strong>{formatInr(row.earned)}</strong> · paid {formatInr(row.paid)}
                </p>
              </Link>
            )}
          />
        )}

        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="grid gap-1">
            <p className="text-muted-foreground text-xs">
              Showing {rows.length} of {data.tutors.length} tutors, highest balance first. Session hours are payable hours:
              each session's scheduled length (a 1.5 h session pays 1.5 × the hourly rate). Amounts are in rupees.
            </p>
            <SyncNote lastSync={data.last_sync} />
          </div>
          {waiting ? (
            <p className="bg-card flex max-w-xl items-start gap-2 rounded-lg border px-3 py-2 text-xs">
              <InfoIcon className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
              <span>
                <strong>Not counted yet:</strong> {waiting}. Each is added by the next sync once it qualifies.{' '}
                <Link to="/sessions?tab=needs_action" className="text-link underline-offset-4 hover:underline">
                  Review in Sessions
                </Link>
              </span>
            </p>
          ) : null}
        </div>
      </div>
    );
  }

  return (
    <Page>
      <PageHeader
        title="Tutor Earnings"
        description="What each tutor has earned for completed, eligible classes, and what has been paid to them. In Indian rupees."
        actions={
          data ? (
            <>
              {data.review_count ? (
                <Button variant="outline" onClick={() => setReviewOpen(true)}>
                  <AlertTriangleIcon className="text-warning" />
                  Needs review
                  <Badge variant="warning">{data.review_count}</Badge>
                </Button>
              ) : null}
              <Button variant="outline" onClick={() => setRatesOpen(true)}>
                <SlidersHorizontalIcon />
                Global rates
              </Button>
            </>
          ) : null
        }
      />
      {content}
      <RatesSheet open={ratesOpen} onOpenChange={setRatesOpen} canManage={canRates} onSaved={reload} />
      <ReviewSheet open={reviewOpen} onOpenChange={setReviewOpen} canCorrect={canCorrect} onChanged={reload} />
    </Page>
  );
}
