import { useCallback, useEffect, useState } from 'react';
import { Download } from 'lucide-react';
import { BottomSheet } from './bottom-sheet';

// ─── Constants ───────────────────────────────────────────────────────────────
const DISMISS_KEY = 'pwa_install_dismissed_at';
const COOLDOWN_MS = 24 * 60 * 60 * 1000; // 24 hours

// ─── Helpers ─────────────────────────────────────────────────────────────────

// Only Android phones/tablets held in portrait. Desktop Chrome/Edge keep their
// own address-bar install button, and iOS has no beforeinstallprompt at all.
function isAndroidPortrait() {
  if (typeof window === 'undefined') return false;
  const isAndroid = /android/i.test(navigator.userAgent);
  const isPortrait = window.innerWidth < window.innerHeight;
  return isAndroid && isPortrait;
}

function isAlreadyInstalled() {
  if (typeof window === 'undefined') return false;
  return window.matchMedia('(display-mode: standalone)').matches;
}

function wasDismissedRecently() {
  try {
    const raw = localStorage.getItem(DISMISS_KEY);
    if (!raw) return false;
    return Date.now() - Number(raw) < COOLDOWN_MS;
  } catch {
    return false;
  }
}

function saveDismissal() {
  try {
    localStorage.setItem(DISMISS_KEY, String(Date.now()));
  } catch {
    // Private mode / blocked storage -- the nudge just reappears next visit.
  }
}

// ─── Component ───────────────────────────────────────────────────────────────

// "Add to Home Screen" nudge, ported from the Next.js Learn app. The sheet only
// opens once the browser tells us the app is installable (beforeinstallprompt),
// and a dismissal is respected for 24 hours.
export function InstallPrompt() {
  const [open, setOpen] = useState(false);
  const [deferredPrompt, setDeferredPrompt] = useState(null);

  useEffect(() => {
    if (!isAndroidPortrait() || isAlreadyInstalled()) return;
    if (wasDismissedRecently()) return;

    function onBeforeInstall(e) {
      e.preventDefault();
      setDeferredPrompt(e);
      // Small delay so the page isn't mid-render when the sheet animates in
      setTimeout(() => setOpen(true), 800);
    }
    window.addEventListener('beforeinstallprompt', onBeforeInstall);

    return () => {
      window.removeEventListener('beforeinstallprompt', onBeforeInstall);
    };
  }, []);

  const handleDismiss = useCallback(() => {
    setOpen(false);
    saveDismissal();
  }, []);

  const handleInstall = useCallback(async () => {
    if (!deferredPrompt) return;
    setOpen(false);
    await deferredPrompt.prompt();
    const { outcome } = await deferredPrompt.userChoice;
    if (outcome !== 'accepted') {
      // Declined the native dialog -- hold off for 24 h like a manual dismiss
      saveDismissal();
    }
    setDeferredPrompt(null);
  }, [deferredPrompt]);

  return (
    <BottomSheet
      open={open}
      onClose={handleDismiss}
      ariaLabel="Add to Home Screen"
      className="h-auto max-h-[55dvh]"
    >
      <div className="flex flex-col gap-5 pb-2">
        {/* ── App identity ─────────────────────────────────────── */}
        <div className="flex items-center gap-3">
          <div className="ring-primary/20 flex h-14 w-14 shrink-0 items-center justify-center overflow-hidden rounded-2xl ring-1">
            <img
              src="/icons/icon-192x192.png"
              alt="Eduport Plus"
              width={56}
              height={56}
              className="h-full w-full object-cover"
            />
          </div>
          <div>
            <p className="text-text-primary text-base leading-tight font-bold">
              Add to Home Screen
            </p>
            <p className="text-text-secondary text-sm">Learn with Eduport Plus</p>
          </div>
        </div>

        {/* ── One-liner benefit ────────────────────────────────── */}
        <p className="text-text-secondary text-sm leading-relaxed">
          Install for instant access, a full-screen experience, and faster
          loading — right from your home screen.
        </p>

        {/* ── CTA ──────────────────────────────────────────────── */}
        <div className="flex flex-col gap-2">
          <button
            onClick={handleInstall}
            className="bg-primary hover:bg-primary-hover active:bg-primary-active focus-visible:ring-primary/40 flex h-12 w-full cursor-pointer items-center justify-center gap-2 rounded-2xl text-sm font-semibold text-white shadow-xs transition-colors focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:outline-none"
          >
            <Download width={18} height={18} strokeWidth={2} />
            Install app
          </button>
          <button
            onClick={handleDismiss}
            className="text-text-secondary hover:text-text-primary focus-visible:ring-primary/40 h-10 w-full cursor-pointer rounded-xl text-sm font-medium transition-colors focus-visible:ring-2 focus-visible:outline-none"
          >
            Not now
          </button>
        </div>
      </div>
    </BottomSheet>
  );
}
