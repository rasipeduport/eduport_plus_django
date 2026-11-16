import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Eye, EyeOff, Loader2 } from 'lucide-react';
import api from '../lib/api';
import { passwordLoginError } from '../lib/auth-errors';

const INPUT_CLASS =
  '!bg-[#0c0f1a] !text-[#f8fafc] w-full rounded-xl border border-[rgba(255,255,255,0.1)] px-4 py-3 text-sm placeholder:text-[#667089] transition-all focus:outline-none focus:ring-2 focus:ring-[#ffd65b]/70';
const LABEL_CLASS = 'mb-1.5 block text-[10px] font-bold uppercase tracking-[0.16em] text-[#a9b1c4]';

// Login Page - Premium Dark Theme Center Card. Staff sign in with their
// username and password only; Google sign-in is for students, on Learn, and
// the API refuses it for staff accounts.
export default function LoginPage() {
  const navigate = useNavigate();
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);

  // Staff username + password sign-in (POST /api/auth/login/). The API client
  // fetches the CSRF token first and keeps the one the login answer returns;
  // the session itself is the cookie. Nothing here is stored in the browser.
  const handlePasswordLogin = async (event) => {
    event.preventDefault();
    if (!username.trim() || !password) {
      setError('Enter your username and password.');
      return;
    }
    setLoading(true);
    setError('');
    // Hidden again once sent, so a refused password is never left on show.
    setShowPassword(false);
    try {
      const res = await api.post('/api/auth/login/', { username: username.trim(), password });
      setPassword('');
      navigate(res.data.must_change_password ? '/change-password' : '/dashboard', { replace: true });
    } catch (err) {
      setPassword('');
      setError(passwordLoginError(err));
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="relative isolate flex min-h-dvh items-center justify-center overflow-hidden bg-[#080a12] px-4 py-8 font-sans text-[#f8fafc] sm:px-6">
      <div aria-hidden="true" className="pointer-events-none absolute inset-0 overflow-hidden">
        <div className="absolute left-1/2 top-[-18rem] h-[34rem] w-[34rem] -translate-x-1/2 rounded-full bg-[#ffd65b]/[0.06] blur-3xl" />
        <div className="absolute bottom-[-18rem] left-[-10rem] h-[30rem] w-[30rem] rounded-full bg-[#5661ff]/[0.08] blur-3xl" />
        <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-[#ffd65b]/70 to-transparent" />
      </div>

      <div className="relative z-10 w-full max-w-[448px]">
        <div className="mb-7 flex flex-col items-center text-center">
          <div className="mb-4 flex items-center gap-3">
            <div className="rounded-[18px] bg-[#151a2b] p-1.5 shadow-[0_12px_30px_rgba(0,0,0,0.28)]">
              <img src="/brand/icon.svg" alt="Eduport Plus" className="h-11 w-11" />
            </div>
            <span className="text-[1.15rem] font-semibold tracking-[-0.03em] text-[#f8fafc]">
              Eduport <span className="text-[#ffd65b]">Plus</span>
            </span>
          </div>
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-[#9ba5bd]">Hub workspace</p>
        </div>

        <section className="w-full rounded-[28px] border border-[rgba(255,255,255,0.1)] bg-[#121521]/95 p-6 shadow-[0_24px_80px_rgba(0,0,0,0.42)] backdrop-blur-xl sm:p-9">
          <div className="mb-7">
            <p className="mb-2 text-xs font-semibold uppercase tracking-[0.18em] text-[#ffd65b]">Staff sign in</p>
            <h1 className="text-3xl font-semibold tracking-[-0.04em] text-[#f8fafc]">Welcome back</h1>
            <p className="mt-3 max-w-[30rem] text-sm leading-6 text-[#a9b1c4]">
              Sign in with your username and password.
            </p>
          </div>

          {error && (
            <div role="alert" className="mb-6 w-full whitespace-pre-line rounded-xl border border-[#ef4444]/20 bg-[#ef4444]/10 p-3.5 text-sm leading-5 text-[#fca5a5]">
              {error}
            </div>
          )}

          <form onSubmit={handlePasswordLogin} className="w-full space-y-4" noValidate>
            <div>
              <label htmlFor="hub-username" className={LABEL_CLASS}>
                Username
              </label>
              <input
                id="hub-username"
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoComplete="username"
                autoCapitalize="none"
                spellCheck={false}
                disabled={loading}
                className={INPUT_CLASS}
              />
            </div>
            <div>
              <label htmlFor="hub-password" className={LABEL_CLASS}>
                Password
              </label>
              <div className="relative">
                <input
                  id="hub-password"
                  type={showPassword ? 'text' : 'password'}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  autoComplete="current-password"
                  disabled={loading}
                  className={`${INPUT_CLASS} pr-12 [&::-ms-reveal]:hidden`}
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((shown) => !shown)}
                  disabled={loading}
                  aria-label={showPassword ? 'Hide password' : 'Show password'}
                  aria-pressed={showPassword}
                  aria-controls="hub-password"
                  className="absolute inset-y-0 right-0 flex w-12 items-center justify-center rounded-r-xl text-[#77819a] transition-colors hover:text-[#f8fafc] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#ffd65b] disabled:opacity-60"
                >
                  {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </div>
            </div>
            <button
              type="submit"
              disabled={loading}
              className="flex h-12 w-full items-center justify-center gap-2 rounded-xl bg-[#ffd65b] text-sm font-semibold text-[#0e101c] shadow-[0_8px_24px_rgba(255,214,91,0.16)] transition-colors hover:bg-[#ffe487] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#ffd65b] focus-visible:ring-offset-2 focus-visible:ring-offset-[#121521] disabled:cursor-wait disabled:opacity-60"
            >
              {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Sign in'}
            </button>
          </form>

          {loading && (
            <div className="mt-4 flex items-center justify-center gap-2 text-xs text-[#9ba5bd]" role="status">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              Signing you in…
            </div>
          )}
        </section>
      </div>
    </main>
  );
}
