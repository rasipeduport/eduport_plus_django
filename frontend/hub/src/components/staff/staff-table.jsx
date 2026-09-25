import { useMemo, useState } from 'react';
import { ArrowUpDownIcon, MailIcon } from 'lucide-react';

import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { DataTable } from '@/components/data-table';
import { formatDate, getInitials } from '@/lib/utils';
import { InvitationActionCell } from '@/components/invitations/invitation-action-cell';
import { StaffActionsCell } from './staff-actions-cell';

const ENTITY_LABEL = {
  admin: 'admin',
  mentor: 'mentor',
  tutor: 'tutor',
};

function renderInvitedBy(row) {
  const inviter = row.invited_by_profile;
  if (!inviter) {
    return <span className="text-muted-foreground">—</span>;
  }
  return <span>{inviter.full_name || inviter.email}</span>;
}

function buildColumns(variant, readOnly, onChanged) {
  const cols = [
    {
      id: 'avatar',
      header: '',
      enableHiding: false,
      cell: ({ row }) => {
        const r = row.original;
        if (r.kind === 'ghost') {
          return (
            <div className="bg-muted text-muted-foreground flex size-8 items-center justify-center rounded-full">
              <MailIcon className="size-4" />
            </div>
          );
        }
        return (
          <Avatar className="size-8 rounded-full">
            <AvatarImage
              src={r.avatar_url || undefined}
              alt={r.full_name || r.email}
              className="size-8 rounded-full object-cover"
            />
            <AvatarFallback className="size-8 rounded-full">{getInitials(r.full_name, r.email)}</AvatarFallback>
          </Avatar>
        );
      },
    },
    {
      id: 'full_name',
      header: 'Name',
      accessorFn: (r) => (r.kind === 'ghost' ? '' : (r.full_name ?? '')),
      cell: ({ row }) => {
        const r = row.original;
        if (r.kind === 'ghost') {
          return <span className="text-muted-foreground italic">Invited</span>;
        }
        return r.full_name || <span className="text-muted-foreground">—</span>;
      },
    },
    {
      id: 'email',
      header: ({ column }) => (
        <Button
          variant="ghost"
          size="sm"
          className="-ml-3 h-8"
          onClick={() => column.toggleSorting(column.getIsSorted() === 'asc')}
        >
          Email
          <ArrowUpDownIcon className="ml-2 size-4" />
        </Button>
      ),
      accessorFn: (r) => r.email,
    },
    {
      id: 'mobile_number',
      header: 'Phone',
      cell: ({ row }) => {
        const r = row.original;
        if (r.kind === 'ghost' || !r.mobile_number) {
          return <span className="text-muted-foreground">—</span>;
        }
        return r.mobile_number;
      },
    },
    {
      id: 'created_at',
      header: 'Joined at',
      accessorFn: (r) => r.created_at,
      cell: ({ row }) => {
        const r = row.original;
        if (r.kind === 'ghost') {
          return <span className="text-muted-foreground">—</span>;
        }
        return formatDate(r.created_at);
      },
    },
    {
      id: 'invited_by',
      header: 'Invited by',
      cell: ({ row }) => renderInvitedBy(row.original),
    },
    {
      id: 'status',
      header: 'Status',
      cell: ({ row }) => {
        const r = row.original;
        if (r.kind === 'ghost') {
          return <span className="text-muted-foreground">—</span>;
        }
        return r.deactivated_at ? (
          <Badge variant="secondary" className="text-muted-foreground">
            Deactivated
          </Badge>
        ) : (
          <Badge variant="success">Active</Badge>
        );
      },
    },
  ];

  if (variant === 'mentor' || variant === 'tutor') {
    cols.push({
      id: 'students_count',
      header: 'Assigned students',
      accessorFn: (r) => (r.kind === 'ghost' ? null : (r.assigned_students_count ?? 0)),
      cell: ({ row }) => {
        const r = row.original;
        if (r.kind === 'ghost') {
          return <span className="text-muted-foreground">—</span>;
        }
        return <span className="tabular-nums">{r.assigned_students_count ?? 0}</span>;
      },
    });
  }

  if (!readOnly) {
    cols.push({
      id: 'actions',
      header: '',
      enableHiding: false,
      cell: ({ row }) => {
        const r = row.original;
        if (r.kind === 'ghost') {
          return (
            <InvitationActionCell
              invitation={{
                id: r.id,
                email: r.email,
                role: r.role,
                extra_data: r.extra_data,
                created_at: r.created_at,
              }}
              onChanged={onChanged}
            />
          );
        }
        return <StaffActionsCell row={r} variant={variant} onChanged={onChanged} />;
      },
    });
  }

  return cols;
}

export function StaffTable({ data, variant, actions, readOnly = false, onChanged }) {
  const columns = useMemo(() => buildColumns(variant, readOnly, onChanged), [variant, readOnly, onChanged]);
  const label = ENTITY_LABEL[variant];

  const [showDeactivated, setShowDeactivated] = useState(false);

  const deactivatedCount = useMemo(
    () => data.filter((r) => r.kind !== 'ghost' && r.deactivated_at).length,
    [data]
  );

  // Default-hide deactivated staff; admins can reveal them to reactivate.
  const visibleData = useMemo(
    () => (showDeactivated ? data : data.filter((r) => r.kind === 'ghost' || !r.deactivated_at)),
    [data, showDeactivated]
  );

  const combinedActions =
    deactivatedCount > 0 && !readOnly ? (
      <div className="flex items-center gap-2">
        <Button variant="outline" size="sm" onClick={() => setShowDeactivated((v) => !v)}>
          {showDeactivated ? 'Hide deactivated' : `Show deactivated (${deactivatedCount})`}
        </Button>
        {actions}
      </div>
    ) : (
      actions
    );

  return (
    <DataTable
      columns={columns}
      data={visibleData}
      filterColumn="email"
      filterPlaceholder="Filter by email..."
      emptyMessage={`No ${label}s found.`}
      initialColumnPinning={readOnly ? {} : { right: ['actions'] }}
      actions={combinedActions}
    />
  );
}
