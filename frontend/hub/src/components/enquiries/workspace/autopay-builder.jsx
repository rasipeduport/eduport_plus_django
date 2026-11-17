import { useRef, useState } from 'react';
import api from '@/lib/api';
import { salesError } from '@/lib/sales';
import { wholeAed } from '@/lib/payments';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';

export function AutopayBuilder({ enquiryId, state, onChanged, onReplacement }) {
  const [initial, setInitial] = useState('');
  const [rows, setRows] = useState([{ key: crypto.randomUUID(), classes: '', due_at: '' }]);
  const [review, setReview] = useState(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState(null);
  const requestId = useRef(crypto.randomUUID());
  const body = () => ({ quote_id: state.quote.id, initial_classes: initial, installments: rows.map(({ classes, due_at }) => ({ classes, due_at })) });
  const change = (callback) => { callback(); setReview(null); setError(null); };
  const preview = async (event) => {
    event.preventDefault(); setPending(true); setError(null);
    try { const { data } = await api.post(`/api/sales/enquiries/${enquiryId}/sale/autopay/preview/`, body()); setReview(data); }
    catch (err) { setError(salesError(err, 'Could not review the schedule.')); }
    finally { setPending(false); }
  };
  const begin = async () => {
    setPending(true); setError(null);
    try {
      const { data } = await api.post(`/api/sales/enquiries/${enquiryId}/sale/autopay/`, { ...body(), review_token: review.review_token, request_id: requestId.current });
      onChanged(data);
    } catch (err) { setError(salesError(err, 'Could not create Autopay Checkout.')); }
    finally { setPending(false); }
  };
  return <div className="flex min-w-0 flex-col gap-4">
    <p className="text-muted-foreground text-sm">Agree the complete schedule with the parent. Dates and times use <strong>{state.billing_timezone}</strong>. Stripe collects the initial tuition and consent to save the card in the same Checkout.</p>
    <p className="text-muted-foreground text-xs">Stripe Billing will collect the future installments after the initial payment and saved card are verified. Up to 10 future installments, each at least AED 2. Amounts are calculated from the agreed quote.</p>
    <form onSubmit={preview} className="flex flex-col gap-4">
      <div className="max-w-sm space-y-1.5"><Label htmlFor="autopay-initial-classes">Initial payment classes</Label><Input id="autopay-initial-classes" type="number" min="0.5" step="0.5" max={state.totals.purchased_classes} required value={initial} onChange={(event) => change(() => setInitial(event.target.value))} /></div>
      <fieldset className="space-y-3" disabled={pending}><legend className="mb-2 text-sm font-medium">Future installments</legend>{rows.map((row, index) => <div key={row.key} className="grid min-w-0 items-end gap-3 rounded-md border p-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,2fr)_auto]">
        <div className="min-w-0 space-y-1.5"><Label htmlFor={`autopay-classes-${index}`}>Installment {index + 1} classes</Label><Input id={`autopay-classes-${index}`} type="number" min="0.5" step="0.5" required value={row.classes} onChange={(event) => change(() => setRows(rows.map((item) => item.key === row.key ? { ...item, classes: event.target.value } : item)))} /></div>
        <div className="min-w-0 space-y-1.5"><Label htmlFor={`autopay-due-${index}`}>Collection date and time</Label><Input id={`autopay-due-${index}`} type="datetime-local" className="min-w-0 max-w-full" required value={row.due_at} onChange={(event) => change(() => setRows(rows.map((item) => item.key === row.key ? { ...item, due_at: event.target.value } : item)))} /></div>
        <Button type="button" variant="ghost" onClick={() => change(() => setRows(rows.filter((item) => item.key !== row.key)))} disabled={rows.length === 1} aria-label={`Remove installment ${index + 1}`}>Remove</Button>
      </div>)}</fieldset>
      <div className="flex flex-wrap gap-2"><Button type="button" variant="outline" disabled={rows.length >= 10 || pending} onClick={() => change(() => setRows([...rows, { key: crypto.randomUUID(), classes: '', due_at: '' }]))}>Add installment</Button><Button variant="outline" disabled={pending}>{pending ? 'Calculating…' : 'Review complete schedule'}</Button></div>
    </form>
    {error ? <div className="space-y-2"><p role="alert" className="text-destructive text-sm">{error.message}</p>{error.code === 'REPLACEMENT_REQUIRED' ? <Button variant="outline" onClick={onReplacement}>Change collection intention</Button> : null}</div> : null}
    {review ? <section aria-label="Reviewed Autopay schedule" className="space-y-3 rounded-md border p-3">
      <h3 className="text-sm font-semibold">Review · {review.classes} classes · {wholeAed(review.package_amount)}</h3>
      <ol className="divide-y text-sm">{review.installments.map((row) => <li key={row.position} className="flex flex-wrap justify-between gap-2 py-2"><span>{row.position === 0 ? 'Initial payment' : `Installment ${row.position}`} · {row.classes} classes</span><span>{wholeAed(row.amount)}</span><span className="text-muted-foreground w-full text-xs">{row.due_at ? new Intl.DateTimeFormat('en-GB', { dateStyle: 'medium', timeStyle: 'short', timeZone: review.billing_timezone }).format(new Date(row.due_at)) : 'Parent’s initial Checkout payment'} · {review.billing_timezone}</span></li>)}</ol>
      {!review.checkout_available ? <p className="text-muted-foreground text-sm">Autopay Checkout requires Stripe keys, a webhook secret and approved terms configuration.</p> : null}
      <Button className="h-auto min-h-9 max-w-full whitespace-normal py-2" disabled={pending || !review.checkout_available} onClick={begin}>{pending ? 'Creating Checkout…' : 'Confirm schedule & generate Stripe Checkout'}</Button>
    </section> : null}
  </div>;
}
