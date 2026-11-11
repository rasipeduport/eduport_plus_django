import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { PERMISSIONS, can } from '@/lib/access';
import api from '@/lib/api';

export function InvitationActionCell({ invitation, user, onChanged }) {
  const [credentials, setCredentials] = useState(null);
  const [error, setError] = useState('');
  const [pending, setPending] = useState(false);
  const [copied, setCopied] = useState(false);
  const reveal = async () => {
    setPending(true); setError('');
    try {
      const { data } = await api.post(`/api/invitations/${invitation.id}/credentials/`);
      setCredentials(data);
    } catch (err) { setError(err.response?.data?.message || err.response?.data?.detail || 'Could not retrieve credentials.'); }
    finally { setPending(false); }
  };
  const issue = async () => {
    setPending(true); setError('');
    try { await api.post(`/api/invitations/students/${invitation.student_id}/issue/`); onChanged?.(); }
    catch (err) { setError(err.response?.data?.detail || 'Could not issue credentials.'); }
    finally { setPending(false); }
  };
  const canReveal = can(user, PERMISSIONS.changeInvitation) && can(user, PERMISSIONS.viewInvitations);
  return <div className="space-y-2">
    {invitation.credentials_available && canReveal ? <Button type="button" size="sm" variant="outline" className="max-w-full whitespace-normal text-left" disabled={pending} onClick={reveal}>Reveal temporary password</Button> : null}
    {invitation.legacy && invitation.student_id && can(user, PERMISSIONS.createInvitation) ? <Button type="button" size="sm" variant="outline" className="max-w-full whitespace-normal text-left" disabled={pending} onClick={issue}>Issue Learn credentials</Button> : null}
    {error ? <p role="alert" className="text-destructive text-sm">{error}</p> : null}
    <Dialog open={Boolean(credentials)} onOpenChange={(open) => { if (!open) { setCredentials(null); setCopied(false); } }}>
      <DialogContent><DialogHeader><DialogTitle>Initial Learn credentials</DialogTitle><DialogDescription>Share privately with the student or parent. The temporary password is erased after the first password change.</DialogDescription></DialogHeader>
        {credentials ? <div className="min-w-0 space-y-4">
          <p className="text-sm">{invitation.student_name} · {credentials.student_code}</p>
          <label className="block space-y-1 text-sm">Username<Input readOnly value={credentials.username} /></label>
          <label className="block space-y-1 text-sm">Temporary password<Input readOnly autoComplete="off" value={credentials.temporary_password} /></label>
          <Button onClick={async () => {
            try { await navigator.clipboard.writeText(`Eduport Plus Learn\n${invitation.student_name} · ${credentials.student_code}\nUsername: ${credentials.username}\nTemporary password: ${credentials.temporary_password}\nChange your password at first sign in.`); setCopied(true); }
            catch { setError('Clipboard unavailable. Copy the credentials manually.'); }
          }}>{copied ? 'Copied' : 'Copy credentials'}</Button>
        </div> : null}
      </DialogContent>
    </Dialog>
  </div>;
}
