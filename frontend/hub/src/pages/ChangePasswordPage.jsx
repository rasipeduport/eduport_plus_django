import { useState } from 'react';
import { Navigate, useNavigate } from 'react-router-dom';
import { Eye, EyeOff, Loader2 } from 'lucide-react';

import api from '@/lib/api';
import { passwordChangeFailure } from '@/lib/auth-errors';
import { PASSWORD_RULE, passwordPolicyError } from '@/lib/password-policy';

const INPUT_CLASS =
  '!bg-[#0c0f1a] !text-[#f8fafc] w-full rounded-xl border border-[rgba(255,255,255,0.1)] px-4 py-3 text-sm placeholder:text-[#667089] transition-all focus:outline-none focus:ring-2 focus:ring-[#ffd65b]/70';
const LABEL_CLASS = 'mb-1.5 block text-[10px] font-bold uppercase tracking-[0.16em] text-[#a9b1c4]';

function FieldError({ failure, field }) {
  if (failure?.field !== field) return null;
  return (
    <div className="mt-1.5 text-sm text-[#fca5a5]">
      <p>{failure.message}</p>
      {failure.details?.length ? (
        <ul className="mt-1 list-disc pl-5">
          {failure.details.map((detail) => (
            <li key={detail}>{detail}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

// A password input with its own show/hide toggle, matching LoginPage's.
function PasswordInput({ id, invalid, describedBy, disabled, ...inputProps }) {
  const [shown, setShown] = useState(false);
  return (
    <div className="relative">
      <input
        id={id}
        type={shown ? 'text' : 'password'}
        disabled={disabled}
        aria-invalid={invalid ? true : undefined}
        aria-describedby={describedBy}
        className={`${INPUT_CLASS} pr-12 [&::-ms-reveal]:hidden`}
        {...inputProps}
      />
      <button
        type="button"
        onClick={() => setShown((value) => !value)}
        disabled={disabled}
        aria-label={shown ? 'Hide password' : 'Show password'}
        aria-pressed={shown}
        aria-controls={id}
        className="absolute inset-y-0 right-0 flex w-12 items-center justify-center rounded-r-xl text-[#77819a] transition-colors hover:text-[#f8fafc] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#ffd65b] disabled:opacity-60"
      >
        {shown ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
      </button>
    </div>
  );
}

/**
 * Forced password change. An account holding a temporary password (set by an
 * administrator) reaches only this page -- App.jsx sends every other Hub route
 * here, and the API refuses everything but this change -- until it sets its
 * own password through POST /api/auth/change-password/, which applies the
 * password policy and keeps this session signed in.
 */
export default function ChangePasswordPage({ user, logout }) {
  const navigate = useNavigate();
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [confirm, setConfirm] = useState('');
  const [failure, setFailure] = useState(null);
  const [pending, setPending] = useState(false);

  // AuthProvider is already on its way to /login.
  if (!user) return null;
  if (!user.must_change_password) return <Navigate to="/dashboard" replace />;

  async function handleSubmit(event) {
    event.preventDefault();
    setFailure(null);
    if (!current || !next || !confirm) {
      setFailure({ message: 'Fill in all three fields.' });
      return;
    }
    if (passwordPolicyError(next)) {
      setFailure({ field: 'next', message: passwordPolicyError(next) });
      return;
    }
    if (next !== confirm) {
      setFailure({ field: 'confirm', message: 'The new passwords do not match.' });
      return;
    }

    setPending(true);
    try {
      await api.post('/api/auth/change-password/', { current_password: current, new_password: next });
    } catch (err) {
      const described = passwordChangeFailure(err);
      if (described.field === 'current') setCurrent('');
      if (described.field === 'next') {
        setNext('');
        setConfirm('');
      }
      setFailure(described);
      setPending(false);
      return;
    }
    setCurrent('');
    setNext('');
    setConfirm('');

    // Re-read the signed-in user before leaving: the API cleared the flag and
    // kept this session. If the read itself fails, the dashboard's own /me
    // check takes over -- retrying the change would now be refused.
    try {
      const me = await api.get('/api/auth/me/');
      if (me.data.must_change_password) {
        setFailure({ message: 'Your password was changed, but the Hub still asks for a new one. Refresh the page.' });
        setPending(false);
        return;
      }
    } catch {
      // Fall through to the dashboard.
    }
    navigate('/dashboard', { replace: true });
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
            <p className="mb-2 text-xs font-semibold uppercase tracking-[0.18em] text-[#ffd65b]">
              Password change required
            </p>
            <h1 className="text-3xl font-semibold tracking-[-0.04em] text-[#f8fafc]">Choose a new password</h1>
            <p className="mt-3 text-sm leading-6 text-[#a9b1c4]">
              You signed in as <strong className="text-[#f8fafc]">{user.username}</strong> with a temporary password.
              Set your own to continue to the Hub.
            </p>
          </div>

          {failure && !failure.field ? (
            <div
              role="alert"
              className="mb-6 w-full rounded-xl border border-[#ef4444]/20 bg-[#ef4444]/10 p-3.5 text-sm leading-5 text-[#fca5a5]"
            >
              <p>{failure.message}</p>
              {failure.sessionEnded ? (
                <button
                  type="button"
                  onClick={() => navigate('/login', { replace: true })}
                  className="mt-2 font-semibold text-[#f8fafc] underline underline-offset-4"
                >
                  Sign in again
                </button>
              ) : null}
            </div>
          ) : null}

          <form onSubmit={handleSubmit} className="w-full space-y-4" noValidate>
            {/* Lets password managers file the new password under this account. */}
            <input type="text" name="username" autoComplete="username" value={user.username} readOnly hidden />
            <div>
              <label htmlFor="hub-current-password" className={LABEL_CLASS}>
                Current (temporary) password
              </label>
              <PasswordInput
                id="hub-current-password"
                value={current}
                onChange={(e) => setCurrent(e.target.value)}
                autoComplete="current-password"
                disabled={pending}
                invalid={failure?.field === 'current'}
              />
              <FieldError failure={failure} field="current" />
            </div>
            <div>
              <label htmlFor="hub-new-password" className={LABEL_CLASS}>
                New password
              </label>
              <PasswordInput
                id="hub-new-password"
                value={next}
                onChange={(e) => setNext(e.target.value)}
                autoComplete="new-password"
                disabled={pending}
                invalid={failure?.field === 'next'}
                describedBy="hub-new-password-hint"
              />
              <p id="hub-new-password-hint" className="mt-1.5 text-xs leading-5 text-[#77819a]">
                {PASSWORD_RULE}
              </p>
              <FieldError failure={failure} field="next" />
            </div>
            <div>
              <label htmlFor="hub-confirm-password" className={LABEL_CLASS}>
                Confirm new password
              </label>
              <PasswordInput
                id="hub-confirm-password"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                autoComplete="new-password"
                disabled={pending}
                invalid={failure?.field === 'confirm'}
              />
              <FieldError failure={failure} field="confirm" />
            </div>
            <button
              type="submit"
              disabled={pending}
              className="flex h-12 w-full items-center justify-center gap-2 rounded-xl bg-[#ffd65b] text-sm font-semibold text-[#0e101c] shadow-[0_8px_24px_rgba(255,214,91,0.16)] transition-colors hover:bg-[#ffe487] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#ffd65b] focus-visible:ring-offset-2 focus-visible:ring-offset-[#121521] disabled:cursor-wait disabled:opacity-60"
            >
              {pending ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Set new password'}
            </button>
          </form>

          <button
            type="button"
            onClick={logout}
            disabled={pending}
            className="mt-4 w-full text-center text-sm text-[#a9b1c4] transition-colors hover:text-[#f8fafc] disabled:opacity-60"
          >
            Sign out
          </button>
        </section>
      </div>
    </main>
  );
}
