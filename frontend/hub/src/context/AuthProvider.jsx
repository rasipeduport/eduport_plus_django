import { useState, useEffect } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { Loader2 } from 'lucide-react';
import api from '../lib/api';

// Configurable Learn URL for redirecting the student role.
const LEARN_URL = import.meta.env.VITE_LEARN_URL || 'http://localhost:3001';

/**
 * Fetches the current user, handles role-based redirects (students -> Learn
 * portal, unauthenticated -> /login), and exposes { user, logout } via a render
 * prop so the rest of the app can stay declarative.
 */
export default function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();
  const location = useLocation();

  const fetchUser = async () => {
    try {
      const response = await api.get('/api/auth/me/');
      const userData = response.data.user;
      setUser(userData);

      // If student logs into Hub, redirect them to the Learn portal
      if (userData.role === 'STUDENT') {
        window.location.href = LEARN_URL;
        return;
      }

      // If logged in and on login page, redirect to dashboard
      if (location.pathname === '/login') {
        navigate('/dashboard');
      }
    } catch {
      setUser(null);
      if (location.pathname !== '/login') {
        navigate('/login');
      }
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchUser();
  }, [location.pathname]);

  const logout = async () => {
    try {
      await api.post('/api/auth/logout/');
      setUser(null);
      navigate('/login');
    } catch (error) {
      console.error('Logout failed:', error);
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-black">
        <div className="text-center">
          <Loader2 className="h-8 w-8 animate-spin text-indigo-500 mx-auto mb-4" />
          <p className="text-zinc-400 font-medium">Loading Eduport Plus...</p>
        </div>
      </div>
    );
  }

  return children({ user, logout });
}
