import { useCallback, useEffect, useState } from 'react';

import api from '@/lib/api';
import { TableSkeleton } from '@/components/table-skeleton';
import { InvitationsTable } from '@/components/invitations/invitations-table';
import { NewInvitation } from '@/components/invitations/new-invitation';
import { Page, PageHeader } from '@/components/page/page';
import { ErrorState } from '@/components/page/states';

/**
 * Invitations: the students invited to Eduport Plus and where each invitation
 * stands, with their initial Learn credentials for whoever may reveal them.
 * Invitations are created by enrollment only: "New Invitation" just says so.
 * Staff are no longer invited: their accounts are made in Team. The API
 * enforces every rule.
 */
export default function InvitationsPage({ user }) {
  const [invitations, setInvitations] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

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

  return (
    <Page>
      <PageHeader
        title="Invitations"
        description="Learn accounts are created at enrollment. Share initial credentials securely here; activation requires a password change."
        actions={<NewInvitation />}
      />

      {error ? <ErrorState message={error} onRetry={fetchInvitations} /> : null}

      {loading ? (
        <TableSkeleton toolbar={false} />
      ) : (
        <InvitationsTable data={invitations} user={user} onChanged={fetchInvitations} />
      )}
    </Page>
  );
}
