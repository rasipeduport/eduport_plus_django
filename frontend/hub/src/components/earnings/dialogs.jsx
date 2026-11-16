import { useState } from 'react';
import { AlertTriangleIcon, ShieldAlertIcon } from 'lucide-react';

import api from '@/lib/api';
import {
  CLASS_TYPES,
  EARNINGS_API,
  PAYMENT_METHODS,
  classSubject,
  classTypeLabel,
  dayLabel,
  earningsError,
  formatInr,
  indiaToday,
  monthLabel,
  rateLabel,
  requestKey,
  reviewDetail,
} from '@/lib/earnings';
import { FormDialog } from '@/components/form-dialog';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';

// An amount in rupees as typed: digits, and at most two decimals.
const AMOUNT_RE = /^\s*\d+(\.\d{1,2})?\s*$/;

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

function ReasonField({ id, value, onChange, disabled, label = 'Reason', hint }) {
  return (
    <div className="grid gap-2">
      <Label htmlFor={id} required>
        {label}
      </Label>
      <Textarea id={id} value={value} onChange={(event) => onChange(event.target.value)} rows={3} maxLength={500} disabled={disabled} aria-required="true" />
      {hint ? <p className="text-muted-foreground text-xs">{hint}</p> : null}
    </div>
  );
}

const nameOf = (tutor) => tutor?.name || tutor?.email || 'this tutor';

/**
 * Record a payment already made to `tutor` outside Eduport Plus (POST
 * /api/earnings/tutors/<id>/payments/): the amount (at most `outstanding`,
 * partial payments welcome), its date, method and reference, then a review
 * before it is recorded. The dialog's own request key makes a repeated
 * submission record it once. The API refuses a reference another payment
 * still counting has, and asks for a confirmation when the same amount was
 * recorded for the tutor that day. `onSaved(answer)` gets the API's answer.
 */
export function RecordPaymentDialog({ tutor, outstanding, open, onOpenChange, onSaved }) {
  const blank = { amount: '', paid_on: indiaToday(), method: 'ACCOUNT_TRANSFER', reference: '', notes: '' };
  const [form, setForm] = useState(blank);
  const [key, setKey] = useState(requestKey);
  const [step, setStep] = useState('form');
  const [errors, setErrors] = useState({});
  const [error, setError] = useState('');
  const [duplicate, setDuplicate] = useState(null);
  const [separate, setSeparate] = useState(false);
  const [pending, setPending] = useState(false);
  useOnOpen(open, () => {
    setForm(blank);
    setKey(requestKey());
    setStep('form');
    setErrors({});
    setError('');
    setDuplicate(null);
    setSeparate(false);
  });

  const owed = Number(outstanding);
  const set = (field) => (event) => setForm((value) => ({ ...value, [field]: event.target.value }));

  const check = () => {
    const found = {};
    if (!AMOUNT_RE.test(form.amount) || !(Number(form.amount) > 0)) found.amount = 'Enter the amount in rupees, such as 7625 or 7625.50.';
    else if (Number(form.amount) > owed) found.amount = `The payment can be at most the ${formatInr(owed)} outstanding.`;
    if (!form.paid_on) found.paid_on = 'Enter the payment date.';
    else if (form.paid_on > indiaToday()) found.paid_on = 'The payment date cannot be in the future.';
    if (!/[A-Za-z0-9]/.test(form.reference)) found.reference = 'Enter the bank UTR or the UPI transaction ID.';
    return found;
  };

  const review = (event) => {
    event.preventDefault();
    const found = check();
    setErrors(found);
    setError(Object.keys(found).length ? 'Check the highlighted fields.' : '');
    if (!Object.keys(found).length) {
      // A payment changed since the API asked about a duplicate is asked about afresh.
      setDuplicate(null);
      setSeparate(false);
      setStep('confirm');
    }
  };

  const record = async () => {
    setPending(true);
    setError('');
    try {
      const response = await api.post(`${EARNINGS_API}/tutors/${tutor.id}/payments/`, {
        request_id: key,
        amount: form.amount.trim(),
        paid_on: form.paid_on,
        method: form.method,
        reference: form.reference.trim(),
        notes: form.notes.trim(),
        confirm_duplicate: separate,
      });
      onOpenChange(false);
      onSaved?.(response.data);
    } catch (err) {
      const refused = earningsError(err, 'Could not record the payment.');
      if (refused.code === 'POSSIBLE_DUPLICATE') {
        setDuplicate(refused.message);
      } else if (refused.code === 'DUPLICATE_REFERENCE' || (refused.code === 'INVALID_INPUT' && refused.field)) {
        setStep('form');
        setErrors({ [refused.field || 'reference']: refused.message });
        setError('Check the highlighted fields.');
      } else {
        if (refused.code === 'IDEMPOTENCY_CONFLICT') setKey(requestKey());
        setError(refused.message);
      }
    } finally {
      setPending(false);
    }
  };

  const after = owed - Number(form.amount || 0);
  const method = PAYMENT_METHODS.find((item) => item.value === form.method)?.label;

  return (
    <Dialog open={open} onOpenChange={(next) => !pending && onOpenChange(next)}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{step === 'form' ? 'Record payment' : `Record ${formatInr(form.amount)} for ${nameOf(tutor)}?`}</DialogTitle>
          <DialogDescription>
            {step === 'form'
              ? `${nameOf(tutor)} · ${formatInr(owed)} outstanding. Record a payment already made; nothing is transferred from here.`
              : 'A recorded payment cannot be edited or deleted; one recorded by mistake is voided, with a reason.'}
          </DialogDescription>
        </DialogHeader>

        {step === 'form' ? (
          <form id="record-payment-form" onSubmit={review} className="grid gap-4" noValidate>
            <div className="grid gap-2">
              <Label htmlFor="payment-amount" required>
                Amount (₹)
              </Label>
              <Input
                id="payment-amount"
                inputMode="decimal"
                value={form.amount}
                onChange={set('amount')}
                aria-invalid={errors.amount ? true : undefined}
                aria-required="true"
              />
              <button
                type="button"
                className="text-link self-start text-xs underline-offset-4 hover:underline"
                onClick={() => setForm((value) => ({ ...value, amount: owed.toFixed(2).replace(/\.00$/, '') }))}
              >
                Pay the full outstanding balance ({formatInr(owed)})
              </button>
              <FieldError message={errors.amount} />
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="grid gap-2">
                <Label htmlFor="payment-date" required>
                  Payment date
                </Label>
                <Input
                  id="payment-date"
                  type="date"
                  max={indiaToday()}
                  value={form.paid_on}
                  onChange={set('paid_on')}
                  aria-invalid={errors.paid_on ? true : undefined}
                />
                <FieldError message={errors.paid_on} />
              </div>
              <div className="grid gap-2">
                <Label htmlFor="payment-method" required>
                  Payment method
                </Label>
                <Select value={form.method} onValueChange={(value) => setForm((current) => ({ ...current, method: value }))}>
                  <SelectTrigger id="payment-method" className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {PAYMENT_METHODS.map((item) => (
                      <SelectItem key={item.value} value={item.value}>
                        {item.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
            <div className="grid gap-2">
              <Label htmlFor="payment-reference" required>
                Reference
              </Label>
              <Input
                id="payment-reference"
                value={form.reference}
                onChange={set('reference')}
                maxLength={100}
                aria-invalid={errors.reference ? true : undefined}
                aria-required="true"
              />
              <p className="text-muted-foreground text-xs">
                Bank UTR or UPI transaction ID. No two payments still counting share one.
              </p>
              <FieldError message={errors.reference} />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="payment-notes">Notes (optional)</Label>
              <Textarea id="payment-notes" value={form.notes} onChange={set('notes')} rows={2} maxLength={1000} />
            </div>
            <p className="bg-muted/50 flex justify-between rounded-lg px-3 py-2 text-sm">
              <span className="text-muted-foreground">Outstanding {formatInr(owed)} → after this payment</span>
              <strong className="tabular-nums">{AMOUNT_RE.test(form.amount) ? formatInr(after) : '—'}</strong>
            </p>
          </form>
        ) : (
          <div className="grid gap-3">
            <dl className="grid grid-cols-[8rem_minmax(0,1fr)] gap-y-2 rounded-lg border px-3 py-3 text-sm">
              <dt className="text-muted-foreground">Payment date</dt>
              <dd>{dayLabel(form.paid_on)}</dd>
              <dt className="text-muted-foreground">Method</dt>
              <dd>{method}</dd>
              <dt className="text-muted-foreground">Reference</dt>
              <dd className="font-mono text-xs break-all">{form.reference.trim()}</dd>
              {form.notes.trim() ? (
                <>
                  <dt className="text-muted-foreground">Notes</dt>
                  <dd>{form.notes.trim()}</dd>
                </>
              ) : null}
              <dt className="text-muted-foreground">Balance after</dt>
              <dd className="font-medium">{after === 0 ? `${formatInr(0)} · paid in full` : formatInr(after)}</dd>
            </dl>
            {duplicate ? (
              <div role="alert" className="border-warning/40 bg-warning/10 grid gap-2 rounded-lg border px-3 py-3 text-sm">
                <p className="flex items-center gap-2 font-medium">
                  <AlertTriangleIcon className="text-warning size-4" aria-hidden="true" />
                  Possible duplicate
                </p>
                <p>{duplicate}</p>
                <label className="flex items-center gap-2 font-medium">
                  <input
                    type="checkbox"
                    className="accent-primary size-4"
                    checked={separate}
                    onChange={(event) => setSeparate(event.target.checked)}
                  />
                  This is a separate payment
                </label>
              </div>
            ) : null}
          </div>
        )}

        {error ? <p className="text-destructive text-sm">{error}</p> : null}

        <DialogFooter>
          {step === 'form' ? (
            <>
              <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
                Cancel
              </Button>
              <Button type="submit" form="record-payment-form" disabled={!(owed > 0)}>
                Review payment
              </Button>
            </>
          ) : (
            <>
              <Button type="button" variant="outline" onClick={() => setStep('form')} disabled={pending}>
                Back
              </Button>
              <Button type="button" onClick={record} disabled={pending || (duplicate && !separate)}>
                {pending ? 'Recording…' : 'Record payment'}
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** Void a payment recorded by mistake (POST /api/earnings/payments/<id>/void/), with the reason: final. */
export function VoidPaymentDialog({ payment, tutorName, open, onOpenChange, onSaved }) {
  const [reason, setReason] = useState('');
  const [error, setError] = useState('');
  const [pending, setPending] = useState(false);
  useOnOpen(open, () => {
    setReason('');
    setError('');
  });

  const confirm = async () => {
    setPending(true);
    setError('');
    try {
      const response = await api.post(`${EARNINGS_API}/payments/${payment.id}/void/`, { reason: reason.trim() });
      onOpenChange(false);
      onSaved?.(response.data);
    } catch (err) {
      setError(earningsError(err, 'Could not void the payment.').message);
    } finally {
      setPending(false);
    }
  };

  return (
    <FormDialog
      open={open}
      onOpenChange={(next) => !pending && onOpenChange(next)}
      title={payment ? `Void ${formatInr(payment.amount)} paid to ${tutorName}?` : 'Void payment'}
      description="The payment stays in the history marked Voided and no longer counts as paid; its reference can be used again. Voiding is final."
      error={error}
      onConfirm={confirm}
      confirmLabel="Void payment"
      pendingLabel="Voiding…"
      confirmVariant="destructive"
      confirmDisabled={!reason.trim()}
      pending={pending}
      size="md"
    >
      {payment ? (
        <dl className="grid grid-cols-[8rem_minmax(0,1fr)] gap-y-2 rounded-lg border px-3 py-3 text-sm">
          <dt className="text-muted-foreground">Payment date</dt>
          <dd>{dayLabel(payment.paid_on)}</dd>
          <dt className="text-muted-foreground">Method</dt>
          <dd>{payment.method_label}</dd>
          <dt className="text-muted-foreground">Reference</dt>
          <dd className="font-mono text-xs break-all">{payment.reference}</dd>
        </dl>
      ) : null}
      <ReasonField id="void-reason" value={reason} onChange={setReason} disabled={pending} />
    </FormDialog>
  );
}

/**
 * Reverse an earning or an adjustment in full (POST
 * /api/earnings/entries/<id>/reverse/), with the reason the tutor sees too.
 * The line stays, marked reversed; a reversed earning's class is never
 * earned again automatically.
 */
export function ReverseEntryDialog({ entry, tutorName, open, onOpenChange, onSaved }) {
  const [reason, setReason] = useState('');
  const [error, setError] = useState('');
  const [pending, setPending] = useState(false);
  useOnOpen(open, () => {
    setReason('');
    setError('');
  });

  const confirm = async () => {
    setPending(true);
    setError('');
    try {
      const response = await api.post(`${EARNINGS_API}/entries/${entry.id}/reverse/`, { reason: reason.trim() });
      onOpenChange(false);
      onSaved?.(response.data);
    } catch (err) {
      setError(earningsError(err, 'Could not reverse it.').message);
    } finally {
      setPending(false);
    }
  };

  const earning = entry?.kind === 'EARNING';
  return (
    <FormDialog
      open={open}
      onOpenChange={(next) => !pending && onOpenChange(next)}
      title={entry ? `Reverse ${formatInr(entry.amount)} for ${tutorName}?` : 'Reverse'}
      description={
        earning
          ? `Adds a ${formatInr(-Number(entry?.amount || 0))} reversal in ${monthLabel(entry?.month)}. The earning stays, marked reversed, and its class is never earned again automatically.`
          : `Adds a reversal of this adjustment in ${monthLabel(entry?.month)}. The adjustment stays, marked reversed.`
      }
      error={error}
      onConfirm={confirm}
      confirmLabel={earning ? 'Reverse earning' : 'Reverse adjustment'}
      pendingLabel="Reversing…"
      confirmVariant="destructive"
      confirmDisabled={!reason.trim()}
      pending={pending}
      size="md"
    >
      {entry && entry.class_type ? (
        <p className="rounded-lg border px-3 py-2 text-sm">
          {classTypeLabel(entry.class_type, { singular: true })} · {classSubject(entry)} · {dayLabel(entry.class_start)}
          {entry.rate ? ` · ${rateLabel(entry.rate, entry.unit)}` : ''}
        </p>
      ) : null}
      <ReasonField id="reverse-reason" value={reason} onChange={setReason} disabled={pending} hint="The tutor sees this reason." />
    </FormDialog>
  );
}

/**
 * Add to or deduct from `tutor`'s earnings (POST
 * /api/earnings/tutors/<id>/adjustments/) in a month since the activation,
 * optionally about one of their classes (`entries`: earnings to pick from),
 * with the reason the tutor sees too. An adjustment is never edited: a
 * mistaken one is reversed.
 */
export function AdjustmentDialog({ tutor, months, entries, open, onOpenChange, onSaved }) {
  const [direction, setDirection] = useState('add');
  const [amount, setAmount] = useState('');
  const [month, setMonth] = useState('');
  const [about, setAbout] = useState('');
  const [reason, setReason] = useState('');
  const [error, setError] = useState('');
  const [pending, setPending] = useState(false);
  useOnOpen(open, () => {
    setDirection('add');
    setAmount('');
    setMonth(months?.[0] || '');
    setAbout('');
    setReason('');
    setError('');
  });

  const valid = AMOUNT_RE.test(amount) && Number(amount) > 0 && reason.trim() && month;
  const classes = (entries || []).filter((entry) => entry.kind === 'EARNING');

  const confirm = async () => {
    setPending(true);
    setError('');
    try {
      const signed = `${direction === 'deduct' ? '-' : ''}${amount.trim()}`;
      const response = await api.post(`${EARNINGS_API}/tutors/${tutor.id}/adjustments/`, {
        amount: signed,
        month,
        reason: reason.trim(),
        entry: about || null,
      });
      onOpenChange(false);
      onSaved?.(response.data);
    } catch (err) {
      setError(earningsError(err, 'Could not add the adjustment.').message);
    } finally {
      setPending(false);
    }
  };

  return (
    <FormDialog
      open={open}
      onOpenChange={(next) => !pending && onOpenChange(next)}
      title={`Adjustment for ${nameOf(tutor)}`}
      description="Added to the ledger with its reason, never edited: a mistaken adjustment is reversed."
      error={error}
      onConfirm={confirm}
      confirmLabel="Add adjustment"
      pendingLabel="Adding…"
      confirmDisabled={!valid}
      pending={pending}
      size="md"
    >
      <fieldset className="flex gap-5 text-sm" disabled={pending}>
        <legend className="mb-2 text-sm font-medium">Direction</legend>
        {[
          ['add', 'Add to earnings'],
          ['deduct', 'Deduct from earnings'],
        ].map(([value, label]) => (
          <label key={value} className="flex items-center gap-2">
            <input type="radio" name="adjustment-direction" className="accent-primary size-4" checked={direction === value} onChange={() => setDirection(value)} />
            {label}
          </label>
        ))}
      </fieldset>
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="grid gap-2">
          <Label htmlFor="adjustment-amount" required>
            Amount (₹)
          </Label>
          <Input id="adjustment-amount" inputMode="decimal" value={amount} onChange={(event) => setAmount(event.target.value)} disabled={pending} />
        </div>
        <div className="grid gap-2">
          <Label htmlFor="adjustment-month" required>
            Counts in
          </Label>
          <Select value={month} onValueChange={setMonth} disabled={pending}>
            <SelectTrigger id="adjustment-month" className="w-full">
              <SelectValue placeholder="Month" />
            </SelectTrigger>
            <SelectContent>
              {(months || []).map((value) => (
                <SelectItem key={value} value={value}>
                  {monthLabel(value)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>
      {classes.length ? (
        <div className="grid gap-2">
          <Label htmlFor="adjustment-class">Class (optional)</Label>
          <Select value={about || '__none__'} onValueChange={(value) => setAbout(value === '__none__' ? '' : value)} disabled={pending}>
            <SelectTrigger id="adjustment-class" className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="__none__">No particular class</SelectItem>
              {classes.map((entry) => (
                <SelectItem key={entry.id} value={entry.id}>
                  {classTypeLabel(entry.class_type, { singular: true })} · {classSubject(entry)} · {dayLabel(entry.class_start)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      ) : null}
      <ReasonField id="adjustment-reason" value={reason} onChange={setReason} disabled={pending} hint="The tutor sees this reason." />
    </FormDialog>
  );
}

/**
 * A tutor's own rates (POST /api/earnings/tutors/<id>/rates/): per class type
 * the global rate or one of their own, with the reason. In effect from the
 * save, for the classes ending from then on; earned classes keep their rate.
 */
export function TutorRatesDialog({ tutor, rates, open, onOpenChange, onSaved }) {
  const fromRates = () =>
    Object.fromEntries(
      (rates || []).map((row) => [
        row.class_type,
        { mode: row.source === 'TUTOR' ? 'tutor' : 'global', amount: row.source === 'TUTOR' ? trimAmount(row.amount) : '' },
      ])
    );
  const [form, setForm] = useState(fromRates);
  const [reason, setReason] = useState('');
  const [error, setError] = useState('');
  const [pending, setPending] = useState(false);
  useOnOpen(open, () => {
    setForm(fromRates());
    setReason('');
    setError('');
  });

  const changes = {};
  let invalid = false;
  for (const row of rates || []) {
    const choice = form[row.class_type] || { mode: 'global', amount: '' };
    if (choice.mode === 'tutor') {
      if (!AMOUNT_RE.test(choice.amount) || !(Number(choice.amount) > 0)) invalid = true;
      else if (row.source !== 'TUTOR' || Number(choice.amount) !== Number(row.amount)) changes[row.class_type] = choice.amount.trim();
    } else if (row.source === 'TUTOR') {
      changes[row.class_type] = null;
    }
  }
  const changed = Object.keys(changes).length > 0;

  const save = async () => {
    setPending(true);
    setError('');
    try {
      const response = await api.post(`${EARNINGS_API}/tutors/${tutor.id}/rates/`, { rates: changes, reason: reason.trim() });
      onOpenChange(false);
      onSaved?.(response.data);
    } catch (err) {
      setError(earningsError(err, 'Could not save the rates.').message);
    } finally {
      setPending(false);
    }
  };

  const setChoice = (type, patch) => setForm((current) => ({ ...current, [type]: { ...current[type], ...patch } }));

  return (
    <FormDialog
      open={open}
      onOpenChange={(next) => !pending && onOpenChange(next)}
      title={`Rates for ${nameOf(tutor)}`}
      description="Each class type uses the global rate unless a tutor rate is set. A change applies to classes ending after it is saved; earned classes keep their rate."
      error={error}
      onConfirm={save}
      confirmLabel="Save tutor rates"
      confirmDisabled={!changed || invalid || !reason.trim()}
      pending={pending}
      size="lg"
    >
      {CLASS_TYPES.map((type) => {
        const row = (rates || []).find((item) => item.class_type === type.value);
        const choice = form[type.value] || { mode: 'global', amount: '' };
        return (
          <fieldset key={type.value} className="grid gap-2 rounded-lg border p-3 text-sm" disabled={pending}>
            <legend className="px-1 font-medium">
              {type.label} <span className="text-muted-foreground font-normal">· {type.unit === 'HOUR' ? 'per class hour' : 'per class'}</span>
            </legend>
            <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
              <label className="flex items-center gap-2">
                <input
                  type="radio"
                  name={`rate-${type.value}`}
                  className="accent-primary size-4"
                  checked={choice.mode === 'global'}
                  onChange={() => setChoice(type.value, { mode: 'global' })}
                />
                Global ({row?.global_amount ? formatInr(row.global_amount) : '—'})
              </label>
              <label className="flex items-center gap-2">
                <input
                  type="radio"
                  name={`rate-${type.value}`}
                  className="accent-primary size-4"
                  checked={choice.mode === 'tutor'}
                  onChange={() => setChoice(type.value, { mode: 'tutor' })}
                />
                Tutor rate
              </label>
              {choice.mode === 'tutor' ? (
                <Input
                  aria-label={`${type.label} tutor rate in rupees`}
                  inputMode="decimal"
                  className="w-28"
                  value={choice.amount}
                  onChange={(event) => setChoice(type.value, { amount: event.target.value })}
                />
              ) : null}
            </div>
          </fieldset>
        );
      })}
      <ReasonField id="tutor-rates-reason" value={reason} onChange={setReason} disabled={pending} />
      {invalid ? (
        <p className="text-destructive flex items-center gap-2 text-sm">
          <ShieldAlertIcon className="size-4" aria-hidden="true" />
          Enter each tutor rate in rupees, above ₹0.
        </p>
      ) : null}
    </FormDialog>
  );
}

function trimAmount(value) {
  if (value === null || value === undefined) return '';
  return String(value).replace(/\.00$/, '');
}

/**
 * Keep an earning that needs review as earned (POST
 * /api/earnings/entries/<id>/keep/), with the reason: it stays as it is and
 * leaves Needs review while its class reads as it does now; a further change
 * brings it back. `item` is the review item as shown, and what it shows is
 * what is kept: when the class has changed since, or was settled meanwhile,
 * the API refuses and `onStale` reads what needs review again.
 */
export function KeepEarningDialog({ item, tutorName, open, onOpenChange, onSaved, onStale }) {
  const [reason, setReason] = useState('');
  const [error, setError] = useState('');
  const [pending, setPending] = useState(false);
  useOnOpen(open, () => {
    setReason('');
    setError('');
  });

  const entry = item?.entry;
  const confirm = async () => {
    setPending(true);
    setError('');
    try {
      const response = await api.post(`${EARNINGS_API}/entries/${entry.id}/keep/`, {
        reason: reason.trim(),
        seen: { problem: item.problem, current: item.current },
      });
      onOpenChange(false);
      onSaved?.(response.data);
    } catch (err) {
      const refused = earningsError(err, 'Could not keep it as earned.');
      setError(refused.message);
      if (refused.code === 'REVIEW_CHANGED' || refused.code === 'NOT_IN_REVIEW') onStale?.();
    } finally {
      setPending(false);
    }
  };

  return (
    <FormDialog
      open={open}
      onOpenChange={(next) => !pending && onOpenChange(next)}
      title={entry ? `Keep ${formatInr(entry.amount)} as earned for ${tutorName}?` : 'Keep as earned'}
      description="The earning stays as it is and leaves Needs review. If its class changes again, it comes back for review."
      error={error}
      onConfirm={confirm}
      confirmLabel="Keep as earned"
      pendingLabel="Keeping…"
      confirmDisabled={!reason.trim()}
      pending={pending}
      size="md"
    >
      {entry ? (
        <p className="rounded-lg border px-3 py-2 text-sm">
          {classTypeLabel(entry.class_type, { singular: true })} · {classSubject(entry)} · {dayLabel(entry.class_start)}.{' '}
          {reviewDetail(item)}
        </p>
      ) : null}
      <ReasonField id="keep-reason" value={reason} onChange={setReason} disabled={pending} hint="Recorded with your name. The tutor doesn't see it." />
    </FormDialog>
  );
}
