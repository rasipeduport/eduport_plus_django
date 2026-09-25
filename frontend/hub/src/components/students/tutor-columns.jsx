import { ArrowUpDownIcon } from 'lucide-react';

import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar';
import { Button } from '@/components/ui/button';
import { getInitials } from '@/lib/utils';
import { TutorActionCell } from './tutor-action-cell';

// Tutors only need enough to identify a student and join their class, so this
// set deliberately omits contact details, assignment history and quota.
export const tutorColumns = [
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
    id: 'mentor',
    header: 'Mentor',
    accessorFn: (row) => row.mentor_profile?.full_name || row.mentor_profile?.email || 'Not Assigned',
  },
  {
    accessorKey: 'meet_link',
    header: 'Meet Link',
    cell: ({ row }) => row.getValue('meet_link') || '—',
  },
  {
    id: 'actions',
    header: '',
    cell: ({ row }) => <TutorActionCell student={row.original} />,
    enableHiding: false,
  },
];
