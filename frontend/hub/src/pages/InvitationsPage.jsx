import { useCallback, useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';

import api from '@/lib/api';
import { PERMISSIONS, can } from '@/lib/access';
import { TableSkeleton } from '@/components/table-skeleton';
import { InvitationsTable } from '@/components/invitations/invitations-table';
import { NewInvitation } from '@/components/invitations/new-invitation';
import { Page, PageHeader } from '@/components/page/page';
import { ErrorState } from '@/components/page/states';

/**
 * Invitations: the students invited to Eduport Plus, where each invitation
 * stands, and -- for holders of accounts.create_invitation -- a new one
 * (?open=true opens its form). Staff are no longer invited: their accounts
 * are made in Team, and the staff invitations still on record can only be
 * withdrawn. The API enforces every rule.
 */
export default function InvitationsPage({ user }) {
  const [searchParams] = useSearchParams();
  const [invitations, setInvitations] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  // Read once on mount: NewInvitation strips the params after consuming them,
  // so re-reading them on every render would close the form again. Only
  // students are invited, so a `role` param no longer preselects anything.
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

  return (
    <Page>
      <PageHeader
        title="Invitations"
        description="Students invited to Eduport Plus, and where each invitation stands. Staff accounts are made in Team."
        actions={
          can(user, PERMISSIONS.createInvitation) ? (
            <NewInvitation initialOpen={initialOpen} onSuccess={fetchInvitations} />
          ) : null
        }
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
