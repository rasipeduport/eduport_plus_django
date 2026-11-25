import { useEffect, useState } from 'react';
import { HistoryIcon, PlusIcon, Trash2Icon } from 'lucide-react';

import api from '@/lib/api';
import {
  CLASS_TYPES,
  CONVERSION,
  CONVERSION_NOTE,
  EARNINGS_API,
  earningsError,
  formatInr,
  rateLabel,
  stampLabel,
  unitPhrase,
} from '@/lib/earnings';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { Skeleton } from '@/components/ui/skeleton';
import { Textarea } from '@/components/ui/textarea';
import { ErrorState } from '@/components/page/states';

const AMOUNT_RE = /^\s*\d+(\.\d{1,2})?\s*$/;
const validAmount = (value) => AMOUNT_RE.test(value || '') && Number(value) > 0;
const blankRates = () => Object.fromEntries(CLASS_TYPES.map((type) => [type.value, '']));
const trimAmount = (value) => (value === null || value === undefined ? '' : String(value).replace(/\.00$/, ''));

/** The rate history: every version, newest first, and who saved it, when and why. */
function History({ versions }) {
  if (!versions.length) return <p className="text-muted-foreground text-sm">No rates yet.</p>;
  return (
    <ul className="flex flex-col divide-y text-sm">
      {versions.map((version) => (
        <li key={version.id} className="py-2">
          <p className="font-medium">
            {CLASS_TYPES.find((type) => type.value === version.class_type)?.label}:{' '}
            {version.amount ? rateLabel(version.amount, version.unit) : 'back to the global rate'}
            {version.initial ? (
              <Badge variant="outline" className="ml-2">
                Initial pricing
              </Badge>
            ) : null}
          </p>
          <p className="text-muted-foreground text-xs">
            From {stampLabel(version.effective_from)} · saved {stampLabel(version.created_at)} by {version.created_by?.name}
            {version.reason ? ` · ${version.reason}` : ''}
          </p>
        </li>
      ))}
    </ul>
  );
}

/**
 * Start pricing, once: the global rate of every class type and of Demo
 * Conversion (required) and any tutors' own rates, all in effect from the
 * activation -- so they price every eligible class, and every Demo whose
 * student enrolled, since then. Confirmed explicitly: it cannot be undone.
 */
function InitialPricingForm({ data, onSaved }) {
  const [rates, setRates] = useState(blankRates);
  const [tutors, setTutors] = useState([]);
  const [reason, setReason] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  const [error, setError] = useState('');
  const [pending, setPending] = useState(false);

  const ready =
    CLASS_TYPES.every((type) => validAmount(rates[type.value])) &&
    tutors.every((row) => row.tutor && CLASS_TYPES.every((type) => !row.rates[type.value] || validAmount(row.rates[type.value]))) &&
    confirmed;
  const taken = new Set(tutors.map((row) => row.tutor));

  const save = async (event) => {
    event.preventDefault();
    setPending(true);
    setError('');
    try {
      const response = await api.post(`${EARNINGS_API}/rates/initial/`, {
        global: Object.fromEntries(CLASS_TYPES.map((type) => [type.value, rates[type.value].trim()])),
        tutors: tutors
          .map((row) => ({
            tutor: row.tutor,
            rates: Object.fromEntries(Object.entries(row.rates).filter(([, value]) => value && value.trim())),
          }))
          .filter((row) => Object.keys(row.rates).length),
        reason: reason.trim(),
        confirm: true,
      });
      onSaved(response.data);
    } catch (err) {
      setError(earningsError(err, 'Could not start pricing.').message);
    } finally {
      setPending(false);
    }
  };

  return (
    <form onSubmit={save} className="grid gap-4" noValidate>
      <p className="bg-muted/50 rounded-lg px-3 py-2 text-sm">
        Eligible classes since the activation are counted and wait for rates. These initial rates price every one of
        them; nothing is priced or owed until pricing starts.
      </p>
      <fieldset className="grid gap-3 rounded-lg border p-3" disabled={pending}>
        <legend className="px-1 text-sm font-medium">Global rates (required)</legend>
        <p className="text-muted-foreground text-xs">Demo Conversion: {CONVERSION_NOTE} At least the Demo rate.</p>
        {CLASS_TYPES.map((type) => (
          <div key={type.value} className="flex items-center justify-between gap-3">
            <Label htmlFor={`initial-${type.value}`} required>
              {type.label} · {unitPhrase(type.unit)}
            </Label>
            <Input
              id={`initial-${type.value}`}
              inputMode="decimal"
              className="w-32"
              placeholder="₹"
              value={rates[type.value]}
              onChange={(event) => setRates((current) => ({ ...current, [type.value]: event.target.value }))}
            />
          </div>
        ))}
      </fieldset>
      <fieldset className="grid gap-3 rounded-lg border p-3" disabled={pending}>
        <legend className="px-1 text-sm font-medium">Tutor rates (optional)</legend>
        {tutors.map((row, index) => (
          <div key={index} className="grid gap-2 rounded-md border p-2">
            <div className="flex items-center gap-2">
              <Select
                value={row.tutor}
                onValueChange={(value) =>
                  setTutors((current) => current.map((item, at) => (at === index ? { ...item, tutor: value } : item)))
                }
              >
                <SelectTrigger aria-label="Tutor" className="min-w-0 flex-1">
                  <SelectValue placeholder="Choose a tutor" />
                </SelectTrigger>
                <SelectContent>
                  {data.tutors
                    .filter((tutor) => tutor.active && (!taken.has(tutor.id) || tutor.id === row.tutor))
                    .map((tutor) => (
                      <SelectItem key={tutor.id} value={tutor.id}>
                        {tutor.name}
                      </SelectItem>
                    ))}
                </SelectContent>
              </Select>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                aria-label="Remove this tutor rate"
                onClick={() => setTutors((current) => current.filter((_, at) => at !== index))}
              >
                <Trash2Icon />
              </Button>
            </div>
            <div className="grid gap-2 sm:grid-cols-2">
              {CLASS_TYPES.map((type) => (
                <Input
                  key={type.value}
                  aria-label={`${type.label} tutor rate`}
                  inputMode="decimal"
                  placeholder={`${type.label}${type.unit === 'HOUR' ? ' / h' : ''}`}
                  title={`${type.label} · ${unitPhrase(type.unit)}`}
                  value={row.rates[type.value] || ''}
                  onChange={(event) =>
                    setTutors((current) =>
                      current.map((item, at) =>
                        at === index ? { ...item, rates: { ...item.rates, [type.value]: event.target.value } } : item
                      )
                    )
                  }
                />
              ))}
            </div>
          </div>
        ))}
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="self-start"
          onClick={() => setTutors((current) => [...current, { tutor: '', rates: {} }])}
        >
          <PlusIcon />
          Add tutor rate
        </Button>
        <p className="text-muted-foreground text-xs">Leave a class type blank to use the global rate.</p>
      </fieldset>
      <div className="grid gap-2">
        <Label htmlFor="initial-reason">Reason (optional)</Label>
        <Textarea id="initial-reason" rows={2} maxLength={500} value={reason} onChange={(event) => setReason(event.target.value)} />
      </div>
      <label className="flex items-start gap-2 text-sm">
        <input type="checkbox" className="accent-primary mt-0.5 size-4" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} />
        Pricing starts once and cannot be undone. Changes after this apply only to classes ending after they are saved.
      </label>
      {error ? <p className="text-destructive text-sm">{error}</p> : null}
      <Button type="submit" disabled={!ready || pending}>
        {pending ? 'Starting…' : 'Start pricing'}
      </Button>
    </form>
  );
}

/**
 * A change of the global rates, from now on, with its reason; only the rates
 * that differ become new versions. A rate with no version yet (Demo
 * Conversion, where pricing started before it existed) may stay blank.
 */
function GlobalRatesForm({ data, onSaved }) {
  const current = Object.fromEntries(data.rates.map((row) => [row.class_type, trimAmount(row.amount)]));
  const [rates, setRates] = useState(current);
  const [reason, setReason] = useState('');
  const [error, setError] = useState('');
  const [pending, setPending] = useState(false);

  const fine = (type, value) => validAmount(value) || (!current[type] && !(value || '').trim());
  const changes = Object.fromEntries(
    Object.entries(rates).filter(([type, value]) => validAmount(value) && Number(value) !== Number(current[type]))
  );
  const invalid = Object.entries(rates).some(([type, value]) => !fine(type, value));
  const ready = Object.keys(changes).length > 0 && !invalid && reason.trim();

  const save = async (event) => {
    event.preventDefault();
    setPending(true);
    setError('');
    try {
      const response = await api.post(`${EARNINGS_API}/rates/`, { rates: changes, reason: reason.trim() });
      setReason('');
      onSaved(response.data);
    } catch (err) {
      setError(earningsError(err, 'Could not save the rates.').message);
    } finally {
      setPending(false);
    }
  };

  return (
    <form onSubmit={save} className="grid gap-4" noValidate>
      <fieldset className="grid gap-3 rounded-lg border p-3" disabled={pending}>
        <legend className="px-1 text-sm font-medium">Global rates</legend>
        {data.rates.map((row) => {
          const type = CLASS_TYPES.find((item) => item.value === row.class_type);
          return (
            <div key={row.class_type} className="flex flex-wrap items-center justify-between gap-3">
              <div className="min-w-0 flex-1">
                <Label htmlFor={`global-${row.class_type}`}>
                  {type?.label} <span className="text-muted-foreground font-normal">· {unitPhrase(row.unit)}</span>
                </Label>
                <p className="text-muted-foreground text-xs">
                  {row.amount ? `Now ${rateLabel(row.amount, row.unit)}` : 'Not set yet: nothing is paid for it until it is'}
                </p>
                {row.class_type === CONVERSION ? (
                  <p className="text-muted-foreground text-xs">{CONVERSION_NOTE} At least the Demo rate.</p>
                ) : null}
              </div>
              <Input
                id={`global-${row.class_type}`}
                inputMode="decimal"
                className="w-32"
                value={rates[row.class_type] ?? ''}
                onChange={(event) => setRates((value) => ({ ...value, [row.class_type]: event.target.value }))}
                aria-invalid={fine(row.class_type, rates[row.class_type]) ? undefined : true}
              />
            </div>
          );
        })}
      </fieldset>
      <div className="grid gap-2">
        <Label htmlFor="global-reason" required>
          Reason
        </Label>
        <Textarea id="global-reason" rows={2} maxLength={500} value={reason} onChange={(event) => setReason(event.target.value)} />
      </div>
      <p className="bg-muted/50 rounded-lg px-3 py-2 text-sm">
        <strong>Takes effect when saved</strong>, for classes ending (and, for Demo Conversion, students enrolling) from
        then on, for every tutor on the global rate. Classes and conversions already earned keep their rate; tutors with
        their own rate are not affected.
      </p>
      {error ? <p className="text-destructive text-sm">{error}</p> : null}
      <Button type="submit" disabled={!ready || pending}>
        {pending ? 'Saving…' : 'Save new rates'}
      </Button>
    </form>
  );
}

/**
 * The global rates, for administrators (GET /api/earnings/rates/): before
 * pricing starts, the initial rates; after, a change of the global rates and
 * the whole history. `canManage` (accounts.manage_tutor_rates) offers the
 * forms; `onSaved` reloads the page behind.
 */
export function RatesSheet({ open, onOpenChange, canManage, onSaved }) {
  const [data, setData] = useState(null);
  const [failure, setFailure] = useState(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    if (!open) return undefined;
    let active = true;
    api
      .get(`${EARNINGS_API}/rates/`)
      .then((response) => {
        if (!active) return;
        setData(response.data);
        setFailure(null);
      })
      .catch((err) => {
        if (active) setFailure(earningsError(err, 'Could not load the rates.'));
      });
    return () => {
      active = false;
    };
  }, [open, reloadKey]);

  const saved = (answer) => {
    setData(answer);
    onSaved?.();
  };

  let body;
  if (failure && !data) {
    body = <ErrorState message={failure.message} onRetry={() => setReloadKey((key) => key + 1)} />;
  } else if (!data) {
    body = <Skeleton className="h-64 w-full rounded-xl" />;
  } else if (!data.activated_at) {
    body = <p className="text-muted-foreground text-sm">Tutor Earnings is not activated, so there is nothing to price yet.</p>;
  } else if (!data.pricing) {
    body = canManage ? (
      <InitialPricingForm data={data} onSaved={saved} />
    ) : (
      <p className="text-muted-foreground text-sm">Pricing has not started yet.</p>
    );
  } else {
    body = (
      <div className="grid gap-6">
        <p className="text-muted-foreground text-sm">
          Pricing started {stampLabel(data.pricing.started_at)} by {data.pricing.started_by?.name}. Global rates now:{' '}
          {data.rates.map((row) => `${CLASS_TYPES.find((type) => type.value === row.class_type)?.label} ${formatInr(row.amount)}`).join(' · ')}.
        </p>
        {canManage ? <GlobalRatesForm key={data.history.length} data={data} onSaved={saved} /> : null}
        <section className="grid gap-2">
          <h3 className="flex items-center gap-2 text-sm font-semibold">
            <HistoryIcon className="size-4" aria-hidden="true" />
            Rate history
          </h3>
          <History versions={data.history} />
        </section>
      </div>
    );
  }

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-lg">
        <SheetHeader>
          <SheetTitle>{data && !data.pricing ? 'Start pricing Tutor Earnings' : 'Global rates'}</SheetTitle>
          <SheetDescription>
            In Indian rupees. Every rate version is kept as history; none is ever edited.
          </SheetDescription>
        </SheetHeader>
        <div className="px-4 pb-6">{body}</div>
      </SheetContent>
    </Sheet>
  );
}
