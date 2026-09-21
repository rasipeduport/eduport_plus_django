import { useState, useEffect } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { Loader2 } from 'lucide-react';
import api from '../lib/api';

// Configurable Hub URL for redirecting staff roles
const HUB_URL = import.meta.env.VITE_HUB_URL || 'http://localhost:3000';

/**
 * Authentication guard. Loads the current user + student profile + dashboard
 * stats, routes students to /waiting-room until their profile is linked, and
 * redirects staff roles to the Hub. Exposes its state via a render prop.
 */
export default function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [students, setStudents] = useState([]);
  const [studentProfile, setStudentProfile] = useState(null);
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();
  const location = useLocation();

  const fetchUserAndStats = async () => {
    try {
      // 1. Fetch current user + linked students from session /me/
      const meResponse = await api.get('/api/auth/me/');
      const userData = meResponse.data.user;
      setUser(userData);

      // If staff logs into Learn, redirect them to the Hub portal
      if (userData.role !== 'STUDENT') {
        window.location.href = HUB_URL;
        return;
      }

      const profiles = meResponse.data.student_profiles || [];
      const selected = meResponse.data.student_profile || null;
      // Only 'EXPIRED' blocks access (a terminal exit state); 'INACTIVE' is a
      // soft pause with full access. The rest of the app only ever sees the
      // usable personas — the backend refuses to act on expired ones anyway.
      const usable = profiles.filter((p) => p.status !== 'EXPIRED');
      setStudents(usable);
      setStudentProfile(selected);

      // No students linked yet -> waiting room
      if (profiles.length === 0) {
        setStats(null);
        if (location.pathname !== '/waiting-room') navigate('/waiting-room');
        return;
      }

      // Personas exist but every one is expired -> access ended
      if (usable.length === 0) {
        setStats(null);
        if (location.pathname !== '/access-ended') navigate('/access-ended');
        return;
      }

      // Several usable students but none chosen -> let the parent pick one
      if (!selected) {
        setStats(null);
        if (location.pathname !== '/select-profile') navigate('/select-profile');
        return;
      }

      // 2. A student is selected -> fetch their dashboard stats
      try {
        const statsResponse = await api.get('/api/student/dashboard/');
        setStats(statsResponse.data);

        // Redirect into the app if currently on a gateway route. Note:
        // /select-profile is intentionally excluded so a parent who already
        // has a child selected can still open it to switch students.
        if (['/waiting-room', '/access-ended', '/login'].includes(location.pathname)) {
          navigate('/dashboard');
        }
      } catch (err) {
        const code = err.response?.data?.error;
        if (code === 'STUDENT_PROFILE_NOT_FOUND') {
          if (location.pathname !== '/waiting-room') navigate('/waiting-room');
        } else if (code === 'STUDENT_NOT_SELECTED') {
          if (location.pathname !== '/select-profile') navigate('/select-profile');
        } else if (code === 'STUDENT_ACCESS_ENDED') {
          if (location.pathname !== '/access-ended') navigate('/access-ended');
        } else {
          console.error('Failed to load dashboard stats', err);
        }
      }
    } catch (error) {
      setUser(null);
      setStudents([]);
      setStudentProfile(null);
      setStats(null);
      if (location.pathname !== '/login') {
        navigate('/login');
      }
    } finally {
      setLoading(false);
    }
  };

  const reloadStats = async () => {
    try {
      const statsResponse = await api.get('/api/student/dashboard/');
      setStats(statsResponse.data);
    } catch (err) {
      console.error('Failed to reload dashboard stats', err);
    }
  };

  // Switch the active child: persist the choice server-side, then re-resolve.
  const switchStudent = async (studentId) => {
    await api.post('/api/auth/select-student/', { student_id: studentId });
    await fetchUserAndStats();
    navigate('/dashboard');
  };

  useEffect(() => {
    fetchUserAndStats();
  }, [location.pathname]);

  const logout = async () => {
    try {
      await api.post('/api/auth/logout/');
      setUser(null);
      setStudents([]);
      setStudentProfile(null);
      setStats(null);
      navigate('/login');
    } catch (error) {
      console.error('Logout failed:', error);
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-surface">
        <div className="text-center">
          <Loader2 className="h-8 w-8 animate-spin text-primary mx-auto mb-4" />
          <p className="text-text-secondary font-medium">Loading Eduport Plus...</p>
        </div>
      </div>
    );
  }

  return children({ user, students, studentProfile, stats, reloadStats, switchStudent, logout });
}
