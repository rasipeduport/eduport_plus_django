import { useState } from 'react';
import { IdCardIcon } from 'lucide-react';

import api from '@/lib/api';
import { salesError } from '@/lib/sales';
import { billingContactUrl, cancelAutopayUrl, identityCorrectionUrl } from '@/lib/payments';
import { FormDialog } from '@/components/form-dialog';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Field, WorkspaceCard } from '@/components/bookings/redemo-workspace/parts';

const RELATIONSHIPS = [['PARENT', 'Parent'], ['MOTHER', 'Mother'], ['FATHER', 'Father'], ['GUARDIAN', 'Guardian'], ['OTHER', 'Other']];

function ContactFields({ value, onChange, idPrefix }) {
  const set = (key) => (event) => onChange({ ...value, [key]: event.target.value });
  return <div className="grid gap-3 sm:grid-cols-3">
    <div className="flex flex-col gap-1.5"><Label htmlFor={`${idPrefix}-name`}>Parent / guardian name</Label><Input id={`${idPrefix}-name`} required maxLength={255} value={value.full_name ?? ''} onChange={set('full_name')} /></div>
    <div className="flex flex-col gap-1.5"><Label htmlFor={`${idPrefix}-email`}>Parent email (optional)</Label><Input id={`${idPrefix}-email`} type="email" maxLength={254} value={value.email ?? ''} onChange={set('email')} /></div>
    <div className="flex flex-col gap-1.5"><Label htmlFor={`${idPrefix}-phone`}>Parent phone</Label><Input id={`${idPrefix}-phone`} maxLength={20} value={value.phone ?? ''} onChange={set('phone')} /></div>
  </div>;
}

/**
 * Who the child's billing contact is when a sale starts. Families sharing this
 * parent's phone or email are only suggested; the BDE decides, and confirms the
 * child is not one already enquired about.
 */
export function FamilyAndContact({ candidates = [], value, onChange }) {
  const family = value.family?.mode === 'EXISTING_FAMILY' ? value.family.guardian_id : 'NEW';
  const choose = (guardianId) => onChange({ ...value, family: guardianId === 'NEW' ? { mode: 'NEW_FAMILY' } : { mode: 'EXISTING_FAMILY', guardian_id: guardianId } });
  return <fieldset className="flex flex-col gap-3">
    <legend className="mb-1 text-sm font-medium">Student account and billing contact</legend>
    <p className="text-muted-foreground text-xs">Each child gets their own student account and Stripe Customer. Eduport Plus supplies the student’s details to Stripe, and the parent cannot change them there. Without a parent email, Stripe asks the parent for one, and it is saved here once the payment is verified.</p>
    {candidates.length ? <div role="group" aria-label="Existing families" className="flex flex-col gap-2 rounded-lg border p-3 text-sm">
      <p className="font-medium">This parent’s {candidates.flatMap((row) => row.matched_on).filter((v, i, a) => a.indexOf(v) === i).join(' and ')} already belongs to a family:</p>
      {candidates.map((row) => <label key={row.guardian_id} className="flex cursor-pointer items-start gap-2">
        <input type="radio" name="family-choice" className="accent-primary mt-1" checked={family === row.guardian_id} onChange={() => choose(row.guardian_id)} />
        <span>Sibling in {row.full_name}’s family <span className="text-muted-foreground block text-xs">Children: {row.children.map((child) => `${child.student_name} (${child.reference}${child.student_code ? ` · ${child.student_code}` : ''})`).join(', ')}</span></span>
      </label>)}
      <label className="flex cursor-pointer items-start gap-2"><input type="radio" name="family-choice" className="accent-primary mt-1" checked={family === 'NEW'} onChange={() => choose('NEW')} /><span>A different family (new billing contact)</span></label>
      <label className="flex items-start gap-2 border-t pt-2"><input type="checkbox" className="accent-primary mt-1" checked={Boolean(value.confirm_distinct_child)} onChange={(event) => onChange({ ...value, confirm_distinct_child: event.target.checked })} />
        <span>I confirmed this is a different child, not one of the children listed above enquiring again.</span></label>
    </div> : null}
    {family === 'NEW' ? <ContactFields idPrefix="billing" value={value.billing_contact ?? {}} onChange={(contact) => onChange({ ...value, billing_contact: contact })} /> : null}
    <div className="flex max-w-xs flex-col gap-1.5"><Label htmlFor="billing-relationship">Relationship to the student</Label>
      <select id="billing-relationship" className="border-input bg-background h-9 rounded-md border px-3 text-sm" value={value.relationship ?? 'PARENT'} onChange={(event) => onChange({ ...value, relationship: event.target.value })}>
        {RELATIONSHIPS.map(([key, label]) => <option key={key} value={key}>{label}</option>)}
      </select></div>
  </fieldset>;
}

function EditContactDialog({ open, onOpenChange, enquiryId, contact, onChanged }) {
  const [value, setValue] = useState(contact);
  const [error, setError] = useState(null);
  const [pending, setPending] = useState(false);
  const save = async () => {
    setPending(true); setError(null);
    try { const { data } = await api.put(billingContactUrl(enquiryId), value); onChanged(data); onOpenChange(false); }
    catch (err) { setError(salesError(err, 'Could not save the billing contact.').message); }
    finally { setPending(false); }
  };
  return <FormDialog open={open} onOpenChange={onOpenChange} size="lg" title="Billing contact"
    description="Used for this child’s Stripe receipts and invoices. Shared siblings in the same family see the change too."
    onConfirm={save} confirmLabel="Save contact" pending={pending} error={error}>
    <ContactFields idPrefix="edit-billing" value={value} onChange={setValue} />
  </FormDialog>;
}

function CorrectIdentityDialog({ open, onOpenChange, account, onChanged }) {
  const [name, setName] = useState(account.student_name);
  const [reason, setReason] = useState('');
  const [error, setError] = useState(null);
  const [pending, setPending] = useState(false);
  const save = async () => {
    setPending(true); setError(null);
    try { await api.post(identityCorrectionUrl(account.id), { student_name: name, reason }); onChanged(); onOpenChange(false); }
    catch (err) { setError(salesError(err, 'Could not correct the student’s identity.').message); }
    finally { setPending(false); }
  };
  return <FormDialog open={open} onOpenChange={onOpenChange} size="lg" title="Correct student identity"
    description={`Corrects ${account.reference} everywhere: enquiry, student record and Stripe Customer. Only for the same child; the reason is kept in the audit trail.`}
    onConfirm={save} confirmLabel="Correct identity" pending={pending} error={error} confirmDisabled={reason.trim().length < 10 || !name.trim()}>
    <div className="flex flex-col gap-3">
      <div className="flex flex-col gap-1.5"><Label htmlFor="corrected-name">Student name</Label><Input id="corrected-name" value={name} maxLength={255} onChange={(event) => setName(event.target.value)} /></div>
      <div className="flex flex-col gap-1.5"><Label htmlFor="correction-reason">Reason (required)</Label><Textarea id="correction-reason" value={reason} maxLength={2000} onChange={(event) => setReason(event.target.value)} /></div>
    </div>
  </FormDialog>;
}

export function StudentAccountCard({ enquiryId, account, onChanged, readOnly = false }) {
  const [editing, setEditing] = useState(false);
  const [correcting, setCorrecting] = useState(false);
  if (!account) return null;
  const contact = account.billing_contact;
  const customers = account.stripe_customers ?? [];
  return <WorkspaceCard icon={IdCardIcon} title="Student account" action={<Badge variant="outline">{account.reference}</Badge>}>
    <dl className="grid gap-x-6 gap-y-4 sm:grid-cols-2 xl:grid-cols-4">
      <Field label="Student" className="grid-cols-1 gap-1 py-0">{account.student_name}</Field>
      <Field label="EDP ID" className="grid-cols-1 gap-1 py-0">{account.student?.student_code ?? 'After the first verified tuition payment'}</Field>
      <Field label="Billing contact" className="grid-cols-1 gap-1 py-0">{contact ? <span>{contact.full_name}<span className="text-muted-foreground block text-xs">{contact.email || 'No email yet: asked on Stripe'} · {contact.phone || 'No phone'}</span></span> : '—'}</Field>
      <Field label="Stripe Customer" className="grid-cols-1 gap-1 py-0">{customers.length ? customers.map((row) => <span key={row.customer_id} className="block break-all font-mono text-xs">{row.customer_id}{row.label_format === 'LEGACY_PARENT' ? ' · legacy parent name' : ''}</span>) : 'Created with the first Stripe link'}</Field>
    </dl>
    {account.identity_locked ? <p className="text-muted-foreground text-xs">Identity locked by a payment record or link: corrections need an administrator and a reason.</p> : null}
    {!readOnly ? <div className="flex flex-wrap gap-2">
      {contact ? <Button type="button" variant="outline" size="sm" onClick={() => setEditing(true)}>Edit billing contact</Button> : null}
      {account.can_correct_identity ? <Button type="button" variant="outline" size="sm" onClick={() => setCorrecting(true)}>Correct identity</Button> : null}
    </div> : null}
    {account.corrections?.length ? <details><summary className="cursor-pointer text-sm">Identity corrections ({account.corrections.length})</summary><ul className="mt-2 space-y-1 text-xs">{account.corrections.map((row) => <li key={row.created_at}>{new Date(row.created_at).toLocaleString()} · {row.corrected_by}: {Object.entries(row.changes).map(([field, change]) => `${field} “${change.old}” → “${change.new}”`).join('; ')} — {row.reason}</li>)}</ul></details> : null}
    {editing ? <EditContactDialog open={editing} onOpenChange={setEditing} enquiryId={enquiryId} contact={{ full_name: contact.full_name, email: contact.email, phone: contact.phone }} onChanged={onChanged} /> : null}
    {correcting ? <CorrectIdentityDialog open={correcting} onOpenChange={setCorrecting} account={account} onChanged={() => onChanged()} /> : null}
  </WorkspaceCard>;
}

export function CancelAutopay({ agreement, onChanged }) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState('');
  const [source, setSource] = useState('ADMIN');
  const [error, setError] = useState(null);
  const [pending, setPending] = useState(false);
  const cancel = async () => {
    setPending(true); setError(null);
    try { const { data } = await api.post(cancelAutopayUrl(agreement.id), { reason, source }); onChanged(data); setOpen(false); }
    catch (err) { setError(salesError(err, 'Could not cancel Autopay.').message); }
    finally { setPending(false); }
  };
  return <>
    <div><Button type="button" variant="outline" onClick={() => setOpen(true)}>Cancel Autopay</Button></div>
    <FormDialog open={open} onOpenChange={setOpen} size="lg" title="Cancel Autopay" confirmVariant="destructive"
      description="Stripe stops future installments first; if it cannot confirm, nothing changes. Paid installments, payments and classes stay as they are, and open invoices are not voided automatically."
      onConfirm={cancel} confirmLabel="Cancel Autopay" pending={pending} error={error} confirmDisabled={reason.trim().length < 10}>
      <div className="flex flex-col gap-3">
        <div role="radiogroup" aria-label="Requested by" className="flex flex-wrap gap-4 text-sm">
          {[['ADMIN', 'Administrator decision'], ['PARENT_REQUEST', 'Parent’s request']].map(([key, label]) => <label key={key} className="flex items-center gap-2"><input type="radio" name="cancel-source" className="accent-primary" checked={source === key} onChange={() => setSource(key)} />{label}</label>)}
        </div>
        <div className="flex flex-col gap-1.5"><Label htmlFor="cancel-reason">Reason (required)</Label><Textarea id="cancel-reason" value={reason} maxLength={2000} onChange={(event) => setReason(event.target.value)} /></div>
      </div>
    </FormDialog>
  </>;
}
