import { useCallback, useEffect, useState } from 'react';
import { PlusIcon } from 'lucide-react';

import api from '@/lib/api';
import { Button } from '@/components/ui/button';
import { TableSkeleton } from '@/components/table-skeleton';
import { StaffTable } from '@/components/staff/staff-table';
import NewInvitationModal from '@/components/NewInvitationModal';

/**
 * Generic staff (Admin / Mentor / Tutor) management page.
 *
 * Behaviour is identical across the three roles; the per-role differences are
 * supplied via `config`:
 *   { variant, entityLabel, endpoint, responseKey, initialRole }
 *
 * Mentors and tutors own students, so their tables add the "Assigned students"
 * column and the deactivate/reactivate lifecycle: staff are soft-deactivated
 * (access revoked, account and history kept), never deleted, and one with
 * assigned students must hand them over to a replacement first. Admins are
 * peers — one admin never deactivates another, so the admins table has no
 * status actions at all.
 */
export default function StaffManagementPage({ config }) {
  const { variant, entityLabel, endpoint, responseKey, initialRole } = config;

  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [isAdmin, setIsAdmin] = useState(false);
  const [isInviteModalOpen, setIsInviteModalOpen] = useState(false);

  const fetchRows = useCallback(async () => {
    setError('');
    try {
      const response = await api.get(endpoint);
      setRows(response.data[responseKey] || []);
    } catch (err) {
      setError(err.response?.data?.message || `Failed to fetch ${entityLabel.toLowerCase()} accounts.`);
    }
  }, [endpoint, responseKey, entityLabel]);

  useEffect(() => {
    let active = true;

    (async () => {
      try {
        const response = await api.get('/api/auth/me/');
        if (active) setIsAdmin(response.data.user?.role === 'ADMIN');
      } catch {
        // Leave the table read-only; the API enforces the real permissions.
      }
      await fetchRows();
      if (active) setLoading(false);
    })();

    return () => {
      active = false;
    };
  }, [fetchRows]);

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

      <StaffTable
        data={rows}
        variant={variant}
        readOnly={!isAdmin}
        onChanged={fetchRows}
        actions={
          isAdmin ? (
            <Button onClick={() => setIsInviteModalOpen(true)}>
              <PlusIcon />
              New {entityLabel}
            </Button>
          ) : undefined
        }
      />

      <NewInvitationModal
        isOpen={isInviteModalOpen}
        onClose={() => setIsInviteModalOpen(false)}
        initialRole={initialRole}
        onSuccess={fetchRows}
      />
    </div>
  );
}
