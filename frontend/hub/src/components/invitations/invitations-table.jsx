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
  { value: 'LEGACY', label: 'Credentials not issued', variant: 'secondary' },
  { value: 'PENDING', label: 'Pending', variant: 'warning' },
  { value: 'ACCEPTED', label: 'Activated', variant: 'success' },
  { value: 'EXPIRED', label: 'Expired', variant: 'secondary' },
];

const accountStatus = (invitation) => invitation.legacy ? 'LEGACY' : invitation.status;

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
// When an administrator last gave the account a temporary password (regenerated
// while pending, or reset once activated); null when never.
const lastReset = (invitation) =>
  invitation.last_password_reset_at ? dateTimeFormatter.format(new Date(invitation.last_password_reset_at)) : null;
const Muted = ({ children }) => <span className="text-muted-foreground">{children}</span>;

// An activated account whose password an administrator reset stays Activated;
// until the student replaces the temporary password, the row says so.
function Status({ invitation }) {
  return (
    <div>
      <StatusBadge status={accountStatus(invitation)} />
      {invitation.status === 'ACCEPTED' && invitation.credentials_available ? (
        <p className="text-muted-foreground mt-1 text-xs">Must change password</p>
      ) : null}
    </div>
  );
}

/**
 * The invitations, as the API lists them all: searched by name, EDP ID or
 * username and filtered by status (both kept in the URL, applied here), each
 * with where its Learn account stands, when and by whom it was sent, when an
 * administrator last gave it a temporary password, and its actions
 * (InvitationActionCell: reveal, regenerate or copy a pending account's
 * credentials; reset an activated account's password). `onChanged` reads the
 * list again after a change. A table where it fits, a card per invitation on a phone.
 */
export function InvitationsTable({ data, user, onChanged }) {
  const { searchParams, update, clear } = useListParams();
  const q = (searchParams.get('q') ?? '').trim();
  const status = STATUSES.some((option) => option.value === searchParams.get('status')) ? searchParams.get('status') : '';
  const filtered = Boolean(q || status);
  const rows = data.filter(
    (invitation) =>
      (!q || [invitation.student_name, invitation.student_code, invitation.username, invitation.email].filter(Boolean).join(' ').toLowerCase().includes(q.toLowerCase())) && (!status || accountStatus(invitation) === status)
  );
  const actions = (invitation) =>
    <InvitationActionCell invitation={invitation} user={user} onChanged={onChanged} />;

  const columns = [
    { key: 'student', header: 'Student', className: 'font-medium', cell: (invitation) => invitation.student_name || invitation.email },
    { key: 'code', header: 'EDP ID', cell: (invitation) => invitation.student_code || <Muted>Legacy invitation</Muted> },
    { key: 'username', header: 'Username', cell: (invitation) => invitation.username || 'Not issued' },
    { key: 'status', header: 'Status', cell: (invitation) => <Status invitation={invitation} /> },
    {
      key: 'invited',
      header: 'Invited At',
      className: 'whitespace-nowrap',
      cell: (invitation) => (
        <div>
          {invitedAt(invitation)}
          {invitedBy(invitation) ? <p className="text-muted-foreground text-xs">by {invitedBy(invitation)}</p> : null}
        </div>
      ),
    },
    { key: 'reset', header: 'Last Credential Update', className: 'whitespace-nowrap', cell: (invitation) => lastReset(invitation) ?? <Muted>—</Muted> },
    { key: 'actions', header: 'Actions', cell: actions },
  ];

  const renderCard = (invitation) => (
    <article className="bg-card flex h-full flex-col gap-3 rounded-xl border p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="truncate font-medium">{invitation.student_name || invitation.email}</h2><p className="text-muted-foreground text-sm">{invitation.student_code} · {invitation.username || 'Not issued'}</p>
          <div className="text-muted-foreground mt-1 text-sm">
            <Role role={invitation.role} />
          </div>
        </div>
        <div className="flex items-center gap-1 text-right">
          <Status invitation={invitation} />
        </div>
      </div>
      {actions(invitation)}
      <p className="text-muted-foreground text-xs">
        {[`Invited ${invitedAt(invitation)}`, invitedBy(invitation) ? `by ${invitedBy(invitation)}` : null]
          .filter(Boolean)
          .join(' ')}
        {lastReset(invitation) ? ` · Credentials updated ${lastReset(invitation)}` : null}
      </p>
    </article>
  );

  let body;
  if (rows.length) {
    body = <ResponsiveList label="Invitations" columns={columns} rows={rows} minTableWidth={920} renderCard={renderCard} />;
  } else if (filtered) {
    body = (
      <EmptyState
        icon={SearchXIcon}
        title="No invitations match these filters"
        description="Try another name, username or status, or clear the filters."
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
          placeholder="Search name, EDP ID or username…"
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
