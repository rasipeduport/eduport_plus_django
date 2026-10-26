import { useMemo } from 'react';

import { DataTable } from '@/components/data-table';
import { PERMISSIONS, can } from '@/lib/access';
import { createColumns } from './columns';
import { NewInvitation } from './new-invitation';

export function InvitationsTable({ data, user, initialOpen, onChanged }) {
  const columns = useMemo(() => createColumns(user, onChanged), [user, onChanged]);

  return (
    <DataTable
      columns={columns}
      data={data}
      actions={
        can(user, PERMISSIONS.createInvitation) ? <NewInvitation initialOpen={initialOpen} onSuccess={onChanged} /> : undefined
      }
    />
  );
}
