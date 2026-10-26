import { useMemo } from 'react';
import { Link } from 'react-router-dom';
import { PlusIcon } from 'lucide-react';

import { DataTable } from '@/components/data-table';
import { Button } from '@/components/ui/button';
import { PERMISSIONS, can } from '@/lib/access';
import { createColumns } from './columns';
import { tutorColumns } from './tutor-columns';
import { ExpiredStudentsSection } from './expired-students-section';

export function StudentsTable({ students, user, onChanged }) {
  // Without the full record (tutors) the API serves the cut-down row, which
  // the narrow column set matches.
  const fullRecord = can(user, PERMISSIONS.viewFullStudentRecord);

  const tableColumns = useMemo(
    () => (fullRecord ? createColumns(user, onChanged) : tutorColumns),
    [fullRecord, user, onChanged]
  );

  // Tutors are only served active/inactive students by the API, so there is no
  // expired bucket to split off for them.
  const activeStudents = fullRecord ? students.filter((s) => s.status !== 'expired') : students;
  const expiredStudents = fullRecord ? students.filter((s) => s.status === 'expired') : [];

  return (
    <>
      <DataTable
        columns={tableColumns}
        data={activeStudents}
        filterColumn="full_name"
        filterPlaceholder="Filter by name..."
        emptyMessage="No students found."
        initialSorting={[{ id: 'student_code', desc: false }]}
        initialColumnPinning={{ right: ['actions'] }}
        actions={
          // Enrolment runs through /invitations, so the button is offered
          // only to whoever may invite students.
          can(user, PERMISSIONS.createInvitation) ? (
            <Link to="/invitations?role=student&open=true">
              <Button>
                <PlusIcon />
                New Student
              </Button>
            </Link>
          ) : undefined
        }
      />
      {fullRecord && <ExpiredStudentsSection columns={tableColumns} data={expiredStudents} />}
    </>
  );
}
