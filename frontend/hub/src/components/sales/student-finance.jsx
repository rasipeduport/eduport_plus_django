import { useEffect, useRef, useState } from 'react';
import {
  BanknoteIcon, CircleCheckIcon, ClockIcon, CreditCardIcon, DownloadIcon, EyeIcon, HistoryIcon, HourglassIcon, PlusIcon,
  RefreshCwIcon, RepeatIcon, ShoppingBagIcon, WalletIcon, ZapIcon,
} from 'lucide-react';

import api from '@/lib/api';
import { quotePlanLabel, salesError } from '@/lib/sales';
import {
  PAYMENT_METHODS, PAYMENT_STATUSES, PAYMENT_TYPES, PURCHASE_KINDS, PURCHASE_STATUSES, studentFinanceUrl, studentPaymentsUrl,
  studentPurchasesUrl, wholeAed,
} from '@/lib/payments';
import { cn, formatDate } from '@/lib/utils';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { ErrorState, Notice } from '@/components/page/states';
import { ListToolbar, FilterSelect } from '@/components/page/list-toolbar';
import { Pagination } from '@/components/page/pagination';
import { ResponsiveList } from '@/components/page/responsive-list';
import { FormDialog } from '@/components/form-dialog';
import { WorkspaceCard } from '@/components/bookings/redemo-workspace/parts';
import { AutopayAgreement } from '@/components/sales/autopay-summary';
import { useSyllabusPdf } from '@/components/sales/syllabus-pdf';
import { AddPurchase, PurchaseDetail } from '@/components/sales/additional-purchases';

const HISTORY_PAGE_SIZE = 10;
const NO_FILTERS = { sale: '', status: '', method: '' };
const TONES = {
  primary: 'bg-primary/10 text-primary', success: 'bg-success/10 text-success', warning: 'bg-warning/10 text-warning', info: 'bg-info/10 text-info',
};
const dateTime = (value) => formatDate(value, { month: 'short', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit' });

/**
 * A student's Finance tab, for their mentor (or an administrator): every
 * purchase on the student's account -- the initial enrollment and each
 * additional purchase -- with its balance, every payment, the total still
 * owed, and collecting it (Stripe link or a received payment with its
 * receipt). All figures are the API's, from the purchase and payment records.
 */
export function StudentFinance({ studentId }) {
  const [overview, setOverview] = useState(null);
  const [error, setError] = useState(null);
  const [reload, setReload] = useState(0);
  const [view, setView] = useState({ name: 'finance' });
  const [choosing, setChoosing] = useState(null);
  const autopayRef = useRef(null);

  useEffect(() => {
    let active = true;
    api.get(studentFinanceUrl(studentId))
      .then(({ data }) => { if (active) { setOverview(data); setError(null); } })
      .catch((err) => { if (active) setError(salesError(err, 'Could not load this student’s finance.')); });
    return () => { active = false; };
  }, [studentId, reload]);

  const refresh = () => setReload((key) => key + 1);
  const toFinance = () => { refresh(); setView({ name: 'finance' }); };
  const open = (saleId, method = 'STRIPE') => setView({ name: 'purchase', saleId, method });
  if (error && !overview) return <ErrorState message={error.message} onRetry={refresh} />;
  if (!overview) return <Skeleton className="h-64 w-full" aria-busy="true" />;
  if (view.name === 'add') {
    return <NewPurchase studentId={studentId} onBack={() => setView({ name: 'finance' })}
      onCreated={(state) => { refresh(); setView({ name: 'purchase', saleId: state.sale.id, state, method: 'STRIPE' }); }} />;
  }
  if (view.name === 'purchase') {
    return <PurchaseDetail key={view.saleId} saleId={view.saleId} initial={view.state} initialMethod={view.method} onBack={toFinance} />;
  }

  const collectible = overview.purchases.filter((row) => row.can_collect);
  // One purchase to collect opens it; several ask which first.
  const collect = (method) => (collectible.length === 1 ? open(collectible[0].id, method) : setChoosing(method));
  return <div className="flex min-w-0 flex-col gap-6">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <h2 className="text-xl font-semibold">Finance</h2>
      <Button variant="outline" size="sm" onClick={refresh}><RefreshCwIcon />Refresh</Button>
    </div>
    {error ? <ErrorState message={error.message} onRetry={refresh} /> : null}
    <SummaryCards summary={overview.summary} />
    <PurchasesOverview overview={overview} onAdd={() => setView({ name: 'add' })} onOpen={(saleId) => open(saleId)} />
    <div className="grid min-w-0 gap-6 lg:grid-cols-3">
      <div className="flex min-w-0 flex-col gap-6 lg:col-span-2">
        <FinancePaymentHistory studentId={studentId} purchases={overview.purchases} reloadKey={reload} />
        <div ref={autopayRef} className="scroll-mt-6"><AutopayAgreements agreements={overview.autopay} /></div>
      </div>
      {/* What is owed and what to do about it come first on a phone. */}
      <div className="flex min-w-0 flex-col gap-6 max-lg:order-first">
        <OutstandingBalance overview={overview} onCollect={() => collect('STRIPE')} />
        <QuickActions overview={overview} onAdd={() => setView({ name: 'add' })} onCollect={() => collect('STRIPE')}
          onDirect={() => collect('TRANSFER')} onAutopay={() => autopayRef.current?.scrollIntoView?.({ behavior: 'smooth', block: 'start' })} />
      </div>
    </div>
    <ChoosePurchase method={choosing} purchases={collectible} onOpenChange={(next) => !next && setChoosing(null)}
      onChoose={(saleId) => { const method = choosing; setChoosing(null); open(saleId, method); }} />
  </div>;
}

function SummaryCard({ icon: Icon, label, value, hint, tone }) {
  return <Card className="min-w-0 flex-row items-center gap-4 px-5 py-5">
    <span className={cn('flex size-11 shrink-0 items-center justify-center rounded-full', TONES[tone])}><Icon className="size-5" aria-hidden="true" /></span>
    <div className="min-w-0">
      <p className="text-muted-foreground text-sm">{label}</p>
      <p className="truncate text-2xl font-semibold tabular-nums">{value}</p>
      {hint ? <p className="text-muted-foreground text-xs text-pretty">{hint}</p> : null}
    </div>
  </Card>;
}

function SummaryCards({ summary }) {
  const notCredited = Number(summary.classes_not_credited) > 0;
  return <section aria-label="Financial summary" className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
    <SummaryCard icon={ShoppingBagIcon} tone="primary" label="Total classes purchased" value={summary.purchased_classes} />
    <SummaryCard icon={CircleCheckIcon} tone="success" label="Paid classes" value={summary.paid_classes}
      hint={notCredited ? `Class quota ${summary.class_quota} · ${summary.classes_not_credited} paid after enrollment, recorded money only` : null} />
    <SummaryCard icon={HourglassIcon} tone="warning" label="Pending classes" value={summary.pending_classes} />
    <SummaryCard icon={WalletIcon} tone="info" label="Total amount" value={wholeAed(summary.total_amount)}
      hint={Number(summary.refunded_amount) > 0 ? `${wholeAed(summary.refunded_amount)} refunded, tracked separately` : null} />
    <SummaryCard icon={BanknoteIcon} tone="success" label="Paid amount" value={wholeAed(summary.paid_amount)} />
    <SummaryCard icon={ClockIcon} tone="warning" label="Pending amount" value={wholeAed(summary.pending_amount)}
      hint={Number(summary.autopay_amount) > 0 ? `${wholeAed(summary.autopay_amount)} scheduled on AutoPay` : null} />
  </section>;
}

function PurchaseType({ row }) {
  return <span className="flex flex-col items-start gap-1">
    <Badge variant={row.kind === 'ADDITIONAL' ? 'secondary' : 'outline'}>{PURCHASE_KINDS[row.kind] ?? row.kind}</Badge>
    <span className="text-muted-foreground text-xs">{row.kind === 'ADDITIONAL'
      ? `${row.classes} classes · ${formatDate(row.created_at)}` : `Enrollment · ${formatDate(row.enrolled_at ?? row.created_at)}`}</span>
  </span>;
}

function PurchaseStatus({ row }) {
  const status = PURCHASE_STATUSES[row.payment_status] ?? { label: row.payment_status, variant: 'outline' };
  const autopay = row.payment_status === 'AUTOPAY' && row.autopay_status ? ` · ${row.autopay_status.toLowerCase().replaceAll('_', ' ')}` : '';
  return <Badge variant={status.variant}>{status.label}{autopay}</Badge>;
}

const planOf = (row) => (row.plan_type ? `${row.syllabus} · ${quotePlanLabel(row)}` : '—');

function PurchasesOverview({ overview, onAdd, onOpen }) {
  const columns = [
    { key: 'type', header: 'Purchase type', className: 'whitespace-normal', cell: (row) => <PurchaseType row={row} /> },
    { key: 'reference', header: 'Reference', cell: (row) => row.quote_reference ?? '—' },
    { key: 'plan', header: 'Plan / package', className: 'min-w-48 whitespace-normal', cell: planOf },
    { key: 'classes', header: 'Classes', cell: (row) => row.classes ?? '—' },
    { key: 'total', header: 'Total', cell: (row) => wholeAed(row.package_amount) },
    { key: 'paid', header: 'Paid', cell: (row) => wholeAed(row.paid_amount) },
    { key: 'pending', header: 'Pending', cell: (row) => wholeAed(row.outstanding_amount) },
    { key: 'status', header: 'Payment status', cell: (row) => <PurchaseStatus row={row} /> },
    { key: 'actions', header: { srOnly: 'Actions' }, cell: (row) => <Button size="sm" variant="outline" onClick={() => onOpen(row.id)}><EyeIcon />View details</Button> },
  ];
  return <WorkspaceCard icon={CreditCardIcon} title="Purchases overview"
    action={<Button size="sm" onClick={onAdd} disabled={!overview.can_add}><PlusIcon />New purchase</Button>}>
    {overview.blockers.map((blocker) => <Notice key={`${blocker.code}:${blocker.sale_id}`}>{blocker.message}</Notice>)}
    <p className="text-muted-foreground text-sm">{overview.student.full_name} · {overview.student.student_code} · {overview.account.reference}. Each purchase is its own sale on this account; adding one never changes an earlier purchase or its payments.</p>
    <ResponsiveList label="Purchases" columns={columns} rows={overview.purchases} minTableWidth={900}
      renderCard={(row) => <article className="flex flex-col gap-2 rounded-lg border p-3 text-sm">
        <div className="flex flex-wrap items-start justify-between gap-2"><PurchaseType row={row} /><PurchaseStatus row={row} /></div>
        <p className="font-medium">{row.quote_reference ?? '—'} · {planOf(row)}</p>
        <p className="text-muted-foreground">{row.classes} classes · Total {wholeAed(row.package_amount)} · Paid {wholeAed(row.paid_amount)} · Pending {wholeAed(row.outstanding_amount)}</p>
        <div><Button size="sm" variant="outline" onClick={() => onOpen(row.id)}><EyeIcon />View details</Button></div>
      </article>} />
  </WorkspaceCard>;
}

const recordedBy = (row) => (row.collection_source === 'AUTOPAY' ? 'Automatic collection' : `Recorded by ${row.recorded_by.name}`);

/**
 * When a payment happened -- a Stripe payment's verification, or the day a
 * received payment was paid on (recorded at `created_at`) -- and who recorded it.
 */
function PaidAt({ row }) {
  const when = row.method === 'STRIPE' ? dateTime(row.verified_at ?? row.created_at) : formatDate(row.payment_date);
  return <span title={row.method === 'STRIPE' ? undefined : `Recorded ${dateTime(row.created_at)}`}>{when}
    <span className="text-muted-foreground block text-xs">{recordedBy(row)}</span></span>;
}

const referenceOf = (row) => row.transaction_reference || row.stripe_payment_intent || '';

function PaymentStatus({ row }) {
  const label = PAYMENT_STATUSES.find((option) => option.value === row.status)?.label ?? row.status;
  return <Badge variant={row.status === 'SUCCEEDED' ? 'success' : row.status === 'PENDING' ? 'warning' : 'outline'}>{label}</Badge>;
}

function FinancePaymentHistory({ studentId, purchases, reloadKey }) {
  const [filters, setFilters] = useState(NO_FILTERS);
  const [page, setPage] = useState(1);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [pending, setPending] = useState(false);
  const [retry, setRetry] = useState(0);
  const files = useSyllabusPdf();

  useEffect(() => {
    let active = true;
    setPending(true);
    const params = { page, page_size: HISTORY_PAGE_SIZE, ...Object.fromEntries(Object.entries(filters).filter(([, value]) => value)) };
    api.get(studentPaymentsUrl(studentId), { params })
      .then(({ data: next }) => { if (active) { setData(next); setError(null); } })
      .catch((err) => { if (active) setError(salesError(err, 'Could not load the payments.')); })
      .finally(() => { if (active) setPending(false); });
    return () => { active = false; };
  }, [studentId, filters, page, reloadKey, retry]);

  const filter = (key) => (value) => { setFilters((current) => ({ ...current, [key]: value })); setPage(1); };
  const receipt = (row, label = null) => (row.proof_url ? <Button variant="outline" size={label ? 'sm' : 'icon'} onClick={() => files.download(row.proof_url, row.proof_name)}
    disabled={Boolean(files.pending)} aria-label={`Download receipt ${row.proof_name}`}><DownloadIcon />{label}</Button> : '—');
  const columns = [
    { key: 'date', header: 'Date and time', className: 'whitespace-normal', cell: (row) => <PaidAt row={row} /> },
    { key: 'type', header: 'Payment type', className: 'whitespace-normal', cell: (row) => <span>{PAYMENT_TYPES[row.payment_type] ?? row.payment_type}<span className="text-muted-foreground block text-xs">{row.purchase_reference ?? '—'}</span></span> },
    { key: 'amount', header: 'Amount', cell: (row) => <span>{wholeAed(row.amount)}<span className="text-muted-foreground block text-xs">{row.purpose === 'TOKEN' ? 'No classes' : `${row.classes} classes`}</span></span> },
    { key: 'method', header: 'Method / reference', className: 'whitespace-normal', cell: (row) => <span className="block max-w-40">{row.method_label}
      <span className="text-muted-foreground block truncate text-xs" title={referenceOf(row) || undefined}>{referenceOf(row) || 'No reference'}</span>
      {row.failure_message ? <span className="text-destructive block text-xs">Declined: {row.failure_message}</span> : null}</span> },
    { key: 'status', header: 'Status', cell: (row) => <PaymentStatus row={row} /> },
    { key: 'receipt', header: 'Receipt', cell: (row) => receipt(row) },
  ];
  const active = Object.values(filters).some(Boolean);
  return <WorkspaceCard icon={HistoryIcon} title="Payment history">
    <ListToolbar active={active} onClear={() => { setFilters(NO_FILTERS); setPage(1); }}>
      <FilterSelect label="Purchase" placeholder="All purchases" value={filters.sale} onChange={filter('sale')}
        options={purchases.map((row) => ({ value: row.id, label: `${row.quote_reference ?? '—'} · ${PURCHASE_KINDS[row.kind] ?? row.kind}` }))} />
      <FilterSelect label="Status" placeholder="All statuses" value={filters.status} onChange={filter('status')} options={PAYMENT_STATUSES} />
      <FilterSelect label="Method" placeholder="All methods" value={filters.method} onChange={filter('method')} options={PAYMENT_METHODS} />
    </ListToolbar>
    {error ? <ErrorState message={error.message} onRetry={() => setRetry((key) => key + 1)} /> : null}
    {!data ? <Skeleton className="h-32 w-full" aria-busy="true" />
      : data.results.length ? <ResponsiveList label="Payments" columns={columns} rows={data.results} pending={pending} minTableWidth={640}
        renderCard={(row) => <article className="flex flex-col gap-2 rounded-lg border p-3 text-sm">
          <div className="flex flex-wrap items-start justify-between gap-2"><strong>{wholeAed(row.amount)}</strong><PaymentStatus row={row} /></div>
          <p>{PAYMENT_TYPES[row.payment_type] ?? row.payment_type} · {row.purchase_reference ?? '—'} · {row.method_label}</p>
          <p className="text-muted-foreground"><PaidAt row={row} /></p>
          <p className="text-muted-foreground break-all">{referenceOf(row) || 'No reference'}</p>
          {row.proof_url ? <div>{receipt(row, 'Receipt')}</div> : null}
        </article>} />
      : <p className="text-muted-foreground text-sm">{active ? 'No payments match these filters.' : 'No payments yet.'}</p>}
    {data && data.count > HISTORY_PAGE_SIZE ? <Pagination page={data.page} pageSize={data.page_size} total={data.count} onPageChange={setPage} pending={pending} /> : null}
    {files.error ? <p role="alert" className="text-destructive text-sm">{files.error}</p> : null}
    {files.dialog}
  </WorkspaceCard>;
}

/** Every AutoPay agreement on the student's account, each opened on its own; a purchase's schedule is never merged with another's. */
function AutopayAgreements({ agreements }) {
  return <WorkspaceCard icon={RepeatIcon} title="AutoPay agreements"
    action={<Badge variant="secondary">{agreements.length} {agreements.length === 1 ? 'agreement' : 'agreements'}</Badge>}>
    {agreements.length
      ? <ul aria-label="AutoPay agreements" className="flex flex-col gap-2">{agreements.map((agreement) => <AutopayAgreement key={agreement.id} agreement={agreement} />)}</ul>
      : <div className="bg-success/5 border-success/30 flex items-center gap-3 rounded-lg border p-4 text-sm">
        <CircleCheckIcon className="text-success size-6 shrink-0" aria-hidden="true" />
        <span><strong className="text-success block">No AutoPay agreements</strong>None of this student’s purchases is collected by AutoPay.</span>
      </div>}
  </WorkspaceCard>;
}

function OutstandingBalance({ overview, onCollect }) {
  const { summary } = overview;
  const owed = overview.purchases.filter((row) => Number(row.outstanding_amount) > 0);
  return <Card className="bg-warning/5 border-warning/30 min-w-0 gap-3 px-5 py-5">
    <h2 className="flex items-center gap-2.5 text-base font-semibold"><ClockIcon className="text-warning size-5" aria-hidden="true" />Outstanding balance</h2>
    <p className="text-warning text-3xl font-semibold tabular-nums">{wholeAed(summary.pending_amount)}</p>
    {owed.length ? <ul className="flex flex-col gap-1 text-sm">{owed.map((row) => <li key={row.id} className="flex flex-wrap justify-between gap-2">
      <span>{row.quote_reference} · {PURCHASE_KINDS[row.kind] ?? row.kind}</span>
      <span className="font-medium">{wholeAed(row.outstanding_amount)}{row.payment_status === 'AUTOPAY' ? ' · on AutoPay' : row.link_pending ? ' · link sent' : ''}</span>
    </li>)}</ul> : <p className="text-muted-foreground text-sm">No pending balance.</p>}
    {overview.can_collect ? <Button variant="outline" onClick={onCollect}>Collect pending balance</Button> : null}
  </Card>;
}

function QuickActions({ overview, onAdd, onCollect, onDirect, onAutopay }) {
  return <WorkspaceCard icon={ZapIcon} title="Quick actions">
    <div className="flex flex-col gap-2">
      <Button onClick={onCollect} disabled={!overview.can_collect}><WalletIcon />Collect pending balance</Button>
      <Button variant="outline" onClick={onAdd} disabled={!overview.can_add}><ShoppingBagIcon />New purchase</Button>
      <Button variant="outline" onClick={onDirect} disabled={!overview.can_collect}><BanknoteIcon />Add direct payment</Button>
      <Button variant="outline" onClick={onAutopay}><RepeatIcon />View AutoPay agreements</Button>
    </div>
    {!overview.can_collect ? <p className="text-muted-foreground text-xs">Nothing can be collected now: every purchase is paid, on AutoPay or awaiting its payment link.</p> : null}
  </WorkspaceCard>;
}

/** Which purchase to collect, when more than one has something to collect. */
function ChoosePurchase({ method, purchases, onOpenChange, onChoose }) {
  const [chosen, setChosen] = useState('');
  return <FormDialog open={Boolean(method)} onOpenChange={(next) => { if (!next) setChosen(''); onOpenChange(next); }}
    title={method === 'STRIPE' ? 'Collect pending balance' : 'Add direct payment'} description="Choose the purchase this payment is for."
    onConfirm={() => { const saleId = chosen; setChosen(''); onChoose(saleId); }} confirmLabel="Continue" confirmDisabled={!chosen}>
    <div role="radiogroup" aria-label="Purchase" className="flex flex-col gap-2">
      {purchases.map((row) => <label key={row.id} className="has-checked:border-primary flex cursor-pointer items-start gap-3 rounded-lg border p-3 text-sm">
        <input type="radio" name="collect-purchase" className="accent-primary mt-1" checked={chosen === row.id} onChange={() => setChosen(row.id)} />
        <span><span className="block font-medium">{row.quote_reference} · {PURCHASE_KINDS[row.kind] ?? row.kind}</span>
          <span className="text-muted-foreground text-xs">{planOf(row)} · {wholeAed(row.outstanding_amount)} outstanding</span></span>
      </label>)}
    </div>
  </FormDialog>;
}

/** The catalogue on sale (from the purchases endpoint), then Add purchase as before. */
function NewPurchase({ studentId, onBack, onCreated }) {
  const [overview, setOverview] = useState(null);
  const [error, setError] = useState(null);
  const [reload, setReload] = useState(0);
  useEffect(() => {
    let active = true;
    api.get(studentPurchasesUrl(studentId))
      .then(({ data }) => { if (active) { setOverview(data); setError(null); } })
      .catch((err) => { if (active) setError(salesError(err, 'Could not load the plans on sale.')); });
    return () => { active = false; };
  }, [studentId, reload]);
  if (error) return <div className="flex flex-col gap-3"><div><Button variant="outline" onClick={onBack}>Back to Finance</Button></div><ErrorState message={error.message} onRetry={() => setReload((key) => key + 1)} /></div>;
  if (!overview) return <Skeleton className="h-48 w-full" aria-busy="true" />;
  return <AddPurchase studentId={studentId} overview={overview} onBack={onBack} onCreated={onCreated} />;
}
