import { useState, useEffect } from 'react';
import { Loader2, ShieldAlert } from 'lucide-react';
import api from '../lib/api';
import { Card } from '../components/ui/card';

// Configurable Hub URL for redirecting staff roles
const HUB_URL = import.meta.env.VITE_HUB_URL || 'http://localhost:3000';

// Global flag to track Google Sign-In initialization
let learnGsiInitialized = false;

export default function LoginPage() {
  const [error, setError] = useState('');
  const [accessRestricted, setAccessRestricted] = useState(false);
  const [loading, setLoading] = useState(false);
  const [gsiLoaded, setGsiLoaded] = useState(false);

  // Initialize Native Google One Tap / Sign In if available
  useEffect(() => {
    if (gsiLoaded && !accessRestricted) {
      const clientId = import.meta.env.VITE_GOOGLE_OAUTH_CLIENT_ID || 'your-google-client-id.apps.googleusercontent.com';

      if (!learnGsiInitialized) {
        window.google?.accounts.id.initialize({
          client_id: clientId,
          callback: handleGoogleCredentialResponse,
        });
        learnGsiInitialized = true;
      }

      const btnEl = document.getElementById('google-signin-btn');
      if (btnEl) {
        window.google?.accounts.id.renderButton(
          btnEl,
          {
            theme: 'filled_black',
            size: 'large',
            // GIS only takes a pixel width: fit the card instead of a fixed 320px.
            width: String(Math.min(320, Math.max(200, btnEl.clientWidth || 320))),
            shape: 'pill',
            text: 'continue_with',
            logo_alignment: 'left'
          }
        );
      }
      window.google?.accounts.id.prompt(); // Trigger Google One Tap
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
      if (res.data.user.role !== 'STUDENT') {
        window.location.href = HUB_URL;
      } else {
        window.location.href = '/dashboard';
      }
    } catch (err) {
      if (err.response?.data?.error === 'ACCESS_RESTRICTED') {
        setAccessRestricted(true);
      } else {
        setError(err.response?.data?.message || 'Authentication failed. Please verify student invitation.');
      }
    } finally {
      setLoading(false);
    }
  };

  // Shown only while the Google Identity script has not loaded. The mock
  // sign-in it used to offer was removed with the backend's mock credential.
  const handleGoogleSignInFallback = () => {
    setError('Google Sign-In has not finished loading. Check your connection and refresh the page.');
  };

  if (accessRestricted) {
    return (
      <main className="relative isolate flex min-h-dvh items-center justify-center overflow-hidden bg-[#080a12] px-4 py-8 font-sans text-[#f8fafc] sm:px-6">
        <div aria-hidden="true" className="pointer-events-none absolute inset-0 overflow-hidden">
          <div className="absolute left-1/2 top-[-18rem] h-[34rem] w-[34rem] -translate-x-1/2 rounded-full bg-[#ffd65b]/[0.06] blur-3xl" />
          <div className="absolute bottom-[-18rem] right-[-10rem] h-[30rem] w-[30rem] rounded-full bg-[#5661ff]/[0.08] blur-3xl" />
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
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-[#9ba5bd]">Learn workspace</p>
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
        <div className="absolute bottom-[-18rem] right-[-10rem] h-[30rem] w-[30rem] rounded-full bg-[#5661ff]/[0.08] blur-3xl" />
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
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-[#9ba5bd]">Learn workspace</p>
        </div>

        {error && (
          <div role="alert" className="mb-6 w-full whitespace-pre-line rounded-xl border border-[#ef4444]/20 bg-[#ef4444]/10 p-3.5 text-sm leading-5 text-[#fca5a5]">
            {error}
          </div>
        )}

        <Card
          variant="elevated"
          padding="none"
          className="!w-full !rounded-[28px] !border-[rgba(255,255,255,0.1)] !bg-[#121521]/95 !p-6 !shadow-[0_24px_80px_rgba(0,0,0,0.42)] backdrop-blur-xl sm:!p-9"
        >
          <div className="mb-7">
            <p className="mb-2 text-xs font-semibold uppercase tracking-[0.18em] text-[#ffd65b]">Student sign in</p>
            <h1 className="text-3xl font-semibold tracking-[-0.04em] text-[#f8fafc]">Welcome back</h1>
            <p className="mt-3 text-sm leading-6 text-[#a9b1c4]">
              Continue your learning journey with Eduport Plus.
            </p>
          </div>

          <div className="flex w-full flex-col items-center gap-4">
            <div
              id="google-signin-btn"
              className="flex min-h-11 w-full justify-center"
              style={{ display: gsiLoaded ? 'flex' : 'none' }}
            ></div>
            {!gsiLoaded && (
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
        </Card>
      </div>
    </main>
  );
}
