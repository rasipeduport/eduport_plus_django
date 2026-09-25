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
import api from '@/lib/api';

const MEET_PREFIX = 'https://meet.google.com/';

function extractMeetCode(link) {
  if (!link) return '';
  return link.startsWith(MEET_PREFIX) ? link.slice(MEET_PREFIX.length) : link;
}

export function EditMeetLinkModal({ student, open, onOpenChange, onSaved }) {
  const [meetCode, setMeetCode] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (open) {
      setMeetCode(extractMeetCode(student.meet_link));
      setError('');
    }
  }, [open, student.meet_link]);

  const handleSubmit = async (event) => {
    event.preventDefault();
    setSaving(true);
    setError('');
    const trimmed = meetCode.trim();
    try {
      await api.put('/api/students/', {
        id: student.id,
        meet_link: trimmed ? `${MEET_PREFIX}${trimmed}` : null,
      });
      onSaved?.();
      onOpenChange(false);
    } catch (err) {
      setError(err.response?.data?.message || 'Failed to save meet link.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>Edit Meet Link</DialogTitle>
          <DialogDescription>{student.full_name}</DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          {error && <p className="text-destructive text-sm">{error}</p>}

          <div className="flex flex-col gap-2">
            <Label htmlFor="meet-code">Google Meet Link</Label>
            <div className="flex items-center gap-2">
              <span className="text-muted-foreground shrink-0 text-sm">meet.google.com/</span>
              <Input
                id="meet-code"
                value={meetCode}
                onChange={(event) => setMeetCode(event.target.value)}
                placeholder="abc-defg-hij"
                disabled={saving}
                required
              />
            </div>
          </div>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={saving}>
              Cancel
            </Button>
            <Button type="submit" disabled={saving}>
              {saving && <Loader2 className="animate-spin" />}
              Save Link
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
