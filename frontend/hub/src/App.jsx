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
import BookingLinksPage from './pages/BookingLinksPage';
import BookingSlotsPage from './pages/BookingSlotsPage';
import { canOpenPage, homePage } from './lib/access';

/**
 * Everything behind sign-in. The account comes from AuthProvider's /me
 * (fetched on every navigation), permissions included, and is handed to each
 * page, so no page guesses what the caller may do.
 */
function HubRoutes({ user, logout }) {
  // AuthProvider is already on its way to /login (no user) or to Learn (students).
  if (!user || user.role === 'STUDENT') return null;
  // A temporary password must be replaced before anything else. The API enforces the same.
  if (user.must_change_password) return <Navigate to="/change-password" replace />;
  // An account holding no permission that opens a Hub page gets nothing but a way to sign out.
  const home = homePage(user);
  if (!home) return <NoAccessPage user={user} logout={logout} />;

  // Each page opens only for the permissions lib/access lists for it; anyone
  // else lands on the first page they may open.
  const page = (path, element) => (canOpenPage(user, path) ? element : <Navigate to={home} replace />);

  return (
    <SidebarLayout user={user} logout={logout}>
      <Routes>
        <Route path="/dashboard" element={page('/dashboard', <DashboardPage user={user} />)} />
        <Route path="/students" element={page('/students', <StudentsPage user={user} />)} />
        {/* One student's full record. Scoped by the API: a mentor or tutor
            opening someone else's student gets a 404. */}
        <Route path="/students/:studentId" element={page('/students', <StudentProfilePage user={user} />)} />
        <Route path="/sessions" element={page('/sessions', <SessionsPage user={user} />)} />
        {/* Exams are a mentor <-> student affair; tutors hold no exam permission. */}
        <Route path="/exams" element={page('/exams', <ExamsPage user={user} />)} />
        {/* Homework review for every staff role; the tutor grades. */}
        <Route path="/homework" element={page('/homework', <HomeworkPage user={user} />)} />
        {/* The former per-role staff pages: Team now manages all
            staff, so old links land on it with the role filtered. */}
        <Route path="/admins" element={<Navigate to="/team?role=ADMIN" replace />} />
        <Route path="/mentors" element={<Navigate to="/team?role=MENTOR" replace />} />
        <Route path="/tutors" element={<Navigate to="/team?role=TUTOR" replace />} />
        <Route path="/invitations" element={page('/invitations', <InvitationsPage user={user} />)} />
        {/* Team Management: holders of accounts.manage_team manage staff
            accounts; staff granted accounts.view_team get the read-only
            directory. The API enforces both. */}
        <Route path="/team" element={page('/team', <TeamPage user={user} />)} />
        <Route path="/team/:memberId" element={page('/team', <TeamMemberPage user={user} />)} />
        {/* The API pins whoever holds only view_own_activity to their own entries. */}
        <Route path="/activity" element={page('/activity', <ActivityPage user={user} />)} />
        {/* Booking slots for administrators: close or reopen the Demo and
            Diagnostic slots parents book. The API enforces the same permission
            and keeps every booking. */}
        <Route path="/booking-slots" element={page('/booking-slots', <BookingSlotsPage />)} />
        {/* The BDE workspace: a BDE's own permanent booking links. The API
            serves each BDE only their own. */}
        <Route path="/booking-links" element={page('/booking-links', <BookingLinksPage />)} />
        <Route path="*" element={<Navigate to={home} replace />} />
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
