import { Link, useSearchParams } from 'react-router-dom';
import { ArrowUpRight, CalendarCheck, X } from 'lucide-react';

const SITE_URL = 'https://plus.eduport.app/';

// The success mark's rays: four each side, in degrees from the horizontal.
const RAYS = [-36, -12, 12, 36].flatMap((angle) => [angle, 180 - angle]);

/**
 * Where Stripe Checkout sends the payer back (backend sales/checkout.py:
 * ?result=submitted from success_url, ?result=cancelled from cancel_url). The
 * return itself proves nothing -- only the signed webhook confirms a payment
 * -- so the page never says the payment succeeded, only that it was received
 * for confirmation. A declined card never lands here: Checkout keeps the payer
 * on its own page. It stands alone (no sign-in, no API calls) and stays light
 * in dark mode too, so the step from Checkout's white page is seamless.
 */
export default function PaymentReturnPage() {
  const [params] = useSearchParams();
  const cancelled = params.get('result') === 'cancelled';
  return (
    <main className="relative isolate flex min-h-dvh flex-col items-center justify-center overflow-hidden bg-white px-4 py-8 font-sans text-[#0f172a] [color-scheme:light] sm:px-6 sm:py-12">
      <div aria-hidden="true" className="pointer-events-none absolute inset-0 overflow-hidden">
        <div className="absolute -left-56 -top-48 h-[26rem] w-[40rem] -rotate-[28deg] rounded-full bg-[#f1faf4]" />
        <div className="absolute -left-64 -top-60 h-[22rem] w-[34rem] -rotate-[28deg] rounded-full bg-[#e7f6ec]" />
        <div className="absolute -bottom-52 -right-40 h-[26rem] w-[26rem] rounded-full bg-[#f1faf4]" />
        <div className="absolute -bottom-64 -right-24 h-[22rem] w-[22rem] rounded-full bg-[#e7f6ec]" />
      </div>

      <div className="relative z-10 flex w-full flex-col items-center">
        <img src="/brand/logo.svg" alt="Eduport Plus" className="h-14 w-auto sm:h-16" />

        <section className="mt-7 w-full max-w-xl rounded-3xl border border-[#e2e8f0] bg-white px-5 py-8 text-center shadow-[0_18px_50px_rgba(15,23,42,0.08)] sm:mt-9 sm:px-10 sm:py-10">
          {cancelled ? <Cancelled /> : <Received />}
        </section>

        <footer className="mt-8 w-full max-w-2xl border-t border-[#e2e8f0] pt-5 text-center text-sm text-[#64748b] sm:mt-10">
          © Eduport Plus · Learn. Grow. Succeed.
        </footer>
      </div>
    </main>
  );
}

function Received() {
  return (
    <>
      <SuccessMark />
      <h1 className="mt-4 text-4xl font-bold tracking-[-0.03em] sm:text-5xl">Thank you!</h1>
      <p className="mt-4 inline-flex rounded-full bg-[#ecfdf3] px-4 py-1.5 text-sm font-semibold text-[#15803d] sm:px-5 sm:text-base">
        Payment received for confirmation
      </p>
      <p className="mx-auto mt-5 max-w-md leading-7 text-[#475569]">
        Your payment is being confirmed. Our Eduport adviser will contact you once the payment is verified and your
        enrollment is confirmed.
      </p>

      <div className="mt-7 flex items-center gap-4 rounded-2xl bg-[#f0faf4] px-4 py-4 text-left sm:gap-5 sm:px-6 sm:py-5">
        <CalendarCheck aria-hidden="true" className="size-7 shrink-0 text-[#15803d] sm:size-8" />
        <div aria-hidden="true" className="w-px shrink-0 self-stretch bg-[#bfe5cc]" />
        <div>
          <h2 className="font-semibold">What's next?</h2>
          <p className="mt-1 text-sm leading-6 text-[#475569]">
            Our team will verify your payment and guide you through the enrollment process.
          </p>
        </div>
      </div>

      <div className="mt-8 flex flex-col items-center gap-3">
        <a
          href={SITE_URL}
          className="inline-flex w-full items-center justify-center gap-2 rounded-full bg-[#15803d] px-8 py-3.5 font-semibold text-white shadow-[0_8px_20px_rgba(21,128,61,0.25)] transition-colors hover:bg-[#166534] focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-[#15803d]/30 sm:w-auto sm:min-w-72"
        >
          Visit Eduport Plus
          <ArrowUpRight aria-hidden="true" className="size-5" />
        </a>
        <a href={SITE_URL} className="text-sm text-[#475569] underline underline-offset-4 hover:text-[#0f172a]">
          {SITE_URL}
        </a>
      </div>
    </>
  );
}

// Cancelled at Checkout: the existing words and link, without the success look.
function Cancelled() {
  return (
    <>
      <div className="mx-auto flex size-16 items-center justify-center rounded-full bg-[#f1f5f9]">
        <X aria-hidden="true" className="size-7 text-[#64748b]" />
      </div>
      <h1 className="mt-5 text-3xl font-bold tracking-[-0.03em] sm:text-4xl">Payment cancelled</h1>
      <p className="mx-auto mt-4 max-w-md leading-7 text-[#475569]">
        No enrollment has been confirmed. You can return to your payment link when you are ready.
      </p>
      <Link to="/login" className="mt-6 inline-block text-sm font-medium underline underline-offset-4">
        Eduport Plus
      </Link>
    </>
  );
}

// The green check in its halo, with short rays around it.
function SuccessMark() {
  return (
    <svg
      viewBox="0 0 140 100"
      aria-hidden="true"
      className="mx-auto h-24 w-auto motion-safe:animate-in motion-safe:fade-in motion-safe:zoom-in-75 motion-safe:duration-500 sm:h-28"
    >
      <g stroke="#86d1a0" strokeWidth="3.5" strokeLinecap="round">
        {RAYS.map((angle) => {
          const [cos, sin] = [Math.cos((angle * Math.PI) / 180), Math.sin((angle * Math.PI) / 180)];
          return <line key={angle} x1={70 + 46 * cos} y1={50 + 46 * sin} x2={70 + 55 * cos} y2={50 + 55 * sin} />;
        })}
      </g>
      <circle cx="70" cy="50" r="38" fill="#e8f7ee" />
      <circle cx="70" cy="50" r="25" fill="#16a34a" />
      <path d="M59 50.5l7.5 7.5L81.5 43" fill="none" stroke="#fff" strokeWidth="5.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
