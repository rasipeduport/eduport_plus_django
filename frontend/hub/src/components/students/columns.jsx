import { useState } from 'react';
import { ArrowUpDownIcon, Maximize2 } from 'lucide-react';

import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import { formatDate, getInitials } from '@/lib/utils';
import { ActionCell } from './action-cell';

function RemarksCell({ remarks }) {
  const [open, setOpen] = useState(false);
  if (!remarks) return <span className="text-muted-foreground">—</span>;
  return (
    <div className="group flex min-w-0 items-center gap-1">
      <span className="max-w-[220px] truncate text-sm">{remarks}</span>
      <Button
        variant="ghost"
        size="icon"
        className="h-5 w-5 shrink-0 opacity-0 transition-opacity group-hover:opacity-100"
        onClick={() => setOpen(true)}
      >
        <Maximize2 className="h-3 w-3" />
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>Remarks for Mentor</DialogTitle>
          </DialogHeader>
          <p className="text-sm leading-relaxed whitespace-pre-wrap">{remarks}</p>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function StatusBadge({ status, note }) {
  const badge =
    status === 'active' ? (
      <Badge variant="success">Active</Badge>
    ) : status === 'inactive' ? (
      <Badge variant="warning">Inactive</Badge>
    ) : (
      <Badge variant="secondary">Expired</Badge>
    );

  if (status !== 'active' && note) {
    return (
      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger asChild>
            <span className="cursor-help">{badge}</span>
          </TooltipTrigger>
          <TooltipContent>
            <p className="max-w-xs">{note}</p>
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>
    );
  }

  return badge;
}

const admissionDateFormatter = new Intl.DateTimeFormat('en-GB', {
  day: '2-digit',
  month: 'short',
  year: 'numeric',
});

/**
 * Build the students table columns for admins and mentors.
 *
 * Mentors lose the columns that are not theirs to see (email, the mentor
 * assignment, state) and the admin-only row actions. Tutors get a narrower set
 * of their own — see tutor-columns.jsx.
 *
 * `onChanged` is called after any row action that mutates a student, so the
 * page can refetch.
 */
export function createColumns(role, onChanged) {
  const isAdmin = role === 'admin';

  return [
    {
      id: 'avatar',
      header: '',
      cell: ({ row }) => {
        const profile = row.original.profile;
        const avatarUrl = profile?.avatar_url ?? null;
        const name = row.original.full_name;
        const email = profile?.email ?? null;
        return (
          <Avatar className="size-8 rounded-full">
            <AvatarImage
              src={avatarUrl || undefined}
              alt={name || email || 'Student'}
              className="size-8 rounded-full object-cover"
            />
            <AvatarFallback className="size-8 rounded-full">{getInitials(name, email)}</AvatarFallback>
          </Avatar>
        );
      },
      enableHiding: false,
    },
    ...(isAdmin
      ? [
          {
            id: 'email',
            header: 'Email',
            accessorFn: (row) => row.profile?.email ?? '',
          },
        ]
      : []),
    {
      accessorKey: 'student_code',
      header: ({ column }) => (
        <Button
          variant="ghost"
          size="sm"
          className="-ml-3 h-8"
          onClick={() => column.toggleSorting(column.getIsSorted() === 'asc')}
        >
          Student ID
          <ArrowUpDownIcon className="ml-2 size-4" />
        </Button>
      ),
    },
    {
      accessorKey: 'full_name',
      header: 'Name',
    },
    {
      accessorKey: 'status',
      header: 'Status',
      cell: ({ row }) => <StatusBadge status={row.original.status ?? 'active'} note={row.original.status_note} />,
    },
    {
      accessorKey: 'mobile_number',
      header: 'Mobile',
      cell: ({ row }) => row.getValue('mobile_number') || '—',
    },
    {
      accessorKey: 'remarks_for_mentor',
      header: 'Remarks for Mentor',
      cell: ({ row }) => <RemarksCell remarks={row.getValue('remarks_for_mentor')} />,
    },
    ...(isAdmin
      ? [
          {
            id: 'mentor',
            header: 'Mentor',
            accessorFn: (row) => row.mentor_profile?.full_name || row.mentor_profile?.email || 'Not Assigned',
          },
        ]
      : []),
    {
      id: 'tutor',
      header: 'Tutor',
      accessorFn: (row) => row.tutor_profile?.full_name || row.tutor_profile?.email || 'Not Assigned',
    },
    {
      accessorKey: 'country',
      header: 'Country',
      cell: ({ row }) => row.getValue('country') || '—',
    },
    ...(isAdmin
      ? [
          {
            accessorKey: 'state',
            header: 'State',
            cell: ({ row }) => row.getValue('state') || '—',
          },
        ]
      : []),
    {
      accessorKey: 'school_name',
      header: 'School',
      cell: ({ row }) => row.getValue('school_name') || '—',
    },
    {
      accessorKey: 'grade',
      header: 'Grade',
      cell: ({ row }) => row.getValue('grade') || '—',
    },
    {
      accessorKey: 'syllabus',
      header: 'Syllabus',
      cell: ({ row }) => row.getValue('syllabus') || '—',
    },
    {
      accessorKey: 'admission_date',
      header: 'Admission Date',
      cell: ({ row }) => {
        const date = row.getValue('admission_date');
        if (!date) return '—';
        return admissionDateFormatter.format(new Date(date));
      },
    },
    {
      accessorKey: 'created_at',
      header: 'Joined At',
      cell: ({ row }) => <span>{formatDate(row.getValue('created_at'))}</span>,
    },
    {
      accessorKey: 'meet_link',
      header: 'Meet Link',
      cell: ({ row }) => row.getValue('meet_link') || '—',
    },
    {
      accessorKey: 'total_class_quota',
      header: 'Class Quota',
      cell: ({ row }) => row.getValue('total_class_quota') ?? 0,
    },
    {
      id: 'actions',
      header: '',
      cell: ({ row }) => <ActionCell student={row.original} role={role} onChanged={onChanged} />,
      enableHiding: false,
    },
  ];
}
