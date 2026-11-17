import { useId, useState } from 'react';
import { ChevronDownIcon, ReceiptTextIcon } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { ResponsiveList } from '@/components/page/responsive-list';
import { WorkspaceCard } from '@/components/bookings/redemo-workspace/parts';
import { PURCHASE_KINDS, autopayStatus, failureReason, scheduleStatus, wholeAed } from '@/lib/payments';
import { cn } from '@/lib/utils';

function when(value, zone) {
  return value ? new Intl.DateTimeFormat('en-GB', { dateStyle: 'medium', timeStyle: 'short', timeZone: zone }).format(new Date(value)) : 'Initial Checkout';
}

export function AutopaySummary({ agreement, action = null }) {
  if (!agreement) return null;
  const initial = agreement.installments.find((row) => row.position === 0);
  const billing = agreement.collection_engine === 'STRIPE_BILLING';
  return <WorkspaceCard title="Autopay" action={<Badge variant={agreement.attention_status ? 'warning' : agreement.status === 'ACTIVE' || agreement.status === 'COMPLETED' ? 'success' : 'outline'}>{(agreement.attention_status || agreement.status).replaceAll('_', ' ')}</Badge>}>
    <dl className="grid gap-3 text-sm sm:grid-cols-2 xl:grid-cols-4">
      {[
        ['Created by', `${agreement.creator.name} · ${agreement.creator.role}`], ['Source', agreement.source.replaceAll('_', ' ')],
        ['Package amount', wholeAed(agreement.package_amount)], ['Initial payment', `${wholeAed(initial?.amount)} · ${initial?.classes ?? '—'} classes · ${initial?.status ?? '—'}`],
        ['Remaining balance', wholeAed(agreement.remaining_amount)], ['Next scheduled collection', agreement.next_collection_at ? when(agreement.next_collection_at, agreement.billing_timezone) : 'None scheduled'],
        ['Payment method', agreement.card_last4 ? `${agreement.card_brand} ···· ${agreement.card_last4}` : agreement.setup_status.replaceAll('_', ' ')],
        ['Billing timezone', agreement.billing_timezone],
        ...(billing ? [['Billing engine', 'Stripe Billing'], ['Provisioning', agreement.billing_status.replaceAll('_', ' ')],
          ['Subscription status', agreement.stripe_subscription_status || 'Awaiting scheduled start'],
          ['Next Stripe recovery attempt', agreement.next_retry_at ? when(agreement.next_retry_at, agreement.billing_timezone) : 'Not scheduled by Stripe']] : []),
      ].map(([label, value]) => <div key={label} className="min-w-0"><dt className="text-muted-foreground">{label}</dt><dd className="mt-1 break-words font-medium">{value}</dd></div>)}
    </dl>
    {agreement.setup_message ? <p role="status" className="text-sm">{agreement.setup_message}</p> : null}
    {billing && agreement.billing_message ? <p role="status" className="text-sm">{agreement.billing_message}</p> : null}
    {agreement.cancelled_at ? <p role="status" className="text-sm">Cancelled {when(agreement.cancelled_at, agreement.billing_timezone)} · {agreement.cancellation_source === 'PARENT_REQUEST' ? 'at the parent’s request' : agreement.cancellation_source === 'STRIPE' ? 'stopped in Stripe' : 'by an administrator'}{agreement.cancelled_by ? ` (${agreement.cancelled_by})` : ''}{agreement.cancellation_reason ? `: ${agreement.cancellation_reason}` : ''}</p> : null}
    <p className="text-muted-foreground text-xs">{billing ? 'Stripe Billing manages recurring invoices and payment recovery using the account’s recovery settings. Outstanding installments stay separate; only verified payments credit classes.' : 'Historical PaymentIntent agreement. An unpaid installment blocks later collections until this agreement is explicitly migrated to Stripe Billing.'}</p>
    <ol className="divide-y rounded-md border px-3" aria-label="Autopay installments">
      {agreement.installments.map((row) => <li key={row.id} className="min-w-0 py-3 text-sm">
        <div className="flex flex-wrap items-center justify-between gap-2"><strong>{row.position === 0 ? 'Initial payment' : `Installment ${row.position}`} · {row.classes} classes · {wholeAed(row.amount)}</strong><Badge variant={row.status === 'PAID' ? 'success' : row.status === 'FAILED' || row.status === 'REQUIRES_CUSTOMER_ACTION' ? 'warning' : 'outline'}>{row.status.replaceAll('_', ' ')}</Badge></div>
        <p className="text-muted-foreground mt-1">{when(row.due_at, agreement.billing_timezone)}</p>
        {row.stripe_invoice_id ? <div className="mt-2 space-y-1 text-xs"><p className="break-all">Invoice {row.stripe_invoice_number || row.stripe_invoice_id} · {row.stripe_invoice_status}</p>{row.next_payment_attempt ? <p>Stripe recovery: {when(row.next_payment_attempt, agreement.billing_timezone)}</p> : null}{row.stripe_invoice_url ? <a href={row.stripe_invoice_url} target="_blank" rel="noopener noreferrer" className="text-primary underline">View Stripe invoice / parent payment page</a> : null}</div> : null}
        {row.attempts.length ? <details className="mt-2"><summary className="cursor-pointer">Collection attempts ({row.attempts.length})</summary><ul className="mt-2 space-y-2">{row.attempts.map((attempt) => <li key={attempt.id} className="break-all text-xs">Attempt {attempt.number} · {attempt.status.replaceAll('_', ' ')} · {when(attempt.created_at, agreement.billing_timezone)}{attempt.error_code ? ` · ${attempt.error_code}` : ''}{attempt.stripe_payment_intent_id ? <span className="block font-mono">{attempt.stripe_payment_intent_id}</span> : null}{attempt.stripe_charge_id ? <span className="block font-mono">{attempt.stripe_charge_id}</span> : null}{attempt.stripe_checkout_id ? <span className="block font-mono">{attempt.stripe_checkout_id}</span> : null}{attempt.action_url ? <a href={attempt.action_url} target="_blank" rel="noopener noreferrer" className="text-primary mt-1 block underline">Parent authentication link</a> : null}</li>)}</ul></details> : null}
      </li>)}
    </ol>
    <p className="text-muted-foreground break-all font-mono text-xs">{agreement.stripe_customer_id} {agreement.stripe_payment_method_id ? `· ${agreement.stripe_payment_method_id}` : ''}</p>
    {billing ? <p className="text-muted-foreground break-all font-mono text-xs">{agreement.stripe_subscription_id || 'Subscription not started'} · {agreement.stripe_schedule_id || 'Schedule not provisioned'}{agreement.stripe_schedule_status ? ` · ${agreement.stripe_schedule_status}` : ''}</p> : null}
    {action && !agreement.cancelled_at && agreement.status !== 'COMPLETED' ? action : null}
  </WorkspaceCard>;
}

/**
 * An Autopay agreement at a glance (sales.student_finance autopay_brief): its
 * purchase, status, progress and next collection. Managing it is the AutoPay tab's.
 */
export function AutopayBrief({ agreement }) {
  const attention = agreement.attention_status;
  const status = (attention || agreement.status).replaceAll('_', ' ').toLowerCase();
  return <div className="flex flex-wrap items-start justify-between gap-3 rounded-lg border p-3 text-sm">
    <div className="min-w-0">
      <p className="font-medium">{agreement.reference} · {agreement.installments_paid} of {agreement.installments_total} payments made</p>
      <p className="text-muted-foreground text-xs">
        {agreement.cancelled_at ? `Cancelled ${when(agreement.cancelled_at, agreement.billing_timezone)}`
          : agreement.next_collection_at ? `Next collection ${when(agreement.next_collection_at, agreement.billing_timezone)}` : 'No collection scheduled'}
        {' · '}{wholeAed(agreement.remaining_amount)} remaining{agreement.card_last4 ? ` · ${agreement.card_brand} ···· ${agreement.card_last4}` : ''}
      </p>
    </div>
    <Badge variant={attention ? 'warning' : agreement.status === 'ACTIVE' || agreement.status === 'COMPLETED' ? 'success' : 'outline'} className="capitalize">{status}</Badge>
  </div>;
}

// The Finance tab's dates, in the agreement's billing timezone: the one its collections are scheduled in.
const onDay = (value, zone, time = false) => new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric', year: 'numeric',
  ...(time ? { hour: 'numeric', minute: '2-digit', timeZoneName: 'short' } : {}), timeZone: zone }).format(new Date(value));
const paymentName = (row) => (row.position ? `EMI ${row.position}` : 'First payment');

function Figure({ label, value, hint }) {
  return <div className="min-w-0">
    <dt className="text-muted-foreground text-xs">{label}</dt>
    <dd className="mt-0.5 font-medium tabular-nums">{value}{hint ? <span className="text-muted-foreground block text-xs font-normal">{hint}</span> : null}</dd>
  </div>;
}

function ScheduleBadge({ row }) {
  const status = scheduleStatus(row);
  return <Badge variant={status.variant} className={status.className}>{status.label}</Badge>;
}

function DueDate({ row, zone }) {
  return <span title={row.due_at ? onDay(row.due_at, zone, true) : undefined}>{row.due_at ? onDay(row.due_at, zone) : 'At checkout'}
    {row.paid_at ? <span className="text-muted-foreground block text-xs">Paid {onDay(row.paid_at, zone)}</span> : null}</span>;
}

function Invoice({ row, label = null }) {
  if (!row.invoice_url) return '—';
  return <Button variant="outline" size={label ? 'sm' : 'icon'} asChild>
    <a href={row.invoice_url} target="_blank" rel="noopener noreferrer" aria-label={row.reference ? `Open invoice ${row.reference} in a new tab` : 'Open invoice in a new tab'}>
      <ReceiptTextIcon />{label}</a>
  </Button>;
}

/**
 * One AutoPay agreement in the Finance tab: its purchase and status, and
 * opened, its figures and the frozen schedule -- the first payment, then each
 * EMI with its status, why it failed, and the paid invoice as its receipt.
 * Read-only; every figure is the API's (sales.student_finance autopay_brief).
 */
export function AutopayAgreement({ agreement }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const status = autopayStatus(agreement);
  const zone = agreement.billing_timezone;
  const short = agreement.id.slice(0, 8);
  const schedule = agreement.schedule;
  const first = schedule.find((row) => row.position === 0);
  const emis = schedule.filter((row) => row.position > 0).map((row) => Number(row.amount));
  const low = Math.min(...emis), high = Math.max(...emis);
  const cancelled = schedule.filter((row) => row.status === 'CANCELLED').length;
  const remaining = schedule.filter((row) => !['PAID', 'CANCELLED'].includes(row.status)).length;
  const total = Number(agreement.package_amount);
  const percent = total > 0 ? Math.floor((100 * Number(agreement.paid_amount)) / total) : 0;
  const next = agreement.cancelled_at ? `Cancelled ${onDay(agreement.cancelled_at, zone)}`
    : agreement.status === 'COMPLETED' ? 'None, fully paid'
      : agreement.next_collection_at ? onDay(agreement.next_collection_at, zone, true) : 'None scheduled';
  // A table nested in the agreement: tighter cells than a page's, so its seven columns fit beside the balance card.
  const columns = [
    { key: 'number', header: 'No.', cell: (row) => row.position + 1 },
    { key: 'type', header: 'Payment type', cell: (row) => <span>{paymentName(row)}<span className="text-muted-foreground block text-xs">{row.classes} classes</span></span> },
    { key: 'amount', header: 'Amount', cell: (row) => wholeAed(row.amount) },
    { key: 'due', header: 'Due date', cell: (row) => <DueDate row={row} zone={zone} /> },
    { key: 'status', header: 'Status', className: 'whitespace-normal', cell: (row) => <span className="flex max-w-28 flex-col items-start gap-1"><ScheduleBadge row={row} />
      {failureReason(row) ? <span className="text-destructive text-xs">{failureReason(row)}</span> : null}</span> },
    { key: 'method', header: 'Method / reference', className: 'whitespace-normal', cell: (row) => <span className="block max-w-36">{row.method_label ?? '—'}
      {row.reference ? <span className="text-muted-foreground block truncate text-xs" title={row.reference}>{row.reference}</span> : null}</span> },
    { key: 'receipt', header: 'Receipt', cell: (row) => <Invoice row={row} /> },
  ].map((column) => ({ ...column, className: cn('px-2 first:pl-3 last:pr-3', column.className), headerClassName: 'px-2 first:pl-3 last:pr-3' }));
  return <li className="min-w-0 rounded-lg border">
    <h3>
      <button type="button" id={`${id}-button`} aria-expanded={open} aria-controls={`${id}-panel`} onClick={() => setOpen((value) => !value)}
        className="hover:bg-muted/50 focus-visible:ring-ring/50 flex w-full flex-wrap items-center gap-x-3 gap-y-1.5 rounded-lg px-4 py-3 text-left text-sm outline-none focus-visible:ring-[3px]">
        <span className="font-medium max-sm:flex-1"><span className="text-muted-foreground font-normal">Agreement </span><span className="font-mono" title={agreement.id}>{short}</span></span>
        {/* A phone gives the purchase its own line under the agreement and its status. */}
        <span className="flex items-center gap-3 max-sm:order-last max-sm:basis-full">
          <Badge variant={agreement.purchase_kind === 'ADDITIONAL' ? 'secondary' : 'outline'}>{PURCHASE_KINDS[agreement.purchase_kind] ?? agreement.purchase_kind}</Badge>
          <span className="text-muted-foreground">{agreement.reference}</span>
        </span>
        <span className="ml-auto flex shrink-0 items-center gap-2">
          <Badge variant={status.variant} className={status.className}>{status.label}</Badge>
          <ChevronDownIcon className={cn('text-muted-foreground size-4 transition-transform', open && 'rotate-180')} aria-hidden="true" />
        </span>
      </button>
    </h3>
    {open ? <div id={`${id}-panel`} role="region" aria-labelledby={`${id}-button`} className="flex min-w-0 flex-col gap-4 border-t px-4 py-4">
      <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm sm:grid-cols-4">
        <Figure label="Total agreement amount" value={wholeAed(agreement.package_amount)} />
        <Figure label="Installment amount" value={!emis.length ? '—' : low === high ? wholeAed(low) : `${wholeAed(low)} – ${wholeAed(high)}`}
          hint={first ? `First payment ${wholeAed(first.amount)}` : null} />
        <Figure label="Total installments" value={schedule.length} hint={`First payment + ${emis.length} EMI${emis.length === 1 ? '' : 's'}`} />
        <Figure label="Paid installments" value={agreement.installments_paid} />
        <Figure label="Remaining installments" value={remaining} hint={cancelled ? `${cancelled} cancelled` : null} />
        <Figure label="Next collection" value={next} />
        <Figure label="Remaining amount" value={wholeAed(agreement.remaining_amount)} />
        <Figure label="Card" value={agreement.card_last4 ? `${agreement.card_brand.replace(/^./, (first) => first.toUpperCase())} ···· ${agreement.card_last4}` : 'Not saved yet'} />
      </dl>
      <div>
        <div className="flex flex-wrap justify-between gap-2 text-xs">
          <span className="text-muted-foreground">Payment progress</span>
          <span className="font-medium tabular-nums">{wholeAed(agreement.paid_amount)} of {wholeAed(agreement.package_amount)} paid · {percent}%</span>
        </div>
        <div role="progressbar" aria-label="Payment progress" aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent}
          className="bg-muted mt-1.5 h-2 overflow-hidden rounded-full">
          <div className="bg-success h-full rounded-full" style={{ width: `${percent}%` }} />
        </div>
      </div>
      <div className="flex min-w-0 flex-col gap-2">
        <h4 className="text-sm font-semibold">EMI schedule</h4>
        <ResponsiveList label={`EMI schedule of agreement ${short}`} columns={columns} rows={schedule} minTableWidth={640}
          renderCard={(row) => <article className="flex flex-col gap-1.5 rounded-lg border p-3 text-sm">
            <div className="flex flex-wrap items-start justify-between gap-2"><strong>{row.position + 1}. {paymentName(row)} · {wholeAed(row.amount)}</strong><ScheduleBadge row={row} /></div>
            {failureReason(row) ? <p className="text-destructive">{failureReason(row)}</p> : null}
            <p className="text-muted-foreground">{row.classes} classes · {row.due_at ? 'Due ' : ''}<DueDate row={row} zone={zone} /></p>
            {row.method_label ? <p className="text-muted-foreground break-all">{row.method_label}{row.reference ? ` · ${row.reference}` : ''}</p> : null}
            {row.invoice_url ? <div><Invoice row={row} label="Invoice" /></div> : null}
          </article>} />
      </div>
      <p className="text-muted-foreground text-xs">Agreement ID <span className="font-mono break-all">{agreement.id}</span> · dates in {zone}. A paid installment’s Stripe invoice is its receipt.</p>
    </div> : null}
  </li>;
}
