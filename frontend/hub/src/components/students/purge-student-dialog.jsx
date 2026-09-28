import { useState } from 'react';

import { FormDialog } from '@/components/form-dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import api from '@/lib/api';

// Hard-delete for a mistaken/test student. The server refuses if the student
// has any history; this dialog requires typing the student code to confirm.
export function PurgeStudentDialog({ student, open, onOpenChange, onSaved }) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [code, setCode] = useState('');

  const [prevOpen, setPrevOpen] = useState(open);
  if (open !== prevOpen) {
    setPrevOpen(open);
    if (open) {
      setError('');
      setCode('');
    }
  }

  async function handleConfirm() {
    setPending(true);
    setError('');
    try {
      await api.delete(`/api/students/${student.id}/`, { data: { confirm_code: code.trim() } });
      onSaved?.();
      onOpenChange(false);
    } catch (err) {
      setError(err.response?.data?.message || 'Failed to delete student.');
    } finally {
      setPending(false);
    }
  }

  return (
    <FormDialog
      open={open}
      onOpenChange={onOpenChange}
      title="Delete student permanently"
      description={
        <>
          This permanently removes <strong>{student.full_name}</strong>. It only works for a student created by
          mistake with no sessions. For a real student who has left, set their status to <strong>expired</strong>{' '}
          instead. This cannot be undone.
        </>
      }
      error={error}
      onConfirm={handleConfirm}
      confirmLabel="Delete permanently"
      pendingLabel="Deleting…"
      confirmVariant="destructive"
      pending={pending}
      confirmDisabled={code.trim() !== student.student_code}
      size="md"
    >
      <div className="space-y-2 py-1">
        <Label htmlFor="purge-code">
          Type <span className="text-foreground font-mono">{student.student_code}</span> to confirm
        </Label>
        <Input
          id="purge-code"
          value={code}
          onChange={(event) => setCode(event.target.value)}
          placeholder={student.student_code}
          autoComplete="off"
        />
      </div>
    </FormDialog>
  );
}
