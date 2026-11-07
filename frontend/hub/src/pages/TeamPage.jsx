import { useCallback, useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { PlusIcon } from 'lucide-react';

import api from '@/lib/api';
import { Button } from '@/components/ui/button';
import { TableSkeleton } from '@/components/table-skeleton';
import { CreateMemberDialog } from '@/components/team/create-member-dialog';
import { TeamDirectory } from '@/components/team/team-directory';
import { Page, PageHeader } from '@/components/page/page';
import { AccessDeniedState, ErrorState, Notice } from '@/components/page/states';
import { TEAM_ROLES, TEAM_URL, canManageTeam, teamError } from '@/lib/team';

const PAGE_SIZE = 25;
const ROLE_VALUES = new Set(TEAM_ROLES.map((role) => role.value));
const STATUS_VALUES = new Set(['active', 'deactivated']);

/**
 * Team Management. Admins and superusers manage staff accounts; staff granted
 * accounts.view_team get the read-only directory. Every rule is the API's:
 * the page hides what it would refuse and shows its answer when it does.
 * Changes to an existing account are made on its details page (/team/:id).
 */
export default function TeamPage({ user }) {
  const canManage = canManageTeam(user);
  const [searchParams] = useSearchParams();
  const [data, setData] = useState(null);
  const [failure, setFailure] = useState(null);
  const [pending, setPending] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const [notice, setNotice] = useState('');
  const [createOpen, setCreateOpen] = useState(false);

  const page = Math.max(1, parseInt(searchParams.get('page') || '1', 10) || 1);
  const q = (searchParams.get('q') ?? '').trim();
  const role = ROLE_VALUES.has(searchParams.get('role')) ? searchParams.get('role') : '';
  const status = STATUS_VALUES.has(searchParams.get('status')) ? searchParams.get('status') : '';

  useEffect(() => {
    let active = true;
    setPending(true);

    // Always paged: the API answers ?page= with {results, count, page, page_size}.
    const params = { page, page_size: PAGE_SIZE };
    if (q) params.q = q;
    if (role) params.role = role;
    if (status) params.status = status;

    api
      .get(TEAM_URL, { params })
      .then((response) => {
        if (!active) return;
        setData(response.data);
        setFailure(null);
      })
      .catch((err) => {
        if (active) setFailure(teamError(err, 'Could not load the team.'));
      })
      .finally(() => {
        if (active) setPending(false);
      });

    return () => {
      active = false;
    };
  }, [page, q, role, status, reloadKey]);

  const handleChanged = useCallback((message) => {
    if (message) setNotice(message);
    setReloadKey((key) => key + 1);
  }, []);

  const retry = () => setReloadKey((key) => key + 1);

  let content;
  if (failure?.status === 403) {
    content = <AccessDeniedState title="You don't have access to the team directory." message={failure.message} />;
  } else if (!data && !failure) {
    content = <TableSkeleton />;
  } else if (!data) {
    content = <ErrorState message={failure.message} onRetry={retry} pending={pending} />;
  } else {
    content = (
      <>
        {failure ? <ErrorState message={failure.message} onRetry={retry} pending={pending} /> : null}
        <TeamDirectory
          rows={data.results ?? []}
          total={data.count ?? 0}
          page={page}
          pageSize={PAGE_SIZE}
          filters={{ q, role, status }}
          pending={pending}
          viewer={user}
          canManage={canManage}
        />
      </>
    );
  }

  return (
    <Page>
      <PageHeader
        title="Team"
        description={
          canManage
            ? 'Staff accounts: who can sign in to the Hub, their roles and any extra permissions.'
            : 'The Eduport Plus staff directory. You can view it but not change it.'
        }
        actions={
          canManage ? (
            <Button onClick={() => setCreateOpen(true)}>
              <PlusIcon />
              Add Staff Member
            </Button>
          ) : null
        }
      />

      {notice ? <Notice onDismiss={() => setNotice('')}>{notice}</Notice> : null}

      {content}

      {canManage ? (
        <CreateMemberDialog viewer={user} open={createOpen} onOpenChange={setCreateOpen} onCreated={handleChanged} />
      ) : null}
    </Page>
  );
}
