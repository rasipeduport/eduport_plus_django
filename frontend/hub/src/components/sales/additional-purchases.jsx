import { useEffect, useRef, useState } from 'react';
import { ArrowLeftIcon, PlusIcon, RefreshCwIcon, ShoppingBagIcon, WalletIcon } from 'lucide-react';

import api from '@/lib/api';
import { chapterPlanError, planTypeLabel, QUOTE_COLLECTION_MODES, quotePreview, salesError } from '@/lib/sales';
import { purchaseAmountUrl, purchaseExpireUrl, purchasePaymentsUrl, purchaseUrl, studentPurchasesUrl, wholeAed } from '@/lib/payments';
import { formatDate } from '@/lib/utils';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Skeleton } from '@/components/ui/skeleton';
import { ErrorState, Notice } from '@/components/page/states';
import { ResponsiveList } from '@/components/page/responsive-list';
import { FormDialog } from '@/components/form-dialog';
import { WorkspaceCard } from '@/components/bookings/redemo-workspace/parts';
import { QuotePlanCard } from '@/components/sales/quote-builder';
import { PaymentHistory, PendingPayment, QuoteSummary, SaleFields } from '@/components/enquiries/workspace/enquiry-sales-payment';

// Autopay for an additional purchase awaits a decision; the API refuses it.
const PURCHASE_COLLECTION_MODES = QUOTE_COLLECTION_MODES.filter((option) => option.value !== 'AUTOPAY');
const SALE_KINDS = { NEW: 'Initial purchase', TOKEN: 'Initial purchase (token)', ADDITIONAL: 'Additional purchase' };

/**
 * A student's purchases, for their mentor (or an administrator): every sale on
 * the student's account, and Add purchase -- a new sale on the same account,
 * priced from the catalogue on sale as any quote is, and paid through its own
 * Stripe links on the student's one Stripe Customer. Earlier sales never change.
 */
export function StudentPurchases({ studentId }) {
  const [overview, setOverview] = useState(null);
  const [error, setError] = useState(null);
  const [reload, setReload] = useState(0);
  const [view, setView] = useState({ name: 'list' });

  useEffect(() => {
    let active = true;
    api.get(studentPurchasesUrl(studentId))
      .then(({ data }) => { if (active) { setOverview(data); setError(null); } })
      .catch((err) => { if (active) setError(salesError(err, 'Could not load this student’s purchases.')); });
    return () => { active = false; };
  }, [studentId, reload]);

  const refresh = () => setReload((key) => key + 1);
  const toList = () => { refresh(); setView({ name: 'list' }); };
  if (error && !overview) return <ErrorState message={error.message} onRetry={refresh} />;
  if (!overview) return <Skeleton className="h-48 w-full" aria-busy="true" />;
  if (view.name === 'add') {
    return <AddPurchase studentId={studentId} overview={overview} onBack={() => setView({ name: 'list' })}
      onCreated={(state) => { refresh(); setView({ name: 'purchase', saleId: state.sale.id, state }); }} />;
  }
  if (view.name === 'purchase') return <PurchaseDetail saleId={view.saleId} initial={view.state} onBack={toList} />;
  return <PurchaseList overview={overview} error={error} onRefresh={refresh} onAdd={() => setView({ name: 'add' })}
    onOpen={(saleId) => setView({ name: 'purchase', saleId })} />;
}

function PurchaseList({ overview, error, onRefresh, onAdd, onOpen }) {
  const columns = [
    { key: 'kind', header: 'Purchase', className: 'whitespace-normal', cell: (row) => <span>{SALE_KINDS[row.kind] ?? row.kind}<span className="text-muted-foreground block text-xs">{row.quote_reference ?? 'No quote'} · {formatDate(row.created_at)}</span></span> },
    { key: 'plan', header: 'Plan', className: 'whitespace-normal', cell: (row) => row.plan_type ? `${planTypeLabel(row.plan_type)} · ${row.classes} classes` : '—' },
    { key: 'package', header: 'Package', cell: (row) => wholeAed(row.package_amount) },
    { key: 'received', header: 'Received', cell: (row) => wholeAed(row.paid_amount) },
    { key: 'outstanding', header: 'Outstanding', cell: (row) => <Outstanding row={row} /> },
    { key: 'open', header: { srOnly: 'Open' }, cell: (row) => row.kind === 'ADDITIONAL' ? <Button size="sm" variant="outline" onClick={() => onOpen(row.id)}>Open</Button> : null },
  ];
  return <div className="flex min-w-0 flex-col gap-4">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <h2 className="text-xl font-semibold">Purchases</h2>
      <div className="flex flex-wrap gap-2">
        <Button variant="outline" size="sm" onClick={onRefresh}><RefreshCwIcon />Refresh</Button>
        <Button size="sm" onClick={onAdd} disabled={!overview.can_add}><PlusIcon />Add purchase</Button>
      </div>
    </div>
    {error ? <ErrorState message={error.message} onRetry={onRefresh} /> : null}
    {overview.blockers.map((blocker) => <Notice key={`${blocker.code}:${blocker.sale_id}`}>{blocker.message}</Notice>)}
    <WorkspaceCard icon={ShoppingBagIcon} title={`${overview.student.full_name} · ${overview.student.student_code}`} action={<Badge variant="outline">{overview.account.reference}</Badge>}>
      <p className="text-muted-foreground text-sm">Each purchase is its own sale on this student’s account. Adding one never changes an earlier purchase or its payments.</p>
      <ResponsiveList label="Purchases" columns={columns} rows={overview.sales} minTableWidth={720}
        renderCard={(row) => <article className="flex flex-col gap-2 rounded-lg border p-3 text-sm">
          <div className="flex flex-wrap justify-between gap-2"><strong>{SALE_KINDS[row.kind] ?? row.kind}</strong><Outstanding row={row} /></div>
          <p>{row.plan_type ? `${planTypeLabel(row.plan_type)} · ${row.classes} classes` : '—'} · {wholeAed(row.package_amount)}</p>
          <p className="text-muted-foreground">{row.quote_reference ?? 'No quote'} · Received {wholeAed(row.paid_amount)}</p>
          {row.kind === 'ADDITIONAL' ? <Button size="sm" variant="outline" onClick={() => onOpen(row.id)}>Open</Button> : null}
        </article>} />
    </WorkspaceCard>
  </div>;
}

function Outstanding({ row }) {
  if (row.autopay_status && !['COMPLETED', 'CANCELLED'].includes(row.autopay_status)) return <Badge variant="outline">Autopay · {row.autopay_status.toLowerCase().replaceAll('_', ' ')}</Badge>;
  if (row.fully_paid) return <Badge variant="success">Paid</Badge>;
  return <span>{wholeAed(row.outstanding_amount)}</span>;
}

/** Choose a syllabus on sale, then its plan, as a quote is chosen; the API prices it before anything is added. */
function AddPurchase({ studentId, overview, onBack, onCreated }) {
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
  const requestId = useRef(crypto.randomUUID());

  useEffect(() => {
    if (!syllabusId) return undefined;
    let active = true;
    api.get(studentPurchasesUrl(studentId), { params: { syllabus: syllabusId } })
      .then(({ data }) => { if (active) setDetail(data.syllabus); })
      .catch((err) => { if (active) setFailure(salesError(err, 'Could not load this syllabus.')); });
    return () => { active = false; };
  }, [studentId, syllabusId]);

  const chooseSyllabus = (id) => {
    setSyllabusId(id); setDetail(null); setFailure(null); setPlanType(null); setBridgeMode(null);
    setClassMode('REGULAR'); setCollectionMode(null); setChapterIds([]); setError(null);
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
    <div><Button variant="outline" onClick={onBack}><ArrowLeftIcon />All purchases</Button></div>
    <WorkspaceCard icon={ShoppingBagIcon} title="1. Choose a syllabus" action={<Badge variant="outline">{overview.account.reference}</Badge>}>
      <p className="text-muted-foreground text-sm">A new purchase for {overview.student.full_name}, on the same student account and Stripe Customer.</p>
      <div className="flex max-w-md flex-col gap-1.5"><Label htmlFor="purchase-syllabus">Syllabus on sale</Label>
        <select id="purchase-syllabus" className="border-input bg-background h-9 rounded-md border px-3 text-sm" value={syllabusId} onChange={(event) => chooseSyllabus(event.target.value)}>
          <option value="">Choose a syllabus…</option>
          {overview.catalogue.map((row) => <option key={row.id} value={row.id}>{row.title} · Grade {row.grade} · {row.board}</option>)}
        </select></div>
    </WorkspaceCard>
    {failure ? <ErrorState message={failure.message} onRetry={() => chooseSyllabus(syllabusId)} /> : null}
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

function PurchaseDetail({ saleId, initial, onBack }) {
  const [state, setState] = useState(initial ?? null);
  const [error, setError] = useState(null);
  const [reload, setReload] = useState(0);
  const refresh = (next) => { if (next) setState(next); else setReload((key) => key + 1); };

  useEffect(() => {
    let active = true;
    api.get(purchaseUrl(saleId))
      .then(({ data }) => { if (active) { setState(data); setError(null); } })
      .catch((err) => { if (active) setError(salesError(err, 'Could not load this purchase.')); });
    return () => { active = false; };
  }, [saleId, reload]);
  const pendingPayment = state?.payments.find((payment) => payment.status === 'PENDING');
  // A verified payment arrives by webhook: look again while a link is open.
  useEffect(() => {
    if (!pendingPayment) return undefined;
    const timer = setTimeout(() => setReload((key) => key + 1), 10000);
    return () => clearTimeout(timer);
  }, [pendingPayment, reload]);

  if (error && !state) return <div className="flex flex-col gap-3"><div><Button variant="outline" onClick={onBack}><ArrowLeftIcon />All purchases</Button></div><ErrorState message={error.message} onRetry={() => refresh()} /></div>;
  if (!state) return <Skeleton className="h-48 w-full" aria-busy="true" />;
  const { totals } = state;
  return <div className="flex min-w-0 flex-col gap-4">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <Button variant="outline" onClick={onBack}><ArrowLeftIcon />All purchases</Button>
      <Button variant="outline" size="sm" onClick={() => refresh()}><RefreshCwIcon />Refresh</Button>
    </div>
    {error ? <ErrorState message={error.message} onRetry={() => refresh()} /> : null}
    <QuoteSummary quote={state.quote} />
    <WorkspaceCard icon={WalletIcon} title="Additional purchase" action={totals.fully_paid ? <Badge variant="success">Paid</Badge> : <Badge variant="outline">{state.account.reference}</Badge>}>
      <SaleFields rows={[['Purchased classes', totals.purchased_classes], ['Paid classes', totals.paid_classes], ['Unpaid classes', totals.unpaid_classes],
        ['Agreed package amount', wholeAed(totals.package_amount)], ['Amount received', wholeAed(totals.paid_amount)], ['Outstanding balance', wholeAed(totals.outstanding_amount)]]} />
      <p className="text-muted-foreground text-sm">Added by {state.sale.created_by.name} on {formatDate(state.sale.created_at)} for {state.student.full_name} · {state.student.student_code}.</p>
      {Number(totals.classes_not_credited) > 0 ? <Notice>Payments are recorded on this purchase, but its {totals.classes_not_credited} paid classes are not added to the student’s class quota: how an additional purchase credits classes is not decided yet.</Notice> : null}
    </WorkspaceCard>
    {pendingPayment ? <PendingPayment payment={pendingPayment} expireUrl={purchaseExpireUrl(saleId, pendingPayment.id)} onChanged={() => refresh()} />
      : state.can_collect ? <CollectLink key={`${totals.paid_classes}:${state.payments.length}`} state={state} onChanged={refresh} /> : null}
    {state.payments.length ? <PaymentHistory rows={state.payments} /> : null}
  </div>;
}

/** A one-time Stripe link for some or all of what is unpaid; the API works out the amount. */
function CollectLink({ state, onChanged }) {
  const saleId = state.sale.id;
  const contact = state.account.billing_contact;
  const [classes, setClasses] = useState(state.totals.unpaid_classes);
  const [preview, setPreview] = useState(null);
  const [calculationError, setCalculationError] = useState(null);
  const [confirming, setConfirming] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState(null);
  const requestId = useRef(crypto.randomUUID());

  useEffect(() => {
    if (!(Number(classes) > 0)) return undefined;
    let active = true;
    const timer = setTimeout(() => {
      api.get(purchaseAmountUrl(saleId), { params: { classes } })
        .then(({ data }) => { if (active) { setPreview(data); setCalculationError(null); } })
        .catch((err) => { if (active) setCalculationError(salesError(err, 'Could not calculate this payment.')); });
    }, 200);
    return () => { active = false; clearTimeout(timer); };
  }, [saleId, classes]);

  const submit = async () => {
    setPending(true); setError(null);
    try {
      const { data } = await api.post(purchasePaymentsUrl(saleId), { request_id: requestId.current, classes });
      setConfirming(false);
      onChanged(data.state);
    } catch (err) {
      setConfirming(false);
      setError(salesError(err, 'Could not create the payment link.').message);
    } finally { setPending(false); }
  };
  return <WorkspaceCard icon={WalletIcon} title={Number(state.totals.paid_classes) > 0 ? 'Collect remaining balance' : 'Collect payment'}>
    <form onSubmit={(event) => { event.preventDefault(); setConfirming(true); }} className="flex flex-col gap-4">
      <div className="flex max-w-sm flex-col gap-1.5"><Label htmlFor="purchase-classes">Classes covered by this payment</Label>
        <Input id="purchase-classes" type="number" step="0.5" min="0.5" max={state.totals.unpaid_classes} value={classes} required
          readOnly={state.purchase.collection_mode === 'FULL'} onChange={(event) => { setClasses(event.target.value); setPreview(null); setCalculationError(null); }} /></div>
      {calculationError ? <p role="alert" className="text-destructive text-sm">{calculationError.message}</p> : null}
      <p role="status" className="text-sm">Amount payable: <strong>{preview ? wholeAed(preview.amount) : '—'}</strong></p>
      {!state.stripe_configured ? <p className="text-muted-foreground text-sm">Stripe payments are currently unavailable.</p> : null}
      {error ? <p role="alert" className="text-destructive text-sm wrap-anywhere">{error}</p> : null}
      <div><Button disabled={pending || !preview || !state.stripe_configured}>{pending ? 'Submitting…' : 'Generate Stripe payment link'}</Button></div>
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
