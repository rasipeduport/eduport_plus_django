import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import AuthProvider from './context/AuthProvider';
import SidebarLayout from './layout/SidebarLayout';
import LoginPage from './pages/LoginPage';
import DashboardPage from './pages/DashboardPage';
import StudentsPage from './pages/StudentsPage';
import SessionsPage from './pages/SessionsPage';
import InvitationsPage from './pages/InvitationsPage';
import ActivityPage from './pages/ActivityPage';
import AdminsPage from './pages/staff/AdminsPage';
import MentorsPage from './pages/staff/MentorsPage';
import TutorsPage from './pages/staff/TutorsPage';

// Router Entry App
export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route
          path="/*"
          element={
            <AuthProvider>
              {({ user, logout }) => (
                <SidebarLayout user={user} logout={logout}>
                  <Routes>
                    <Route path="/dashboard" element={<DashboardPage />} />
                    <Route path="/students" element={<StudentsPage />} />
                    <Route path="/sessions" element={<SessionsPage />} />
                    <Route path="/admins" element={user?.role === 'ADMIN' ? <AdminsPage /> : <Navigate to="/dashboard" replace />} />
                    <Route path="/mentors" element={user?.role === 'ADMIN' ? <MentorsPage /> : <Navigate to="/dashboard" replace />} />
                    <Route path="/tutors" element={user?.role === 'ADMIN' ? <TutorsPage /> : <Navigate to="/dashboard" replace />} />
                    <Route path="/invitations" element={user?.role === 'ADMIN' ? <InvitationsPage /> : <Navigate to="/dashboard" replace />} />
                    {/* The activity log is an admin-only oversight tool. */}
                    <Route path="/activity" element={user?.role === 'ADMIN' ? <ActivityPage /> : <Navigate to="/dashboard" replace />} />
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
