import { Link } from 'react-router-dom';
import { ChevronRightIcon, SearchXIcon, UsersRoundIcon, XIcon } from 'lucide-react';

import { Avatar, AvatarFallback } from '@/components/ui/avatar';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { EmptyState } from '@/components/page/page';
import { FilterSelect, SearchField } from '@/components/page/list-toolbar';
import { Pagination } from '@/components/page/pagination';
import { ResponsiveList } from '@/components/page/responsive-list';
import { useListParams } from '@/hooks/use-list-params';
import { getInitials } from '@/lib/utils';
import { TEAM_ROLES, roleLabel } from '@/lib/team';
import { MemberBadges } from './member-badges';

const STATUSES = [
  { value: 'active', label: 'Active' },
  { value: 'deactivated', label: 'Deactivated' },
];

const nameOf = (member) => member.full_name || member.username;

function Member({ member, viewer }) {
  return (
    <Link to={`/team/${member.id}`} className="flex w-fit min-w-0 items-center gap-2 font-medium hover:underline">
      <Avatar className="size-8 rounded-full">
        <AvatarFallback className="size-8 rounded-full">{getInitials(member.full_name, member.email)}</AvatarFallback>
      </Avatar>
      <span className="truncate">{nameOf(member)}</span>
      {member.id === viewer?.id ? <Badge variant="outline">You</Badge> : null}
    </Link>
  );
}

/**
 * The staff directory: search, role and status filters, and paging, all kept
 * in the URL and applied by the API. Students are never part of it; the API
 * returns staff accounts only. Each member opens their details page
 * (/team/:memberId), where every change is made. A table where it fits, a
 * card per member on a phone or a narrow screen.
 */
export function TeamDirectory({ rows, total, page, pageSize, filters, pending, viewer, canManage }) {
  const { update, clear } = useListParams();
  const filtered = Boolean(filters.q || filters.role || filters.status);
  const badges = (member) => (
    <MemberBadges member={member} viewer={viewer} detailed={canManage} withRole={false} withSelf={false} />
  );

  const columns = [
    { key: 'name', header: 'Name', cell: (member) => <Member member={member} viewer={viewer} /> },
    { key: 'username', header: 'Username', className: 'text-muted-foreground', cell: (member) => member.username },
    { key: 'email', header: 'Email', cell: (member) => member.email },
    { key: 'role', header: 'Role', cell: (member) => roleLabel(member.role) },
    { key: 'status', header: 'Status', cell: badges },
    {
      key: 'open',
      header: { srOnly: 'Open' },
      headerClassName: 'w-10',
      cell: (member) => (
        <Button variant="ghost" size="icon" className="size-8" asChild>
          <Link to={`/team/${member.id}`} aria-label={`Open ${nameOf(member)}`}>
            <ChevronRightIcon className="size-4" />
          </Link>
        </Button>
      ),
    },
  ];

  const renderCard = (member) => (
    <article className="bg-card relative flex h-full flex-col gap-3 rounded-xl border p-4">
      <div className="flex items-start justify-between gap-3">
        <Member member={member} viewer={viewer} />
        <Badge variant="secondary">{roleLabel(member.role)}</Badge>
      </div>
      <div className="grid gap-1 text-sm">
        <p className="truncate">{member.email}</p>
        <p className="text-muted-foreground truncate">{member.username}</p>
      </div>
      <div className="mt-auto border-t pt-3">{badges(member)}</div>
    </article>
  );

  let body;
  if (rows.length) {
    body = (
      <ResponsiveList label="Staff" columns={columns} rows={rows} pending={pending} minTableWidth={860} renderCard={renderCard} />
    );
  } else if (total > 0) {
    body = (
      <EmptyState
        icon={SearchXIcon}
        title="Nothing on this page"
        description="This page is past the last one."
        action={
          <Button variant="outline" onClick={() => update({ page: null })}>
            Go to the first page
          </Button>
        }
      />
    );
  } else if (filtered) {
    body = (
      <EmptyState
        icon={SearchXIcon}
        title="No staff match these filters"
        description="Try another search, role or status, or clear the filters."
        action={
          <Button variant="outline" onClick={clear}>
            Clear all filters
          </Button>
        }
      />
    );
  } else {
    body = <EmptyState icon={UsersRoundIcon} title="No staff accounts yet" />;
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <SearchField
          value={filters.q}
          onSearch={(text) => update({ q: text || null })}
          label="Search staff"
          placeholder="Search name, username or email…"
        />
        <FilterSelect
          label="Filter by role"
          placeholder="All roles"
          value={filters.role}
          onChange={(value) => update({ role: value || null })}
          options={TEAM_ROLES}
        />
        <FilterSelect
          label="Filter by status"
          placeholder="All statuses"
          value={filters.status}
          onChange={(value) => update({ status: value || null })}
          options={STATUSES}
        />
        {filtered ? (
          <Button variant="ghost" className="text-muted-foreground" onClick={clear}>
            <XIcon className="size-4" />
            Clear all filters
          </Button>
        ) : null}
      </div>
      {body}
      {total > 0 ? (
        <Pagination
          page={page}
          pageSize={pageSize}
          total={total}
          pending={pending}
          onPageChange={(next) => update({ page: String(next) })}
        />
      ) : null}
    </div>
  );
}
