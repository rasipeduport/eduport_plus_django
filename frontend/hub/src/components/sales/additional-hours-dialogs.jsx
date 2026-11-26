import { useState } from 'react';
import { AlertTriangleIcon } from 'lucide-react';

import api from '@/lib/api';
import { firstMessage, salesError } from '@/lib/sales';
import { PAYMENT_TYPES, wholeAed } from '@/lib/payments';
import {
  DIRECT_METHODS, VOID_KINDS, additionalHoursEligibilityUrl, allocationPaymentsUrl, allocationStripeLinksUrl, allocationUrl,
  allocationVoidUrl, chapterLabel,
  classes, hours, requestKey, studentAdditionalHoursUrl, today,
} from '@/lib/additional-hours';
import { formatDate } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Skeleton } from '@/components/ui/skeleton';
import { Textarea } from '@/components/ui/textarea';
import { FormDialog } from '@/components/form-dialog';
import { ErrorState } from '@/components/page/states';

const SELECT = 'border-input bg-background h-9 w-full rounded-md border px-3 text-sm';

/** Reset a dialog's state each time it opens (not on every render). */
function useOnOpen(open, reset) {
  const [prevOpen, setPrevOpen] = useState(open);
  if (open !== prevOpen) {
    setPrevOpen(open);
    if (open) reset();
  }
}

function FieldError({ message }) {
  return message ? <p className="text-destructive text-sm">{message}</p> : null;
}

/** The API's field errors, each as its first message. */
const fieldErrors = (refused) => Object.fromEntries(Object.entries(refused.fields).map(([key, value]) => [key, firstMessage(value)]));

const PROBLEM_TITLES = {
  NOT_ELIGIBLE: 'Not eligible',
  NO_PLAN: 'No plan',
  PAID_CLASSES_NOT_CREDITED: 'Paid classes not added to the quota',
  PAYMENT_IN_PROGRESS: 'A plan payment is in progress',
  PLAN_CLASSES_UNPAID: 'A plan still has unpaid classes',
  QUOTA_MISMATCH: 'The class quota does not add up',
};

/** Why additional hours cannot be added now, as the API listed it: each reason with what it concerns. */
export function EligibilityProblems({ problems }) {
  return <ul aria-label="Why additional hours cannot be added" className="flex flex-col gap-3">
    {problems.map((problem) => <li key={problem.code} role="alert" className="border-destructive/30 bg-destructive/5 flex flex-col gap-1.5 rounded-lg border px-3 py-3 text-sm">
      <strong>{PROBLEM_TITLES[problem.code] ?? problem.code}</strong>
      <span>{problem.message}</span>
      {problem.payments?.length ? <ul className="text-muted-foreground flex flex-col gap-0.5 text-xs">{problem.payments.map((row) => <li key={row.payment_id}>
        {formatDate(row.payment_date)} · {wholeAed(row.amount)} · {classes(row.classes)} · {PAYMENT_TYPES[row.payment_type] ?? row.payment_type} · {row.quote_reference}
      </li>)}</ul> : null}
      {problem.code === 'PLAN_CLASSES_UNPAID' ? <ul className="text-muted-foreground flex flex-col gap-0.5 text-xs">{problem.plans.map((plan) => <li key={plan.quote_reference}>
        {plan.quote_reference} · {plan.syllabus} · {classes(plan.unpaid_classes)} unpaid · {wholeAed(plan.outstanding_amount)} outstanding{plan.autopay_status ? ' · on AutoPay' : ''}
      </li>)}</ul> : null}
      {problem.code === 'PAYMENT_IN_PROGRESS' ? <p className="text-muted-foreground text-xs">{problem.plans.join(', ')}</p> : null}
      {problem.quota ? <p className="text-muted-foreground text-xs">Quota {hours(problem.quota.quota)} · credited plan classes {classes(problem.quota.credited_plan_classes)} + additional {hours(problem.quota.additional_hours)} = {hours(problem.quota.expected_quota)}</p> : null}
    </li>)}
  </ul>;
}

function PlanChoice({ plan, checked, onChange }) {
  return <label className="has-checked:border-primary flex cursor-pointer items-start gap-3 rounded-lg border p-3 text-sm">
    <input type="radio" name="hours-plan" className="accent-primary mt-1" checked={checked} onChange={onChange} />
    <span className="min-w-0"><span className="block font-medium">{plan.kind_label} · {plan.quote_reference}</span>
      <span className="text-muted-foreground block text-xs">{plan.syllabus} · {plan.plan_type_label} · {classes(plan.classes)} · purchased {formatDate(plan.purchased_at)}</span>
      {Number(plan.additional_hours) > 0 ? <span className="text-muted-foreground block text-xs">{hours(plan.additional_hours)} already added against this plan</span> : null}</span>
  </label>;
}

const BLANK = { plan: '', chapter: '', hours: '', amount: '', due_date: '', reason: '' };

/**
 * An administrator adds hours to the student's quota at once, owed for by a
 * due date (POST students/<id>/additional-hours/). The form opens on the API's
 * eligibility: whatever keeps hours from being added -- paid classes never
 * credited, unpaid plan classes, a payment in progress, a quota that does not
 * add up -- is shown instead, as the API states it. The plan is one of the
 * student's purchases, the chapter one of its own and for reference only. The
 * API checks everything again; a likely duplicate is asked about once.
 */
export function AddHoursDialog({ studentId, student, open, onOpenChange, onCreated }) {
  const [eligibility, setEligibility] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [form, setForm] = useState(BLANK);
  const [key, setKey] = useState(requestKey);
  const [step, setStep] = useState('form');
  const [errors, setErrors] = useState({});
  const [error, setError] = useState('');
  const [duplicate, setDuplicate] = useState(null);
  const [further, setFurther] = useState(false);
  const [pending, setPending] = useState(false);

  const load = () => {
    setEligibility(null);
    setLoadError(null);
    api.get(additionalHoursEligibilityUrl(studentId))
      .then(({ data }) => {
        setEligibility(data);
        if (data.plans.length === 1) setForm((value) => ({ ...value, plan: data.plans[0].id }));
      })
      .catch((err) => setLoadError(salesError(err, 'Could not check whether hours can be added.')));
  };
  useOnOpen(open, () => {
    setForm(BLANK); setKey(requestKey()); setStep('form'); setErrors({}); setError(''); setDuplicate(null); setFurther(false);
    load();
  });

  const plan = eligibility?.plans.find((row) => row.id === form.plan) ?? null;
  const chapter = plan?.chapters.find((row) => row.id === form.chapter) ?? null;
  const set = (field) => (event) => setForm((value) => ({ ...value, [field]: event.target.value }));
  const filled = form.plan && form.hours && form.amount && form.due_date && form.reason.trim();
  const guide = plan && Number(form.hours) > 0 ? Math.round(Number(plan.rate_per_class) * Number(form.hours)) : null;
  const quotaAfter = eligibility?.quota && Number(form.hours) > 0 ? String(Number(eligibility.quota.quota) + Number(form.hours)) : null;

  const submit = async () => {
    setPending(true); setError('');
    try {
      const { data } = await api.post(studentAdditionalHoursUrl(studentId), {
        request_id: key, purchase: form.plan, chapter: form.chapter || null, hours: form.hours.trim(), amount: form.amount.trim(),
        due_date: form.due_date, reason: form.reason.trim(), confirm_duplicate: further,
      });
      onOpenChange(false);
      onCreated?.(data);
    } catch (err) {
      const refused = salesError(err, 'Could not add the hours.');
      if (refused.code === 'POSSIBLE_DUPLICATE') {
        setDuplicate(refused.message);
      } else if (refused.problems.length) {
        // Something changed since the form opened: the API's reasons replace the form.
        setEligibility((value) => ({ ...value, eligible: false, problems: refused.problems }));
      } else {
        if (refused.code === 'IDEMPOTENCY_CONFLICT') setKey(requestKey());
        const found = fieldErrors(refused);
        // A due date the API finds past belongs to its field, not the dialog.
        if (refused.code === 'DUE_DATE_PAST') found.due_date = refused.message;
        setErrors(found);
        setStep('form');
        setError(refused.code === 'DUE_DATE_PAST' ? '' : refused.message);
      }
    } finally {
      setPending(false);
    }
  };

  let body;
  if (loadError) body = <ErrorState message={loadError.message} onRetry={load} />;
  else if (!eligibility) body = <Skeleton className="h-40 w-full" aria-busy="true" />;
  else if (!eligibility.eligible) body = <EligibilityProblems problems={eligibility.problems} />;
  else if (step === 'form') {
    body = <form id="add-hours-form" className="grid gap-4" noValidate onSubmit={(event) => { event.preventDefault(); setDuplicate(null); setFurther(false); setStep('review'); }}>
      <fieldset className="grid gap-2"><legend className="mb-2 text-sm font-medium">Plan</legend>
        <div role="radiogroup" aria-label="Plan" className="flex flex-col gap-2">
          {eligibility.plans.map((row) => <PlanChoice key={row.id} plan={row} checked={form.plan === row.id}
            onChange={() => setForm((value) => ({ ...value, plan: row.id, chapter: '' }))} />)}
        </div>
        <FieldError message={errors.purchase} /></fieldset>
      <div className="grid gap-2"><Label htmlFor="hours-chapter">Chapter (for reference)</Label>
        <select id="hours-chapter" className={SELECT} value={form.chapter} onChange={set('chapter')} disabled={!plan}>
          <option value="">Not chapter-specific</option>
          {(plan?.chapters ?? []).map((row) => <option key={row.id} value={row.id}>{chapterLabel(row)}</option>)}
        </select>
        <p className="text-muted-foreground text-xs">Only records what the hours are for. They join the student’s overall quota, usable for any session.</p>
        <FieldError message={errors.chapter} /></div>
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="grid gap-2"><Label htmlFor="hours-hours">Additional hours</Label>
          <Input id="hours-hours" type="number" inputMode="decimal" step="0.5" min="0.5" value={form.hours} onChange={set('hours')} aria-invalid={errors.hours ? true : undefined} />
          <p className="text-muted-foreground text-xs">Quota hours, in half hours. 1 plan class = 1 hour of quota.</p>
          <FieldError message={errors.hours} /></div>
        <div className="grid gap-2"><Label htmlFor="hours-amount">Amount (whole AED)</Label>
          <Input id="hours-amount" type="number" inputMode="numeric" step="1" min="1" value={form.amount} onChange={set('amount')} aria-invalid={errors.amount ? true : undefined} />
          {guide != null ? <p className="text-muted-foreground text-xs">A guide only: at this plan’s {wholeAed(plan.rate_per_class)} a class, {wholeAed(guide)}.</p> : null}
          <FieldError message={errors.amount} /></div>
      </div>
      <div className="grid gap-2"><Label htmlFor="hours-due">Payment due date</Label>
        <Input id="hours-due" type="date" min={today()} value={form.due_date} onChange={set('due_date')} aria-invalid={errors.due_date ? true : undefined} />
        <p className="text-muted-foreground text-xs">When the amount should be collected. The hours can be booked as soon as they are added.</p>
        <FieldError message={errors.due_date} /></div>
      <div className="grid gap-2"><Label htmlFor="hours-reason">Reason</Label>
        <Textarea id="hours-reason" rows={3} maxLength={1000} value={form.reason} onChange={set('reason')} aria-invalid={errors.reason ? true : undefined} />
        <FieldError message={errors.reason} /></div>
    </form>;
  } else {
    body = <div className="grid gap-3">
      <dl className="grid grid-cols-[8rem_minmax(0,1fr)] gap-y-2 rounded-lg border px-3 py-3 text-sm">
        <dt className="text-muted-foreground">Student</dt><dd>{student ? `${student.full_name} · ${student.student_code}` : '—'}</dd>
        <dt className="text-muted-foreground">Plan</dt><dd>{plan ? `${plan.quote_reference} · ${plan.syllabus} · ${plan.plan_type_label}` : '—'}</dd>
        <dt className="text-muted-foreground">Chapter</dt><dd>{chapterLabel(chapter)}</dd>
        <dt className="text-muted-foreground">Hours</dt><dd>{hours(form.hours)}{quotaAfter ? ` · quota ${hours(eligibility.quota.quota)} → ${hours(quotaAfter)} now` : ''}</dd>
        <dt className="text-muted-foreground">Amount</dt><dd className="font-medium">{wholeAed(form.amount)} due by {formatDate(form.due_date)}</dd>
        <dt className="text-muted-foreground">Reason</dt><dd className="break-words">{form.reason.trim()}</dd>
      </dl>
      {duplicate ? <div role="alert" className="border-warning/40 bg-warning/10 grid gap-2 rounded-lg border px-3 py-3 text-sm">
        <p className="flex items-center gap-2 font-medium"><AlertTriangleIcon className="text-warning size-4" aria-hidden="true" />Possible duplicate</p>
        <p>{duplicate}</p>
        <label className="flex items-center gap-2 font-medium"><input type="checkbox" className="accent-primary size-4" checked={further} onChange={(event) => setFurther(event.target.checked)} />These are further hours</label>
      </div> : null}
    </div>;
  }

  const ready = eligibility?.eligible;
  return <Dialog open={open} onOpenChange={(next) => !pending && onOpenChange(next)}>
    <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-lg">
      <DialogHeader>
        <DialogTitle>{step === 'review' && ready ? 'Add these hours now?' : 'Add additional hours'}</DialogTitle>
        <DialogDescription>{step === 'review' && ready
          ? 'The hours join the quota as soon as you confirm; the amount is collected later, by its due date.'
          : 'New hours with a new charge, on top of the student’s plans. Payments are recorded against them separately.'}</DialogDescription>
      </DialogHeader>
      {body}
      {error ? <p role="alert" className="text-destructive text-sm">{error}</p> : null}
      <DialogFooter>
        {!ready ? <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>Close</Button>
          : step === 'form' ? <>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
            <Button type="submit" form="add-hours-form" disabled={!filled}>Review</Button>
          </> : <>
            <Button type="button" variant="outline" onClick={() => setStep('form')} disabled={pending}>Back</Button>
            <Button type="button" onClick={submit} disabled={pending || (duplicate && !further)}>{pending ? 'Adding…' : 'Add hours'}</Button>
          </>}
      </DialogFooter>
    </DialogContent>
  </Dialog>;
}

/**
 * Money received for the hours, with its receipt (POST additional-hours/<id>/payments/): part or all of what is
 * still due -- the API refuses more. Recording a payment never changes the quota. A likely duplicate is asked
 * about once; the form's own key makes a repeated submission record it once.
 */
export function RecordHoursPaymentDialog({ allocation, open, onOpenChange, onSaved }) {
  const blank = { amount: '', method: DIRECT_METHODS[0].value, payment_date: today(), reference: '', notes: '' };
  const [form, setForm] = useState(blank);
  const [proof, setProof] = useState(null);
  const [confirmed, setConfirmed] = useState(false);
  const [key, setKey] = useState(requestKey);
  const [errors, setErrors] = useState({});
  const [error, setError] = useState('');
  const [duplicate, setDuplicate] = useState(null);
  const [separate, setSeparate] = useState(false);
  const [pending, setPending] = useState(false);
  useOnOpen(open, () => {
    setForm(blank); setProof(null); setConfirmed(false); setKey(requestKey()); setErrors({}); setError(''); setDuplicate(null); setSeparate(false);
  });
  const set = (field) => (event) => { setForm((value) => ({ ...value, [field]: event.target.value })); setDuplicate(null); setSeparate(false); };

  const submit = async (event) => {
    event.preventDefault();
    setPending(true); setError(''); setErrors({});
    const body = new FormData();
    for (const [field, value] of Object.entries({ request_id: key, amount: form.amount.trim(), method: form.method, payment_date: form.payment_date,
      transaction_reference: form.reference.trim(), notes: form.notes.trim(), received_confirmed: confirmed, confirm_duplicate: separate })) {
      body.append(field, String(value));
    }
    body.append('proof', proof);
    try {
      const { data } = await api.post(allocationPaymentsUrl(allocation.id), body);
      onOpenChange(false);
      onSaved?.(data.allocation);
    } catch (err) {
      const refused = salesError(err, 'Could not record the payment.');
      if (refused.code === 'POSSIBLE_DUPLICATE') {
        setDuplicate(refused.message);
      } else {
        if (refused.code === 'IDEMPOTENCY_CONFLICT') setKey(requestKey());
        const found = fieldErrors(refused);
        if (refused.code === 'DUPLICATE_REFERENCE') found.transaction_reference = refused.message;
        else if (refused.code === 'EXCEEDS_OUTSTANDING') found.amount = refused.message;
        setErrors(found);
        setError(refused.message);
      }
    } finally {
      setPending(false);
    }
  };

  const outstanding = allocation?.outstanding_amount;
  return <Dialog open={open} onOpenChange={(next) => !pending && onOpenChange(next)}>
    <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-lg">
      <DialogHeader>
        <DialogTitle>Record payment</DialogTitle>
        <DialogDescription>{allocation ? `${allocation.reference} · ${hours(allocation.hours)} · ${wholeAed(outstanding)} still due. ` : ''}Record money already received; the student’s quota does not change.</DialogDescription>
      </DialogHeader>
      <form id="hours-payment-form" className="grid gap-4" noValidate onSubmit={submit}>
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="grid gap-2"><Label htmlFor="hours-payment-amount">Amount received (whole AED)</Label>
            <Input id="hours-payment-amount" type="number" inputMode="numeric" step="1" min="1" value={form.amount} onChange={set('amount')} aria-invalid={errors.amount ? true : undefined} />
            <button type="button" className="text-link self-start text-xs underline-offset-4 hover:underline" onClick={() => setForm((value) => ({ ...value, amount: String(outstanding) }))}>
              Pay the full {wholeAed(outstanding)} still due</button>
            <FieldError message={errors.amount} /></div>
          <div className="grid gap-2"><Label htmlFor="hours-payment-date">Payment date</Label>
            <Input id="hours-payment-date" type="date" max={today()} value={form.payment_date} onChange={set('payment_date')} aria-invalid={errors.payment_date ? true : undefined} />
            <FieldError message={errors.payment_date} /></div>
        </div>
        <div className="grid gap-2"><Label htmlFor="hours-payment-method">Payment method</Label>
          <select id="hours-payment-method" className={SELECT} value={form.method} onChange={set('method')}>
            {DIRECT_METHODS.map((method) => <option key={method.value} value={method.value}>{method.label}</option>)}
          </select></div>
        <div className="grid gap-2"><Label htmlFor="hours-payment-proof">Payment screenshot / receipt</Label>
          <Input id="hours-payment-proof" type="file" accept="application/pdf,image/png,image/jpeg,image/webp" onChange={(event) => setProof(event.target.files?.[0] ?? null)} />
          <FieldError message={errors.proof} /></div>
        <div className="grid gap-2"><Label htmlFor="hours-payment-reference">Transaction reference (optional)</Label>
          <Input id="hours-payment-reference" maxLength={255} value={form.reference} onChange={set('reference')} aria-invalid={errors.transaction_reference ? true : undefined} />
          <FieldError message={errors.transaction_reference} /></div>
        <div className="grid gap-2"><Label htmlFor="hours-payment-notes">Notes (optional)</Label>
          <Textarea id="hours-payment-notes" rows={2} maxLength={1000} value={form.notes} onChange={set('notes')} /></div>
        <label className="flex items-start gap-2 text-sm"><input type="checkbox" className="accent-primary mt-1" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} />I confirm this amount has actually been received.</label>
        {duplicate ? <div role="alert" className="border-warning/40 bg-warning/10 grid gap-2 rounded-lg border px-3 py-3 text-sm">
          <p className="flex items-center gap-2 font-medium"><AlertTriangleIcon className="text-warning size-4" aria-hidden="true" />Possible duplicate</p>
          <p>{duplicate}</p>
          <label className="flex items-center gap-2 font-medium"><input type="checkbox" className="accent-primary size-4" checked={separate} onChange={(event) => setSeparate(event.target.checked)} />This is a separate payment</label>
        </div> : null}
      </form>
      {error ? <p role="alert" className="text-destructive text-sm">{error}</p> : null}
      <DialogFooter>
        <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={pending}>Cancel</Button>
        <Button type="submit" form="hours-payment-form" disabled={pending || !form.amount || !proof || !confirmed || (duplicate && !separate)}>
          {pending ? 'Recording…' : 'Record payment'}</Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>;
}

/** An administrator changes an open allocation's due date and/or amount (never below what is paid), with the reason. */
export function ChangeHoursDialog({ allocation, open, onOpenChange, onSaved }) {
  const [form, setForm] = useState({ due_date: '', amount: '', reason: '' });
  const [errors, setErrors] = useState({});
  const [error, setError] = useState('');
  const [pending, setPending] = useState(false);
  useOnOpen(open, () => {
    setForm({ due_date: allocation?.due_date ?? '', amount: allocation?.amount ?? '', reason: '' }); setErrors({}); setError('');
  });
  const set = (field) => (event) => setForm((value) => ({ ...value, [field]: event.target.value }));
  const changes = {};
  if (allocation && form.due_date && form.due_date !== allocation.due_date) changes.due_date = form.due_date;
  if (allocation && form.amount && form.amount.trim() !== allocation.amount) changes.amount = form.amount.trim();

  const save = async (event) => {
    event.preventDefault();
    setPending(true); setError(''); setErrors({});
    try {
      const { data } = await api.patch(allocationUrl(allocation.id), { ...changes, change_reason: form.reason.trim() });
      onOpenChange(false);
      onSaved?.(data);
    } catch (err) {
      const refused = salesError(err, 'Could not save the change.');
      const found = fieldErrors(refused);
      if (refused.code === 'AMOUNT_BELOW_PAID') found.amount = refused.message;
      if (refused.code === 'DUE_DATE_PAST') found.due_date = refused.message;
      setErrors(found);
      // A due date the API finds past is shown under its field only.
      setError(refused.code === 'DUE_DATE_PAST' ? '' : refused.message);
    } finally {
      setPending(false);
    }
  };
  return <FormDialog open={open} onOpenChange={(next) => !pending && onOpenChange(next)} size="md" title="Change due date or amount"
    description={allocation ? `${allocation.reference} · ${wholeAed(allocation.paid_amount)} paid so far. The hours themselves never change.` : ''}
    formId="change-hours-form" confirmLabel="Save change" pending={pending} error={error}
    confirmDisabled={!Object.keys(changes).length || !form.reason.trim()}>
    <form id="change-hours-form" className="grid gap-4" noValidate onSubmit={save}>
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="grid gap-2"><Label htmlFor="change-hours-due">Payment due date</Label>
          <Input id="change-hours-due" type="date" min={today()} value={form.due_date} onChange={set('due_date')} />
          <FieldError message={errors.due_date} /></div>
        <div className="grid gap-2"><Label htmlFor="change-hours-amount">Amount (whole AED)</Label>
          <Input id="change-hours-amount" type="number" inputMode="numeric" step="1" min="1" value={form.amount} onChange={set('amount')} />
          <FieldError message={errors.amount} /></div>
      </div>
      <div className="grid gap-2"><Label htmlFor="change-hours-reason">Reason for the change</Label>
        <Textarea id="change-hours-reason" rows={3} maxLength={1000} value={form.reason} onChange={set('reason')} />
        <FieldError message={errors.change_reason} /></div>
    </form>
  </FormDialog>;
}

const CLOSINGS = {
  waive: { title: 'Waive what is still due', confirm: 'Waive', pending: 'Waiving…',
    description: (row) => `${row.reference}: ${wholeAed(row.outstanding_amount)} is written off. The ${hours(row.hours)} stay in the quota, and the allocation takes no further payment.` },
  withdraw: { title: 'Withdraw the hours', confirm: 'Withdraw hours', pending: 'Withdrawing…',
    description: (row) => `${row.reference}: the ${hours(row.hours)} leave the quota again. Only unbooked hours with no payment that still counts can be withdrawn.` },
};

/** An administrator closes an allocation: waive (the hours stay) or withdraw (the hours go), with the reason. */
export function CloseHoursDialog({ allocation, closing, open, onOpenChange, onSaved }) {
  const [reason, setReason] = useState('');
  const [error, setError] = useState('');
  const [pending, setPending] = useState(false);
  useOnOpen(open, () => { setReason(''); setError(''); });
  const words = CLOSINGS[closing] ?? CLOSINGS.waive;
  const save = async () => {
    setPending(true); setError('');
    try {
      const { data } = await api.post(`${allocationUrl(allocation.id)}${closing}/`, { reason: reason.trim() });
      onOpenChange(false);
      onSaved?.(data);
    } catch (err) {
      setError(salesError(err, 'Could not save this.').message);
    } finally {
      setPending(false);
    }
  };
  return <FormDialog open={open} onOpenChange={(next) => !pending && onOpenChange(next)} size="md" title={words.title}
    description={allocation ? words.description(allocation) : ''} onConfirm={save} confirmLabel={words.confirm} pendingLabel={words.pending}
    confirmVariant="destructive" confirmDisabled={!reason.trim()} pending={pending} error={error}>
    <div className="grid gap-2"><Label htmlFor="close-hours-reason">Reason</Label>
      <Textarea id="close-hours-reason" rows={3} maxLength={1000} value={reason} onChange={(event) => setReason(event.target.value)} /></div>
  </FormDialog>;
}

/** An administrator voids a payment, with its kind and reason: it stays in the history, stops counting, and the balance reopens. */
export function VoidHoursPaymentDialog({ allocation, payment, open, onOpenChange, onSaved }) {
  const [kind, setKind] = useState(VOID_KINDS[0].value);
  const [reason, setReason] = useState('');
  const [error, setError] = useState('');
  const [pending, setPending] = useState(false);
  useOnOpen(open, () => { setKind(VOID_KINDS[0].value); setReason(''); setError(''); });
  const save = async () => {
    setPending(true); setError('');
    try {
      const { data } = await api.post(allocationVoidUrl(allocation.id, payment.id), { kind, reason: reason.trim() });
      onOpenChange(false);
      onSaved?.(data);
    } catch (err) {
      setError(salesError(err, 'Could not void the payment.').message);
    } finally {
      setPending(false);
    }
  };
  return <FormDialog open={open} onOpenChange={(next) => !pending && onOpenChange(next)} size="md" title="Void payment"
    description={payment ? `${wholeAed(payment.amount)} recorded on ${formatDate(payment.payment_date)} stops counting and ${wholeAed(payment.amount)} is due again. Voiding is final; the payment stays in the history.` : ''}
    onConfirm={save} confirmLabel="Void payment" pendingLabel="Voiding…" confirmVariant="destructive" confirmDisabled={!reason.trim()} pending={pending} error={error}>
    <div className="grid gap-2"><Label htmlFor="void-hours-kind">Why it no longer counts</Label>
      <select id="void-hours-kind" className={SELECT} value={kind} onChange={(event) => setKind(event.target.value)}>
        {VOID_KINDS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
      </select></div>
    <div className="grid gap-2"><Label htmlFor="void-hours-reason">Reason</Label>
      <Textarea id="void-hours-reason" rows={3} maxLength={1000} value={reason} onChange={(event) => setReason(event.target.value)} /></div>
  </FormDialog>;
}

/**
 * A Stripe Checkout link for the hours (POST additional-hours/<id>/stripe-links/): for all that is still due,
 * or part of it -- the API refuses more. The parent pays on Stripe; only Stripe's verified webhook records the
 * payment. The form's own key makes a repeated request return the same link, never a second one. When Stripe
 * does not confirm the link in time, `onRefresh` shows the attempt so it can be tried again.
 */
export function GenerateStripeLinkDialog({ allocation, open, onOpenChange, onSaved, onRefresh }) {
  const [amount, setAmount] = useState('');
  const [key, setKey] = useState(requestKey);
  const [errors, setErrors] = useState({});
  const [error, setError] = useState('');
  const [pending, setPending] = useState(false);
  useOnOpen(open, () => { setAmount(allocation?.outstanding_amount ?? ''); setKey(requestKey()); setErrors({}); setError(''); });

  const save = async (event) => {
    event.preventDefault();
    setPending(true); setError(''); setErrors({});
    try {
      const { data } = await api.post(allocationStripeLinksUrl(allocation.id), { request_id: key, amount: amount.trim() });
      onOpenChange(false);
      onSaved?.(data.allocation);
    } catch (err) {
      const refused = salesError(err, 'Could not create the payment link.');
      const found = fieldErrors(refused);
      if (refused.code === 'EXCEEDS_OUTSTANDING') found.amount = refused.message;
      if (refused.code === 'IDEMPOTENCY_CONFLICT') setKey(requestKey());
      setErrors(found);
      setError(refused.code === 'EXCEEDS_OUTSTANDING' ? '' : refused.message);
      // Stripe may have made it (or another link is open): show the hours as they now stand.
      if (['STRIPE_UNAVAILABLE', 'STRIPE_LINK_OPEN', 'CHECKOUT_REVIEW_REQUIRED'].includes(refused.code)) onRefresh?.();
    } finally {
      setPending(false);
    }
  };
  return <FormDialog open={open} onOpenChange={(next) => !pending && onOpenChange(next)} size="md" title="Generate Stripe payment link"
    description={allocation ? `${allocation.reference} · ${wholeAed(allocation.outstanding_amount)} still due. The parent pays by card on Stripe; the payment is recorded only when Stripe confirms it, and the student’s quota does not change.` : ''}
    formId="stripe-link-form" confirmLabel="Generate link" pendingLabel="Generating…" pending={pending} error={error} confirmDisabled={!amount}>
    <form id="stripe-link-form" className="grid gap-2" noValidate onSubmit={save}>
      <Label htmlFor="stripe-link-amount">Amount (whole AED)</Label>
      <Input id="stripe-link-amount" type="number" inputMode="numeric" step="1" min="1" value={amount} onChange={(event) => setAmount(event.target.value)}
        aria-invalid={errors.amount ? true : undefined} />
      <p className="text-muted-foreground text-xs">All that is still due by default; a smaller amount leaves the rest to collect later.</p>
      <FieldError message={errors.amount} />
    </form>
  </FormDialog>;
}
