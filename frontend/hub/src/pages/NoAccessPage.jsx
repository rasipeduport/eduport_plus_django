/**
 * Shown instead of the Hub to a signed-in account holding no permission that
 * opens a Hub page (lib/access homePage) -- a role whose permissions are not
 * set up yet, such as BDE or Sales TL today. It stands alone like the forced password
 * change: no sidebar, no data requests -- the API refuses such an account
 * anyway -- and signing out is the only action.
 */
export default function NoAccessPage({ user, logout }) {
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
          <p className="mb-2 text-xs font-semibold uppercase tracking-[0.18em] text-[#ffd65b]">No Hub access</p>
          <h1 className="text-3xl font-semibold tracking-[-0.04em] text-[#f8fafc]">Your access isn't set up yet</h1>
          <p className="mt-3 text-sm leading-6 text-[#a9b1c4]">
            You signed in as <strong className="text-[#f8fafc]">{user?.username}</strong>, but this account doesn't
            have any Hub access yet. Ask an administrator to set up your access, then sign in again.
          </p>

          <button
            type="button"
            onClick={logout}
            className="mt-7 flex h-12 w-full items-center justify-center rounded-xl bg-[#ffd65b] text-sm font-semibold text-[#0e101c] shadow-[0_8px_24px_rgba(255,214,91,0.16)] transition-colors hover:bg-[#ffe487] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#ffd65b] focus-visible:ring-offset-2 focus-visible:ring-offset-[#121521]"
          >
            Sign out
          </button>
        </section>
      </div>
    </main>
  );
}
