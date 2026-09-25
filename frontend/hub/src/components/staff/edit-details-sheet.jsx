import { useState } from 'react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Sheet, SheetContent, SheetDescription, SheetFooter, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import api from '@/lib/api';

export function EditDetailsSheet({ row, open, onOpenChange, onSaved }) {
  const [fullName, setFullName] = useState(row.full_name ?? '');
  const [mobileNumber, setMobileNumber] = useState(row.mobile_number ?? '');
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState('');

  // Re-sync the form from the row prop each time the sheet is opened.
  // Adjusting state during render, guarded by the previous open value, is
  // React's recommended alternative to a synchronizing effect.
  const [prevOpen, setPrevOpen] = useState(open);
  if (open !== prevOpen) {
    setPrevOpen(open);
    if (open) {
      setFullName(row.full_name ?? '');
      setMobileNumber(row.mobile_number ?? '');
      setError('');
    }
  }

  const handleSubmit = async (event) => {
    event.preventDefault();
    setError('');

    const trimmedName = fullName.trim();
    if (!trimmedName) {
      setError('Name is required');
      return;
    }

    setIsSaving(true);
    try {
      await api.patch(`/api/users/${row.id}/`, {
        full_name: trimmedName,
        mobile_number: mobileNumber.trim() || null,
      });
      onSaved?.();
      onOpenChange(false);
    } catch (err) {
      setError(err.response?.data?.message || 'Failed to update user');
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="flex flex-col gap-0 sm:max-w-md">
        <SheetHeader>
          <SheetTitle>Edit details</SheetTitle>
          <SheetDescription>
            Update name and phone number for {row.email}. Email is managed by their sign-in provider and cannot be
            changed.
          </SheetDescription>
        </SheetHeader>
        <form onSubmit={handleSubmit} className="flex flex-1 flex-col gap-4 overflow-y-auto px-4 pt-4">
          <div className="grid gap-2">
            <Label htmlFor="full_name">Name</Label>
            <Input
              id="full_name"
              value={fullName}
              onChange={(event) => setFullName(event.target.value)}
              placeholder="Full name"
              disabled={isSaving}
              required
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="mobile_number">Phone number</Label>
            <Input
              id="mobile_number"
              value={mobileNumber}
              onChange={(event) => setMobileNumber(event.target.value)}
              placeholder="+91 98765 43210"
              disabled={isSaving}
              inputMode="tel"
            />
          </div>
          {error && <p className="text-destructive text-sm">{error}</p>}
          <SheetFooter className="mt-auto px-0">
            <Button type="submit" disabled={isSaving}>
              {isSaving ? 'Saving...' : 'Save changes'}
            </Button>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={isSaving}>
              Cancel
            </Button>
          </SheetFooter>
        </form>
      </SheetContent>
    </Sheet>
  );
}
