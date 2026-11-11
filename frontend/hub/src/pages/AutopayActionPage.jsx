import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import api from '@/lib/api';
import { wholeAed } from '@/lib/payments';
import { Button } from '@/components/ui/button';

let stripeScript;
function loadStripe() {
  if (window.Stripe) return Promise.resolve(window.Stripe);
  if (!stripeScript) stripeScript = new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.src = 'https://js.stripe.com/v3/';
    script.onload = () => resolve(window.Stripe);
    script.onerror = () => { stripeScript = null; reject(new Error('Could not load Stripe. Please try again.')); };
    document.head.appendChild(script);
  });
  return stripeScript;
}

export default function AutopayActionPage() {
  const { token } = useParams();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [pending, setPending] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  useEffect(() => {
    let active = true;
    const meta = document.createElement('meta'); meta.name = 'referrer'; meta.content = 'no-referrer'; document.head.appendChild(meta);
    api.get(`/api/sales/autopay/actions/${token}/`).then(({ data }) => { if (active) setData(data); })
      .catch((err) => { if (active) setError(err.response?.data?.message || 'This private payment link is unavailable.'); });
    return () => { active = false; meta.remove(); };
  }, [token]);
  const authenticate = async () => {
    setPending(true); setError(null);
    try {
      const Stripe = await loadStripe();
      const result = await Stripe(data.publishable_key).confirmCardPayment(data.client_secret, { payment_method: data.payment_method_id });
      if (result.error) throw new Error(result.error.message);
      // Provider callbacks never credit quota; the signed webhook remains authoritative.
      setSubmitted(true);
    } catch (err) { setError(err.message || 'Authentication could not be completed.'); }
    finally { setPending(false); }
  };
  return <main className="mx-auto flex min-h-screen max-w-2xl flex-col justify-center gap-5 px-5 py-10">
    <h1 className="text-2xl font-semibold">Eduport Plus Autopay</h1>
    {error ? <p role="alert" className="text-destructive">{error}</p> : null}
    {data ? <>
      <p className="text-sm">{data.consent_text}</p><p className="text-sm">Package: <strong>{wholeAed(data.package_amount)}</strong> · {data.billing_timezone}</p>
      <ol className="divide-y rounded-md border px-4" aria-label="Agreed installment schedule">{data.schedule.map((row) => <li key={row.position} className="flex flex-wrap justify-between gap-2 py-3 text-sm"><strong>{row.position === 0 ? 'Initial payment' : `Installment ${row.position}`} · {row.classes} classes</strong><span>{wholeAed(row.amount)}</span><span className="text-muted-foreground w-full text-xs">{row.due_at ? new Intl.DateTimeFormat('en-GB', { dateStyle: 'medium', timeStyle: 'short', timeZone: data.billing_timezone }).format(new Date(row.due_at)) : 'Initial Stripe Checkout'}</span></li>)}</ol>
      <a href={data.terms_url} target="_blank" rel="noopener noreferrer" className="text-sm underline">Autopay terms</a>
      {submitted ? <p role="status">Authentication submitted. Your payment and class allocation will update once Stripe verifies the payment.</p> : data.needs_action ? <div><p className="mb-3 text-sm">Your bank requires authentication for {wholeAed(data.amount)}. No classes are credited until payment succeeds.</p><Button disabled={pending} onClick={authenticate}>{pending ? 'Contacting Stripe…' : `Authenticate ${wholeAed(data.amount)}`}</Button></div> : <p className="text-muted-foreground text-sm">Payment status: {data.status.replaceAll('_', ' ')}</p>}
    </> : !error ? <p>Loading your agreed schedule…</p> : null}
  </main>;
}
