import { useState } from 'react';

import api from '@/lib/api';
import { QUOTES_URL, enquiryLabel, firstMessage, planTypeLabel, quoteCancelUrl, salesError } from '@/lib/sales';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { FormDialog } from '@/components/form-dialog';
import { QuoteFigures } from '@/components/sales/quote-parts';

// The longest reason the API keeps (backend QuoteCancelSerializer).
export const CANCEL_REASON_MAX = 255;

/**
 * Issuing a quote of `planType` from the plan on sale (`syllabusId`, its
 * catalogue `detail` at the revision shown): `preview` is what it will say
 * (lib/sales quotePreview) and `chapterIds` the chapters or days chosen (none:
 * the whole course), for `enquiry`, replacing its latest quote (`replaces`).
 * The API prices it afresh and keeps it as issued:
 * `onIssued(quote)` gets it. A refusal the page answers itself -- a newer
 * revision published meanwhile, the plan withdrawn -- goes to
 * `onRefused(refusal)` and closes the dialog; any other stays in it.
 */
export function CreateQuoteDialog({
  open,
  onOpenChange,
  syllabusId,
  detail,
  planType,
  chapterIds,
  preview,
  coverage,
  enquiry,
  replaces,
  onIssued,
  onRefused,
}) {
  const [failure, setFailure] = useState(null);
  const [pending, setPending] = useState(false);

  // Each opening starts afresh.
  const [prevOpen, setPrevOpen] = useState(open);
  if (open !== prevOpen) {
    setPrevOpen(open);
    if (open) setFailure(null);
  }

  const issue = async () => {
    setPending(true);
    setFailure(null);
    try {
      const response = await api.post(QUOTES_URL, {
        syllabus: syllabusId,
        revision: detail.revision,
        plan_type: planType,
        chapter_ids: chapterIds,
        lead: enquiry?.id ?? null,
        ...(enquiry ? { replaces: replaces ?? null, pricing_version: detail.pricing.version } : {}),
      });
      onOpenChange(false);
      onIssued(response.data);
    } catch (err) {
      const refused = salesError(err, 'Could not issue the quote.');
      if (['REVISION_CHANGED', 'PRICING_CHANGED', 'PLAN_CHANGED', 'PLAN_LOCKED'].includes(refused.code) || refused.status === 404) {
        onOpenChange(false);
        // REVISION_CHANGED names the revision on sale now.
        onRefused({ status: refused.status, code: refused.code, message: refused.message, revision: err.response?.data?.revision ?? null });
      } else {
        setFailure(refused);
      }
    } finally {
      setPending(false);
    }
  };

  const leadError = firstMessage(failure?.fields?.lead);
  return (
    <FormDialog
      open={open}
      onOpenChange={onOpenChange}
      title="Create quote"
      description={`${detail.title} · ${planTypeLabel(planType)} · ${coverage}`}
      error={failure && !leadError ? failure.message : null}
      onConfirm={issue}
      confirmLabel="Issue quote"
      pendingLabel="Issuing…"
      confirmDisabled={!preview}
      pending={pending}
      size="lg"
      contentClassName="max-h-[90vh] overflow-y-auto"
    >
      <div className="flex flex-col gap-4">
        {preview ? <QuoteFigures figures={preview} currency={detail.pricing.currency} /> : null}
        {enquiry ? <p className="text-sm font-medium">For {enquiryLabel(enquiry)}</p> : null}
        {enquiry && leadError ? (
          <p role="alert" className="text-destructive text-sm">
            {leadError}
          </p>
        ) : null}
        {replaces ? <p className="text-muted-foreground text-sm">This becomes the current plan. The previous quote remains in history.</p> : null}
        <p className="text-muted-foreground text-xs">
          The quote is priced at the pricing in effect now and kept exactly as issued: it cannot be changed later, only cancelled by an administrator.
        </p>
      </div>
    </FormDialog>
  );
}

/**
 * Cancelling an issued `quote` (administrators), with the reason it is
 * withdrawn -- required, kept with the quote for the team, never printed on
 * the PDF. A cancelled quote stays cancelled. `onCancelled(quote)` gets it as
 * cancelled; one cancelled meanwhile by someone else goes to `onChanged()`.
 */
export function CancelQuoteDialog({ open, onOpenChange, quote, onCancelled, onChanged }) {
  const [reason, setReason] = useState('');
  const [failure, setFailure] = useState(null);
  const [pending, setPending] = useState(false);

  const [prevOpen, setPrevOpen] = useState(open);
  if (open !== prevOpen) {
    setPrevOpen(open);
    if (open) {
      setReason('');
      setFailure(null);
    }
  }

  const text = reason.trim();
  const cancel = async () => {
    if (!text) return;
    setPending(true);
    setFailure(null);
    try {
      const response = await api.post(quoteCancelUrl(quote.id), { reason: text });
      onOpenChange(false);
      onCancelled(response.data);
    } catch (err) {
      const refused = salesError(err, 'Could not cancel the quote.');
      setFailure(refused);
      if (refused.code === 'ALREADY_CANCELLED') onChanged?.();
    } finally {
      setPending(false);
    }
  };

  const reasonError = firstMessage(failure?.fields?.reason);
  return (
    <FormDialog
      open={open}
      onOpenChange={onOpenChange}
      title={`Cancel quote ${quote.reference}`}
      description="The quote stays in the history, cancelled for good. Its PDF is then marked CANCELLED on every page, with the date; the reason stays with the team."
      error={failure && !reasonError ? failure.message : null}
      onConfirm={cancel}
      confirmLabel="Cancel quote"
      pendingLabel="Cancelling…"
      confirmVariant="destructive"
      confirmDisabled={!text}
      cancelLabel="Keep it"
      pending={pending}
      size="md"
    >
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="quote-cancel-reason">Why is it cancelled?</Label>
        <Textarea
          id="quote-cancel-reason"
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          maxLength={CANCEL_REASON_MAX}
          disabled={pending}
          aria-invalid={Boolean(reasonError) || undefined}
          placeholder="For example: the parent chose another plan."
        />
        <p className="text-muted-foreground text-right text-xs tabular-nums">
          {reason.length}/{CANCEL_REASON_MAX}
        </p>
        {reasonError ? <p className="text-destructive text-sm">{reasonError}</p> : null}
      </div>
    </FormDialog>
  );
}
