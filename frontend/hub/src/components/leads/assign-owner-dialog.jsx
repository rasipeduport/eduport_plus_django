import { useState } from 'react';

import { FormDialog } from '@/components/form-dialog';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import api from '@/lib/api';
import { enquiryError } from '@/lib/enquiries';
import { leadOwnerUrl } from '@/lib/leads';

/**
 * Gives `lead` (a list row or the lead in full: id, student_name, owner) to
 * an active BDE -- the first owner of an unassigned lead, or another BDE for
 * one already owned. The lead leaves its previous BDE's My Leads and joins the
 * new one's at once. The owner the page showed is sent with the choice
 * (`current_owner_id`): when someone else changed it meanwhile the API changes
 * nothing and answers OWNER_CHANGED, and the page reads the lead again
 * (`onStale`) so the administrator decides on what is true now.
 */
export function AssignOwnerDialog({ lead, bdes, open, onOpenChange, onAssigned, onStale }) {
  const [bdeId, setBdeId] = useState('');
  const [error, setError] = useState(null);
  const [pending, setPending] = useState(false);

  // A fresh choice on every open.
  const [prevOpen, setPrevOpen] = useState(open);
  if (open !== prevOpen) {
    setPrevOpen(open);
    if (open) {
      setBdeId('');
      setError(null);
    }
  }

  const current = lead?.owner ?? null;
  // Only an active BDE takes a lead (backend bookings.ownership), and never the one who has it.
  const choices = (bdes ?? []).filter((bde) => bde.assignable && bde.id !== current?.id);

  async function handleSubmit(event) {
    event.preventDefault();
    if (!bdeId) {
      setError('Choose the BDE to assign.');
      return;
    }
    setPending(true);
    setError(null);
    try {
      const response = await api.put(leadOwnerUrl(lead.id), { bde_id: bdeId, current_owner_id: current?.id ?? null });
      onAssigned?.(response.data);
      onOpenChange(false);
    } catch (err) {
      const failure = enquiryError(err, 'Could not assign the lead.');
      setError(failure.message);
      if (failure.code === 'OWNER_CHANGED') onStale?.();
    } finally {
      setPending(false);
    }
  }

  const verb = current ? 'Reassign' : 'Assign';
  return (
    <FormDialog
      open={open}
      onOpenChange={onOpenChange}
      title={`${verb} lead`}
      description={
        lead
          ? current
            ? `${lead.student_name}'s lead is ${current.full_name}'s. The BDE you choose takes it over, with its bookings; it leaves ${current.full_name}'s My Leads.`
            : `${lead.student_name}'s lead has no BDE yet. The BDE you choose finds it in their My Leads.`
          : null
      }
      error={error}
      formId="assign-lead-owner"
      confirmLabel={verb}
      pendingLabel={current ? 'Reassigning…' : 'Assigning…'}
      pending={pending}
      confirmDisabled={!choices.length}
    >
      <form id="assign-lead-owner" onSubmit={handleSubmit} className="grid gap-2 py-1" noValidate>
        <Label htmlFor="lead-owner" required>
          BDE
        </Label>
        <Select value={bdeId} onValueChange={setBdeId} disabled={pending || !choices.length}>
          <SelectTrigger id="lead-owner" className="w-full" aria-label="BDE" aria-required="true">
            <SelectValue placeholder={choices.length ? 'Choose a BDE' : 'No other active BDE'} />
          </SelectTrigger>
          <SelectContent>
            {choices.map((bde) => (
              <SelectItem key={bde.id} value={bde.id}>
                {bde.full_name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </form>
    </FormDialog>
  );
}
