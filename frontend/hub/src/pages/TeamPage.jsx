import { useCallback, useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { CheckCircle2Icon, PlusIcon, ShieldAlertIcon, XIcon } from 'lucide-react';

import api from '@/lib/api';
import { Button } from '@/components/ui/button';
import { TableSkeleton } from '@/components/table-skeleton';
import { CreateMemberDialog } from '@/components/team/create-member-dialog';
import { TeamDirectory } from '@/components/team/team-directory';
import { TEAM_ROLES, TEAM_URL, canManageTeam, teamError } from '@/lib/team';

const PAGE_SIZE = 25;
const ROLE_VALUES = new Set(TEAM_ROLES.map((role) => role.value));
const STATUS_VALUES = new Set(['active', 'deactivated']);

function AccessDenied({ message }) {
  return (
    <div className="flex flex-col items-center gap-2 rounded-md border px-6 py-12 text-center">
      <ShieldAlertIcon className="text-muted-foreground size-8" />
      <p className="font-medium">You don&apos;t have access to the team directory.</p>
      {message ? <p className="text-muted-foreground max-w-md text-sm">{message}</p> : null}
    </div>
  );
}

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
    content = <AccessDenied message={failure.message} />;
  } else if (!data && !failure) {
    content = <TableSkeleton />;
  } else if (!data) {
    content = (
      <div className="flex flex-wrap items-center gap-3">
        <p className="text-destructive text-sm">{failure.message}</p>
        <Button variant="outline" size="sm" onClick={retry} disabled={pending}>
          Try again
        </Button>
      </div>
    );
  } else {
    content = (
      <>
        {failure ? (
          <div className="mb-4 flex flex-wrap items-center gap-3">
            <p className="text-destructive text-sm">{failure.message}</p>
            <Button variant="outline" size="sm" onClick={retry} disabled={pending}>
              Try again
            </Button>
          </div>
        ) : null}
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
    <div className="container mx-auto px-4 py-16">
      <div className="mb-6 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">Team</h1>
          <p className="text-muted-foreground text-sm">
            {canManage
              ? 'Staff accounts: who can sign in to the Hub, their roles and any extra permissions.'
              : 'The Eduport Plus staff directory. You can view it but not change it.'}
          </p>
        </div>
        {canManage ? (
          <Button onClick={() => setCreateOpen(true)}>
            <PlusIcon />
            Add staff member
          </Button>
        ) : null}
      </div>

      {notice ? (
        <div
          role="status"
          className="bg-success/10 text-success mb-4 flex items-start gap-2 rounded-md px-3 py-2 text-sm"
        >
          <CheckCircle2Icon className="mt-0.5 size-4 shrink-0" />
          <p className="flex-1">{notice}</p>
          <button type="button" onClick={() => setNotice('')} className="shrink-0" aria-label="Dismiss">
            <XIcon className="size-4" />
          </button>
        </div>
      ) : null}

      {content}

      {canManage ? (
        <CreateMemberDialog viewer={user} open={createOpen} onOpenChange={setCreateOpen} onCreated={handleChanged} />
      ) : null}
    </div>
  );
}
