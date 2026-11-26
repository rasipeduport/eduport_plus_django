import { useState } from 'react';
import { CopyIcon, ExternalLinkIcon, MessageCircleIcon, RefreshCwIcon } from 'lucide-react';

import api from '@/lib/api';
import { salesError } from '@/lib/sales';
import { wholeAed } from '@/lib/payments';
import { CREATING_CHECKOUT, allocationStripeExpireUrl, allocationStripeLinksUrl, checkoutStatus } from '@/lib/additional-hours';
import { formatDate } from '@/lib/utils';
import { useLinkCopy } from '@/hooks/use-link-copy';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { FormDialog } from '@/components/form-dialog';

const dateTime = (value) => formatDate(value, { month: 'short', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit' });

/**
 * The hours' open Stripe link: its URL to copy, open or send, and expiring it. Paying it is the parent's, on
 * Stripe; the payment is recorded only when Stripe confirms it. While it is open nothing else may change what
 * is owed. A link Stripe has not confirmed yet is tried again with the same request -- never a second link.
 */
export function OpenStripeLink({ allocation, checkout, onChanged, onRefresh }) {
  const { copied, manual, urlRef, copy } = useLinkCopy();
  const [expiring, setExpiring] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState(null);
  const status = checkoutStatus(checkout);
  const creating = CREATING_CHECKOUT.includes(checkout.status);
  const url = checkout.checkout_url;
  const message = `Eduport Plus: please pay ${wholeAed(checkout.amount)} for additional hours (${allocation.reference}) using this secure Stripe link: ${url}`;
  const retry = async () => {
    setPending(true); setError(null);
    try {
      const { data } = await api.post(allocationStripeLinksUrl(allocation.id), { request_id: checkout.id, amount: checkout.amount });
      onChanged(data.allocation, 'Stripe confirmed the payment link.');
    } catch (err) {
      setError(salesError(err, 'Could not confirm the payment link.').message);
      onRefresh();
    } finally { setPending(false); }
  };
  const expire = async () => {
    setPending(true); setError(null);
    try {
      const { data } = await api.post(allocationStripeExpireUrl(allocation.id, checkout.id));
      setExpiring(false);
      onChanged(data, 'Payment link expired.');
    } catch (err) {
      setError(salesError(err, 'Could not expire the payment link.').message);
      setExpiring(false);
      onRefresh();
    } finally { setPending(false); }
  };
  return <section aria-label="Stripe payment link" className="border-info/30 bg-info/5 flex flex-col gap-2 rounded-lg border p-3 text-sm">
    <div className="flex flex-wrap items-center justify-between gap-2"><strong>Stripe payment link · {wholeAed(checkout.amount)}</strong>
      <Badge variant={status.variant}>{status.label}</Badge></div>
    {creating ? <>
      <p>Stripe has not confirmed this link yet. Trying again recovers the same link; it never creates a second one.</p>
      <div><Button size="sm" variant="outline" onClick={retry} disabled={pending}><RefreshCwIcon />{pending ? 'Trying…' : 'Try again'}</Button></div>
    </> : <>
      <p className="text-muted-foreground text-xs">Created by {checkout.created_by?.name} · {dateTime(checkout.created_at)}. Share it with the parent: the payment is recorded only when Stripe confirms it. While the link is open, other payments, amount changes, waiving and withdrawing are paused.</p>
      {url ? <Input readOnly value={url} aria-label="Payment link" onFocus={(event) => event.target.select()} /> : null}
      <div className="flex flex-wrap gap-2">
        <Button size="sm" variant="outline" onClick={() => copy(checkout.id, url)} disabled={!url}><CopyIcon />{copied ? 'Copied' : 'Copy link'}</Button>
        {url ? <Button size="sm" variant="outline" asChild><a href={url} target="_blank" rel="noopener noreferrer"><ExternalLinkIcon />Open</a></Button> : null}
        {url ? <Button size="sm" variant="outline" asChild><a href={`https://wa.me/?text=${encodeURIComponent(message)}`} target="_blank" rel="noopener noreferrer">
          <MessageCircleIcon />WhatsApp</a></Button> : null}
        <Button size="sm" variant="ghost" onClick={() => setExpiring(true)}>Expire link</Button>
      </div>
    </>}
    {manual ? <p ref={urlRef} className="text-muted-foreground text-sm break-all">{manual.url}</p> : null}
    {error ? <p role="alert" className="text-destructive text-sm">{error}</p> : null}
    <FormDialog open={expiring} onOpenChange={(next) => !pending && setExpiring(next)} title="Expire this payment link?"
      description="The parent can no longer pay through it. If they have just paid, Stripe keeps it open and the payment is recorded when Stripe confirms it."
      onConfirm={expire} confirmLabel="Expire link" pendingLabel="Expiring…" confirmVariant="destructive" pending={pending} />
  </section>;
}

/**
 * The hours' earlier Stripe links, newest first (the API keeps every one): what became of each -- and, for a
 * payment Stripe took that could not be applied (Needs review), why.
 */
export function StripeLinkHistory({ checkouts }) {
  if (!checkouts.length) return null;
  return <section aria-label="Stripe link history" className="flex flex-col gap-1.5">
    <h3 className="text-sm font-semibold">Earlier Stripe links</h3>
    <ul className="flex flex-col gap-1.5 text-sm">{checkouts.map((checkout) => {
      const status = checkoutStatus(checkout);
      const review = checkout.status === 'REQUIRES_REVIEW';
      return <li key={checkout.id} className={review ? 'border-destructive/30 bg-destructive/5 rounded-lg border px-3 py-2' : 'flex flex-wrap items-center gap-2'}>
        <span className="flex flex-wrap items-center gap-2"><Badge variant={status.variant}>{status.label}</Badge>
          <span>{wholeAed(checkout.amount)} · {checkout.created_by?.name} · {dateTime(checkout.created_at)}</span></span>
        {checkout.message ? <span className={review ? 'mt-1 block' : 'text-muted-foreground text-xs'}>{checkout.message}</span> : null}
      </li>;
    })}</ul>
  </section>;
}
