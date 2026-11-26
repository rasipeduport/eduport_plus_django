import { useCallback, useEffect, useRef, useState } from 'react';

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
 *
 * Until the list has loaded once, a failed read shows only its error (never an
 * empty table that reads as "no invitations"); after that, a failed read keeps
 * the table with the error above it. Try again turns while it reads.
 */
export default function InvitationsPage({ user }) {
  // null until the list has loaded once.
  const [invitations, setInvitations] = useState(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  // Only the latest read counts (a retry, or the re-read after an action); none after the page goes.
  const seq = useRef(0);

  const fetchInvitations = useCallback(async () => {
    const mine = ++seq.current;
    setPending(true);
    try {
      const response = await api.get('/api/invitations/');
      if (mine !== seq.current) return;
      setInvitations(response.data);
      setError('');
    } catch (err) {
      if (mine !== seq.current) return;
      setError(err.response?.data?.message || 'Failed to fetch invitations.');
    } finally {
      if (mine === seq.current) setPending(false);
    }
  }, []);

  useEffect(() => {
    fetchInvitations();
    return () => {
      seq.current += 1;
    };
  }, [fetchInvitations]);

  return (
    <Page>
      <PageHeader
        title="Invitations"
        description="Learn accounts are created at enrollment. Share initial credentials securely here; activation requires a password change."
        actions={<NewInvitation />}
      />

      {error ? <ErrorState message={error} onRetry={fetchInvitations} pending={pending} /> : null}

      {invitations ? (
        <InvitationsTable data={invitations} user={user} onChanged={fetchInvitations} />
      ) : error ? null : (
        <TableSkeleton toolbar={false} />
      )}
    </Page>
  );
}
