import { useState } from 'react';

import api from '@/lib/api';
import { PRICING_URL, PRIVILEGE_PLAN_TYPES, apiFieldErrors, orderedPlanTypes, planTypeLabel, salesError, toCents } from '@/lib/sales';
import { FormDialog } from '@/components/form-dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';

const FORM_ID = 'pricing-version-form';
const PERCENT_RE = /^\s*\d{1,2}(\.\d{1,2})?\s*$/;

function FieldError({ message }) {
  return message ? <p className="text-destructive text-sm">{message}</p> : null;
}

/**
 * The form, filled from the version in effect (`current`) so a change starts
 * from what applies now. Set up from nothing, the privilege is on for Regular,
 * as in the reference PDFs, with its percentage still to be entered.
 */
function formFrom(current) {
  const offered = Number(current?.single_payment_percent ?? 0) > 0;
  return {
    currency: current?.currency ?? 'AED',
    standard_fee: current?.standard_fee ?? '',
    offer_fee: current?.offer_fee ?? '',
    single_payment: current ? offered : true,
    single_payment_percent: offered ? current.single_payment_percent : '',
    single_payment_plan_types: offered
      ? current.single_payment_plan_types.filter((type) => PRIVILEGE_PLAN_TYPES.includes(type))
      : ['REGULAR'],
    note: '',
  };
}

function check(form) {
  const errors = {};
  if (!/^[A-Za-z]{3}$/.test(form.currency.trim())) errors.currency = 'Use a three-letter currency code, such as AED.';
  const standard = toCents(form.standard_fee);
  const offer = toCents(form.offer_fee);
  if (!standard) errors.standard_fee = 'Enter the standard fee per class, such as 45 or 45.50.';
  if (!offer) errors.offer_fee = 'Enter the offer fee per class, such as 35 or 35.50.';
  else if (standard && offer > standard) errors.offer_fee = 'The offer fee cannot be more than the standard fee.';
  if (form.single_payment) {
    if (!PERCENT_RE.test(form.single_payment_percent) || !(Number(form.single_payment_percent) > 0)) {
      errors.single_payment_percent = 'Enter the discount, from 0.01 to 99.99%, or switch the privilege off.';
    }
    if (!form.single_payment_plan_types.length) {
      errors.single_payment_plan_types = 'Choose the packages the single-payment privilege applies to.';
    }
  }
  return errors;
}

/**
 * The next version of the global pricing (D3): a per-class standard and offer
 * fee in one currency, and the single-payment privilege, on or off -- a
 * percentage off the packages it names, rounded to the nearest whole currency
 * unit, printed as the green box under each of them in the PDF. It takes effect
 * as soon as it is saved; every earlier version stays, unchanged, in the
 * history, and so do the prices already quoted from it. `onSaved(pricing)`
 * gets the API's answer (current and history).
 */
export function PricingDialog({ open, onOpenChange, current, onSaved }) {
  const [form, setForm] = useState(() => formFrom(current));
  const [errors, setErrors] = useState({});
  const [error, setError] = useState('');
  const [pending, setPending] = useState(false);

  const [prevOpen, setPrevOpen] = useState(open);
  if (open !== prevOpen) {
    setPrevOpen(open);
    if (open) {
      setForm(formFrom(current));
      setErrors({});
      setError('');
    }
  }

  const set = (field) => (event) => setForm((value) => ({ ...value, [field]: event.target.value }));
  const togglePlanType = (planType) =>
    setForm((value) => ({
      ...value,
      single_payment_plan_types: value.single_payment_plan_types.includes(planType)
        ? value.single_payment_plan_types.filter((item) => item !== planType)
        : [...value.single_payment_plan_types, planType],
    }));

  const submit = async (event) => {
    event.preventDefault();
    const found = check(form);
    setErrors(found);
    if (Object.keys(found).length) {
      setError('Check the highlighted fields.');
      return;
    }
    setPending(true);
    setError('');
    try {
      const response = await api.post(PRICING_URL, {
        currency: form.currency.trim().toUpperCase(),
        standard_fee: form.standard_fee.trim(),
        offer_fee: form.offer_fee.trim(),
        single_payment_percent: form.single_payment ? form.single_payment_percent.trim() : '0',
        single_payment_plan_types: form.single_payment ? orderedPlanTypes(form.single_payment_plan_types) : [],
        note: form.note.trim(),
      });
      onOpenChange(false);
      onSaved?.(response.data);
    } catch (err) {
      const refused = salesError(err, 'Could not save the pricing.');
      setErrors(apiFieldErrors(refused.fields));
      setError(refused.message);
    } finally {
      setPending(false);
    }
  };

  const invalid = (field) => (errors[field] ? true : undefined);
  const nextVersion = (current?.version ?? 0) + 1;

  return (
    <FormDialog
      open={open}
      onOpenChange={(next) => {
        if (!pending) onOpenChange(next);
      }}
      title={current ? 'Change the pricing' : 'Set up the pricing'}
      description={`Saved as version ${nextVersion}, in effect at once for every syllabus. Earlier versions — and the prices already quoted from them — never change.`}
      formId={FORM_ID}
      confirmLabel={`Save version ${nextVersion}`}
      pending={pending}
      error={error}
      size="lg"
    >
      <form id={FORM_ID} onSubmit={submit} className="grid gap-4 py-1" noValidate>
        <fieldset className="grid gap-4 sm:grid-cols-3" disabled={pending}>
          <div className="grid gap-2">
            <Label htmlFor="pricing-currency" required>
              Currency
            </Label>
            <Input
              id="pricing-currency"
              value={form.currency}
              onChange={set('currency')}
              maxLength={3}
              className="uppercase"
              aria-required="true"
              aria-invalid={invalid('currency')}
            />
            <FieldError message={errors.currency} />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="pricing-standard-fee" required>
              Standard fee / class
            </Label>
            <Input
              id="pricing-standard-fee"
              value={form.standard_fee}
              onChange={set('standard_fee')}
              inputMode="decimal"
              placeholder="45"
              aria-required="true"
              aria-invalid={invalid('standard_fee')}
            />
            <FieldError message={errors.standard_fee} />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="pricing-offer-fee" required>
              Offer fee / class
            </Label>
            <Input
              id="pricing-offer-fee"
              value={form.offer_fee}
              onChange={set('offer_fee')}
              inputMode="decimal"
              placeholder="35"
              aria-required="true"
              aria-invalid={invalid('offer_fee')}
            />
            <FieldError message={errors.offer_fee} />
          </div>
        </fieldset>
        <p className="text-muted-foreground -mt-2 text-xs">Every package is priced at the offer fee for each of its classes.</p>

        <fieldset className="grid gap-3 rounded-lg border p-3" disabled={pending}>
          <legend className="px-1 text-sm font-medium">Single-payment privilege</legend>
          <label className="flex items-center gap-2 text-sm">
            <input
              id="pricing-single-payment"
              type="checkbox"
              className="accent-primary size-4"
              checked={form.single_payment}
              onChange={(event) => setForm((value) => ({ ...value, single_payment: event.target.checked }))}
            />
            Offer a single-payment privilege
          </label>
          {form.single_payment ? (
            <>
              <div className="grid gap-2 sm:max-w-48">
                <Label htmlFor="pricing-single-payment-percent" required>
                  Discount (%)
                </Label>
                <Input
                  id="pricing-single-payment-percent"
                  value={form.single_payment_percent}
                  onChange={set('single_payment_percent')}
                  inputMode="decimal"
                  placeholder="5"
                  aria-required="true"
                  aria-invalid={invalid('single_payment_percent')}
                  aria-describedby="pricing-single-payment-help"
                />
                <FieldError message={errors.single_payment_percent} />
              </div>
              <p id="pricing-single-payment-help" className="text-muted-foreground text-xs">
                Off the package total when it is paid in one instalment, rounded to the nearest whole currency unit (a half rounds up). The PDF
                shows it as a green Single-Payment Privilege box under each package chosen; Regular + Revision shows a
                Regular and a Revision package.
              </p>
              <div className="flex flex-wrap gap-x-5 gap-y-2" role="group" aria-label="Packages the privilege applies to">
                {PRIVILEGE_PLAN_TYPES.map((planType) => (
                  <label key={planType} className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      className="accent-primary size-4"
                      checked={form.single_payment_plan_types.includes(planType)}
                      onChange={() => togglePlanType(planType)}
                    />
                    {planTypeLabel(planType)}
                  </label>
                ))}
              </div>
              <FieldError message={errors.single_payment_plan_types} />
            </>
          ) : (
            <p className="text-muted-foreground text-xs">Off: no package offers a single-payment price, and the PDFs show no Single-Payment Privilege box.</p>
          )}
        </fieldset>

        <div className="grid gap-2">
          <Label htmlFor="pricing-note">Reason for the change</Label>
          <Textarea
            id="pricing-note"
            value={form.note}
            onChange={set('note')}
            maxLength={255}
            rows={2}
            placeholder="New academic year offer"
            disabled={pending}
          />
        </div>
      </form>
    </FormDialog>
  );
}
