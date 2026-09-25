import { useState } from 'react';
import { MoreHorizontal } from 'lucide-react';
import { Link } from 'react-router-dom';

import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { EditMeetLinkModal } from './edit-meet-link-modal';
import { TopupQuotaModal } from './topup-quota-modal';
import { ChangeStatusDialog } from './change-status-dialog';
import { StudentHistorySheet } from './student-history-sheet';

export function ActionCell({ student, role, onChanged }) {
  const [meetLinkOpen, setMeetLinkOpen] = useState(false);
  const [topupOpen, setTopupOpen] = useState(false);
  const [statusOpen, setStatusOpen] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);

  const isAdmin = role === 'admin';

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="ghost" size="icon" className="size-8">
            <MoreHorizontal className="size-4" />
            <span className="sr-only">Open menu</span>
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuLabel>Actions</DropdownMenuLabel>
          <DropdownMenuSeparator />
          <DropdownMenuItem asChild>
            <Link to={`/sessions?student_id=${student.id}`}>Manage Sessions</Link>
          </DropdownMenuItem>
          <DropdownMenuItem onSelect={() => setMeetLinkOpen(true)}>Edit Meet Link</DropdownMenuItem>
          <DropdownMenuItem onSelect={() => setTopupOpen(true)}>Top-up Class Quota</DropdownMenuItem>
          <DropdownMenuItem onSelect={() => setStatusOpen(true)}>Change Status</DropdownMenuItem>
          {isAdmin ? (
            <>
              <DropdownMenuSeparator />
              <DropdownMenuItem onSelect={() => setHistoryOpen(true)}>View History</DropdownMenuItem>
            </>
          ) : null}
        </DropdownMenuContent>
      </DropdownMenu>

      <EditMeetLinkModal student={student} open={meetLinkOpen} onOpenChange={setMeetLinkOpen} onSaved={onChanged} />
      <TopupQuotaModal student={student} open={topupOpen} onOpenChange={setTopupOpen} onSaved={onChanged} />
      <ChangeStatusDialog student={student} open={statusOpen} onOpenChange={setStatusOpen} onSaved={onChanged} />
      {isAdmin ? (
        <StudentHistorySheet
          studentId={student.id}
          studentName={student.full_name}
          open={historyOpen}
          onOpenChange={setHistoryOpen}
        />
      ) : null}
    </>
  );
}
