import { useState } from 'react';

import { FormDialog } from '@/components/form-dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import api from '@/lib/api';
import { HANDOVER_ROLES, isActiveMember, memberUrl, reassignUrl, teamError } from '@/lib/team';
import { ReplacementSelect } from './student-handover';

/**
 * Deactivates an active account (with an optional reason) or reactivates a
 * deactivated one. Deactivation ends the person's open sessions at once. The
 * API never deactivates the last admin, and refuses while a mentor or tutor
 * still has active students: the dialog then asks for a colleague to hand
 * them to, and reassigns before deactivating.
 */
export function MemberStatusDialog({ member, open, onOpenChange, onDone }) {
  // Fixed when the dialog opens, so the refreshed member arriving after a
  // success does not flip the dialog while it closes.
  const [deactivating, setDeactivating] = useState(() => isActiveMember(member));
  const [reason, setReason] = useState('');
  const [failure, setFailure] = useState(null);
  const [pending, setPending] = useState(false);
  // Set once the API has answered HANDOVER_REQUIRED: the explanation it gave.
  const [handoverNote, setHandoverNote] = useState('');
  const [replacement, setReplacement] = useState('');

  const [prevOpen, setPrevOpen] = useState(open);
  if (open !== prevOpen) {
    setPrevOpen(open);
    if (open) {
      setDeactivating(isActiveMember(member));
      setReason('');
      setFailure(null);
      setHandoverNote('');
      setReplacement('');
    }
  }

  const name = member.full_name || member.username;
  const handover = handoverNote ? HANDOVER_ROLES[member.role] : null;

  async function handleConfirm() {
    setPending(true);
    setFailure(null);
    try {
      if (deactivating) {
        if (handover) await api.post(reassignUrl(member.id), { [handover.field]: replacement });
        await api.post(memberUrl(member.id, 'deactivate/'), reason.trim() ? { reason: reason.trim() } : {});
        onDone?.(
          handover
            ? `Handed over ${name}'s students and deactivated ${name}. Their open sessions have ended.`
            : `Deactivated ${name}. Their open sessions have ended.`
        );
      } else {
        await api.post(memberUrl(member.id, 'reactivate/'), {});
        onDone?.(`Reactivated ${name}.`);
      }
      onOpenChange(false);
    } catch (err) {
      const refusal = teamError(
        err,
        deactivating ? 'Could not deactivate the account.' : 'Could not reactivate the account.'
      );
      if (deactivating && refusal.code === 'HANDOVER_REQUIRED' && HANDOVER_ROLES[member.role]) {
        setHandoverNote(refusal.message);
      } else {
        setFailure(refusal);
      }
    } finally {
      setPending(false);
    }
  }

  return (
    <FormDialog
      open={open}
      onOpenChange={onOpenChange}
      title={deactivating ? 'Deactivate account' : 'Reactivate account'}
      description={
        deactivating ? (
          <>
            This revokes <strong>{name}</strong>&apos;s access and signs them out everywhere. Their account and history
            are kept, and they can be reactivated later.
          </>
        ) : (
          <>
            Restore <strong>{name}</strong>&apos;s access. They can sign in again immediately.
          </>
        )
      }
      error={failure?.message}
      onConfirm={handleConfirm}
      confirmLabel={!deactivating ? 'Reactivate' : handover ? 'Reassign & deactivate' : 'Deactivate'}
      pendingLabel="Working…"
      confirmVariant={deactivating ? 'destructive' : 'default'}
      confirmDisabled={Boolean(handover) && !replacement}
      pending={pending}
      size="md"
    >
      {deactivating ? (
        <div className="flex flex-col gap-4 py-1">
          {handover ? (
            <>
              <p className="bg-muted text-muted-foreground rounded-md p-3 text-sm">
                {handoverNote} Choose the {handover.noun} who takes them over; {name} is deactivated straight after.
              </p>
              <ReplacementSelect member={member} value={replacement} onChange={setReplacement} disabled={pending} />
            </>
          ) : null}
          <div className="flex flex-col gap-2">
            <Label htmlFor="team-deactivate-reason">Reason (optional)</Label>
            <Input
              id="team-deactivate-reason"
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              placeholder="e.g. Left the company"
              maxLength={500}
              disabled={pending}
            />
          </div>
        </div>
      ) : null}
    </FormDialog>
  );
}
