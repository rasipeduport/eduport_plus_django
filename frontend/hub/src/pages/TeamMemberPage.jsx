import { useCallback, useEffect, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { ArrowLeft, CheckCircle2Icon, Loader2, XIcon } from 'lucide-react';

import api from '@/lib/api';
import { Avatar, AvatarFallback } from '@/components/ui/avatar';
import { Button } from '@/components/ui/button';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { MemberActivityTab } from '@/components/team/member-activity-tab';
import { MemberBadges } from '@/components/team/member-badges';
import { MemberDetailsForm } from '@/components/team/member-details-form';
import { MemberStatusDialog } from '@/components/team/member-status-dialog';
import { getInitials } from '@/lib/utils';
import {
  TEAM_PERMISSIONS_URL,
  canManageTeam,
  changeRestriction,
  isActiveMember,
  memberUrl,
  roleLabel,
  teamError,
} from '@/lib/team';

const READ_ONLY_VIEWER = 'You can view this account but not change it.';

/**
 * /team/:memberId -- one staff account. Loaded from GET /api/team/<id>/ on
 * every visit, so a direct link or a refresh shows the account as it is now.
 *
 * Team managers edit details, role, password and permissions on the first
 * tab and read the account's history on the second; deactivation is its own
 * confirmed action in the header, apart from ordinary editing. Staff holding
 * accounts.view_team get the read-only directory fields. Every rule is the
 * API's: what it would refuse is not offered, and its refusals are shown.
 */
export default function TeamMemberPage({ user }) {
  const { memberId } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const canManage = canManageTeam(user);

  const [member, setMember] = useState(null);
  const [failure, setFailure] = useState(null);
  const [loading, setLoading] = useState(true);
  const [reloadKey, setReloadKey] = useState(0);
  const [activityKey, setActivityKey] = useState(0);
  const [catalogue, setCatalogue] = useState({ status: 'loading', items: [], error: '' });
  const [catalogueKey, setCatalogueKey] = useState(0);
  const [notice, setNotice] = useState('');
  const [statusOpen, setStatusOpen] = useState(false);

  const tab = canManage && searchParams.get('tab') === 'activity' ? 'activity' : 'details';
  const setTab = (next) => {
    const params = new URLSearchParams(searchParams);
    if (next === 'details') params.delete('tab');
    else params.set('tab', next);
    setSearchParams(params, { replace: true });
  };

  useEffect(() => {
    let active = true;
    setLoading(true);
    api
      .get(memberUrl(memberId))
      .then((response) => {
        if (!active) return;
        setMember(response.data);
        setFailure(null);
      })
      .catch((err) => {
        if (active) setFailure(teamError(err, 'Could not load this staff account.'));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [memberId, reloadKey]);

  // The approved permission catalogue: managers only, as in the API.
  useEffect(() => {
    if (!canManage) return undefined;
    let active = true;
    api
      .get(TEAM_PERMISSIONS_URL)
      .then((response) => {
        if (active) setCatalogue({ status: 'ready', items: response.data ?? [], error: '' });
      })
      .catch((err) => {
        if (active) {
          setCatalogue({
            status: 'error',
            items: [],
            error: teamError(err, 'Could not load the permission catalogue.').message,
          });
        }
      });
    return () => {
      active = false;
    };
  }, [canManage, catalogueKey]);

  const retryCatalogue = useCallback(() => {
    setCatalogue({ status: 'loading', items: [], error: '' });
    setCatalogueKey((key) => key + 1);
  }, []);

  // The details form hands back the member as the API returned it.
  const handleSaved = useCallback((message, fresh) => {
    if (fresh) setMember(fresh);
    if (message) setNotice(message);
    setActivityKey((key) => key + 1);
  }, []);

  const handleStatusChanged = useCallback((message) => {
    setNotice(message);
    setReloadKey((key) => key + 1);
    setActivityKey((key) => key + 1);
  }, []);

  const shown = member && member.id === memberId ? member : null;

  if (!shown && (loading || !failure)) {
    return (
      <div className="flex h-96 items-center justify-center">
        <Loader2 className="text-muted-foreground size-8 animate-spin" />
      </div>
    );
  }

  if (!shown) {
    let message = failure.message;
    if (failure.status === 404) message = 'This staff account does not exist.';
    return (
      <div className="container mx-auto px-4 py-16">
        <div className="rounded-xl border px-6 py-12 text-center">
          <p className="text-sm">{message}</p>
          <div className="mt-4 flex justify-center gap-2">
            {failure.status !== 404 && failure.status !== 403 ? (
              <Button variant="outline" onClick={() => setReloadKey((key) => key + 1)}>
                Try again
              </Button>
            ) : null}
            <Button variant="outline" asChild>
              <Link to="/team">Back to Team</Link>
            </Button>
          </div>
        </div>
      </div>
    );
  }

  const name = shown.full_name || shown.username;
  const restriction = canManage ? changeRestriction(user, shown) : READ_ONLY_VIEWER;

  return (
    <div className="container mx-auto flex flex-col gap-6 px-4 py-16">
      <div className="flex flex-col gap-4">
        <Button variant="ghost" size="sm" className="text-muted-foreground -ml-2 w-fit" asChild>
          <Link to="/team">
            <ArrowLeft className="size-4" />
            Team
          </Link>
        </Button>

        <div className="flex flex-wrap items-start gap-4">
          <Avatar className="size-12 rounded-full">
            <AvatarFallback className="size-12 rounded-full text-sm">{getInitials(name, shown.email)}</AvatarFallback>
          </Avatar>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="truncate text-xl font-semibold">{name}</h1>
              <MemberBadges member={shown} viewer={user} detailed={canManage} withRole={false} />
            </div>
            <p className="text-muted-foreground mt-1 text-sm">
              {shown.username} · {roleLabel(shown.role)} · {shown.email}
            </p>
          </div>
          {canManage && !restriction ? (
            isActiveMember(shown) ? (
              <Button
                variant="outline"
                className="border-destructive/40 text-destructive hover:bg-destructive/10 hover:text-destructive"
                onClick={() => setStatusOpen(true)}
              >
                Deactivate account
              </Button>
            ) : (
              <Button variant="outline" onClick={() => setStatusOpen(true)}>
                Reactivate account
              </Button>
            )
          ) : null}
        </div>
      </div>

      {notice ? (
        <div
          role="status"
          className="bg-success/10 text-success flex items-start gap-2 rounded-md px-3 py-2 text-sm"
        >
          <CheckCircle2Icon className="mt-0.5 size-4 shrink-0" />
          <p className="flex-1">{notice}</p>
          <button type="button" onClick={() => setNotice('')} className="shrink-0" aria-label="Dismiss">
            <XIcon className="size-4" />
          </button>
        </div>
      ) : null}
      {failure ? <p className="text-destructive text-sm">{failure.message}</p> : null}

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="details">Details &amp; Permissions</TabsTrigger>
          {canManage ? <TabsTrigger value="activity">Activity Log</TabsTrigger> : null}
        </TabsList>

        {/* Kept mounted so switching tabs never drops unsaved edits. */}
        <TabsContent value="details" forceMount className="data-[state=inactive]:hidden">
          <div className="rounded-xl border p-4 sm:p-6">
            <MemberDetailsForm
              key={shown.id}
              member={shown}
              viewer={user}
              catalogue={catalogue}
              restriction={restriction}
              onSaved={handleSaved}
              onRetryCatalogue={retryCatalogue}
            />
          </div>
        </TabsContent>

        {canManage ? (
          <TabsContent value="activity">
            <MemberActivityTab memberId={shown.id} memberName={name} refreshKey={activityKey} />
          </TabsContent>
        ) : null}
      </Tabs>

      {canManage && !restriction ? (
        <MemberStatusDialog
          member={shown}
          open={statusOpen}
          onOpenChange={setStatusOpen}
          onDone={handleStatusChanged}
        />
      ) : null}
    </div>
  );
}
