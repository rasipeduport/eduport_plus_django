import { useState } from 'react';

import { FormDialog } from '@/components/form-dialog';
import api from '@/lib/api';

export function ReactivateUserDialog({ row, open, onOpenChange, onSaved }) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');

  const [prevOpen, setPrevOpen] = useState(open);
  if (open !== prevOpen) {
    setPrevOpen(open);
    if (open) setError('');
  }

  const target = row.full_name || row.email;

  async function handleConfirm() {
    setPending(true);
    setError('');
    try {
      await api.post(`/api/users/${row.id}/status/`, { action: 'reactivate' });
      onSaved?.();
      onOpenChange(false);
    } catch (err) {
      setError(err.response?.data?.message || 'Failed to reactivate user');
    } finally {
      setPending(false);
    }
  }

  return (
    <FormDialog
      open={open}
      onOpenChange={onOpenChange}
      title="Reactivate user"
      description={
        <>
          Restore <strong>{target}</strong>&apos;s access to the Hub.
        </>
      }
      error={error}
      onConfirm={handleConfirm}
      confirmLabel="Reactivate"
      pendingLabel="Working…"
      pending={pending}
      size="md"
    >
      <p className="text-muted-foreground text-sm">
        They will be able to sign in again immediately. You can re-assign students to them afterwards.
      </p>
    </FormDialog>
  );
}
