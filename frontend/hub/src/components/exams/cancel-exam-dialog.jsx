import { useState } from 'react';

import { FormDialog } from '@/components/form-dialog';
import { Label } from '@/components/ui/label';
import api from '@/lib/api';

/** Cancel a scheduled chapter exam; a reason is mandatory (the Hub's MarkCancelledDialog). */
export function CancelExamDialog({ exam, open, onOpenChange, onSaved }) {
  const [reason, setReason] = useState('');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');

  const [prevOpen, setPrevOpen] = useState(open);
  if (open !== prevOpen) {
    setPrevOpen(open);
    if (open) {
      setReason('');
      setError('');
    }
  }

  const handleConfirm = async () => {
    if (!reason.trim()) {
      setError('Please provide a reason.');
      return;
    }
    setPending(true);
    setError('');
    try {
      await api.put('/api/exams/', { id: exam.id, status: 'cancelled', cancellation_reason: reason.trim() });
      onSaved?.();
      onOpenChange(false);
    } catch (err) {
      setError(err.response?.data?.error || err.response?.data?.message || 'Failed to cancel exam.');
    } finally {
      setPending(false);
    }
  };

  return (
    <FormDialog
      open={open}
      onOpenChange={(v) => !pending && onOpenChange(v)}
      title="Cancel Exam"
      description={`${exam?.chapter_name ?? ''} — this cannot be undone.`}
      error={error}
      onConfirm={handleConfirm}
      confirmLabel="Confirm Cancel"
      pendingLabel="Cancelling…"
      confirmVariant="destructive"
      confirmDisabled={reason.trim() === ''}
      cancelLabel="Keep Scheduled"
      pending={pending}
    >
      <div className="flex flex-col gap-2">
        <Label htmlFor="exam-cancel-reason">Reason</Label>
        <textarea
          id="exam-cancel-reason"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          rows={3}
          placeholder="e.g. Student unwell"
          className="border-input bg-transparent placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-ring/50 w-full rounded-md border px-3 py-2 text-sm shadow-xs outline-none focus-visible:ring-[3px]"
          disabled={pending}
        />
      </div>
    </FormDialog>
  );
}
