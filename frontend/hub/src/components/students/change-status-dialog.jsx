import { useState } from 'react';

import { FormDialog } from '@/components/form-dialog';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import api from '@/lib/api';

export function ChangeStatusDialog({ student, open, onOpenChange, onSaved }) {
  const [status, setStatus] = useState(student.status ?? 'active');
  const [note, setNote] = useState(student.status_note ?? '');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  // Re-sync from the student prop each time the dialog is opened, so the form
  // reflects the latest saved values rather than stale local state. Adjusting
  // state during render, guarded by the previous open value, is React's
  // recommended alternative to a synchronizing effect.
  const [prevOpen, setPrevOpen] = useState(open);
  if (open !== prevOpen) {
    setPrevOpen(open);
    if (open) {
      setStatus(student.status ?? 'active');
      setNote(student.status_note ?? '');
      setError(null);
    }
  }

  const noteRequired = status !== 'active';

  async function handleSave() {
    setLoading(true);
    setError(null);
    try {
      await api.put('/api/students/', {
        id: student.id,
        status,
        status_note: status === 'active' ? null : note.trim(),
      });
      onSaved?.();
      onOpenChange(false);
    } catch (err) {
      setError(err.response?.data?.message || 'Failed to update student status.');
    } finally {
      setLoading(false);
    }
  }

  return (
    <FormDialog
      open={open}
      onOpenChange={onOpenChange}
      title="Change Student Status"
      description={`Update the status for ${student.full_name}.`}
      error={error}
      onConfirm={handleSave}
      confirmLabel="Save"
      pending={loading}
      confirmDisabled={noteRequired && note.trim() === ''}
    >
      <div className="flex flex-col gap-2 py-2">
        <Label htmlFor="status-select">Status</Label>
        <Select value={status} onValueChange={setStatus}>
          <SelectTrigger id="status-select" className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="active">Active</SelectItem>
            <SelectItem value="inactive">Inactive</SelectItem>
            <SelectItem value="expired">Expired</SelectItem>
          </SelectContent>
        </Select>
        {noteRequired && (
          <div className="flex flex-col gap-1.5 pt-2">
            <Label htmlFor="status-note">Reason / Note</Label>
            <Input
              id="status-note"
              placeholder="e.g. Course completed, Fees pending…"
              value={note}
              onChange={(event) => setNote(event.target.value)}
              disabled={loading}
            />
          </div>
        )}
      </div>
    </FormDialog>
  );
}
