import { useState } from 'react';
import { MoreVertical } from 'lucide-react';

import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { EditDetailsSheet } from './edit-details-sheet';
import { DeactivateUserDialog } from './deactivate-user-dialog';
import { ReactivateUserDialog } from './reactivate-user-dialog';

export function StaffActionsCell({ row, variant, onChanged }) {
  const [editOpen, setEditOpen] = useState(false);
  const [deactivateOpen, setDeactivateOpen] = useState(false);
  const [reactivateOpen, setReactivateOpen] = useState(false);

  const isDeactivated = !!row.deactivated_at;
  // Admins are peers — one admin never deactivates/reactivates another. Only
  // mentors and tutors are managed through this menu.
  const canManageStatus = variant !== 'admin';

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="ghost" size="icon" className="size-8">
            <MoreVertical className="size-4" />
            <span className="sr-only">Open menu</span>
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuLabel>Actions</DropdownMenuLabel>
          <DropdownMenuSeparator />
          <DropdownMenuItem onSelect={() => setEditOpen(true)}>Edit details</DropdownMenuItem>
          {canManageStatus &&
            (isDeactivated ? (
              <DropdownMenuItem onSelect={() => setReactivateOpen(true)}>Reactivate</DropdownMenuItem>
            ) : (
              <DropdownMenuItem
                onSelect={() => setDeactivateOpen(true)}
                className="text-destructive focus:text-destructive"
              >
                Deactivate
              </DropdownMenuItem>
            ))}
        </DropdownMenuContent>
      </DropdownMenu>

      <EditDetailsSheet row={row} open={editOpen} onOpenChange={setEditOpen} onSaved={onChanged} />
      {canManageStatus && (
        <>
          <DeactivateUserDialog
            row={row}
            variant={variant}
            open={deactivateOpen}
            onOpenChange={setDeactivateOpen}
            onSaved={onChanged}
          />
          <ReactivateUserDialog row={row} open={reactivateOpen} onOpenChange={setReactivateOpen} onSaved={onChanged} />
        </>
      )}
    </>
  );
}
