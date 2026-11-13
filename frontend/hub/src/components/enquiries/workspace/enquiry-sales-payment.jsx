import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { CopyIcon, DownloadIcon, MessageCircleIcon, RefreshCwIcon, WalletIcon } from 'lucide-react';

import api from '@/lib/api';
import { can, PERMISSIONS } from '@/lib/access';
import { whatsAppUrl } from '@/lib/enquiries';
import { quotePlanLabel, salesError, quoteCollectionLabel } from '@/lib/sales';
import { collectionCompatibility, collectPaymentUrl, expirePaymentUrl, initialStudentSaleUrl, PAYMENT_METHODS, paymentToday, saleAmountUrl, saleUrl, wholeAed } from '@/lib/payments';
import { useLinkCopy } from '@/hooks/use-link-copy';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Skeleton } from '@/components/ui/skeleton';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { ErrorState, Notice } from '@/components/page/states';
import { Field, WorkspaceCard } from '@/components/bookings/redemo-workspace/parts';
import { QuoteChapters, QuoteStatusBadge } from '@/components/sales/quote-parts';
import { useSyllabusPdf } from '@/components/sales/syllabus-pdf';
import { CollectionReplacementDialog } from '@/components/sales/collection-replacement-dialog';
import { AutopayBuilder } from './autopay-builder';
import { AutopaySummary } from '@/components/sales/autopay-summary';
import { CancelAutopay, FamilyAndContact, StudentAccountCard } from '@/components/sales/student-account';
import { FormDialog } from '@/components/form-dialog';
import { ResponsiveList } from '@/components/page/responsive-list';

export function SaleFields({ rows }) {
  return <dl className="grid gap-x-6 gap-y-4 sm:grid-cols-2 xl:grid-cols-4">{rows.map(([label, value]) => <Field key={label} label={label} className="grid-cols-1 gap-1 py-0">{value}</Field>)}</dl>;
}

export function QuoteSummary({ quote }) {
  return (
    <WorkspaceCard icon={WalletIcon} title="Selected quote" action={<QuoteStatusBadge status={quote.status} />}>
      <SaleFields rows={[
        ['Syllabus', quote.syllabus.title], ['Plan', quotePlanLabel(quote)], ['Collection intention', quote.collection_intention_confirmed === false ? 'Not recorded (historical quote)' : quoteCollectionLabel(quote.collection_mode)], ['Purchased classes', quote.classes],
        ['Quote', `${quote.reference} · Revision ${quote.revision}`], ['Original price', wholeAed(quote.collection_subtotal ?? quote.total_fee)],
        ['Discount', wholeAed(quote.collection_discount ?? (Number(quote.total_fee) - Number(quote.collection_amount ?? quote.payable_amount)))],
        ['Agreed package amount', <span className="font-semibold">{wholeAed(quote.collection_amount ?? quote.payable_amount)}</span>],
      ]} />
      <details>
        <summary className="cursor-pointer text-sm font-medium">Selected chapters ({quote.chapters.length})</summary>
        <div className="mt-3"><QuoteChapters quote={quote} /></div>
      </details>
    </WorkspaceCard>
  );
}

function QuoteCompatibilityNotice({ enquiryId, state, issue, tokenSale, onChanged }) {
  const [replacing, setReplacing] = useState(false);
  return <div className="flex flex-col items-start gap-3">
    <p role="alert" className="text-destructive text-sm">{issue.message}</p>
    <Button type="button" size="sm" variant="outline" onClick={() => setReplacing(true)}>Create replacement quote</Button>
    <CollectionReplacementDialog open={replacing} onOpenChange={setReplacing} enquiryId={enquiryId} quote={state.quote} tokenSale={tokenSale} onChanged={onChanged} />
  </div>;
}

function StartSale({ enquiryId, enquiry, state, onChanged }) {
  const [kind, setKind] = useState('NEW');
  const [date, setDate] = useState('');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState(null);
  const candidates = state.family_candidates ?? [];
  const [account, setAccount] = useState(() => ({ family: { mode: 'NEW_FAMILY' }, relationship: 'PARENT', confirm_distinct_child: false,
    billing_contact: { full_name: enquiry?.parent_name ?? '', email: state.parent_email ?? '',
      phone: enquiry?.phone_dial_code && enquiry?.phone_number ? `${enquiry.phone_dial_code}${enquiry.phone_number}` : '' } }));
  const blocked = collectionCompatibility(state, kind);
  const unconfirmed = candidates.length > 0 && !account.confirm_distinct_child;
  const submit = async (event) => {
    event.preventDefault();
    if (blocked || unconfirmed) return;
    setPending(true); setError(null);
    try {
      const choice = account.family.mode === 'EXISTING_FAMILY' ? { family: account.family } : { family: account.family, billing_contact: account.billing_contact };
      const { data } = await api.post(saleUrl(enquiryId), { kind, ...(kind === 'TOKEN' ? { expected_start_date: date } : {}),
        ...choice, relationship: account.relationship, confirm_distinct_child: account.confirm_distinct_child });
      onChanged(data);
    } catch (err) { setError(salesError(err, 'Could not start the sale.').message); }
    finally { setPending(false); }
  };
  return (
    <WorkspaceCard icon={WalletIcon} title="Start the initial sale">
      {blocked ? <QuoteCompatibilityNotice enquiryId={enquiryId} state={state} issue={blocked} tokenSale={kind === 'TOKEN'} onChanged={onChanged} /> : null}
      <form onSubmit={submit} className="flex flex-col gap-4">
        <fieldset className="grid gap-2 sm:grid-cols-2" disabled={pending}>
          <legend className="mb-2 text-sm font-medium">Sale type</legend>
          {[['NEW', 'New Sale', 'Ready to pay for classes.'], ['TOKEN', 'Token Sale', 'Reserve a future start date for AED 100.']].map(([value, title, hint]) => (
            <label key={value} className="flex cursor-pointer items-start gap-3 rounded-lg border p-3 text-sm has-checked:border-primary">
              <input type="radio" name="sale-kind" value={value} checked={kind === value} onChange={() => setKind(value)} className="accent-primary mt-1" />
              <span><span className="block font-medium">{title}</span><span className="text-muted-foreground text-xs">{hint}</span></span>
            </label>
          ))}
        </fieldset>
        {kind === 'TOKEN' ? <div className="flex max-w-sm flex-col gap-1.5"><Label htmlFor="token-start-date">Expected Class Start Date (Token)</Label><Input id="token-start-date" type="date" min={paymentToday()} required value={date} onChange={(event) => setDate(event.target.value)} /></div> : null}
        {kind === 'TOKEN' ? <p className="text-muted-foreground text-sm">The reservation is confirmed after payment. Tuition payment is required before enrollment and class quota.</p> : null}
        <FamilyAndContact candidates={candidates} value={account} onChange={setAccount} />
        {error ? <p role="alert" className="text-destructive text-sm">{error}</p> : null}
        <div><Button disabled={pending || Boolean(blocked) || unconfirmed}>{pending ? 'Starting…' : kind === 'TOKEN' ? 'Start token reservation' : 'Start New Sale'}</Button></div>
      </form>
    </WorkspaceCard>
  );
}

function CollectPayment({ enquiryId, state, onChanged }) {
  const token = state.sale.kind === 'TOKEN' && Number(state.sale.token_paid) === 0;
  const purpose = token ? 'TOKEN' : 'TUITION';
  const mode = state.autopay ? 'AUTOPAY' : state.purchase?.collection_mode ?? state.quote?.collection_mode;
  const [classes, setClasses] = useState(token ? '0' : state.totals.unpaid_classes);
  const [method, setMethod] = useState('STRIPE');
  const [amount, setAmount] = useState('');
  const [preview, setPreview] = useState(null);
  const [calculationError, setCalculationError] = useState(null);
  const [date, setDate] = useState(paymentToday());
  const [proof, setProof] = useState(null);
  const [reference, setReference] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState(null);
  const [replacing, setReplacing] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const requestId = useRef(crypto.randomUUID());
  const enrolled = Boolean(state.sale.student);
  const autopaySelected = !token && !enrolled && state.sale.kind === 'NEW' && mode === 'AUTOPAY';
  const effectiveMode = token ? 'FULL' : autopaySelected ? 'PARTIAL' : mode;
  const direct = method !== 'STRIPE';

  useEffect(() => {
    let active = true;
    setPreview(null); setCalculationError(null);
    if (autopaySelected) return;
    if (!token && !(Number(classes) > 0)) return;
    const timer = setTimeout(() => {
      api.get(saleAmountUrl(enquiryId), { params: { purpose, collection_mode: effectiveMode, classes } })
        .then(({ data }) => { if (active) { setPreview(data); setAmount(data.amount); } })
        .catch((err) => { if (active) setCalculationError(salesError(err, 'Could not calculate this payment.')); });
    }, 200);
    return () => { active = false; clearTimeout(timer); };
  }, [enquiryId, purpose, effectiveMode, classes, token, autopaySelected]);

  const submit = async (event) => {
    event?.preventDefault();
    // A Stripe link is reviewed first: whose account, how much, and which contact Stripe receives.
    if (!direct && !confirming) { setConfirming(true); return; }
    setConfirming(false); setPending(true); setError(null);
    try {
      const body = new FormData();
      for (const [key, value] of Object.entries({ request_id: requestId.current, method, purpose, collection_mode: effectiveMode, classes,
        ...(direct ? { amount, payment_date: date, received_confirmed: confirmed, transaction_reference: reference } : {}) })) body.append(key, String(value));
      if (direct && proof) body.append('proof', proof);
      const { data } = await api.post(collectPaymentUrl(enquiryId), body);
      onChanged(data.state);
    } catch (err) { setError(salesError(err, 'Could not record this payment.').message); }
    finally { setPending(false); }
  };
  return (
    <WorkspaceCard icon={WalletIcon} title={token ? 'Collect token · AED 100' : enrolled ? 'Collect remaining balance' : 'Collect initial tuition'}>
      {!token ? <div className="grid gap-4 sm:grid-cols-2">
        <div className="flex flex-col gap-1.5"><Label>{state.quote?.collection_intention_confirmed === false ? 'Frozen collection terms' : 'Collection intention from quote'}</Label><p className="text-sm font-medium">{quoteCollectionLabel(mode)}</p><p className="text-muted-foreground text-xs">Changing this intention requires an explicit replacement quote.</p>{!state.purchase ? <Button type="button" size="sm" variant="outline" className="self-start" onClick={() => setReplacing(true)}>Change collection intention</Button> : null}</div>
        {!autopaySelected ? <div className="flex flex-col gap-1.5"><Label htmlFor="paid-classes">Classes covered by this payment</Label><Input id="paid-classes" form="initial-payment-form" type="number" step="0.5" min="0.5" max={state.totals.unpaid_classes} value={classes} onChange={(event) => setClasses(event.target.value)} readOnly={mode === 'FULL'} required /></div> : null}
      </div> : null}
      {autopaySelected ? <AutopayBuilder enquiryId={enquiryId} state={state} onChanged={onChanged} onReplacement={() => setReplacing(true)} /> : <form id="initial-payment-form" onSubmit={submit} className="flex flex-col gap-4">
        {calculationError ? <div className="flex flex-col items-start gap-2"><p role="alert" className="text-destructive text-sm">{calculationError.message}</p>{calculationError.code === 'REPLACEMENT_REQUIRED' ? <Button type="button" variant="outline" onClick={() => setReplacing(true)}>Change collection intention</Button> : null}</div> : null}
        <p role="status" className="text-sm">Amount payable: <strong>{preview ? wholeAed(preview.amount) : '—'}</strong>{token ? ' · No classes allocated' : ''}</p>
        <div className="flex max-w-sm flex-col gap-1.5"><Label htmlFor="payment-method">Payment method</Label><Select value={method} onValueChange={setMethod} disabled={pending}><SelectTrigger id="payment-method" className="w-full"><SelectValue /></SelectTrigger><SelectContent>{PAYMENT_METHODS.map((option) => <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>)}</SelectContent></Select></div>
        {direct ? <>
          <div className="grid gap-4 sm:grid-cols-2"><div className="flex flex-col gap-1.5"><Label htmlFor="received-amount">Amount received (whole AED)</Label><Input id="received-amount" type="number" step="1" min="1" required value={amount} onChange={(event) => setAmount(event.target.value)} /></div><div className="flex flex-col gap-1.5"><Label htmlFor="payment-date">Payment date</Label><Input id="payment-date" type="date" max={paymentToday()} value={date} onChange={(event) => setDate(event.target.value)} required /></div></div>
          <div className="flex flex-col gap-1.5"><Label htmlFor="payment-proof">Payment screenshot / receipt</Label><Input id="payment-proof" type="file" accept="application/pdf,image/png,image/jpeg,image/webp" required onChange={(event) => setProof(event.target.files?.[0] ?? null)} /></div>
          <div className="flex flex-col gap-1.5"><Label htmlFor="transaction-reference">Transaction reference (optional)</Label><Input id="transaction-reference" maxLength={255} value={reference} onChange={(event) => setReference(event.target.value)} /></div>
          <label className="flex items-start gap-2 text-sm"><input type="checkbox" className="accent-primary mt-1" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} />I confirm this amount has actually been received.</label>
        </> : !state.stripe_configured ? <p className="text-muted-foreground text-sm">Stripe payments are currently unavailable. Choose a direct payment method.</p> : null}
        {error ? <p role="alert" className="text-destructive text-sm wrap-anywhere">{error}</p> : null}
        <div><Button disabled={pending || !preview || (direct ? !confirmed || !proof : !state.stripe_configured)}>{pending ? 'Submitting…' : direct ? 'Confirm received payment' : 'Generate Stripe payment link'}</Button></div>
      </form>}
      <FormDialog open={confirming} onOpenChange={setConfirming} size="lg" title="Generate Stripe payment link"
        description="The parent opens the link and enters card details. Student details come from Eduport Plus and cannot be changed on Stripe; Stripe asks for the parent’s email only when Eduport Plus has none."
        onConfirm={() => submit()} confirmLabel="Generate link" pending={pending}>
        <dl className="grid gap-2 text-sm sm:grid-cols-2">
          <div><dt className="text-muted-foreground">Student account</dt><dd className="font-medium">{state.account ? `${state.account.student_name} · ${state.account.reference}` : '—'}</dd></div>
          <div><dt className="text-muted-foreground">This payment</dt><dd className="font-medium">{preview ? wholeAed(preview.amount) : '—'}{token ? ' · token' : ` · ${classes} classes`}</dd></div>
          <div><dt className="text-muted-foreground">Billing contact</dt><dd className="font-medium">{state.account?.billing_contact ? `${state.account.billing_contact.full_name} · ${state.account.billing_contact.email || 'no email: the parent enters it on Stripe'}` : '—'}</dd></div>
          <div><dt className="text-muted-foreground">Remaining after this payment</dt><dd className="font-medium">{preview?.remaining_amount != null ? wholeAed(preview.remaining_amount) : '—'}</dd></div>
        </dl>
      </FormDialog>
      <CollectionReplacementDialog open={replacing} onOpenChange={setReplacing} enquiryId={enquiryId} quote={state.quote} tokenSale={state.sale.kind === 'TOKEN'} onChanged={onChanged} />
    </WorkspaceCard>
  );
}

export function PendingPayment({ payment, enquiry, onChanged, expireUrl = expirePaymentUrl(payment.id) }) {
  const { copied, manual, urlRef, copy } = useLinkCopy();
  const [error, setError] = useState(null);
  const [pending, setPending] = useState(false);
  const message = `Eduport Plus: pay ${wholeAed(payment.amount)} using this payment link: ${payment.payment_url}`;
  const whatsapp = whatsAppUrl(enquiry?.phone_dial_code, enquiry?.phone_number, message) ?? `https://wa.me/?text=${encodeURIComponent(message)}`;
  const expire = async () => {
    setPending(true); setError(null);
    try { await api.post(expireUrl); onChanged(); }
    catch (err) { setError(salesError(err, 'Could not expire the payment link.').message); }
    finally { setPending(false); }
  };
  return <WorkspaceCard icon={WalletIcon} title="Awaiting payment" action={<Badge variant="warning">Pending</Badge>}>
    <p className="text-sm">{wholeAed(payment.amount)} · {payment.purpose === 'TOKEN' ? 'Token reservation' : `${payment.classes} classes`}</p>
    <div className="flex flex-wrap gap-2"><Button variant="outline" onClick={() => copy(payment.id, payment.payment_url)}><CopyIcon />{copied ? 'Copied' : 'Copy payment link'}</Button><Button variant="outline" asChild><a href={whatsapp} target="_blank" rel="noopener noreferrer"><MessageCircleIcon />WhatsApp</a></Button><Button variant="ghost" onClick={expire} disabled={pending}>Expire unpaid link</Button></div>
    {manual ? <p ref={urlRef} className="text-muted-foreground text-sm break-all">{manual.url}</p> : null}
    {error ? <p role="alert" className="text-destructive text-sm">{error}</p> : null}
  </WorkspaceCard>;
}

// Received tuition the existing class-credit rules did not add to the student's quota.
const notCredited = (row) => row.purpose === 'TUITION' && row.status === 'SUCCEEDED' && row.classes_credited === false;

export function PaymentHistory({ rows }) {
  const files = useSyllabusPdf();
  const columns = [
    { key: 'date', header: 'Payment date', cell: (row) => row.payment_date },
    { key: 'method', header: 'Method', className: 'whitespace-normal', cell: (row) => row.method_label },
    { key: 'amount', header: 'Amount', cell: (row) => wholeAed(row.amount) },
    { key: 'classes', header: 'Classes', cell: (row) => row.purpose === 'TOKEN' ? 'Token · 0' : <>{row.classes}{notCredited(row) ? <span className="text-muted-foreground block text-xs">Not added to quota</span> : null}</> },
    { key: 'status', header: 'Status', cell: (row) => <Badge variant={row.status === 'SUCCEEDED' ? 'success' : 'outline'}>{row.status === 'SUCCEEDED' ? 'Received' : row.status}</Badge> },
    { key: 'reference', header: 'Reference / recorded by', className: 'whitespace-normal', cell: (row) => <span className="block max-w-60 break-all">{row.transaction_reference || row.stripe_payment_intent || '—'}<span className="text-muted-foreground block text-xs">{row.collection_source === 'AUTOPAY' ? 'Automatic collection' : row.recorded_by.name}{row.payer?.name || row.payer?.cardholder_name ? ` · paid by ${row.payer.name || row.payer.cardholder_name}` : ''}</span>{row.failure_message ? <span className="text-destructive block text-xs">Last attempt declined: {row.failure_message}</span> : null}{(row.refunds ?? []).map((refund) => <span key={refund.id} className="block text-xs">Refund {refund.currency} {refund.amount} · {refund.status}</span>)}{(row.disputes ?? []).map((dispute) => <span key={dispute.id} className="text-destructive block text-xs">Dispute {dispute.currency} {dispute.amount} · {dispute.status.replaceAll('_', ' ')}</span>)}</span> },
    { key: 'proof', header: 'Receipt', cell: (row) => row.proof_url ? <Button variant="outline" size="sm" onClick={() => files.download(row.proof_url, row.proof_name)} disabled={Boolean(files.pending)}><DownloadIcon />Receipt</Button> : '—' },
  ];
  return <WorkspaceCard icon={WalletIcon} title="Payment history"><ResponsiveList label="Payments" columns={columns} rows={rows} minTableWidth={760} renderCard={(row) => <article className="flex flex-col gap-2 rounded-lg border p-3 text-sm"><div className="flex flex-wrap justify-between gap-2"><strong>{wholeAed(row.amount)}</strong><span>{row.status}</span></div><p>{row.method_label} · {row.payment_date} · {row.classes} classes{notCredited(row) ? ' · not added to quota' : ''}</p><p className="text-muted-foreground break-all">{row.transaction_reference || row.stripe_payment_intent || row.recorded_by.name}</p>{row.proof_url ? <Button variant="outline" size="sm" onClick={() => files.download(row.proof_url, row.proof_name)}>Download receipt</Button> : null}</article>} />{files.error ? <p role="alert" className="text-destructive text-sm">{files.error}</p> : null}{files.dialog}</WorkspaceCard>;
}

export function EnquirySalesPayment({ enquiryId, enquiry, user, studentId, onChanged }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [reload, setReload] = useState(0);
  const endpoint = studentId ? initialStudentSaleUrl(studentId) : saleUrl(enquiryId);
  const refresh = (next) => { if (next) setData(next); else setReload((key) => key + 1); onChanged?.(); };
  useEffect(() => {
    let active = true;
    api.get(endpoint).then(({ data: state }) => { if (active) { setData(state); setError(null); } })
      .catch((err) => { if (active) setError(salesError(err, 'Could not load the initial sale.')); });
    return () => { active = false; };
  }, [endpoint, reload]);
  const pendingPayment = data?.payments.find((payment) => payment.status === 'PENDING');
  useEffect(() => {
    if (!pendingPayment) return;
    const timer = setTimeout(() => setReload((key) => key + 1), 10000);
    return () => clearTimeout(timer);
  }, [pendingPayment, reload]);
  if (error && !data) return studentId && error.status === 404 ? null : <ErrorState message={error.message} onRetry={() => refresh()} />;
  if (!data) return <Skeleton className="h-48 w-full" aria-busy="true" />;
  const enrolled = Boolean(data.sale?.student);
  const compatibilityIssue = collectionCompatibility(data);
  return <div className="flex min-w-0 flex-col gap-4">
    <div className="flex items-center justify-between gap-3"><h2 className="text-xl font-semibold">{studentId ? 'Initial enrollment & purchase' : 'Sales & Payment'}</h2><Button variant="outline" size="sm" onClick={() => refresh()}><RefreshCwIcon />Refresh</Button></div>
    {error ? <ErrorState message={error.message} onRetry={() => refresh()} /> : null}
    {data.quote ? <QuoteSummary quote={data.quote} /> : <Notice>Choose a plan and issue a quote before collecting tuition. A token reservation can be started before a package is chosen.</Notice>}
    {data.sale && data.account ? <StudentAccountCard enquiryId={enquiryId} account={data.account} onChanged={refresh} readOnly={Boolean(studentId)} /> : null}
    {data.sale ? <WorkspaceCard icon={WalletIcon} title={data.sale.kind === 'TOKEN' ? 'Token reservation' : 'New Sale'} action={enrolled ? <Badge variant="success">Enrolled</Badge> : null}>
      {data.sale.kind === 'TOKEN' ? <p className="text-sm">{data.sale.reservation_reference} · Expected start: {data.sale.expected_start_date} · {data.sale.token_status} · Token paid: {wholeAed(data.sale.token_paid)}</p> : null}
      <SaleFields rows={[["Purchased classes", data.totals.purchased_classes], ["Paid classes", data.totals.paid_classes], ["Unpaid classes", data.totals.unpaid_classes], ["Used classes", data.totals.used_classes], ["Available quota", data.totals.available_quota], ["Amount received", wholeAed(data.totals.paid_amount)], ["Outstanding balance", wholeAed(data.totals.outstanding_amount ?? data.totals.remaining_amount)],
        ...(Number(data.totals.classes_not_credited) > 0 ? [["Class quota", data.totals.class_quota], ["Paid, not added to quota", data.totals.classes_not_credited]] : []),
        ...(Number(data.totals.refunded_amount) > 0 ? [["Refunded (classes unchanged)", `AED ${data.totals.refunded_amount}`], ["Net collected", `AED ${data.totals.net_collected}`]] : [])]} />
      {enrolled ? <p className="text-sm"><strong>{data.sale.student.student_code}</strong> · Enrollment complete.{data.can_collect ? ' The remaining balance of this purchase can still be collected here. Collecting it records the payment; it does not change the class quota.' : ' Payment records remain available here.'} {can(user, PERMISSIONS.viewAllStudents) ? <Link className="text-primary underline" to={`/students/${data.sale.student.id}`}>Open student and assign mentor</Link> : null}</p> : null}
    </WorkspaceCard> : !studentId ? <StartSale enquiryId={enquiryId} enquiry={enquiry} state={data} onChanged={refresh} /> : null}
    {data.autopay ? <AutopaySummary agreement={data.autopay} action={!studentId && data.can_cancel_autopay ? <CancelAutopay agreement={data.autopay} onChanged={refresh} /> : null} /> : null}
    {!studentId && data.sale ? pendingPayment ? <PendingPayment payment={pendingPayment} enquiry={enquiry} onChanged={refresh} /> : !enrolled && data.autopay ? <RestartAutopay agreement={data.autopay} onChanged={refresh} /> : !enrolled && compatibilityIssue ? <WorkspaceCard title="Replacement quote required"><QuoteCompatibilityNotice enquiryId={enquiryId} state={data} issue={compatibilityIssue} tokenSale={data.sale.kind === 'TOKEN'} onChanged={refresh} /></WorkspaceCard> : (enrolled ? data.can_collect && !data.autopay : true) ? <CollectPayment key={`${data.sale.id}:${data.purchase?.id}:${data.quote?.id}:${data.sale.token_paid}:${data.totals.paid_classes}`} enquiryId={enquiryId} state={data} onChanged={refresh} /> : null : null}
    {data.payments.length ? <PaymentHistory rows={data.payments} /> : null}
  </div>;
}

function RestartAutopay({ agreement, onChanged }) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState(null);
  const requestId = useRef(crypto.randomUUID());
  const restart = async () => {
    setPending(true); setError(null);
    try { const { data } = await api.post(`/api/sales/autopay/${agreement.id}/initial-checkout/`, { request_id: requestId.current }); onChanged(data); }
    catch (err) { setError(salesError(err, 'Could not restart initial Checkout.').message); }
    finally { setPending(false); }
  };
  return <WorkspaceCard title="Initial Autopay payment"><p className="text-sm">The agreed schedule stays unchanged. Generate a new initial Checkout after an expired or failed payment.</p><div><Button disabled={pending} onClick={restart}>Generate initial Checkout again</Button></div>{error ? <p role="alert" className="text-destructive text-sm">{error}</p> : null}</WorkspaceCard>;
}
