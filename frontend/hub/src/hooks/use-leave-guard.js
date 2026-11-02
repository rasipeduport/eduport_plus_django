import { useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';

// The Back and Forward handler of the page holding them, if one is (useLeaveGuard).
let heldPop = null;
// That page's way of asking before something else leaves it (confirmLeave).
let heldLeave = null;
let installed = false;

/**
 * Listens for the browser's Back and Forward on behalf of useLeaveGuard.
 * Called once in main.jsx, before the app renders: at the window, listeners
 * run in the order they were added -- capturing or not -- so this one must
 * come before the one <BrowserRouter> adds, to hold a step before React
 * Router hears of it.
 */
export function installLeaveGuard() {
  if (installed) return;
  installed = true;
  window.addEventListener('popstate', (event) => heldPop?.(event));
}

/**
 * Runs `proceed` -- something that leaves the page shown, such as logging
 * out -- at once, or, while a page holds the way out (useLeaveGuard), only
 * once that page has asked and been told to go ahead.
 */
export function confirmLeave(proceed) {
  if (heldLeave) heldLeave(proceed);
  else proceed();
}

/**
 * While `active`, holds the ways out of a page that happen inside the Hub --
 * a click on a link to another of its pages (the sidebar, the breadcrumbs),
 * the browser's Back and Forward, and whatever leaves through confirmLeave
 * (logging out) -- and hands each to `onBlocked(proceed)`; calling
 * `proceed()` leaves after all. Reloading, closing the tab and links out of
 * the Hub are for a beforeunload warning.
 *
 * App.jsx routes with <BrowserRouter>, which has no useBlocker, so this works
 * on the page itself, ahead of React Router: link clicks in the capture phase
 * on the document, Back and Forward through installLeaveGuard -- then undone
 * with history.go(), so the page and the address bar stay as they were. That
 * needs the index React Router gives each history entry (history.state.idx);
 * a step to an entry without one is let through.
 */
export function useLeaveGuard(active, onBlocked) {
  const navigate = useNavigate();
  const blocked = useRef(onBlocked);
  blocked.current = onBlocked;

  useEffect(() => {
    if (!active) return undefined;
    const here = window.history.state?.idx;
    let stepping = null; // 'back': our own step back to this page; 'out': the step out, let through

    const onClick = (event) => {
      if (event.defaultPrevented || event.button !== 0) return;
      if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return; // a new tab or window
      const link = event.target instanceof Element ? event.target.closest('a[href]') : null;
      if (!link || link.hasAttribute('download') || (link.target && link.target !== '_self')) return;
      const url = new URL(link.href, window.location.href);
      if (url.origin !== window.location.origin) return;
      if (url.pathname === window.location.pathname && url.search === window.location.search) return;
      event.preventDefault();
      event.stopPropagation();
      blocked.current(() => navigate(`${url.pathname}${url.search}${url.hash}`));
    };

    const onPopState = (event) => {
      if (stepping === 'out') {
        stepping = null;
        return;
      }
      if (stepping === 'back') {
        stepping = null;
        event.stopImmediatePropagation();
        return;
      }
      const there = event.state?.idx;
      if (typeof here !== 'number' || typeof there !== 'number' || there === here) return;
      event.stopImmediatePropagation();
      stepping = 'back';
      window.history.go(here - there);
      blocked.current(() => {
        stepping = 'out';
        window.history.go(there - here);
      });
    };

    const onLeave = (proceed) => blocked.current(proceed);

    document.addEventListener('click', onClick, true);
    heldPop = onPopState;
    heldLeave = onLeave;
    return () => {
      document.removeEventListener('click', onClick, true);
      if (heldPop === onPopState) heldPop = null;
      if (heldLeave === onLeave) heldLeave = null;
    };
  }, [active, navigate]);
}
