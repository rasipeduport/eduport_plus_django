import { useEffect, useId, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import {
  AlertTriangle,
  BarChart3,
  ChevronRight,
  CircleDollarSign,
  Funnel,
  HandCoins,
  Hourglass,
  Link2,
  ListTodo,
  PieChart,
  ReceiptText,
  RefreshCwIcon,
  Repeat,
  ShieldAlert,
  Target,
  UserCheck,
  Users,
  Wallet,
} from 'lucide-react';
import { format } from 'date-fns';

import api from '@/lib/api';
import { RANGE_OPTIONS, leadsPath } from '@/lib/admissions';
import { rangeLabel, toPickerDate } from '@/lib/date-range';
import { enquiryError } from '@/lib/enquiries';
import { PAYMENT_TYPES, PURCHASE_KINDS, PURCHASE_STATUSES, autopayStatus, wholeAed } from '@/lib/payments';
import {
  COLLECTION_PLANS,
  FUNNEL_HINTS,
  SALES_DASHBOARD_URL,
  SALES_DEFAULT_RANGE,
  SALE_KINDS,
  UNIT_WORDS,
  aedDigits,
  percent,
  readSalesRange,
  studentFinancePath,
} from '@/lib/sales-dashboard';
import { cn } from '@/lib/utils';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { Tile } from '@/components/dashboard/kpi-cards';
import { Panel, PanelEmpty, ScrollList } from '@/components/dashboard/dashboard-primitives';
import { SalesTrendChart } from '@/components/sales/sales-trend-chart';
import { DatePresets } from '@/components/page/date-presets';
import { Page, PageHeader } from '@/components/page/page';
import { ResponsiveList } from '@/components/page/responsive-list';
import { AccessDeniedState, ErrorState } from '@/components/page/states';

const plural = (count, one, many = `${one}s`) => `${count} ${count === 1 ? one : many}`;
const shortDate = (iso) => format(toPickerDate(iso), 'd MMM yyyy');

function DashboardSkeleton() {
  return (
    <div className="flex flex-col gap-4" aria-busy="true">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-5">
        {[0, 1, 2, 3, 4].map((i) => (
          <Skeleton key={i} className="h-24 rounded-xl" />
        ))}
      </div>
      <div className="grid gap-4 xl:grid-cols-5">
        <Skeleton className="h-80 rounded-xl xl:col-span-3" />
        <Skeleton className="h-80 rounded-xl xl:col-span-2" />
      </div>
      <Skeleton className="h-56 rounded-xl" />
    </div>
  );
}

/** The span the dashboard counts: a preset (this month unless chosen otherwise), or a Custom range on a calendar. */
function RangeFilter({ range, onChange }) {
  const labelId = useId();
  return (
    <div className="flex min-w-0 flex-1 flex-col gap-1.5 sm:items-end">
      <span id={labelId} className="sr-only">
        Dates to count
      </span>
      <DatePresets
        options={RANGE_OPTIONS}
        value={range.range}
        from={range.from}
        to={range.to}
        anyLabel="This month"
        labelledBy={labelId}
        onPick={(preset) => onChange({ range: preset === SALES_DEFAULT_RANGE ? null : preset, from: null, to: null })}
        onCustom={(picked) => onChange(picked.from ? { range: 'custom', ...picked } : { range: null, from: null, to: null })}
      />
      <p className="text-muted-foreground text-xs" aria-live="polite">
        {rangeLabel(range.from, range.to, '')} · Indian dates (IST)
      </p>
    </div>
  );
}

// Where five tiles share a row (xl) the longer labels take two lines: each label
// gets room for two there, so every value sits at the same height.
const KPI_LABEL = 'xl:min-h-8 2xl:min-h-0';

/** A tile's amount: the currency small beside its digits, so the figure keeps to one line in a narrow tile. */
function Amount({ value }) {
  return (
    <span className="whitespace-nowrap">
      <span className="text-muted-foreground text-sm font-medium">AED</span> {aedDigits(value)}
    </span>
  );
}

function KpiTiles({ summary, range }) {
  const conversion = percent(summary.enrolled_leads, summary.leads);
  const refunded = Number(summary.refunded) > 0 ? ` · ${wholeAed(summary.refunded)} refunded` : '';
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-5">
      <Tile
        labelClassName={KPI_LABEL}
        icon={ReceiptText}
        tone="info"
        label="Sales Value"
        value={<Amount value={summary.sales_value} />}
        hint={`${plural(summary.sales_count, 'sale')} · ${summary.additional_purchases} additional`}
      />
      <Tile
        labelClassName={KPI_LABEL}
        icon={HandCoins}
        tone="success"
        label="Collected"
        value={<Amount value={summary.collected} />}
        hint={`${plural(summary.payments, 'payment')} received${refunded}`}
      />
      <Tile
        labelClassName={KPI_LABEL}
        icon={UserCheck}
        label="New Enrollments"
        value={summary.enrollments}
        hint="Students enrolled by a first payment"
      />
      <Tile
        labelClassName={KPI_LABEL}
        icon={Hourglass}
        tone={Number(summary.outstanding) > 0 ? 'warning' : 'default'}
        label="Outstanding Balance"
        value={<Amount value={summary.outstanding} />}
        hint={`${plural(summary.outstanding_purchases, 'purchase')} · as things stand`}
      />
      <Tile
        labelClassName={KPI_LABEL}
        icon={Target}
        label="Lead Conversion"
        value={`${conversion}%`}
        hint={`${summary.enrolled_leads} of ${plural(summary.leads, 'lead')} enrolled`}
        to={leadsPath(range, 'ENROLLED')}
      />
    </div>
  );
}

/** A share of a whole, as the Admissions pipeline draws one: a label over its hint, a bar, the figures. */
function ShareRow({ label, hint, share, figure, detail, to, ariaLabel }) {
  const content = (
    <>
      <span className="min-w-0">
        <span className="block truncate text-sm font-medium">{label}</span>
        {hint ? <span className="text-muted-foreground block truncate text-xs">{hint}</span> : null}
      </span>
      <span className="bg-muted h-2 overflow-hidden rounded-full" aria-hidden="true">
        <span className="bg-primary block h-full rounded-full" style={{ width: share > 0 ? `max(${share}%, 0.5rem)` : 0 }} />
      </span>
      <span className="flex items-baseline justify-end gap-2 text-right whitespace-nowrap tabular-nums">
        <span className="text-sm font-semibold">{figure}</span>
        {detail != null ? <span className="text-muted-foreground min-w-9 text-xs">{detail}</span> : null}
      </span>
    </>
  );
  const layout = 'grid grid-cols-[minmax(0,9rem)_1fr_auto] items-center gap-x-4 gap-y-1 rounded-md py-2';
  return (
    <li>
      {to ? (
        <Link to={to} aria-label={ariaLabel} className={cn(layout, 'hover:bg-muted/40 -mx-2 px-2 transition-colors')}>
          {content}
        </Link>
      ) : (
        <div className={layout}>{content}</div>
      )}
    </li>
  );
}

function SectionHeading({ children }) {
  return <h3 className="text-muted-foreground mb-1 text-xs font-medium tracking-wide uppercase">{children}</h3>;
}

/** The span's sales value beside the money received, bucket by bucket. */
function TrendPanel({ data, className }) {
  const unit = data.trend.unit;
  return (
    <Panel
      icon={BarChart3}
      title="Sales & Collections"
      subtitle={`Sales value and money received, ${UNIT_WORDS[unit]} (IST)`}
      className={className}
    >
      <SalesTrendChart trend={data.trend} totals={{ sales: data.summary.sales_value, collected: data.summary.collected }} />
    </Panel>
  );
}

/** What was sold on the span's dates: new enrollments against additional purchases, and how each is collected. */
function SalesMix({ mix, summary, className }) {
  const total = Number(summary.sales_value);
  const rows = (items, labels, key) =>
    items.map((item) => {
      const share = total > 0 ? (Number(item.value) / total) * 100 : 0;
      return (
        <ShareRow
          key={item[key]}
          label={labels[item[key]]}
          hint={plural(item.count, 'sale')}
          share={share}
          figure={wholeAed(item.value)}
          detail={`${Math.round(share)}%`}
          ariaLabel={`${labels[item[key]]}: ${plural(item.count, 'sale')}, ${wholeAed(item.value)}, ${Math.round(share)}% of the sales value`}
        />
      );
    });
  return (
    <Panel icon={PieChart} title="Sales Mix" subtitle="What was sold on these dates, by value" className={className}>
      {summary.sales_count === 0 ? (
        <PanelEmpty icon={PieChart} message="Nothing sold on these dates" hint="Try a longer span of dates." />
      ) : (
        <div className="flex flex-col gap-4">
          <section>
            <SectionHeading>Purchase type</SectionHeading>
            <ul>{rows(mix.kinds, SALE_KINDS, 'kind')}</ul>
          </section>
          <section>
            <SectionHeading>Collection plan</SectionHeading>
            <ul>{rows(mix.plans, COLLECTION_PLANS, 'plan')}</ul>
          </section>
        </div>
      )}
    </Panel>
  );
}

/** How far the leads that came in on the span's dates have gone, stage by stage. */
function ConversionFunnel({ funnel, range, className }) {
  const leads = funnel[0].count;
  return (
    <Panel
      icon={Funnel}
      title="Lead to Enrollment"
      subtitle={`Where the ${plural(leads, 'lead')} from these dates have reached`}
      actionTo={leadsPath(range)}
      className={className}
    >
      {leads === 0 ? (
        <PanelEmpty icon={Funnel} message="No leads came in on these dates" hint="Try a longer span of dates." />
      ) : (
        <ol aria-label="Leads by stage reached">
          {funnel.map((stage) => {
            const share = percent(stage.count, leads);
            const to = stage.stage === 'LEADS' ? leadsPath(range) : stage.stage === 'ENROLLED' ? leadsPath(range, 'ENROLLED') : null;
            return (
              <ShareRow
                key={stage.stage}
                label={stage.label}
                hint={FUNNEL_HINTS[stage.stage]}
                share={share}
                figure={stage.count}
                detail={`${share}%`}
                to={to}
                ariaLabel={`${stage.label}: ${plural(stage.count, 'lead')}, ${share}% of the leads${to ? '. Open them on the Leads page.' : ''}`}
              />
            );
          })}
        </ol>
      )}
    </Panel>
  );
}

/** What was received on the span's dates, by what each payment was for and how it was paid. */
function Collections({ collections, summary, className }) {
  const total = Number(summary.collected);
  const rows = (items, label, key) =>
    items
      .filter((item) => item.count > 0)
      .map((item) => {
        const share = total > 0 ? (Number(item.amount) / total) * 100 : 0;
        return (
          <ShareRow
            key={item[key]}
            label={label(item)}
            hint={plural(item.count, 'payment')}
            share={share}
            figure={wholeAed(item.amount)}
            detail={`${Math.round(share)}%`}
            ariaLabel={`${label(item)}: ${plural(item.count, 'payment')}, ${wholeAed(item.amount)}`}
          />
        );
      });
  return (
    <Panel icon={Wallet} title="Collections" subtitle="Money received on these dates" className={className}>
      {summary.payments === 0 ? (
        <PanelEmpty icon={Wallet} message="Nothing received on these dates" hint="Payments appear here once Stripe or a receipt confirms them." />
      ) : (
        <div className="flex flex-col gap-4">
          <section>
            <SectionHeading>By payment type</SectionHeading>
            <ul>{rows(collections.types, (item) => PAYMENT_TYPES[item.type], 'type')}</ul>
          </section>
          <section>
            <SectionHeading>By method</SectionHeading>
            <ul>{rows(collections.methods, (item) => item.label, 'method')}</ul>
          </section>
        </div>
      )}
    </Panel>
  );
}

const bdeColumns = [
  { key: 'name', header: 'BDE', className: 'font-medium', cell: (row) => row.full_name },
  { key: 'leads', header: 'Leads', className: 'tabular-nums', cell: (row) => row.leads },
  {
    key: 'conversion',
    header: 'Conversion',
    className: 'tabular-nums whitespace-nowrap',
    cell: (row) => (
      <>
        {percent(row.enrolled_leads, row.leads)}%<span className="text-muted-foreground text-xs"> · {row.enrolled_leads}/{row.leads}</span>
      </>
    ),
  },
  { key: 'enrollments', header: 'Enrollments', className: 'tabular-nums', cell: (row) => row.enrollments },
  { key: 'sales', header: 'Sales value', className: 'tabular-nums whitespace-nowrap', cell: (row) => wholeAed(row.sales_value) },
  { key: 'collected', header: 'Collected', className: 'tabular-nums whitespace-nowrap', cell: (row) => wholeAed(row.collected) },
];

function BdeCard({ row }) {
  return (
    <article className="rounded-lg border p-3">
      <div className="flex items-baseline justify-between gap-2">
        <p className="min-w-0 text-sm font-medium break-words">{row.full_name}</p>
        <p className="text-sm font-semibold tabular-nums">{wholeAed(row.sales_value)}</p>
      </div>
      <p className="text-muted-foreground mt-1 text-xs">
        {plural(row.leads, 'lead')} · {percent(row.enrolled_leads, row.leads)}% converted · {plural(row.enrollments, 'enrollment')} ·{' '}
        {wholeAed(row.collected)} collected
      </p>
    </article>
  );
}

/**
 * Each BDE's share. Leads and conversion follow the leads that came in on the
 * span's dates; enrollments, sales value and collections what happened on
 * those dates, on the BDE's first sales (additional purchases are a mentor's).
 */
function BdePerformance({ rows, unassigned }) {
  return (
    <Panel
      icon={Users}
      title="BDE Performance"
      subtitle="Leads and conversion: the leads from these dates · enrollments, sales and collections: on these dates"
    >
      {rows.length === 0 ? (
        <PanelEmpty icon={Users} message="No BDE has leads or sales yet" />
      ) : (
        <ResponsiveList label="BDE performance" columns={bdeColumns} rows={rows} minTableWidth={640} renderCard={(row) => <BdeCard row={row} />} />
      )}
      {unassigned > 0 ? (
        <p className="text-muted-foreground mt-3 text-xs">
          {plural(unassigned, 'lead')} from these dates {unassigned === 1 ? 'has' : 'have'} no BDE yet.{' '}
          <Link to="/leads?owner=unassigned" className="text-link underline-offset-4 hover:underline">
            Assign them
          </Link>
        </p>
      ) : null}
    </Panel>
  );
}

function StatusBadge({ status }) {
  const shown = PURCHASE_STATUSES[status] ?? { label: status, variant: 'outline' };
  return (
    <Badge variant={shown.variant} className="whitespace-nowrap">
      {shown.label}
    </Badge>
  );
}

function StudentLink({ student, fallback }) {
  if (!student) return <span>{fallback || 'Not enrolled yet'}</span>;
  return (
    <Link to={studentFinancePath(student.id)} className="hover:underline">
      {student.full_name}
    </Link>
  );
}

const outstandingColumns = [
  {
    key: 'student',
    header: 'Student',
    cell: (row) => (
      <>
        <p className="font-medium">
          <StudentLink student={row.student} />
        </p>
        <p className="text-muted-foreground text-xs">{row.student?.student_code}</p>
      </>
    ),
  },
  {
    key: 'purchase',
    header: 'Purchase',
    cell: (row) => (
      <>
        <p>{row.syllabus}</p>
        <p className="text-muted-foreground text-xs">
          {row.reference} · {PURCHASE_KINDS[row.kind]} · {COLLECTION_PLANS[row.plan]}
        </p>
      </>
    ),
  },
  {
    key: 'paid',
    header: 'Paid',
    className: 'tabular-nums whitespace-nowrap',
    cell: (row) => (
      <>
        {wholeAed(row.paid_amount)}
        <span className="text-muted-foreground text-xs"> of {wholeAed(row.package_amount)}</span>
      </>
    ),
  },
  { key: 'outstanding', header: 'Outstanding', className: 'font-semibold tabular-nums whitespace-nowrap', cell: (row) => wholeAed(row.outstanding_amount) },
  { key: 'status', header: 'Status', cell: (row) => <StatusBadge status={row.payment_status} /> },
];

function OutstandingCard({ row }) {
  return (
    <article className="rounded-lg border p-3">
      <div className="flex items-start justify-between gap-2">
        {/* Wrapping, not truncated: a card grid is as wide as its longest unbroken line. */}
        <div className="min-w-0 break-words">
          <p className="text-sm font-medium">
            <StudentLink student={row.student} />
          </p>
          <p className="text-muted-foreground text-xs">
            {row.reference} · {row.syllabus} · {COLLECTION_PLANS[row.plan]}
          </p>
        </div>
        <StatusBadge status={row.payment_status} />
      </div>
      <p className="mt-2 text-sm tabular-nums">
        <span className="font-semibold">{wholeAed(row.outstanding_amount)}</span>
        <span className="text-muted-foreground text-xs">
          {' '}
          outstanding · {wholeAed(row.paid_amount)} of {wholeAed(row.package_amount)} paid
        </span>
      </p>
    </article>
  );
}

/** The balances still to be received, whatever the dates: by status, then the largest, each opening its student's Finance tab. */
function OutstandingBalances({ outstanding }) {
  const shown = outstanding.rows.length;
  return (
    <Panel
      icon={CircleDollarSign}
      title="Outstanding Balances"
      subtitle={shown < outstanding.count ? `The largest ${shown} of ${outstanding.count} · as things stand` : 'As things stand now'}
      action={
        <Badge variant="secondary" className="tabular-nums">
          {wholeAed(outstanding.total)}
        </Badge>
      }
    >
      {outstanding.count === 0 ? (
        <PanelEmpty icon={CircleDollarSign} message="No balance outstanding" hint="Every purchase is fully paid." />
      ) : (
        <div className="flex flex-col gap-4">
          <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            {outstanding.by_status.map((part) => (
              <div key={part.status} className="bg-muted/40 rounded-lg px-3 py-2">
                <dt className="text-muted-foreground truncate text-xs">{PURCHASE_STATUSES[part.status]?.label ?? part.status}</dt>
                <dd className="text-sm font-semibold tabular-nums">{wholeAed(part.amount)}</dd>
                <dd className="text-muted-foreground text-xs">{plural(part.count, 'purchase')}</dd>
              </div>
            ))}
          </dl>
          <ResponsiveList
            label="Outstanding balances"
            columns={outstandingColumns}
            rows={outstanding.rows}
            rowKey={(row) => row.sale_id}
            minTableWidth={760}
            renderCard={(row) => <OutstandingCard row={row} />}
          />
        </div>
      )}
    </Panel>
  );
}

function Figure({ label, value, hint }) {
  return (
    <div className="bg-muted/40 rounded-lg px-3 py-2">
      <dt className="text-muted-foreground truncate text-xs">{label}</dt>
      <dd className="text-sm font-semibold tabular-nums">{value}</dd>
      {hint ? <dd className="text-muted-foreground truncate text-xs">{hint}</dd> : null}
    </div>
  );
}

/** Every AutoPay agreement by state, what AutoPay collected on the span's dates, what falls due next, and those needing attention. */
function AutopayPanel({ autopay, className }) {
  const { counts } = autopay;
  return (
    <Panel icon={Repeat} title="AutoPay" subtitle="Agreements as they stand · collected on these dates" className={className}>
      <div className="flex flex-col gap-4">
        <dl className="grid grid-cols-2 gap-2">
          <Figure label="Active" value={counts.ACTIVE} hint={counts.SETTING_UP ? `${counts.SETTING_UP} setting up` : null} />
          <Figure label="Completed · Cancelled" value={`${counts.COMPLETED} · ${counts.CANCELLED}`} />
          <Figure label="Collected" value={wholeAed(autopay.collected.amount)} hint={plural(autopay.collected.count, 'installment')} />
          <Figure
            label={`Due in ${autopay.due.days} days`}
            value={wholeAed(autopay.due.amount)}
            hint={plural(autopay.due.count, 'installment')}
          />
        </dl>
        <section>
          <SectionHeading>Needs attention</SectionHeading>
          {autopay.attention.length === 0 ? (
            <p className="text-muted-foreground py-2 text-sm">No agreement needs attention.</p>
          ) : (
            <ScrollList total={autopay.attention.length} maxRows={4} className="divide-y">
              {autopay.attention.map((row) => {
                const status = autopayStatus(row);
                return (
                  <li key={row.id} className="flex items-center gap-3 py-2">
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium">
                        <StudentLink student={row.student} />
                      </p>
                      <p className="text-muted-foreground truncate text-xs">
                        {row.reference} · {wholeAed(row.remaining_amount)} remaining
                      </p>
                    </div>
                    <Badge variant={status.variant} className={cn('whitespace-nowrap', status.className)}>
                      {status.label}
                    </Badge>
                  </li>
                );
              })}
            </ScrollList>
          )}
        </section>
      </div>
    </Panel>
  );
}

function ActionRow({ icon: Icon, label, detail, count }) {
  return (
    <li className="flex items-center gap-3 py-2.5">
      <span
        className={cn(
          'flex size-7 shrink-0 items-center justify-center rounded-md',
          count > 0 ? 'bg-warning/10 text-warning' : 'bg-muted text-muted-foreground'
        )}
      >
        <Icon className="size-3.5" aria-hidden="true" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm">{label}</span>
        {detail ? <span className="text-muted-foreground block truncate text-xs">{detail}</span> : null}
      </span>
      <span className={cn('shrink-0 text-sm font-semibold tabular-nums', count > 0 ? 'text-foreground' : 'text-muted-foreground')}>
        {count}
      </span>
    </li>
  );
}

/** What awaits an administrator now, whatever the dates. */
function PendingActions({ pending, autopay, className }) {
  const links = pending.links;
  return (
    <Panel icon={ListTodo} title="Needs Attention" subtitle="As things stand now" className={className}>
      <ul className="divide-y">
        <ActionRow
          icon={Link2}
          label="Payment links awaiting the parent"
          detail={links.count > 0 ? `${wholeAed(links.amount)} · ${links.before_enrollment} before enrollment` : null}
          count={links.count}
        />
        <ActionRow icon={Repeat} label="AutoPay agreements needing attention" count={autopay.attention.length} />
        <ActionRow icon={ShieldAlert} label="Stripe activity not matched to a sale" count={pending.stripe_review} />
        <ActionRow icon={AlertTriangle} label="Open payment disputes" count={pending.disputes} />
      </ul>
    </Panel>
  );
}

/** The latest payments received, whatever the dates, each opening its student's Finance tab. */
function RecentPayments({ rows, className }) {
  return (
    <Panel icon={HandCoins} title="Recent Payments" subtitle="The latest money received" className={className}>
      {rows.length === 0 ? (
        <PanelEmpty icon={HandCoins} message="No payment received yet" />
      ) : (
        <ScrollList total={rows.length} className="divide-y">
          {rows.map((row) => (
            <li key={row.id} className="flex items-center gap-3 py-2.5 first:pt-0 last:pb-0">
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium">
                  <StudentLink student={row.student} fallback={row.student_name} />
                </p>
                <p className="text-muted-foreground truncate text-xs">
                  {PAYMENT_TYPES[row.payment_type]} · {row.method_label} · {shortDate(row.payment_date)}
                </p>
              </div>
              <span className="shrink-0 text-sm font-semibold tabular-nums">{wholeAed(row.amount)}</span>
              {row.student ? <ChevronRight className="text-muted-foreground size-4 shrink-0" aria-hidden="true" /> : null}
            </li>
          ))}
        </ScrollList>
      )}
    </Panel>
  );
}

/**
 * The Sales Dashboard, for administrators: Eduport Plus sales and collections
 * across every student enrolled through its payments. Over the dates picked
 * (this month unless chosen otherwise, kept in the URL) what was sold and
 * received, how it was sold and collected, how far the leads converted and
 * each BDE's share; then, as things stand now, the outstanding balances,
 * AutoPay, what awaits action and the latest payments -- all from one request
 * (GET /api/sales/dashboard/), with the Finance tab's own figures.
 */
export default function SalesDashboardPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const range = readSalesRange(searchParams);
  const { from, to } = range;
  const [data, setData] = useState(null);
  const [failure, setFailure] = useState(null);
  const [pending, setPending] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let active = true;
    setPending(true);
    api
      .get(SALES_DASHBOARD_URL, { params: { from, to } })
      .then((response) => {
        if (!active) return;
        setData(response.data);
        setFailure(null);
      })
      .catch((err) => {
        if (active) setFailure(enquiryError(err, 'Could not load the sales dashboard.'));
      })
      .finally(() => {
        if (active) setPending(false);
      });
    return () => {
      active = false;
    };
  }, [from, to, reloadKey]);

  const changeRange = (updates) => {
    const params = new URLSearchParams(searchParams);
    for (const [key, value] of Object.entries(updates)) {
      if (value) params.set(key, value);
      else params.delete(key);
    }
    setSearchParams(params, { replace: true });
  };
  const reload = () => setReloadKey((key) => key + 1);

  let content;
  if (failure && !data && failure.status === 403) {
    content = <AccessDeniedState title="You don't have access to the sales dashboard." message={failure.message} />;
  } else if (failure && !data) {
    content = <ErrorState message={failure.message} onRetry={reload} pending={pending} />;
  } else if (!data) {
    content = <DashboardSkeleton />;
  } else {
    content = (
      <div className={cn('flex flex-col gap-4', pending && 'opacity-70 transition-opacity')} aria-busy={pending || undefined}>
        {failure ? <ErrorState message={failure.message} onRetry={reload} pending={pending} /> : null}
        <KpiTiles summary={data.summary} range={range} />
        <div className="grid min-w-0 gap-4 xl:grid-cols-5 xl:items-start">
          <TrendPanel data={data} className="xl:col-span-3" />
          <SalesMix mix={data.mix} summary={data.summary} className="xl:col-span-2" />
        </div>
        <div className="grid min-w-0 gap-4 xl:grid-cols-5 xl:items-start">
          <ConversionFunnel funnel={data.funnel} range={range} className="xl:col-span-3" />
          <Collections collections={data.collections} summary={data.summary} className="xl:col-span-2" />
        </div>
        <BdePerformance rows={data.bdes} unassigned={data.summary.unassigned_leads} />
        <OutstandingBalances outstanding={data.outstanding} />
        <div className="grid min-w-0 gap-4 lg:grid-cols-2 lg:items-start xl:grid-cols-3">
          <AutopayPanel autopay={data.autopay} />
          <RecentPayments rows={data.recent_payments} />
          <PendingActions pending={data.pending} autopay={data.autopay} className="lg:col-span-2 xl:col-span-1" />
        </div>
      </div>
    );
  }

  return (
    <Page>
      <PageHeader
        title="Sales Dashboard"
        description="Sales, collections and balances across every student enrolled through Eduport Plus payments."
        actionsClassName="w-full sm:w-auto"
        actions={
          <div className="flex w-full items-start gap-2">
            <RangeFilter range={range} onChange={changeRange} />
            <Button variant="ghost" size="icon" onClick={reload} disabled={pending} aria-label="Refresh">
              <RefreshCwIcon />
            </Button>
          </div>
        }
      />
      {content}
    </Page>
  );
}
