import { useEffect, useState } from 'react';

import { FormDialog } from '@/components/form-dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import api from '@/lib/api';

// Deactivating a mentor/tutor who still has assigned active students is blocked
// server-side until those students are reassigned. This dialog enforces that up
// front: when a handover is needed it requires picking a replacement and runs
// the bulk reassign before the deactivate.
export function DeactivateUserDialog({ row, variant, open, onOpenChange, onSaved }) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [reason, setReason] = useState('');

  const assignedCount = row.assigned_students_count ?? 0;
  const needsHandover = (variant === 'mentor' || variant === 'tutor') && assignedCount > 0;

  const [replacements, setReplacements] = useState([]);
  const [loadedReplacements, setLoadedReplacements] = useState(false);
  const [replacementId, setReplacementId] = useState('');

  const [prevOpen, setPrevOpen] = useState(open);
  if (open !== prevOpen) {
    setPrevOpen(open);
    if (open) {
      setError('');
      setReason('');
      setReplacementId('');
    }
  }

  // Load active replacement staff of the same role (excluding the target) when
  // a handover is required. The slim endpoint already excludes deactivated
  // staff, so nothing can be handed to someone who has lost access.
  useEffect(() => {
    if (!open || !needsHandover || loadedReplacements) return undefined;
    let cancelled = false;
    const key = variant === 'mentor' ? 'mentors' : 'tutors';

    api
      .get(`/api/${key}/`)
      .then((res) => {
        if (cancelled) return;
        setReplacements((res.data[key] ?? []).filter((option) => option.id !== row.id));
      })
      .catch(() => {
        if (!cancelled) setError('Failed to load replacement options');
      })
      .finally(() => {
        if (!cancelled) setLoadedReplacements(true);
      });

    return () => {
      cancelled = true;
    };
  }, [open, needsHandover, loadedReplacements, variant, row.id]);

  const target = row.full_name || row.email;

  async function handleConfirm() {
    setPending(true);
    setError('');
    try {
      if (needsHandover) {
        if (!replacementId) {
          setError('Select a replacement first');
          setPending(false);
          return;
        }
        const reassignBody = variant === 'mentor' ? { new_mentor: replacementId } : { new_tutor: replacementId };
        try {
          await api.post(`/api/users/${row.id}/reassign/`, reassignBody);
        } catch (err) {
          setError(err.response?.data?.message || 'Failed to reassign students');
          setPending(false);
          return;
        }
      }

      await api.post(`/api/users/${row.id}/status/`, {
        action: 'deactivate',
        ...(reason.trim() ? { reason: reason.trim() } : {}),
      });
      onSaved?.();
      onOpenChange(false);
    } catch (err) {
      setError(err.response?.data?.message || 'Failed to deactivate user');
    } finally {
      setPending(false);
    }
  }

  return (
    <FormDialog
      open={open}
      onOpenChange={onOpenChange}
      title="Deactivate user"
      description={
        <>
          This revokes <strong>{target}</strong>&apos;s access to the Hub. Their account and history are kept, and they
          can be reactivated later.
        </>
      }
      error={error}
      onConfirm={handleConfirm}
      confirmLabel={needsHandover ? 'Reassign & deactivate' : 'Deactivate'}
      pendingLabel="Working…"
      confirmVariant="destructive"
      confirmDisabled={needsHandover && (!loadedReplacements || !replacementId)}
      pending={pending}
      size="md"
    >
      <div className="flex flex-col gap-4 py-1">
        {needsHandover && (
          <div className="flex flex-col gap-2">
            <p className="bg-muted text-muted-foreground rounded-md p-3 text-sm">
              This {variant} is assigned to{' '}
              <strong className="text-foreground">
                {assignedCount} {assignedCount === 1 ? 'student' : 'students'}
              </strong>
              . Choose a replacement {variant} to hand them over to before deactivating.
            </p>
            <Label htmlFor="replacement">Reassign students to</Label>
            <Select value={replacementId} onValueChange={setReplacementId} disabled={!loadedReplacements}>
              <SelectTrigger id="replacement" className="w-full">
                <SelectValue placeholder={loadedReplacements ? `Select a ${variant}` : 'Loading…'} />
              </SelectTrigger>
              <SelectContent>
                {replacements.map((option) => (
                  <SelectItem key={option.id} value={option.id}>
                    {option.full_name || option.email}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        )}
        <div className="flex flex-col gap-2">
          <Label htmlFor="deactivate-reason">Reason (optional)</Label>
          <Input
            id="deactivate-reason"
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            placeholder="e.g. Left the company"
          />
        </div>
      </div>
    </FormDialog>
  );
}
