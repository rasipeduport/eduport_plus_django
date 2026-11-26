import { useState, useEffect, useRef } from 'react';
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
  // The student shown now, for reloadStats to compare an answer with when it
  // arrives (not with the one shown when it set off).
  const selectedRef = useRef(null);
  useEffect(() => {
    selectedRef.current = studentProfile;
  }, [studentProfile]);

  // Only the latest load counts: one an earlier, slower load would overwrite is kept.
  const loadSeq = useRef(0);

  /**
   * Who is signed in and where they belong, routing them there. Resolves to
   * what it found, for a page that asked (recheck): 'ready' (a student's
   * stats), 'waiting' (no profile linked yet), 'select' (several, none
   * chosen), 'ended' (access ended), 'unreachable' (the API did not answer, or
   * not usably), 'signed-out', 'redirected' (Hub, change password) or 'stale'
   * (a later load came first). With `keepSession`, a failure to reach the API
   * leaves the page as it is instead of signing out -- only a refused session
   * (401/403) goes to the sign-in page.
   */
  const fetchUserAndStats = async ({ keepSession = false } = {}) => {
    const seq = ++loadSeq.current;
    const latest = () => seq === loadSeq.current;
    try {
      // 1. Fetch current user + linked students from session /me/
      const meResponse = await api.get('/api/auth/me/');
      if (!latest()) return 'stale';
      const userData = meResponse.data.user;
      setUser(userData);

      // If staff logs into Learn, redirect them to the Hub portal
      if (userData.role !== 'STUDENT') {
        window.location.href = HUB_URL;
        return 'redirected';
      }

      if (meResponse.data.must_change_password) {
        navigate('/change-password', { replace: true });
        return 'redirected';
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
        return 'waiting';
      }

      // Personas exist but every one is expired -> access ended
      if (usable.length === 0) {
        setStats(null);
        if (location.pathname !== '/access-ended') navigate('/access-ended');
        return 'ended';
      }

      // Several usable students but none chosen -> let the parent pick one
      if (!selected) {
        setStats(null);
        if (location.pathname !== '/select-profile') navigate('/select-profile');
        return 'select';
      }

      // 2. A student is selected -> fetch their dashboard stats
      try {
        const statsResponse = await api.get('/api/student/dashboard/');
        if (!latest()) return 'stale';
        setStats(statsResponse.data);

        // Redirect into the app if currently on a gateway route. Note:
        // /select-profile is intentionally excluded so a parent who already
        // has a child selected can still open it to switch students.
        if (['/waiting-room', '/access-ended', '/login'].includes(location.pathname)) {
          navigate('/dashboard');
        }
        return 'ready';
      } catch (err) {
        if (!latest()) return 'stale';
        const code = err.response?.data?.error;
        if (code === 'STUDENT_PROFILE_NOT_FOUND') {
          if (location.pathname !== '/waiting-room') navigate('/waiting-room');
          return 'waiting';
        }
        if (code === 'STUDENT_NOT_SELECTED') {
          if (location.pathname !== '/select-profile') navigate('/select-profile');
          return 'select';
        }
        if (code === 'STUDENT_ACCESS_ENDED') {
          if (location.pathname !== '/access-ended') navigate('/access-ended');
          return 'ended';
        }
        console.error('Failed to load dashboard stats', err);
        return 'unreachable';
      }
    } catch (err) {
      if (!latest()) return 'stale';
      // Asked for on a page that is up (recheck): an API that did not answer is
      // said there. A refused session still signs out.
      const status = err?.response?.status;
      if (keepSession && status !== 401 && status !== 403) return 'unreachable';
      setUser(null);
      setStudents([]);
      setStudentProfile(null);
      setStats(null);
      if (location.pathname !== '/login') {
        navigate('/login');
      }
      return 'signed-out';
    } finally {
      setLoading(false);
    }
  };

  // A gateway page's "Check" (waiting room, access ended): the same resolve as
  // a route change, routing the student wherever they now belong, resolving to
  // what it found for the page to say.
  const recheck = () => fetchUserAndStats({ keepSession: true });

  const reloadStats = async () => {
    try {
      const statsResponse = await api.get('/api/student/dashboard/');
      // The selected student is a cookie every tab shares: after a switch in
      // another tab the dashboard answers for that student. Then re-resolve who
      // is selected and read their stats with them, so one student's stats never
      // show under another's name.
      const answeredFor = statsResponse.data?.student_id;
      const shown = selectedRef.current?.id;
      if (answeredFor && shown && String(answeredFor) !== String(shown)) {
        await fetchUserAndStats();
        return;
      }
      setStats(statsResponse.data);
    } catch (err) {
      console.error('Failed to reload dashboard stats', err);
    }
  };

  // Switch the active child: persist the choice server-side, then re-resolve
  // once -- the dashboard's route reads the new child on its own; already
  // there, it is read here.
  const switchStudent = async (studentId) => {
    await api.post('/api/auth/select-student/', { student_id: studentId });
    if (location.pathname === '/dashboard') await fetchUserAndStats();
    else navigate('/dashboard');
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

  if (!user || user.must_change_password) return null;

  return children({ user, students, studentProfile, stats, reloadStats, switchStudent, recheck, logout });
}
