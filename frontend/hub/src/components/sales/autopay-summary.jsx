import { Badge } from '@/components/ui/badge';
import { WorkspaceCard } from '@/components/bookings/redemo-workspace/parts';
import { wholeAed } from '@/lib/payments';

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
