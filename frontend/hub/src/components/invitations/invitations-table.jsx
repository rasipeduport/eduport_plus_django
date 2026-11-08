import { MailIcon, SearchXIcon, XIcon } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { EmptyState } from '@/components/page/page';
import { FilterSelect, SearchField } from '@/components/page/list-toolbar';
import { ResponsiveList } from '@/components/page/responsive-list';
import { useListParams } from '@/hooks/use-list-params';
import { InvitationActionCell } from './invitation-action-cell';

const dateTimeFormatter = new Intl.DateTimeFormat('en-US', {
  year: 'numeric',
  month: 'short',
  day: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
});

// Where an invitation stands (backend invitations.InvitationStatusChoices).
const STATUSES = [
  { value: 'PENDING', label: 'Pending', variant: 'warning' },
  { value: 'ACCEPTED', label: 'Accepted', variant: 'success' },
  { value: 'EXPIRED', label: 'Expired', variant: 'secondary' },
];

function StatusBadge({ status }) {
  const shown = STATUSES.find((option) => option.value === status);
  return shown ? <Badge variant={shown.variant}>{shown.label}</Badge> : <span className="text-muted-foreground">—</span>;
}

function Role({ role }) {
  return (
    <span className="flex items-center gap-2">
      <span className="capitalize">{role ? role.toLowerCase() : 'N/A'}</span>
      {/* Staff are no longer invited (accounts are made in Team); these
          rows are kept on record and can only be withdrawn. */}
      {role && role !== 'STUDENT' ? (
        <Badge variant="outline" title="Staff are no longer invited: create their account in Team.">
          Legacy
        </Badge>
      ) : null}
    </span>
  );
}

const invitedAt = (invitation) => (invitation.created_at ? dateTimeFormatter.format(new Date(invitation.created_at)) : 'N/A');
const invitedBy = (invitation) => {
  const inviter = invitation.invited_by_profile;
  return inviter ? inviter.full_name || inviter.email : null;
};

/**
 * The invitations, as the API lists them all: searched by email and filtered
 * by status (both kept in the URL, applied here), each with its role, where it
 * stands, when and by whom it was sent and, unless accepted, its actions
 * (InvitationActionCell: change the email, withdraw). An accepted invitation's
 * row survives with status ACCEPTED and the API refuses to edit or withdraw
 * it, so it offers none. `onChanged` reads the list again after a change.
 * A table where it fits, a card per invitation on a phone.
 */
export function InvitationsTable({ data, user, onChanged }) {
  const { searchParams, update, clear } = useListParams();
  const q = (searchParams.get('q') ?? '').trim();
  const status = STATUSES.some((option) => option.value === searchParams.get('status')) ? searchParams.get('status') : '';
  const filtered = Boolean(q || status);
  const rows = data.filter(
    (invitation) =>
      (!q || (invitation.email ?? '').toLowerCase().includes(q.toLowerCase())) && (!status || invitation.status === status)
  );
  const actions = (invitation) =>
    invitation.status === 'ACCEPTED' ? null : <InvitationActionCell invitation={invitation} user={user} onChanged={onChanged} />;

  const columns = [
    { key: 'email', header: 'Email', className: 'font-medium', cell: (invitation) => invitation.email },
    { key: 'role', header: 'Role', cell: (invitation) => <Role role={invitation.role} /> },
    { key: 'status', header: 'Status', cell: (invitation) => <StatusBadge status={invitation.status} /> },
    { key: 'invited', header: 'Invited At', className: 'whitespace-nowrap', cell: invitedAt },
    {
      key: 'by',
      header: 'Invited by',
      cell: (invitation) => invitedBy(invitation) ?? <span className="text-muted-foreground">—</span>,
    },
    { key: 'actions', header: { srOnly: 'Actions' }, headerClassName: 'w-px', cell: actions },
  ];

  const renderCard = (invitation) => (
    <article className="bg-card flex h-full flex-col gap-3 rounded-xl border p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="truncate font-medium">{invitation.email}</h2>
          <div className="text-muted-foreground mt-1 text-sm">
            <Role role={invitation.role} />
          </div>
        </div>
        <div className="flex items-center gap-1">
          <StatusBadge status={invitation.status} />
          {actions(invitation)}
        </div>
      </div>
      <p className="text-muted-foreground text-xs">
        {[`Invited ${invitedAt(invitation)}`, invitedBy(invitation) ? `by ${invitedBy(invitation)}` : null]
          .filter(Boolean)
          .join(' ')}
      </p>
    </article>
  );

  let body;
  if (rows.length) {
    body = <ResponsiveList label="Invitations" columns={columns} rows={rows} minTableWidth={760} renderCard={renderCard} />;
  } else if (filtered) {
    body = (
      <EmptyState
        icon={SearchXIcon}
        title="No invitations match these filters"
        description="Try another email or status, or clear the filters."
        action={
          <Button variant="outline" onClick={clear}>
            Clear all filters
          </Button>
        }
      />
    );
  } else {
    body = <EmptyState icon={MailIcon} title="No invitations yet" description="Students you invite to Eduport Plus appear here." />;
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <SearchField
          value={q}
          onSearch={(text) => update({ q: text || null })}
          label="Search invitations"
          placeholder="Search by email…"
        />
        <FilterSelect
          label="Filter by status"
          placeholder="All statuses"
          value={status}
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
      {data.length > 0 ? (
        <p className="text-muted-foreground text-sm" role="status">
          {filtered ? `${rows.length} of ${data.length} invitations` : `${data.length} invitations`}
        </p>
      ) : null}
    </div>
  );
}
