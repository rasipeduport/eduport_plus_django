import { LogOut, RefreshCw } from 'lucide-react';
import { useStudent } from '../components/student/student-context';
import { useStatusCheck } from '../hooks/useStatusCheck';

// What a check that leaves the student here says.
const OUTCOMES = {
  waiting: { tone: 'info', text: "Your profile isn't linked yet. You'll get in as soon as it is, so check again in a little while." },
  unreachable: { tone: 'danger', text: "We couldn't check right now. Check your internet connection and try again." },
};

// Shown to students whose profile is not yet linked to student records. Check
// Status resolves the account again, as signing in does: linked, it opens the
// dashboard (or choosing a child, when several are linked and none chosen);
// expired, access ended; otherwise it says why it stays.
export default function WaitingRoomPage() {
  const { logout } = useStudent();
  const { checking, outcome, check } = useStatusCheck();
  const said = OUTCOMES[outcome] ?? null;

  return (
    <div className="bg-surface flex min-h-dvh flex-col text-text-primary">
      {/* Header */}
      <div className="from-primary to-primary-hover relative overflow-hidden bg-gradient-to-br px-6 pt-7 pb-6 md:px-7 md:pt-9 md:pb-8">
        <div className="pointer-events-none absolute -top-20 -right-20 h-60 w-60 rounded-full bg-white/10 blur-3xl" />
        <div className="pointer-events-none absolute -bottom-10 -left-10 h-40 w-40 rounded-full bg-white/5 blur-2xl" />

        <div className="relative mx-auto max-w-sm text-center">
          <div className="mx-auto mb-5 flex h-12 w-12 items-center justify-center rounded-2xl bg-white shadow-sm">
            <img
              src="/brand/icon.png"
              alt="Eduport Plus"
              className="w-7.5 h-7.5 object-contain"
            />
          </div>
          <h1 className="text-2xl font-bold text-white md:text-3xl">
            Account Verification
          </h1>
          <p className="mt-1.5 text-sm text-white/75 md:text-base">
            Processing your profile setup
          </p>
        </div>
      </div>

      {/* Content area */}
      <div className="mx-auto w-full max-w-sm flex-1 px-5 py-6 md:py-8 flex flex-col justify-between">
        <div className="flex-1 space-y-4">
          <div className="rounded-2xl border border-border-light bg-surface-elevated p-5 shadow-card">
            <p className="text-text-primary text-sm leading-relaxed mb-4">
              We're just getting your account ready! Your profile is currently waiting to be linked with your student records.
            </p>
            <div className="rounded-xl bg-surface-muted p-4">
              <h3 className="text-sm font-semibold text-text-primary mb-1">Need help?</h3>
              <p className="text-text-secondary text-[13px] leading-relaxed">
                Please contact your <span className="font-medium text-text-primary">mentor</span> to fast-track this process. If you aren't sure who your mentor is, feel free to reach out to our{' '}
                <a
                  href="https://wa.me/971585982494?text=Hi%21%20I%27m%20waiting%20to%20be%20verified%20on%20Eduport%20Plus."
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-primary hover:underline font-medium"
                >
                  support team
                </a>.
              </p>
            </div>
          </div>

          <button
            onClick={check}
            disabled={checking}
            aria-busy={checking || undefined}
            className="flex w-full items-center justify-center gap-2 rounded-xl bg-primary px-4 h-11 text-sm font-semibold text-white shadow-sm hover:bg-primary-hover transition-colors disabled:opacity-70 cursor-pointer"
          >
            <RefreshCw className={`h-4 w-4 ${checking ? 'animate-spin' : ''}`} aria-hidden="true" />
            {checking ? 'Checking...' : 'Check Status'}
          </button>
          <p
            role="status"
            aria-live="polite"
            className={said ? `rounded-xl px-4 py-3 text-sm ${said.tone === 'danger' ? 'bg-danger-subtle text-danger' : 'bg-info-subtle text-info'}` : 'sr-only'}
          >
            {said?.text ?? ''}
          </p>
        </div>

        <div className="mt-8">
          <button
            onClick={logout}
            className="border-border bg-surface-elevated text-text-secondary hover:bg-surface-muted hover:text-text-primary flex h-11 w-full items-center justify-center gap-2 rounded-xl border px-4 text-sm font-semibold transition-colors duration-150 cursor-pointer"
          >
            <LogOut className="h-4 w-4" />
            Sign Out
          </button>
        </div>
      </div>
    </div>
  );
}
