import { useEffect, useState } from 'react';
import { CheckCheckIcon, CopyIcon, MessageCircleIcon, TriangleAlertIcon } from 'lucide-react';

import api from '@/lib/api';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Skeleton } from '@/components/ui/skeleton';
import { CopyStatus } from '@/components/dashboard/share-link-buttons';
import { useLinkCopy } from '@/hooks/use-link-copy';
import { useRefusalRefresh } from '@/hooks/use-refusal-refresh';
import {
  communicationError,
  confirmationRequestSentUrl,
  messagePreviewUrl,
  messageState,
  sentByHand,
  sentByHandLine,
} from '@/lib/communications';
import { bookingTypeLabel, slotLabel, whatsAppUrl } from '@/lib/enquiries';

/** What the request still lacks (MESSAGE_BLOCKED's `missing`, or the preview's unmet requirements), in words. */
const lacking = (items) => items.map((item) => item.label).join(', ');

/** Where a request already written stands, in a line: who sent it by hand and when, or its WhatsApp status. */
function requestLine(request) {
  if (!request) return null;
  return sentByHandLine(request) ?? `Confirmation request: ${messageState(request).label}`;
}

/**
 * The parent's confirmation request, sent from the caller's own WhatsApp --
 * never by the Hub. The request as WhatsApp will show it (GET
 * …/preview/?step=CONFIRMATION_REQUEST, which also gives the parent's
 * WhatsApp number and whose name signs it), or what it still lacks; then two
 * separate actions. Open WhatsApp opens a chat with the parent with the
 * message filled in, for the caller to send -- it writes and records nothing,
 * so it may be opened again at any time (Copy message is there when WhatsApp
 * cannot open). Once they have pressed Send in WhatsApp, "I've sent it – Mark
 * as sent" records that they did (POST …/confirmation-request/mark-sent/):
 * sent by hand, by them, now -- never delivered or read. Offered while
 * `canMark` (the API's `mark_request_sent`); `request` is the request already
 * written, if any, to say where it stands. An Admin acting on a BDE's lead is
 * warned that it goes from their own WhatsApp under the BDE's name. The API
 * checks every rule again, and its refusal is shown as it comes.
 */
export function ConfirmationRequestDialog({
  booking,
  request = null,
  canMark = false,
  open,
  onOpenChange,
  onMarked,
  onRefused,
}) {
  // Refused as out of date (404/409): once closed, `onRefused` lets the page read it again.
  const refusal = useRefusalRefresh(onOpenChange, onRefused);
  const { copy, copied, manual, urlRef } = useLinkCopy();
  const [preview, setPreview] = useState(null);
  const [previewFailure, setPreviewFailure] = useState(null);
  const [retryKey, setRetryKey] = useState(0);
  const [error, setError] = useState(null);
  const [marking, setMarking] = useState(false);
  const bookingType = booking?.booking_type;
  const bookingId = booking?.id;

  // A fresh dialog, and a fresh preview, on every open.
  const [prevOpen, setPrevOpen] = useState(open);
  if (open !== prevOpen) {
    setPrevOpen(open);
    if (open) {
      setPreview(null);
      setPreviewFailure(null);
      setError(null);
    }
  }

  useEffect(() => {
    if (!open || !bookingType || !bookingId) return undefined;
    let active = true;
    setPreviewFailure(null);
    api
      .get(messagePreviewUrl(bookingType, bookingId), { params: { step: 'CONFIRMATION_REQUEST' } })
      .then((response) => {
        if (active) setPreview(response.data);
      })
      .catch((err) => {
        if (active) setPreviewFailure(communicationError(err, 'Could not prepare the message.'));
      });
    return () => {
      active = false;
    };
  }, [open, bookingType, bookingId, retryKey]);

  async function markSent() {
    setMarking(true);
    setError(null);
    try {
      const response = await api.post(confirmationRequestSentUrl(bookingType, bookingId));
      refusal.accepted();
      onMarked?.(response.data);
      onOpenChange(false);
    } catch (err) {
      const failure = communicationError(err, 'Could not mark the confirmation request as sent.');
      refusal.refused(failure);
      const missing = err?.response?.data?.missing;
      setError(Array.isArray(missing) && missing.length ? `${failure.message} Missing: ${lacking(missing)}.` : failure.message);
    } finally {
      setMarking(false);
    }
  }

  const ready = Boolean(preview?.ready);
  // The parent's number as WhatsApp addresses it (digits only), null when it is not a full international number.
  const url = ready && preview.whatsapp_number ? whatsAppUrl(preview.whatsapp_number, '', preview.text) : null;
  const signer = ready && preview.signed_by && !preview.signed_by_caller ? preview.signed_by.full_name : null;
  const status = requestLine(request);

  let content;
  if (previewFailure) {
    content = (
      <div className="flex flex-wrap items-center gap-3">
        <p className="text-destructive text-sm">{previewFailure.message}</p>
        <Button variant="outline" size="sm" onClick={() => setRetryKey((key) => key + 1)}>
          Try again
        </Button>
      </div>
    );
  } else if (!preview) {
    content = <Skeleton className="h-40" aria-busy="true" />;
  } else if (ready) {
    content = (
      <div className="flex flex-col gap-3">
        {signer ? (
          <p role="note" className="bg-warning/10 text-warning flex gap-2 rounded-md px-3 py-2 text-sm">
            <TriangleAlertIcon className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
            <span>
              This opens your own WhatsApp: the parent receives it from your personal WhatsApp number, while the
              message is signed with {signer}’s name.
            </span>
          </p>
        ) : null}
        <div className="flex min-w-0 flex-col gap-2">
          <p className="text-muted-foreground text-sm">The parent receives this on WhatsApp:</p>
          <p
            className="bg-muted max-h-72 overflow-y-auto rounded-md p-3 text-sm whitespace-pre-wrap [overflow-wrap:anywhere]"
            aria-label="Message preview"
          >
            {preview.text}
          </p>
        </div>
        {url ? null : (
          <p className="bg-warning/10 text-warning rounded-md px-3 py-2 text-sm">
            The parent’s number is not a full international number, so WhatsApp cannot open a chat with it. Copy the
            message and send it to the parent yourself.
          </p>
        )}
      </div>
    );
  } else {
    content = (
      <p className="bg-warning/10 text-warning rounded-md px-3 py-2 text-sm">
        This message cannot be sent yet. It still needs: {lacking(preview.requirements.filter((item) => !item.met))}.
      </p>
    );
  }

  return (
    <Dialog open={open} onOpenChange={refusal.onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Confirmation request</DialogTitle>
          {booking ? (
            <DialogDescription>
              {`${booking.student_name} · ${bookingTypeLabel(booking.booking_type)} · ${slotLabel(booking.slot)}`}
            </DialogDescription>
          ) : null}
        </DialogHeader>
        {status ? (
          <p role="status" className="flex items-center gap-2 text-sm">
            {sentByHand(request) ? <CheckCheckIcon className="text-success size-4 shrink-0" aria-hidden="true" /> : null}
            {status}
          </p>
        ) : null}
        {content}
        {/* Step 1, in the caller's own WhatsApp: the two ways to get the message there. They wrap, never widen the dialog. */}
        <div className="flex min-w-0 flex-wrap gap-2 *:flex-1 sm:*:flex-none">
          <Button variant="outline" disabled={!ready} onClick={() => copy('message', preview.text)}>
            <CopyIcon />
            Copy message
          </Button>
          {url ? (
            <Button variant={canMark ? 'outline' : 'default'} asChild>
              <a href={url} target="_blank" rel="noopener noreferrer">
                <MessageCircleIcon />
                Open WhatsApp
              </a>
            </Button>
          ) : (
            <Button variant={canMark ? 'outline' : 'default'} disabled>
              <MessageCircleIcon />
              Open WhatsApp
            </Button>
          )}
        </div>
        {ready ? (
          <p className="text-muted-foreground text-xs">
            Opening WhatsApp sends nothing and records nothing: press Send in WhatsApp yourself
            {canMark ? ', then come back and mark it as sent.' : '.'}
          </p>
        ) : null}
        <CopyStatus manual={manual} urlRef={urlRef} copiedLabel={copied ? 'Message' : null} />
        {error ? <p className="text-destructive text-sm">{error}</p> : null}
        {/* Step 2, back in the Hub: only the caller's word that they sent it records anything. */}
        {canMark ? (
          <DialogFooter>
            <Button className="w-full sm:w-auto" onClick={markSent} disabled={!ready || marking}>
              {marking ? 'Marking…' : 'I’ve sent it – Mark as sent'}
            </Button>
          </DialogFooter>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}
