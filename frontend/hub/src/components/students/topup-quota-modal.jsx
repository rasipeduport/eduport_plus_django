import { useEffect, useState } from 'react';
import { Loader2 } from 'lucide-react';

import { Button } from '@/components/ui/button';
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
import { Separator } from '@/components/ui/separator';
import api from '@/lib/api';

export function TopupQuotaModal({ student, open, onOpenChange, onSaved }) {
  const [additionalQuota, setAdditionalQuota] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (open) {
      setAdditionalQuota('');
      setError('');
    }
  }, [open]);

  const currentQuota = student.total_class_quota ?? 0;
  const parsed = parseInt(additionalQuota, 10);

  const handleSubmit = async (event) => {
    event.preventDefault();
    if (Number.isNaN(parsed) || parsed <= 0) {
      setError('Please enter a valid positive number of classes.');
      return;
    }
    setSaving(true);
    setError('');
    try {
      await api.put('/api/students/', {
        id: student.id,
        total_class_quota: currentQuota + parsed,
      });
      onSaved?.();
      onOpenChange(false);
    } catch (err) {
      setError(err.response?.data?.message || 'Failed to update class quota.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>Top-up Class Quota</DialogTitle>
          <DialogDescription>Manage the session balance for {student.full_name}</DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          {error && <p className="text-destructive text-sm">{error}</p>}

          <div className="flex items-center justify-between text-sm">
            <span className="text-muted-foreground">Total classes purchased</span>
            <span className="font-mono font-medium tabular-nums">{currentQuota}</span>
          </div>

          <Separator />

          <div className="flex items-center justify-between gap-4">
            <Label htmlFor="topup-val">Add classes</Label>
            <Input
              id="topup-val"
              type="number"
              min="1"
              placeholder="0"
              value={additionalQuota}
              onChange={(event) => setAdditionalQuota(event.target.value)}
              className="w-24 text-right"
              disabled={saving}
              required
            />
          </div>

          <Separator />

          <div className="flex items-center justify-between text-sm">
            <span className="text-muted-foreground">Updated total quota</span>
            <span className="text-success font-mono font-medium tabular-nums">
              {currentQuota + (Number.isNaN(parsed) ? 0 : parsed)}
            </span>
          </div>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={saving}>
              Cancel
            </Button>
            <Button type="submit" disabled={saving || !additionalQuota}>
              {saving && <Loader2 className="animate-spin" />}
              Confirm Top-up
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
