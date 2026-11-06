import { useEffect, useState } from 'react';
import { CheckIcon, ChevronDownIcon, CopyIcon, ExternalLinkIcon, MessageCircleIcon } from 'lucide-react';

import api from '@/lib/api';
import { whatsAppUrl } from '@/lib/enquiries';
import { useLinkCopy } from '@/hooks/use-link-copy';
import { Button } from '@/components/ui/button';
import { ButtonGroup, ButtonGroupSeparator } from '@/components/ui/button-group';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Skeleton } from '@/components/ui/skeleton';

// The BDE's own permanent links (DEVT-5934): issued on the first request and
// the same on every request after, so sharing never makes a new token.
const BOOKING_LINKS_URL = '/api/bde/booking-links/';
const MANUAL_COPY = 'Copying is blocked here, so the link is selected: press Ctrl+C (⌘C on a Mac).';

// What each link is for, keyed by the API's booking_type, in the order the
// API returns them (Demo, then Diagnostic): Demo in blue, Diagnostic in green.
const LINK_COPY = {
  DEMO: {
    label: 'Demo Link',
    noun: 'demo',
    message: 'Book a demo class with Eduport Plus:',
    button: 'bg-blue-600 text-white hover:bg-blue-600/90 dark:hover:bg-blue-500',
  },
  DIAGNOSTIC: {
    label: 'Diagnostic Link',
    noun: 'diagnostic',
    message: 'Book a Maths diagnostic test with Eduport Plus:',
    button: 'bg-green-600 text-white hover:bg-green-600/90 dark:hover:bg-green-500',
  },
};

function linkCopy(link) {
  return (
    LINK_COPY[link.booking_type] ?? {
      label: `${link.booking_type} Link`,
      noun: link.booking_type.toLowerCase(),
      message: '',
      button: '',
    }
  );
}

/**
 * What useLinkCopy (hooks/use-link-copy.js) did: the link the browser would not copy, selected, with
 * how to copy it; and, for screen readers, "<copiedLabel> copied.".
 */
export function CopyStatus({ manual, urlRef, copiedLabel }) {
  const status = manual ? MANUAL_COPY : copiedLabel ? `${copiedLabel} copied.` : '';
  return (
    <>
      {manual ? (
        <p ref={urlRef} className="bg-muted max-w-full rounded-md px-2 py-1 font-mono text-xs break-all">
          {manual.url}
        </p>
      ) : null}
      {/* Always in the page so screen readers announce changes; only the
          manual-copy instruction needs to be seen. */}
      <p role="status" className={manual ? 'text-muted-foreground text-xs' : 'sr-only'}>
        {status}
      </p>
    </>
  );
}

/**
 * The ways to pass a link on, as menu items: copy it (`onCopy`), send it on
 * WhatsApp with `message` before it -- to `recipient`'s chat when given, else
 * to whoever WhatsApp asks -- or preview the public page it opens. The BDE's
 * booking links share them, and so does a Diagnostic's Demo invitation
 * (components/bookings/demo-invite-button.jsx).
 */
export function ShareLinkMenuItems({ url, message, recipient = null, onCopy }) {
  const text = `${message} ${url}`;
  const toParent = recipient ? whatsAppUrl(recipient.dialCode, recipient.number, text) : null;
  const whatsApp = toParent ?? `https://wa.me/?text=${encodeURIComponent(text)}`;
  return (
    <>
      <DropdownMenuItem onSelect={onCopy}>
        <CopyIcon />
        Copy Link
      </DropdownMenuItem>
      <DropdownMenuItem asChild>
        <a href={whatsApp} target="_blank" rel="noopener noreferrer">
          <MessageCircleIcon />
          {toParent ? 'Send to the parent on WhatsApp' : 'Share on WhatsApp'}
        </a>
      </DropdownMenuItem>
      {/* The public page itself, as the parent will open it. */}
      <DropdownMenuItem asChild>
        <a href={url} target="_blank" rel="noopener noreferrer">
          <ExternalLinkIcon />
          Preview Link
        </a>
      </DropdownMenuItem>
    </>
  );
}

/**
 * One link: the main button copies it; the arrow's menu copies, shares on
 * WhatsApp or previews it. With a `recipient` the WhatsApp chat is that
 * parent's, the message filled in; without one WhatsApp asks whom to send it to.
 */
function ShareLinkButton({ link, copied, onCopy, recipient }) {
  const copy = linkCopy(link);

  return (
    <ButtonGroup>
      <Button type="button" className={copy.button} onClick={() => onCopy(link)} aria-label={`Copy ${copy.label}`}>
        {copied ? <CheckIcon /> : <CopyIcon />}
        {copied ? 'Copied' : copy.label}
      </Button>
      <ButtonGroupSeparator className="bg-white/25" />
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button type="button" size="icon" className={copy.button} aria-label={`More ways to share the ${copy.noun} link`}>
            <ChevronDownIcon />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <ShareLinkMenuItems url={link.url} message={copy.message} recipient={recipient} onCopy={() => onCopy(link)} />
        </DropdownMenuContent>
      </DropdownMenu>
    </ButtonGroup>
  );
}

/**
 * The BDE's quick sharing -- on their dashboard and My Leads, and on one of
 * their leads for that lead's parent (`recipient`: `{ dialCode, number }`):
 * the BDE's own Demo and Diagnostic booking links, each copied in one click or
 * shared on WhatsApp or previewed from its menu. The API serves each BDE only
 * their own links.
 */
export function ShareLinkButtons({ recipient = null }) {
  const [links, setLinks] = useState(null);
  const [failure, setFailure] = useState(null);
  const [reloadKey, setReloadKey] = useState(0);
  // The booking type just copied, for a moment; or the link the browser
  // refused to copy (e.g. an insecure origin), then shown selected instead.
  const { copied, manual, urlRef, copy } = useLinkCopy();

  useEffect(() => {
    let active = true;
    api
      .get(BOOKING_LINKS_URL)
      .then((response) => {
        if (!active) return;
        setLinks(response.data?.links ?? []);
        setFailure(null);
      })
      .catch((err) => {
        if (!active) return;
        const response = err?.response;
        setFailure({
          status: response?.status ?? null,
          message: response
            ? response.data?.message || response.data?.detail || 'Could not load your booking links.'
            : 'Could not reach the server. Check your connection and try again.',
        });
      });
    return () => {
      active = false;
    };
  }, [reloadKey]);

  const copyLink = (link) => copy(link.booking_type, link.url);

  if (failure) {
    // An account the API holds no links for (not a BDE) has nothing to share.
    if (failure.status === 403) return null;
    return (
      <div className="flex flex-wrap items-center gap-2">
        <p className="text-destructive text-sm">{failure.message}</p>
        <Button variant="outline" size="sm" onClick={() => setReloadKey((key) => key + 1)}>
          Try again
        </Button>
      </div>
    );
  }

  if (!links) {
    return (
      <div className="flex flex-wrap gap-2" aria-busy="true">
        <Skeleton className="h-9 w-40" />
        <Skeleton className="h-9 w-44" />
      </div>
    );
  }

  const copiedLink = links.find((link) => link.booking_type === copied);

  return (
    <div className="flex min-w-0 flex-col gap-1.5 sm:items-end">
      <div className="flex flex-wrap gap-2">
        {links.map((link) => (
          <ShareLinkButton
            key={link.booking_type}
            link={link}
            copied={copied === link.booking_type}
            onCopy={copyLink}
            recipient={recipient}
          />
        ))}
      </div>
      <CopyStatus manual={manual} urlRef={urlRef} copiedLabel={copiedLink ? linkCopy(copiedLink).label : null} />
    </div>
  );
}
