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
import { EditStudentProfileSheet } from './edit-student-profile-sheet';
import { EditMeetLinkModal } from './edit-meet-link-modal';
import { TopupQuotaModal } from './topup-quota-modal';
import { ChangeStatusDialog } from './change-status-dialog';
import { ReassignStaffDialog } from './reassign-staff-dialog';
import { StudentHistorySheet } from './student-history-sheet';
import { PurgeStudentDialog } from './purge-student-dialog';

/**
 * Row actions for the admin/mentor students table. Item order, separators
 * and labels follow the Hub's action cell; the admin-only block (reassign,
 * history, purge) is gated here and again by the API.
 */
export function ActionCell({ student, role, onChanged }) {
  const [profileOpen, setProfileOpen] = useState(false);
  const [meetLinkOpen, setMeetLinkOpen] = useState(false);
  const [topupOpen, setTopupOpen] = useState(false);
  const [statusOpen, setStatusOpen] = useState(false);
  const [reassignOpen, setReassignOpen] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [purgeOpen, setPurgeOpen] = useState(false);

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
          <DropdownMenuItem onSelect={() => setProfileOpen(true)}>Edit Profile</DropdownMenuItem>
          <DropdownMenuItem asChild>
            <Link to={`/sessions?student_id=${student.id}`}>Manage Sessions</Link>
          </DropdownMenuItem>
          <DropdownMenuItem asChild>
            <Link to={`/exams?student_id=${student.id}`}>Manage Exams</Link>
          </DropdownMenuItem>
          <DropdownMenuItem onSelect={() => setMeetLinkOpen(true)}>Edit Demo Link</DropdownMenuItem>
          <DropdownMenuItem onSelect={() => setTopupOpen(true)}>Top-up Class Quota</DropdownMenuItem>
          <DropdownMenuItem onSelect={() => setStatusOpen(true)}>Change Status</DropdownMenuItem>
          {isAdmin ? (
            <>
              <DropdownMenuSeparator />
              <DropdownMenuItem onSelect={() => setReassignOpen(true)}>Reassign Mentor / Tutor</DropdownMenuItem>
              <DropdownMenuItem onSelect={() => setHistoryOpen(true)}>View History</DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem variant="destructive" onSelect={() => setPurgeOpen(true)}>
                Delete permanently
              </DropdownMenuItem>
            </>
          ) : null}
        </DropdownMenuContent>
      </DropdownMenu>

      <EditStudentProfileSheet student={student} open={profileOpen} onOpenChange={setProfileOpen} onSaved={onChanged} />
      <EditMeetLinkModal student={student} open={meetLinkOpen} onOpenChange={setMeetLinkOpen} onSaved={onChanged} />
      <TopupQuotaModal student={student} open={topupOpen} onOpenChange={setTopupOpen} onSaved={onChanged} />
      <ChangeStatusDialog student={student} open={statusOpen} onOpenChange={setStatusOpen} onSaved={onChanged} />
      {isAdmin ? (
        <>
          <ReassignStaffDialog student={student} open={reassignOpen} onOpenChange={setReassignOpen} onSaved={onChanged} />
          <StudentHistorySheet
            studentId={student.id}
            studentName={student.full_name}
            open={historyOpen}
            onOpenChange={setHistoryOpen}
          />
          <PurgeStudentDialog student={student} open={purgeOpen} onOpenChange={setPurgeOpen} onSaved={onChanged} />
        </>
      ) : null}
    </>
  );
}
