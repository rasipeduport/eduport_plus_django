import { useState, useEffect } from 'react';
import { Loader2, ArrowRight, ShieldAlert } from 'lucide-react';
import api from '../lib/api';

const LEARN_URL = import.meta.env.VITE_LEARN_URL || 'http://localhost:3001';

// Global flag to track Google Sign-In initialization
let hubGsiInitialized = false;

// Login Page - Premium Dark Theme Center Card
export default function LoginPage() {
  const [error, setError] = useState('');
  const [accessRestricted, setAccessRestricted] = useState(false);
  const [mockEmail, setMockEmail] = useState('');
  const [mockName, setMockName] = useState('');
  const [mockRole, setMockRole] = useState('ADMIN');
  const [loading, setLoading] = useState(false);
  const [gsiLoaded, setGsiLoaded] = useState(false);
  const [showMock, setShowMock] = useState(false);

  // Initialize Native Google One Tap / Sign In if available
  useEffect(() => {
    if (gsiLoaded && !accessRestricted) {
      const clientId = import.meta.env.VITE_GOOGLE_OAUTH_CLIENT_ID || 'your-google-client-id.apps.googleusercontent.com';

      console.log("Origin:", window.location.origin);
      console.log("Client ID:", clientId);

      if (!hubGsiInitialized) {
        window.google.accounts.id.initialize({
          client_id: clientId,
          callback: handleGoogleCredentialResponse,
        });
        hubGsiInitialized = true;
      }

      const btnEl = document.getElementById('google-signin-btn');
      if (btnEl) {
        window.google.accounts.id.renderButton(
          btnEl,
          {
            theme: 'filled_black',
            size: 'large',
            width: '320',
            shape: 'pill',
            text: 'continue_with',
            logo_alignment: 'left'
          }
        );
      }
      window.google.accounts.id.prompt(); // Trigger Google One Tap
    }
  }, [gsiLoaded, accessRestricted]);

  useEffect(() => {
    if (window.google) {
      setGsiLoaded(true);
      return;
    }
    const interval = setInterval(() => {
      if (window.google) {
        setGsiLoaded(true);
        clearInterval(interval);
      }
    }, 100);
    return () => clearInterval(interval);
  }, []);

  const handleGoogleCredentialResponse = async (response) => {
    setLoading(true);
    setError('');
    try {
      const res = await api.post('/api/auth/google/', { credential: response.credential });
      if (res.data.user.role === 'STUDENT') {
        window.location.href = LEARN_URL;
      } else {
        window.location.href = '/dashboard';
      }
    } catch (err) {
      if (err.response?.data?.error === 'ACCESS_RESTRICTED') {
        setAccessRestricted(true);
      } else {
        setError(err.response?.data?.message || 'Authentication failed. Please verify whitelist invitation.');
      }
    } finally {
      setLoading(false);
    }
  };

  const handleGoogleSignInFallback = () => {
    // Falls back to mock authentication if real credentials aren't initialized yet
    if (!window.google) {
      const email = prompt('Enter Google Whitelisted Email to simulate Google Sign-in:');
      if (email) {
        setMockEmail(email);
        setMockRole('ADMIN');
        // trigger login simulation
        const mockCredential = `mock:${email}:Test User:https://api.dicebear.com/7.x/adventurer/svg?seed=Test`;
        setLoading(true);
        api.post('/api/auth/google/', { credential: mockCredential })
          .then((res) => {
            if (res.data.user.role === 'STUDENT') {
              window.location.href = LEARN_URL;
            } else {
              window.location.href = '/dashboard';
            }
          })
          .catch((err) => {
            if (err.response?.data?.error === 'ACCESS_RESTRICTED') {
              setAccessRestricted(true);
            } else {
              setError(err.response?.data?.message || 'Authentication failed. Whitelist invitation required.');
            }
            setLoading(false);
          });
      }
    }
  };

  const handleMockLogin = async (e) => {
    e.preventDefault();
    if (!mockEmail.trim()) {
      setError('Please provide a mock email address.');
      return;
    }
    const name = mockName.trim() || mockEmail.split('@')[0];
    const mockCredential = `mock:${mockEmail}:${name}:https://api.dicebear.com/7.x/adventurer/svg?seed=${name}`;
    setLoading(true);
    setError('');

    try {
      const res = await api.post('/api/auth/google/', { credential: mockCredential });
      if (res.data.user.role === 'STUDENT') {
        window.location.href = LEARN_URL;
      } else {
        window.location.href = '/dashboard';
      }
    } catch (err) {
      if (err.response?.data?.error === 'ACCESS_RESTRICTED') {
        setAccessRestricted(true);
      } else {
        setError(err.response?.data?.message || 'Authentication failed. Whitelist invitation required.');
      }
    } finally {
      setLoading(false);
    }
  };

  if (accessRestricted) {
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

          <section className="flex w-full flex-col items-center rounded-[28px] border border-[rgba(255,255,255,0.1)] bg-[#121521]/95 p-6 text-center shadow-[0_24px_80px_rgba(0,0,0,0.42)] backdrop-blur-xl sm:p-9">
            <div className="mb-6 flex h-14 w-14 items-center justify-center rounded-2xl border border-[#ef4444]/20 bg-[#ef4444]/10 text-[#f87171]">
              <ShieldAlert className="h-7 w-7" />
            </div>
            <h1 className="text-2xl font-semibold tracking-[-0.03em] text-[#f8fafc]">Access restricted</h1>

            <div className="mt-4 space-y-2 text-sm leading-6 text-[#a9b1c4]">
              <p>Your email is not authorized to access Eduport Plus.</p>
              <p>Please contact your administrator for access.</p>
            </div>

            <button
              onClick={() => {
                setAccessRestricted(false);
                setError('');
              }}
              className="mt-8 h-12 w-full rounded-xl bg-[#f8fafc] text-sm font-semibold text-[#111827] transition-colors hover:bg-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#ffd65b] focus-visible:ring-offset-2 focus-visible:ring-offset-[#121521]"
            >
              Try another account
            </button>
          </section>
        </div>
      </main>
    );
  }

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
              <img
                src="/brand/icon.svg"
                alt="Eduport Plus"
                className="h-11 w-11 cursor-pointer"
                onDoubleClick={() => setShowMock(prev => !prev)}
                title="Double-click to toggle Developer Mock Access"
              />
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
              Sign in to continue to your Eduport Plus workspace.
            </p>
          </div>

          {error && (
            <div role="alert" className="mb-6 w-full whitespace-pre-line rounded-xl border border-[#ef4444]/20 bg-[#ef4444]/10 p-3.5 text-sm leading-5 text-[#fca5a5]">
              {error}
            </div>
          )}

          <div className="flex w-full flex-col items-center gap-4">
            <div
              id="google-signin-btn"
              className="flex min-h-11 w-full justify-center"
              style={{ display: gsiLoaded ? 'flex' : 'none' }}
            ></div>
            {!gsiLoaded && (
              /* Custom Styled Google OAuth Button (Pill Style) Fallback */
              <button
                onClick={handleGoogleSignInFallback}
                disabled={loading}
                className="flex h-12 w-full items-center justify-center gap-3 rounded-xl border border-[#e5e7eb] bg-[#f8fafc] px-4 text-sm font-semibold text-[#111827] shadow-[0_8px_20px_rgba(0,0,0,0.18)] transition-colors duration-150 hover:bg-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#ffd65b] focus-visible:ring-offset-2 focus-visible:ring-offset-[#121521] disabled:cursor-wait disabled:opacity-70"
              >
                {loading ? (
                  <Loader2 className="h-5 w-5 animate-spin text-[#475569]" />
                ) : (
                  <>
                    <svg className="h-5 w-5 shrink-0" viewBox="0 0 24 24" aria-hidden="true">
                      <path
                        fill="#EA4335"
                        d="M5.266 9.765A7.077 7.077 0 0 1 12 4.909c1.69 0 3.218.6 4.418 1.582l3.51-3.51C17.745 1.055 15.045 0 12 0 7.354 0 3.373 2.668 1.445 6.555L5.266 9.765z"
                      />
                      <path
                        fill="#4285F4"
                        d="M23.49 12.275c0-.818-.073-1.609-.209-2.373H12v4.5h6.49c-.282 1.482-1.12 2.74-2.38 3.59l3.7 2.87c2.164-1.99 3.68-4.927 3.68-8.587z"
                      />
                      <path
                        fill="#FBBC05"
                        d="M5.266 14.235L1.445 17.44A11.97 11.97 0 0 0 12 24c3.055 0 5.864-1.01 7.91-2.74l-3.7-2.87c-1.145.764-2.618 1.218-4.21 1.218-3.136 0-5.8-2.127-6.734-5.373z"
                      />
                      <path
                        fill="#34A853"
                        d="M1.445 6.555A11.996 11.996 0 0 0 0 12c0 1.99.49 3.864 1.445 5.445l3.821-3.205C4.945 13.127 4.909 12.573 4.909 12c0-.573.036-1.127.127-1.682L1.445 6.555z"
                      />
                    </svg>
                    Continue with Google
                  </>
                )}
              </button>
            )}
            {loading && (
              <div className="flex items-center gap-2 text-xs text-[#9ba5bd]" role="status">
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                Signing you in…
              </div>
            )}
          </div>

          {showMock && (
            <div className="mt-7 space-y-6">
              <div className="relative flex items-center justify-center">
                <div className="absolute inset-x-0 h-px bg-[rgba(255,255,255,0.1)]" />
                <span className="relative bg-[#121521] px-3 text-[10px] font-bold uppercase tracking-[0.18em] text-[#77819a]">
                  Developer mock access
                </span>
              </div>

              <form onSubmit={handleMockLogin} className="w-full space-y-4">
                <div>
                  <label className="mb-1.5 block text-[10px] font-bold uppercase tracking-[0.16em] text-[#a9b1c4]">Email</label>
                  <input
                    type="email"
                    value={mockEmail}
                    onChange={(e) => setMockEmail(e.target.value)}
                    placeholder="mentor@eduport.com"
                    className="!bg-[#0c0f1a] !text-[#f8fafc] w-full rounded-xl border border-[rgba(255,255,255,0.1)] px-4 py-3 text-sm placeholder:text-[#667089] transition-all focus:outline-none focus:ring-2 focus:ring-[#ffd65b]/70"
                    required
                  />
                </div>

                <div className="grid gap-4 sm:grid-cols-2">
                  <div>
                    <label className="mb-1.5 block text-[10px] font-bold uppercase tracking-[0.16em] text-[#a9b1c4]">Full name</label>
                    <input
                      type="text"
                      value={mockName}
                      onChange={(e) => setMockName(e.target.value)}
                      placeholder="Jane Mentor"
                      className="!bg-[#0c0f1a] !text-[#f8fafc] w-full rounded-xl border border-[rgba(255,255,255,0.1)] px-4 py-3 text-sm placeholder:text-[#667089] transition-all focus:outline-none focus:ring-2 focus:ring-[#ffd65b]/70"
                    />
                  </div>
                  <div>
                    <label className="mb-1.5 block text-[10px] font-bold uppercase tracking-[0.16em] text-[#a9b1c4]">Testing role</label>
                    <select
                      value={mockRole}
                      onChange={(e) => setMockRole(e.target.value)}
                      className="!bg-[#0c0f1a] !text-[#f8fafc] w-full rounded-xl border border-[rgba(255,255,255,0.1)] px-3 py-3 text-sm transition-all focus:outline-none focus:ring-2 focus:ring-[#ffd65b]/70"
                    >
                      <option value="ADMIN">Admin</option>
                      <option value="MENTOR">Mentor</option>
                      <option value="TUTOR">Tutor</option>
                      <option value="STUDENT">Student</option>
                    </select>
                  </div>
                </div>

                <button
                  type="submit"
                  disabled={loading}
                  className="flex h-12 w-full items-center justify-center gap-2 rounded-xl bg-[#ffd65b] text-sm font-semibold text-[#0e101c] shadow-[0_8px_24px_rgba(255,214,91,0.16)] transition-colors hover:bg-[#ffe487] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#ffd65b] focus-visible:ring-offset-2 focus-visible:ring-offset-[#121521] disabled:cursor-wait disabled:opacity-60"
                >
                  {loading ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <>
                      Continue with mock profile
                      <ArrowRight className="h-4 w-4" />
                    </>
                  )}
                </button>
              </form>
            </div>
          )}
        </section>
      </div>
    </main>
  );
}
