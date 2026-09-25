import { useState } from 'react';
import { MoreVertical } from 'lucide-react';

import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { EMAIL_RE } from '@/lib/utils';
import api from '@/lib/api';

function EditEmailDialog({ invitation, open, onOpenChange, onSuccess }) {
  const [email, setEmail] = useState(invitation.email);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState('');

  const handleOpenChange = (value) => {
    onOpenChange(value);
    if (value) {
      setEmail(invitation.email);
      setError('');
    }
  };

  const handleSubmit = async (event) => {
    event.preventDefault();
    setError('');

    const trimmedEmail = email.trim();
    if (!trimmedEmail) {
      setError('Email is required');
      return;
    }
    if (!EMAIL_RE.test(trimmedEmail)) {
      setError('Invalid email format');
      return;
    }

    setIsSaving(true);
    try {
      await api.patch('/api/invitations/', {
        old_email: invitation.email,
        new_email: trimmedEmail.toLowerCase(),
      });
      onOpenChange(false);
      onSuccess?.();
    } catch (err) {
      setError(err.response?.data?.message || 'Failed to update email');
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="sm:max-w-[425px]">
        <DialogHeader>
          <DialogTitle>Edit Email</DialogTitle>
          <DialogDescription>Update the email address for this invitation.</DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit}>
          <div className="grid gap-4 py-4">
            <div className="grid gap-2">
              <Label htmlFor="invitation-email">Email</Label>
              <Input
                id="invitation-email"
                type="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                placeholder="user@example.com"
                disabled={isSaving}
              />
              {error && <p className="text-destructive text-sm">{error}</p>}
            </div>
          </div>
          <DialogFooter>
            <Button type="submit" disabled={isSaving}>
              {isSaving ? 'Saving...' : 'Save changes'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function WithdrawDialog({ invitation, open, onOpenChange, onSuccess }) {
  const [isDeleting, setIsDeleting] = useState(false);
  const [error, setError] = useState('');

  const handleOpenChange = (value) => {
    onOpenChange(value);
    if (value) setError('');
  };

  const handleDelete = async () => {
    setError('');
    setIsDeleting(true);
    try {
      await api.delete('/api/invitations/', { data: { email: invitation.email } });
      onOpenChange(false);
      onSuccess?.();
    } catch (err) {
      setError(err.response?.data?.message || 'Failed to delete invitation');
    } finally {
      setIsDeleting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="sm:max-w-[425px]">
        <DialogHeader>
          <DialogTitle>Withdraw Invitation</DialogTitle>
          <DialogDescription>
            Are you sure you want to withdraw the invitation for <strong>{invitation.email}</strong>? This action cannot
            be undone.
          </DialogDescription>
        </DialogHeader>
        {error && <p className="text-destructive text-sm">{error}</p>}
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isDeleting}>
            Cancel
          </Button>
          <Button variant="destructive" onClick={handleDelete} disabled={isDeleting}>
            {isDeleting ? 'Deleting...' : 'Withdraw'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function InvitationActionCell({ invitation, onChanged }) {
  const [editOpen, setEditOpen] = useState(false);
  const [withdrawOpen, setWithdrawOpen] = useState(false);

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="ghost" className="h-8 w-8 p-0">
            <span className="sr-only">Open menu</span>
            <MoreVertical className="h-4 w-4" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuLabel>Actions</DropdownMenuLabel>
          <DropdownMenuItem onClick={() => setEditOpen(true)}>Edit email</DropdownMenuItem>
          <DropdownMenuItem onClick={() => setWithdrawOpen(true)}>Withdraw invitation</DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
      <EditEmailDialog invitation={invitation} open={editOpen} onOpenChange={setEditOpen} onSuccess={onChanged} />
      <WithdrawDialog invitation={invitation} open={withdrawOpen} onOpenChange={setWithdrawOpen} onSuccess={onChanged} />
    </>
  );
}
