import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import AuthProvider from './context/AuthProvider';
import StudentProvider from './context/StudentProvider';
import { AppShell } from './components/student/app-shell';
import LoginPage from './pages/LoginPage';
import WaitingRoomPage from './pages/WaitingRoomPage';
import AccessEndedPage from './pages/AccessEndedPage';
import SelectProfilePage from './pages/SelectProfilePage';
import DashboardPage from './pages/DashboardPage';
import SessionsPage from './pages/SessionsPage';
import LibraryPage from './pages/LibraryPage';
import ProfilePage from './pages/ProfilePage';

// App Router Entry
export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route
          path="/*"
          element={
            <AuthProvider>
              {({ user, students, studentProfile, stats, reloadStats, switchStudent, logout }) => (
                <StudentProvider
                  user={user}
                  students={students}
                  studentProfile={studentProfile}
                  stats={stats}
                  reloadStats={reloadStats}
                  switchStudent={switchStudent}
                  logout={logout}
                >
                  <Routes>
                    <Route path="/dashboard" element={<AppShell><DashboardPage /></AppShell>} />
                    <Route path="/sessions" element={<AppShell><SessionsPage /></AppShell>} />
                    <Route path="/library" element={<AppShell><LibraryPage /></AppShell>} />
                    <Route path="/profile" element={<AppShell><ProfilePage /></AppShell>} />
                    <Route path="/select-profile" element={<SelectProfilePage />} />
                    <Route path="/waiting-room" element={<WaitingRoomPage />} />
                    <Route path="/access-ended" element={<AccessEndedPage />} />
                    <Route path="*" element={<Navigate to="/dashboard" replace />} />
                  </Routes>
                </StudentProvider>
              )}
            </AuthProvider>
          }
        />
      </Routes>
    </BrowserRouter>
  );
}
