import { useMemo } from 'react';

import { DataTable } from '@/components/data-table';
import { createColumns } from './columns';
import { NewInvitation } from './new-invitation';

export function InvitationsTable({ data, initialRole, initialOpen, onChanged }) {
  const columns = useMemo(() => createColumns(onChanged), [onChanged]);

  return (
    <DataTable
      columns={columns}
      data={data}
      actions={<NewInvitation initialRole={initialRole} initialOpen={initialOpen} onSuccess={onChanged} />}
    />
  );
}
