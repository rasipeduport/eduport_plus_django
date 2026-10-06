export function WelcomeSection({ studentName }) {
  const firstName = studentName ? studentName.split(' ')[0] : 'Student';

  return (
    <div className="from-primary to-primary-hover relative -mx-4 -mt-4 overflow-hidden rounded-b-[2rem] bg-gradient-to-br px-5 pt-12 pb-10 shadow-md md:mx-0 md:mt-0 md:px-7 md:pt-14 md:pb-12">
      {/* Decorative orbs */}
      <div className="pointer-events-none absolute -top-16 -right-16 h-48 w-48 rounded-full bg-accent/15 blur-3xl" />
      <div className="pointer-events-none absolute -bottom-8 -left-8 h-32 w-32 rounded-full bg-white/5 blur-2xl" />

      <div className="relative flex flex-col items-center gap-3 text-center">
        {/* Logo */}
        <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-white shadow-sm">
          <img
            src="/brand/icon.png"
            alt="Eduport Plus"
            className="w-7 h-7 object-contain"
          />
        </div>

        {/* Greeting */}
        <div>
          <h1 className="text-2xl font-bold text-white md:text-3xl">
            Hi {firstName}
          </h1>
          <p className="mt-0.5 text-sm text-white/75">
            Welcome back to Eduport Plus
          </p>
        </div>
      </div>
    </div>
  );
}
