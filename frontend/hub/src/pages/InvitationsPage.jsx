import { useCallback, useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';

import api from '@/lib/api';
import { TableSkeleton } from '@/components/table-skeleton';
import { InvitationsTable } from '@/components/invitations/invitations-table';

export default function InvitationsPage() {
  const [searchParams] = useSearchParams();
  const [invitations, setInvitations] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  // Read once on mount: NewInvitation strips these params after consuming them,
  // so re-reading them on every render would close the form again.
  const [initialRole] = useState(() => searchParams.get('role') || undefined);
  const [initialOpen] = useState(() => searchParams.get('open') === 'true');

  const fetchInvitations = useCallback(async () => {
    setError('');
    try {
      const response = await api.get('/api/invitations/');
      setInvitations(response.data);
    } catch (err) {
      setError(err.response?.data?.message || 'Failed to fetch invitations.');
    }
  }, []);

  useEffect(() => {
    let active = true;

    (async () => {
      await fetchInvitations();
      if (active) setLoading(false);
    })();

    return () => {
      active = false;
    };
  }, [fetchInvitations]);

  if (loading) {
    return (
      <div className="container mx-auto px-4 py-16">
        <TableSkeleton />
      </div>
    );
  }

  return (
    <div className="container mx-auto px-4 py-16">
      {error && <p className="text-destructive mb-4 text-sm">{error}</p>}

      <InvitationsTable
        data={invitations}
        initialRole={initialRole}
        initialOpen={initialOpen}
        onChanged={fetchInvitations}
      />
    </div>
  );
}
