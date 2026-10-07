import { useMemo } from 'react';
import { StudentContext } from '../components/student/student-context';
import { resolveStudentZone } from '../lib/formatting';

// Provides shared student state (profile, dashboard stats, auth actions) to the
// student-facing pages via StudentContext / useStudent().
export default function StudentProvider({ children, user, students, studentProfile, stats, reloadStats, switchStudent, logout }) {
  const value = useMemo(() => ({
    user,
    students: students || [],
    selectedStudent: studentProfile,
    // Resolved once here so every card formats in the same zone: the
    // student's own, or IST when none is set. Never the device's.
    timezone: resolveStudentZone(studentProfile),
    switchStudent,
    profileEmail: user?.email,
    dashboardStats: stats,
    reloadStats,
    logout
  }), [user, students, studentProfile, stats, reloadStats, switchStudent, logout]);

  return (
    <StudentContext.Provider value={value}>
      {children}
    </StudentContext.Provider>
  );
}
