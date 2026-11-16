import { useState } from 'react';
import { InfoIcon, PlusIcon } from 'lucide-react';

import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog';

export const AUTOMATIC_INVITATIONS = 'Student invitations are now created automatically during enrollment.';

/**
 * "New Invitation": where the manual student invitation form used to open.
 * Student Learn accounts and their invitations are now created only by
 * enrollment, so it opens nothing but that message -- no student code, sheet
 * lookup or form, and no request. Staff accounts are made in Team.
 */
export function NewInvitation() {
  const [open, setOpen] = useState(false);
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button>
          <PlusIcon />
          New Invitation
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-[425px]">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <InfoIcon className="text-muted-foreground size-4" aria-hidden="true" />
            New Invitation
          </DialogTitle>
          <DialogDescription>{AUTOMATIC_INVITATIONS}</DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)}>
            OK
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
