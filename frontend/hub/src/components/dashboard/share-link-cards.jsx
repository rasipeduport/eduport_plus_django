import { useEffect, useRef, useState } from 'react';
import { CheckIcon, ChevronDownIcon, CopyIcon, ExternalLinkIcon, Link2, MessageCircleIcon } from 'lucide-react';

import api from '@/lib/api';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Skeleton } from '@/components/ui/skeleton';
import { ToneIcon } from '@/components/dashboard/dashboard-primitives';

// The BDE's own permanent links (DEVT-5934): issued on the first request and
// the same on every request after, so sharing never makes a new token.
const BOOKING_LINKS_URL = '/api/bde/booking-links/';
const MANUAL_COPY = 'Copying is blocked here, so the link is selected: press Ctrl+C (⌘C on a Mac).';

// What each link is for, keyed by the API's booking_type, in the order the
// API returns them (Demo, then Diagnostic). The tones match the dashboard's
// Demo and Diagnostic booking tiles.
const LINK_COPY = {
  DEMO: {
    title: 'Share Demo Link',
    noun: 'demo',
    tone: 'success',
    message: 'Book a demo class with Eduport Plus:',
  },
  DIAGNOSTIC: {
    title: 'Share Diagnostic Link',
    noun: 'diagnostic',
    tone: 'warning',
    message: 'Book a Maths diagnostic test with Eduport Plus:',
  },
};

function selectContents(element) {
  const selection = window.getSelection();
  const range = document.createRange();
  range.selectNodeContents(element);
  selection.removeAllRanges();
  selection.addRange(range);
}

function ShareLinkCard({ link }) {
  const copy = LINK_COPY[link.booking_type] ?? {
    title: `Share ${link.booking_type} Link`,
    noun: link.booking_type.toLowerCase(),
    tone: 'default',
    message: '',
  };
  const urlRef = useRef(null);
  // 'copied' for a moment after a copy; 'manual' when the browser refused the
  // clipboard (e.g. an insecure origin) and the link was selected instead.
  const [copyState, setCopyState] = useState('idle');

  useEffect(() => {
    if (copyState !== 'copied') return undefined;
    const timer = setTimeout(() => setCopyState('idle'), 2000);
    return () => clearTimeout(timer);
  }, [copyState]);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(link.url);
      setCopyState('copied');
    } catch {
      if (urlRef.current) selectContents(urlRef.current);
      setCopyState('manual');
    }
  };

  const whatsAppUrl = `https://wa.me/?text=${encodeURIComponent(`${copy.message} ${link.url}`)}`;
  const status = { copied: `${copy.title.replace('Share ', '')} copied.`, manual: MANUAL_COPY }[copyState] ?? '';

  return (
    <div className="bg-card flex items-start gap-3 rounded-xl border p-4">
      <ToneIcon icon={Link2} tone={copy.tone} />
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium">{copy.title}</p>
        <p ref={urlRef} className="text-muted-foreground mt-0.5 truncate font-mono text-xs" title={link.url}>
          {link.url}
        </p>
        <div className="mt-3 flex items-center gap-2">
          <Button type="button" size="sm" onClick={handleCopy}>
            {copyState === 'copied' ? <CheckIcon /> : <CopyIcon />}
            {copyState === 'copied' ? 'Copied' : 'Copy Link'}
          </Button>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button type="button" size="icon-sm" variant="outline" aria-label={`More ways to share the ${copy.noun} link`}>
                <ChevronDownIcon />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start">
              <DropdownMenuItem onSelect={handleCopy}>
                <CopyIcon />
                Copy Link
              </DropdownMenuItem>
              <DropdownMenuItem asChild>
                <a href={whatsAppUrl} target="_blank" rel="noopener noreferrer">
                  <MessageCircleIcon />
                  Share on WhatsApp
                </a>
              </DropdownMenuItem>
              {/* The public booking page itself, the BDE's ref token in its URL. */}
              <DropdownMenuItem asChild>
                <a href={link.url} target="_blank" rel="noopener noreferrer">
                  <ExternalLinkIcon />
                  Preview Link
                </a>
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
        {/* Always in the page so screen readers announce changes; only the
            manual-copy instruction needs to be seen. */}
        <p role="status" className={copyState === 'manual' ? 'text-muted-foreground mt-2 text-xs' : 'sr-only'}>
          {status}
        </p>
      </div>
    </div>
  );
}

/**
 * The BDE dashboard's quick sharing: the BDE's own Demo and Diagnostic
 * booking links, each copied in one click or shared on WhatsApp or previewed
 * from its menu. The API serves each BDE only their own links.
 */
export function ShareLinkCards() {
  const [links, setLinks] = useState(null);
  const [failure, setFailure] = useState(null);
  const [reloadKey, setReloadKey] = useState(0);

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

  if (failure) {
    // An account the API holds no links for (not a BDE) has nothing to share.
    if (failure.status === 403) return null;
    return (
      <div className="flex flex-wrap items-center gap-3 rounded-xl border p-4">
        <p className="text-destructive text-sm">{failure.message}</p>
        <Button variant="outline" size="sm" onClick={() => setReloadKey((key) => key + 1)}>
          Try again
        </Button>
      </div>
    );
  }

  if (!links) {
    return (
      <div className="grid gap-4 sm:grid-cols-2" aria-busy="true">
        {[0, 1].map((key) => (
          <Skeleton key={key} className="h-[7.5rem] rounded-xl" />
        ))}
      </div>
    );
  }

  return (
    <div className="grid gap-4 sm:grid-cols-2">
      {links.map((link) => (
        <ShareLinkCard key={link.booking_type} link={link} />
      ))}
    </div>
  );
}
