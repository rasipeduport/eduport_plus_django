import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import AuthProvider from './context/AuthProvider';
import SidebarLayout from './layout/SidebarLayout';
import LoginPage from './pages/LoginPage';
import ChangePasswordPage from './pages/ChangePasswordPage';
import NoAccessPage from './pages/NoAccessPage';
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
import { canOpenPage, hubRole } from './lib/access';

/**
 * Everything behind sign-in. The role comes from AuthProvider's /me (fetched
 * on every navigation) and is handed to each page, so no page guesses it.
 */
function HubRoutes({ user, logout }) {
  // AuthProvider is already on its way to /login (no user) or to Learn (students).
  if (!user || user.role === 'STUDENT') return null;
  // A temporary password must be replaced before anything else. The API enforces the same.
  if (user.must_change_password) return <Navigate to="/change-password" replace />;
  // A role the Hub has no pages for gets nothing but a way to sign out.
  const role = hubRole(user);
  if (!role) return <NoAccessPage user={user} logout={logout} />;

  // Each page opens only for the roles lib/access lists for it; anyone else lands on the dashboard.
  const page = (path, element) => (canOpenPage(user, path) ? element : <Navigate to="/dashboard" replace />);

  return (
    <SidebarLayout user={user} logout={logout}>
      <Routes>
        {/* Every Hub role has the dashboard: it is where the other guards send people. */}
        <Route path="/dashboard" element={<DashboardPage user={user} role={role} />} />
        <Route path="/students" element={page('/students', <StudentsPage role={role} />)} />
        {/* One student's full record. Scoped by the API: a mentor or tutor
            opening someone else's student gets a 404. */}
        <Route path="/students/:studentId" element={page('/students', <StudentProfilePage role={role} />)} />
        <Route path="/sessions" element={page('/sessions', <SessionsPage role={role} />)} />
        {/* Exams are a mentor <-> student affair; tutors have no access. */}
        <Route path="/exams" element={page('/exams', <ExamsPage role={role} />)} />
        {/* Homework review for every staff role; the tutor grades. */}
        <Route path="/homework" element={page('/homework', <HomeworkPage role={role} />)} />
        {/* The former per-role staff pages: Team now manages all
            staff, so old links land on it with the role filtered. */}
        <Route path="/admins" element={<Navigate to="/team?role=ADMIN" replace />} />
        <Route path="/mentors" element={<Navigate to="/team?role=MENTOR" replace />} />
        <Route path="/tutors" element={<Navigate to="/team?role=TUTOR" replace />} />
        <Route path="/invitations" element={page('/invitations', <InvitationsPage />)} />
        {/* Team Management: admins and superusers manage staff
            accounts; staff granted accounts.view_team get the
            read-only directory. The API enforces both. */}
        <Route path="/team" element={page('/team', <TeamPage user={user} />)} />
        <Route path="/team/:memberId" element={page('/team', <TeamMemberPage user={user} />)} />
        {/* Every staff role gets the activity log; the API pins
            mentors and tutors to their own entries. */}
        <Route path="/activity" element={page('/activity', <ActivityPage role={role} />)} />
        <Route path="*" element={<Navigate to="/dashboard" replace />} />
      </Routes>
    </SidebarLayout>
  );
}

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
        <Route path="/*" element={<AuthProvider>{({ user, logout }) => <HubRoutes user={user} logout={logout} />}</AuthProvider>} />
      </Routes>
    </BrowserRouter>
  );
}
