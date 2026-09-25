import { useMemo } from 'react';
import { Link } from 'react-router-dom';
import { PlusIcon } from 'lucide-react';

import { DataTable } from '@/components/data-table';
import { Button } from '@/components/ui/button';
import { createColumns } from './columns';
import { tutorColumns } from './tutor-columns';
import { ExpiredStudentsSection } from './expired-students-section';

export function StudentsTable({ students, role, onChanged }) {
  const isTutor = role === 'tutor';
  const isMentor = role === 'mentor';

  const tableColumns = useMemo(
    () => (isTutor ? tutorColumns : createColumns(isMentor ? 'mentor' : 'admin', onChanged)),
    [isTutor, isMentor, onChanged]
  );

  // Tutors are only served active/inactive students by the API, so there is no
  // expired bucket to split off for them.
  const activeStudents = isTutor ? students : students.filter((s) => s.status !== 'expired');
  const expiredStudents = isTutor ? [] : students.filter((s) => s.status === 'expired');

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
          // Admin only. Enrolment runs through /invitations, which the router
          // does not allow mentors or tutors to open, so showing them the
          // button led nowhere.
          isTutor || isMentor ? undefined : (
            <Link to="/invitations?role=student&open=true">
              <Button>
                <PlusIcon />
                New Student
              </Button>
            </Link>
          )
        }
      />
      {!isTutor && <ExpiredStudentsSection columns={tableColumns} data={expiredStudents} />}
    </>
  );
}
