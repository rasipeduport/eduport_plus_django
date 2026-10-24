import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import AuthProvider from './context/AuthProvider';
import SidebarLayout from './layout/SidebarLayout';
import LoginPage from './pages/LoginPage';
import ChangePasswordPage from './pages/ChangePasswordPage';
import DashboardPage from './pages/DashboardPage';
import StudentsPage from './pages/StudentsPage';
import StudentProfilePage from './pages/StudentProfilePage';
import SessionsPage from './pages/SessionsPage';
import ExamsPage from './pages/ExamsPage';
import HomeworkPage from './pages/HomeworkPage';
import InvitationsPage from './pages/InvitationsPage';
import ActivityPage from './pages/ActivityPage';
import TeamPage from './pages/TeamPage';
import TeamMemberPage from './pages/TeamMemberPage';
import { canViewTeam } from './lib/team';

// Router Entry App
export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        {/* A temporary password must be replaced before anything else: this
            page stands alone (no sidebar), and every other Hub route sends an
            account with must_change_password here. The API enforces the same. */}
        <Route
          path="/change-password"
          element={<AuthProvider>{({ user, logout }) => <ChangePasswordPage user={user} logout={logout} />}</AuthProvider>}
        />
        <Route
          path="/*"
          element={
            <AuthProvider>
              {({ user, logout }) => user?.must_change_password ? (
                <Navigate to="/change-password" replace />
              ) : (
                <SidebarLayout user={user} logout={logout}>
                  <Routes>
                    <Route path="/dashboard" element={<DashboardPage user={user} />} />
                    <Route path="/students" element={<StudentsPage />} />
                    {/* One student's full record. Scoped by the API: a mentor
                        or tutor opening someone else's student gets a 404. */}
                    <Route path="/students/:studentId" element={<StudentProfilePage role={user?.role} />} />
                    <Route path="/sessions" element={<SessionsPage />} />
                    {/* Exams are a mentor <-> student affair; tutors have no access. */}
                    <Route path="/exams" element={user?.role !== 'TUTOR' ? <ExamsPage /> : <Navigate to="/dashboard" replace />} />
                    {/* Homework review for every staff role; the tutor grades. */}
                    <Route path="/homework" element={<HomeworkPage />} />
                    {/* The former per-role staff pages: Team now manages all
                        staff, so old links land on it with the role filtered. */}
                    <Route path="/admins" element={<Navigate to="/team?role=ADMIN" replace />} />
                    <Route path="/mentors" element={<Navigate to="/team?role=MENTOR" replace />} />
                    <Route path="/tutors" element={<Navigate to="/team?role=TUTOR" replace />} />
                    <Route path="/invitations" element={user?.role === 'ADMIN' ? <InvitationsPage /> : <Navigate to="/dashboard" replace />} />
                    {/* Team Management: admins and superusers manage staff
                        accounts; staff granted accounts.view_team get the
                        read-only directory. The API enforces both. */}
                    <Route path="/team" element={canViewTeam(user) ? <TeamPage user={user} /> : <Navigate to="/dashboard" replace />} />
                    <Route path="/team/:memberId" element={canViewTeam(user) ? <TeamMemberPage user={user} /> : <Navigate to="/dashboard" replace />} />
                    {/* Every staff role gets the activity log; the API pins
                        mentors and tutors to their own entries. */}
                    <Route path="/activity" element={<ActivityPage role={user?.role} />} />
                    <Route path="*" element={<Navigate to="/dashboard" replace />} />
                  </Routes>
                </SidebarLayout>
              )}
            </AuthProvider>
          }
        />
      </Routes>
    </BrowserRouter>
  );
}
