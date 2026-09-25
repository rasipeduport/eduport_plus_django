import { InvitationActionCell } from './invitation-action-cell';

const dateTimeFormatter = new Intl.DateTimeFormat('en-US', {
  year: 'numeric',
  month: 'short',
  day: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
});

/**
 * Columns for the invitations table (Hub parity).
 *
 * `onChanged` refetches the list after the action cell edits or withdraws a
 * row -- the SPA equivalent of the Hub's `router.refresh()`.
 */
export function createColumns(onChanged) {
  return [
    {
      accessorKey: 'email',
      header: 'Email',
    },
    {
      accessorKey: 'role',
      header: 'Role',
      cell: ({ row }) => {
        const role = row.getValue('role');
        return <span className="capitalize">{role ? role.toLowerCase() : 'N/A'}</span>;
      },
    },
    {
      accessorKey: 'created_at',
      header: 'Invited At',
      cell: ({ row }) => {
        const timestamp = row.getValue('created_at');
        if (!timestamp) return 'N/A';
        return dateTimeFormatter.format(new Date(timestamp));
      },
    },
    {
      id: 'invited_by',
      header: 'Invited by',
      cell: ({ row }) => {
        const inviter = row.original.invited_by_profile;
        if (!inviter) return <span className="text-muted-foreground">—</span>;
        return <span>{inviter.full_name || inviter.email}</span>;
      },
    },
    {
      id: 'actions',
      cell: ({ row }) => {
        // The Hub's signup trigger deletes the whitelist row, so an accepted
        // invitation never reaches its table. Here the row survives with
        // status ACCEPTED and the API refuses to edit or withdraw it, so the
        // menu is hidden rather than offering actions that always fail.
        if (row.original.status === 'ACCEPTED') return null;
        return <InvitationActionCell invitation={row.original} onChanged={onChanged} />;
      },
    },
  ];
}
