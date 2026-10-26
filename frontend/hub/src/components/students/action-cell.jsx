import { useState } from 'react';
import { Eye, MoreHorizontal } from 'lucide-react';
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
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { EXAM_VIEW, PERMISSIONS, SESSION_VIEW, can, canAny } from '@/lib/access';
import { EditStudentProfileSheet } from './edit-student-profile-sheet';
import { EditMeetLinkModal } from './edit-meet-link-modal';
import { ChangeStatusDialog } from './change-status-dialog';
import { ReassignStaffDialog } from './reassign-staff-dialog';
import { StudentHistorySheet } from './student-history-sheet';
import { PurgeStudentDialog } from './purge-student-dialog';

/**
 * Row actions for the admin/mentor students table: "View profile" next to the
 * menu, then the menu itself. Item order, separators and labels follow the
 * Hub's action cell; the admin-only block (reassign, history, purge) is gated
 * here and again by the API.
 *
 * The profile page reuses this component for its header actions, with
 * `showProfileLink={false}` -- every action a row offers is available there
 * too, so nobody has to go back to the list to act on a student.
 *
 * There is deliberately no "Top-up Class Quota" item: the quota is synced
 * from the enrolment sheet's "No of classes paid for" column, and
 * PUT /api/students/ now refuses `total_class_quota` outright.
 */
export function ActionCell({ student, user, onChanged, showProfileLink = true }) {
  const [profileOpen, setProfileOpen] = useState(false);
  const [meetLinkOpen, setMeetLinkOpen] = useState(false);
  const [statusOpen, setStatusOpen] = useState(false);
  const [reassignOpen, setReassignOpen] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [purgeOpen, setPurgeOpen] = useState(false);

  // Each item follows the permission the API checks for it.
  const canChange = can(user, PERMISSIONS.changeStudentDetails);
  const canReassign = can(user, PERMISSIONS.reassignStudentStaff);
  // The history sheet reads the student's whole activity log.
  const canSeeHistory = can(user, PERMISSIONS.viewAllActivity);
  const canPurge = can(user, PERMISSIONS.purgeStudent);

  return (
    <div className="flex items-center justify-end gap-0.5">
      {/* Hidden on the profile itself, where it would link to this page. */}
      {showProfileLink ? (
        <Tooltip>
          <TooltipTrigger asChild>
            <Button variant="ghost" size="icon" className="size-8" asChild>
              <Link to={`/students/${student.id}`}>
                <Eye className="size-4" />
                <span className="sr-only">View profile</span>
              </Link>
            </Button>
          </TooltipTrigger>
          <TooltipContent>View profile</TooltipContent>
        </Tooltip>
      ) : null}

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
          {canChange ? <DropdownMenuItem onSelect={() => setProfileOpen(true)}>Edit Profile</DropdownMenuItem> : null}
          {canAny(user, SESSION_VIEW) ? (
            <DropdownMenuItem asChild>
              <Link to={`/sessions?student_id=${student.id}`}>Manage Sessions</Link>
            </DropdownMenuItem>
          ) : null}
          {canAny(user, EXAM_VIEW) ? (
            <DropdownMenuItem asChild>
              <Link to={`/exams?student_id=${student.id}`}>Manage Exams</Link>
            </DropdownMenuItem>
          ) : null}
          {canChange ? (
            <>
              <DropdownMenuItem onSelect={() => setMeetLinkOpen(true)}>Edit Demo Link</DropdownMenuItem>
              <DropdownMenuItem onSelect={() => setStatusOpen(true)}>Change Status</DropdownMenuItem>
            </>
          ) : null}
          {canReassign || canSeeHistory ? (
            <>
              <DropdownMenuSeparator />
              {canReassign ? (
                <DropdownMenuItem onSelect={() => setReassignOpen(true)}>Reassign Mentor / Tutor</DropdownMenuItem>
              ) : null}
              {canSeeHistory ? <DropdownMenuItem onSelect={() => setHistoryOpen(true)}>View History</DropdownMenuItem> : null}
            </>
          ) : null}
          {canPurge ? (
            <>
              <DropdownMenuSeparator />
              <DropdownMenuItem variant="destructive" onSelect={() => setPurgeOpen(true)}>
                Delete permanently
              </DropdownMenuItem>
            </>
          ) : null}
        </DropdownMenuContent>
      </DropdownMenu>

      {canChange ? (
        <>
          <EditStudentProfileSheet student={student} open={profileOpen} onOpenChange={setProfileOpen} onSaved={onChanged} />
          <EditMeetLinkModal student={student} open={meetLinkOpen} onOpenChange={setMeetLinkOpen} onSaved={onChanged} />
          <ChangeStatusDialog student={student} open={statusOpen} onOpenChange={setStatusOpen} onSaved={onChanged} />
        </>
      ) : null}
      {canReassign ? (
        <ReassignStaffDialog student={student} open={reassignOpen} onOpenChange={setReassignOpen} onSaved={onChanged} />
      ) : null}
      {canSeeHistory ? (
        <StudentHistorySheet
          studentId={student.id}
          studentName={student.full_name}
          open={historyOpen}
          onOpenChange={setHistoryOpen}
        />
      ) : null}
      {canPurge ? (
        <PurgeStudentDialog student={student} open={purgeOpen} onOpenChange={setPurgeOpen} onSaved={onChanged} />
      ) : null}
    </div>
  );
}
