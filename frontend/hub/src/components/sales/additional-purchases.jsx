import { useEffect, useRef, useState } from 'react';
import { ArrowLeftIcon, ShoppingBagIcon, WalletIcon } from 'lucide-react';

import api from '@/lib/api';
import { chapterPlanError, planTypeLabel, QUOTE_COLLECTION_MODES, quotePreview, salesError } from '@/lib/sales';
import { PAYMENT_METHODS, PURCHASE_KINDS, PURCHASE_STATUSES, purchaseAmountUrl, purchaseExpireUrl, purchasePaymentsUrl, purchaseUrl,
  studentPurchasesUrl, paymentToday, wholeAed } from '@/lib/payments';
import { formatDate } from '@/lib/utils';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Skeleton } from '@/components/ui/skeleton';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { RefreshButton } from '@/components/page/refresh-button';
import { ErrorState, Notice } from '@/components/page/states';
import { FormDialog } from '@/components/form-dialog';
import { WorkspaceCard } from '@/components/bookings/redemo-workspace/parts';
import { QuotePlanCard } from '@/components/sales/quote-builder';
import { AutopayBrief } from '@/components/sales/autopay-summary';
import { DirectPaymentFields, PaymentHistory, PendingPayment, QuoteSummary, SaleFields } from '@/components/enquiries/workspace/enquiry-sales-payment';

// Autopay for an additional purchase awaits a decision; the API refuses it.
const PURCHASE_COLLECTION_MODES = QUOTE_COLLECTION_MODES.filter((option) => option.value !== 'AUTOPAY');

/** Choose a syllabus on sale, then its plan, as a quote is chosen; the API prices it before anything is added. */
export function AddPurchase({ studentId, overview, onBack, onCreated }) {
  const [syllabusId, setSyllabusId] = useState('');
  const [detail, setDetail] = useState(null);
  const [failure, setFailure] = useState(null);
  const [planType, setPlanType] = useState(null);
  const [bridgeMode, setBridgeMode] = useState(null);
  const [classMode, setClassMode] = useState('REGULAR');
  const [collectionMode, setCollectionMode] = useState(null);
  const [chapterIds, setChapterIds] = useState([]);
  const [review, setReview] = useState(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState(null);
  // Try again reads the same syllabus once more: choosing it again alone would not.
  const [syllabusKey, setSyllabusKey] = useState(0);
  const requestId = useRef(crypto.randomUUID());

  useEffect(() => {
    if (!syllabusId) return undefined;
    let active = true;
    api.get(studentPurchasesUrl(studentId), { params: { syllabus: syllabusId } })
      .then(({ data }) => { if (active) setDetail(data.syllabus); })
      .catch((err) => { if (active) setFailure(salesError(err, 'Could not load this syllabus.')); });
    return () => { active = false; };
  }, [studentId, syllabusId, syllabusKey]);

  const chooseSyllabus = (id) => {
    setSyllabusId(id); setDetail(null); setFailure(null); setPlanType(null); setBridgeMode(null);
    setClassMode('REGULAR'); setCollectionMode(null); setChapterIds([]); setError(null);
  };
  const retrySyllabus = () => {
    chooseSyllabus(syllabusId);
    setSyllabusKey((key) => key + 1);
  };
  const bridge = detail?.structure === 'BRIDGE_COURSE';
  const plan = bridge && bridgeMode && detail.plan_types.includes('BRIDGE_COURSE') ? 'BRIDGE_COURSE' : planType;
  const partial = plan === 'CHAPTER_PLAN' || (bridge && bridgeMode === 'selected');
  const ids = partial ? chapterIds : [];
  const selectionError = detail && plan === 'CHAPTER_PLAN' ? chapterPlanError(detail.chapters, ids, classMode) : null;
  const preview = detail?.pricing && plan && (!partial || ids.length) ? quotePreview(plan, detail.chapters, ids, detail.pricing, classMode, collectionMode) : null;
  const body = () => ({ syllabus: detail.id, revision: detail.revision, plan_type: plan, collection_mode: collectionMode,
    ...(plan === 'CHAPTER_PLAN' ? { class_mode: classMode } : {}), chapter_ids: ids });

  const reviewPurchase = async () => {
    setPending(true); setError(null);
    try {
      const { data } = await api.post(studentPurchasesUrl(studentId), { ...body(), preview: true });
      setReview(data.preview);
    } catch (err) { setError(salesError(err, 'Could not price this purchase.').message); }
    finally { setPending(false); }
  };
  const create = async () => {
    setPending(true); setError(null);
    try {
      const { data } = await api.post(studentPurchasesUrl(studentId), { ...body(), request_id: requestId.current, pricing_version: review.pricing_version });
      setReview(null);
      onCreated(data);
    } catch (err) {
      setReview(null);
      setError(salesError(err, 'Could not add this purchase.').message);
    } finally { setPending(false); }
  };

  return <div className="flex min-w-0 flex-col gap-4">
    <div><Button variant="outline" onClick={onBack}><ArrowLeftIcon />Back to Finance</Button></div>
    <WorkspaceCard icon={ShoppingBagIcon} title="1. Choose a syllabus" action={<Badge variant="outline">{overview.account.reference}</Badge>}>
      <p className="text-muted-foreground text-sm">A new purchase for {overview.student.full_name}, on the same student account and Stripe Customer.</p>
      <div className="flex max-w-md flex-col gap-1.5"><Label htmlFor="purchase-syllabus">Syllabus on sale</Label>
        <select id="purchase-syllabus" className="border-input bg-background h-9 rounded-md border px-3 text-sm" value={syllabusId} onChange={(event) => chooseSyllabus(event.target.value)}>
          <option value="">Choose a syllabus…</option>
          {overview.catalogue.map((row) => <option key={row.id} value={row.id}>{row.title} · Grade {row.grade} · {row.board}</option>)}
        </select></div>
    </WorkspaceCard>
    {failure ? <ErrorState message={failure.message} onRetry={retrySyllabus} /> : null}
    {syllabusId && !detail && !failure ? <Skeleton className="h-48 w-full" aria-busy="true" /> : null}
    {detail && !detail.pricing ? <p role="status" className="text-muted-foreground text-sm">Pricing is not set up yet. A purchase cannot be priced.</p> : null}
    {detail ? <QuotePlanCard detail={detail} planType={plan} onPlanType={setPlanType} bridgeMode={bridgeMode} onBridgeMode={setBridgeMode}
      chapterIds={chapterIds} onChapterIds={setChapterIds} collectionMode={collectionMode} onCollectionMode={setCollectionMode}
      collectionModes={PURCHASE_COLLECTION_MODES} classMode={classMode} onClassMode={setClassMode} selectionError={selectionError}
      preview={preview} onCreate={reviewPurchase} locked={pending} createLabel="Review purchase…" /> : null}
    {detail ? <p className="text-muted-foreground text-sm">Autopay for an additional purchase is not available yet.</p> : null}
    {error ? <p role="alert" className="text-destructive text-sm wrap-anywhere">{error}</p> : null}
    <FormDialog open={Boolean(review)} onOpenChange={(open) => !open && setReview(null)} size="lg" title="Add purchase"
      description={`A new sale on ${overview.account.reference}. Earlier purchases and their payments stay as they are.`}
      onConfirm={create} confirmLabel="Add purchase" pending={pending}>
      {review ? <dl className="grid gap-2 text-sm sm:grid-cols-2">
        <div><dt className="text-muted-foreground">Student</dt><dd className="font-medium">{overview.student.full_name} · {overview.student.student_code}</dd></div>
        <div><dt className="text-muted-foreground">Plan</dt><dd className="font-medium">{detail.title} · {planTypeLabel(review.plan_type)} · {review.classes} classes</dd></div>
        <div><dt className="text-muted-foreground">Payment</dt><dd className="font-medium">{PURCHASE_COLLECTION_MODES.find((option) => option.value === review.collection_mode)?.label}</dd></div>
        <div><dt className="text-muted-foreground">Original price</dt><dd className="font-medium">{wholeAed(review.collection_subtotal)}</dd></div>
        <div><dt className="text-muted-foreground">Discount</dt><dd className="font-medium">{wholeAed(review.collection_discount)}</dd></div>
        <div><dt className="text-muted-foreground">Agreed package amount</dt><dd className="font-semibold">{wholeAed(review.collection_amount)}</dd></div>
      </dl> : null}
    </FormDialog>
  </div>;
}

/**
 * One of the student's purchases -- the initial sale or an additional one -- for
 * their mentor (or an administrator): its plan, totals and payments, and
 * collecting what is unpaid, through a Stripe link or a received payment with
 * its receipt. Collected after enrollment, it records money only.
 */
export function PurchaseDetail({ saleId, initial, initialMethod = 'STRIPE', onBack }) {
  const [state, setState] = useState(initial ?? null);
  const [error, setError] = useState(null);
  const [reload, setReload] = useState(0);
  // A read of the purchase under way (Refresh, Try again, or the pending-payment poll).
  const [loading, setLoading] = useState(false);
  const refresh = (next) => { if (next) setState(next); else setReload((key) => key + 1); };

  useEffect(() => {
    let active = true;
    setLoading(true);
    api.get(purchaseUrl(saleId))
      .then(({ data }) => { if (active) { setState(data); setError(null); } })
      .catch((err) => { if (active) setError(salesError(err, 'Could not load this purchase.')); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [saleId, reload]);
  const pendingPayment = state?.payments.find((payment) => payment.status === 'PENDING');
  // A verified payment arrives by webhook: look again while a link is open.
  useEffect(() => {
    if (!pendingPayment) return undefined;
    const timer = setTimeout(() => setReload((key) => key + 1), 10000);
    return () => clearTimeout(timer);
  }, [pendingPayment, reload]);

  const back = <Button variant="outline" onClick={onBack}><ArrowLeftIcon />Back to Finance</Button>;
  if (error && !state) return <div className="flex flex-col gap-3"><div>{back}</div><ErrorState message={error.message} onRetry={() => refresh()} pending={loading} /></div>;
  if (!state) return <Skeleton className="h-48 w-full" aria-busy="true" />;
  const { totals, sale } = state;
  const status = PURCHASE_STATUSES[state.payment_status];
  return <div className="flex min-w-0 flex-col gap-4">
    <div className="flex flex-wrap items-center justify-between gap-3">
      {back}
      <RefreshButton onClick={() => refresh()} pending={loading} />
    </div>
    {error ? <ErrorState message={error.message} onRetry={() => refresh()} pending={loading} /> : null}
    <QuoteSummary quote={state.quote} />
    <WorkspaceCard icon={WalletIcon} title={PURCHASE_KINDS[sale.kind] ?? sale.kind} action={status ? <Badge variant={status.variant}>{status.label}</Badge> : null}>
      <SaleFields rows={[['Purchased classes', totals.purchased_classes], ['Paid classes', totals.paid_classes], ['Unpaid classes', totals.unpaid_classes],
        ['Agreed package amount', wholeAed(totals.package_amount)], ['Amount received', wholeAed(totals.paid_amount)], ['Outstanding balance', wholeAed(totals.outstanding_amount)]]} />
      <p className="text-muted-foreground text-sm">{sale.kind === 'ADDITIONAL'
        ? `Added by ${sale.created_by.name} on ${formatDate(sale.created_at)}`
        : `Enrolled on ${formatDate(sale.enrolled_at ?? sale.created_at)}`} for {state.student.full_name} · {state.student.student_code} · {state.account.reference}.</p>
      {Number(totals.classes_not_credited) > 0 ? <Notice>Payments collected after enrollment record money only: {totals.classes_not_credited} paid classes of this purchase are not added to the student’s class quota.</Notice> : null}
    </WorkspaceCard>
    {state.autopay ? <AutopayBrief agreement={state.autopay} /> : null}
    {pendingPayment ? <PendingPayment payment={pendingPayment} expireUrl={purchaseExpireUrl(saleId, pendingPayment.id)} onChanged={() => refresh()} />
      : state.can_collect ? <CollectPurchasePayment key={`${totals.paid_classes}:${state.payments.length}`} state={state} initialMethod={initialMethod} onChanged={refresh} /> : null}
    {state.payments.length ? <PaymentHistory rows={state.payments} /> : null}
  </div>;
}

/** Some or all of what is unpaid: a one-time Stripe link, or money already received with its receipt. The API works out the amount. */
function CollectPurchasePayment({ state, initialMethod, onChanged }) {
  const saleId = state.sale.id;
  const contact = state.account.billing_contact;
  const [classes, setClasses] = useState(state.totals.unpaid_classes);
  const [method, setMethod] = useState(initialMethod);
  const [preview, setPreview] = useState(null);
  const [calculationError, setCalculationError] = useState(null);
  const [amount, setAmount] = useState('');
  const [date, setDate] = useState(paymentToday());
  const [proof, setProof] = useState(null);
  const [reference, setReference] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState(null);
  const requestId = useRef(crypto.randomUUID());
  const direct = method !== 'STRIPE';

  useEffect(() => {
    if (!(Number(classes) > 0)) return undefined;
    let active = true;
    const timer = setTimeout(() => {
      api.get(purchaseAmountUrl(saleId), { params: { classes } })
        .then(({ data }) => { if (active) { setPreview(data); setAmount(data.amount); setCalculationError(null); } })
        .catch((err) => { if (active) setCalculationError(salesError(err, 'Could not calculate this payment.')); });
    }, 200);
    return () => { active = false; clearTimeout(timer); };
  }, [saleId, classes]);

  const submit = async () => {
    setPending(true); setError(null);
    try {
      let body = { request_id: requestId.current, classes };
      if (direct) {
        body = new FormData();
        for (const [key, value] of Object.entries({ request_id: requestId.current, method, classes, amount, payment_date: date,
          received_confirmed: confirmed, transaction_reference: reference })) body.append(key, String(value));
        body.append('proof', proof);
      }
      const { data } = await api.post(purchasePaymentsUrl(saleId), body);
      setConfirming(false);
      onChanged(data.state);
    } catch (err) {
      setConfirming(false);
      setError(salesError(err, direct ? 'Could not record this payment.' : 'Could not create the payment link.').message);
    } finally { setPending(false); }
  };
  return <WorkspaceCard icon={WalletIcon} title={Number(state.totals.paid_classes) > 0 ? 'Collect remaining balance' : 'Collect payment'}>
    <form onSubmit={(event) => { event.preventDefault(); if (direct) submit(); else setConfirming(true); }} className="flex flex-col gap-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="flex flex-col gap-1.5"><Label htmlFor="purchase-classes">Classes covered by this payment</Label>
          <Input id="purchase-classes" type="number" step="0.5" min="0.5" max={state.totals.unpaid_classes} value={classes} required
            readOnly={state.purchase.collection_mode === 'FULL'} onChange={(event) => { setClasses(event.target.value); setPreview(null); setCalculationError(null); }} />
          {state.purchase.collection_mode === 'FULL' ? <p className="text-muted-foreground text-xs">Complete Payment: the whole balance is collected at once.</p> : null}</div>
        <div className="flex flex-col gap-1.5"><Label htmlFor="purchase-method">Payment method</Label>
          <Select value={method} onValueChange={setMethod} disabled={pending}><SelectTrigger id="purchase-method" className="w-full"><SelectValue /></SelectTrigger>
            <SelectContent>{PAYMENT_METHODS.map((option) => <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>)}</SelectContent></Select></div>
      </div>
      {calculationError ? <p role="alert" className="text-destructive text-sm">{calculationError.message}</p> : null}
      <p role="status" className="text-sm">Amount payable: <strong>{preview ? wholeAed(preview.amount) : '—'}</strong>{preview ? ` · ${wholeAed(preview.remaining_amount)} remaining after it` : ''}</p>
      {direct ? <DirectPaymentFields amount={amount} onAmount={setAmount} date={date} onDate={setDate} onProof={setProof}
        reference={reference} onReference={setReference} confirmed={confirmed} onConfirmed={setConfirmed} />
        : !state.stripe_configured ? <p className="text-muted-foreground text-sm">Stripe payments are currently unavailable. Choose a direct payment method.</p> : null}
      {error ? <p role="alert" className="text-destructive text-sm wrap-anywhere">{error}</p> : null}
      <div><Button disabled={pending || !preview || (direct ? !confirmed || !proof : !state.stripe_configured)}>
        {pending ? 'Submitting…' : direct ? 'Confirm received payment' : 'Generate Stripe payment link'}</Button></div>
    </form>
    <FormDialog open={confirming} onOpenChange={setConfirming} size="lg" title="Generate Stripe payment link"
      description="The parent opens the link and enters card details. Student details come from Eduport Plus and cannot be changed on Stripe; Stripe asks for the parent’s email only when Eduport Plus has none."
      onConfirm={submit} confirmLabel="Generate link" pending={pending}>
      <dl className="grid gap-2 text-sm sm:grid-cols-2">
        <div><dt className="text-muted-foreground">Student account</dt><dd className="font-medium">{state.account.student_name} · {state.account.reference}</dd></div>
        <div><dt className="text-muted-foreground">This payment</dt><dd className="font-medium">{preview ? wholeAed(preview.amount) : '—'} · {classes} classes</dd></div>
        <div><dt className="text-muted-foreground">Billing contact</dt><dd className="font-medium">{contact ? `${contact.full_name} · ${contact.email || 'no email: the parent enters it on Stripe'}` : '—'}</dd></div>
        <div><dt className="text-muted-foreground">Remaining after this payment</dt><dd className="font-medium">{preview ? wholeAed(preview.remaining_amount) : '—'}</dd></div>
      </dl>
    </FormDialog>
  </WorkspaceCard>;
}
