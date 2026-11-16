import { useEffect, useState } from 'react';

import api from '@/lib/api';
import { FormDialog } from '@/components/form-dialog';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { communicationError, confirmationRequestUrl, messagePreviewUrl } from '@/lib/communications';
import { bookingTypeLabel, slotLabel } from '@/lib/enquiries';

/** What the request still lacks (MESSAGE_BLOCKED's `missing`, or the preview's unmet requirements), in words. */
const lacking = (items) => items.map((item) => item.label).join(', ');

/**
 * Asking the parent to confirm a booking (Phase 3.2): first the confirmation
 * request exactly as WhatsApp would show it (GET …/preview/?step=CONFIRMATION_REQUEST),
 * or what it still lacks; then, once reviewed, the request written for the
 * sending engine to send (POST …/confirmation-request/). Asking again is
 * answered with the request already written, never a second. The API checks
 * every rule again, and its refusal is shown as it comes.
 */
export function ConfirmationRequestDialog({ booking, open, onOpenChange, onRequested }) {
  const [preview, setPreview] = useState(null);
  const [previewFailure, setPreviewFailure] = useState(null);
  const [retryKey, setRetryKey] = useState(0);
  const [error, setError] = useState(null);
  const [pending, setPending] = useState(false);
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

  async function request() {
    setPending(true);
    setError(null);
    try {
      const response = await api.post(confirmationRequestUrl(bookingType, bookingId));
      onRequested?.(response.data);
      onOpenChange(false);
    } catch (err) {
      const failure = communicationError(err, 'Could not request the confirmation.');
      const missing = err?.response?.data?.missing;
      setError(Array.isArray(missing) && missing.length ? `${failure.message} Missing: ${lacking(missing)}.` : failure.message);
    } finally {
      setPending(false);
    }
  }

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
  } else if (preview.ready) {
    content = (
      <div className="flex flex-col gap-2">
        <p className="text-muted-foreground text-sm">The parent receives this on WhatsApp:</p>
        <p className="bg-muted max-h-72 overflow-y-auto rounded-md p-3 text-sm whitespace-pre-wrap" aria-label="Message preview">
          {preview.text}
        </p>
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
    <FormDialog
      open={open}
      onOpenChange={onOpenChange}
      title="Request confirmation"
      description={
        booking ? `${booking.student_name} · ${bookingTypeLabel(booking.booking_type)} · ${slotLabel(booking.slot)}` : null
      }
      error={error}
      onConfirm={request}
      confirmLabel="Request confirmation"
      pendingLabel="Requesting…"
      confirmDisabled={!preview?.ready}
      pending={pending}
      size="md"
    >
      {content}
    </FormDialog>
  );
}
