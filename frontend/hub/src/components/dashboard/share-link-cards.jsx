import { useEffect, useRef, useState } from 'react';
import { CheckIcon, ChevronDownIcon, CopyIcon, ExternalLinkIcon, LinkIcon, MessageCircleIcon } from 'lucide-react';

import api from '@/lib/api';
import { cn } from '@/lib/utils';
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
    title: 'Share Demo Link',
    description: 'Your unique demo booking link',
    noun: 'demo',
    message: 'Book a demo class with Eduport Plus:',
    icon: 'bg-blue-500/15 text-blue-600 dark:text-blue-400',
    button: 'bg-blue-600 text-white hover:bg-blue-600/90 dark:hover:bg-blue-500',
  },
  DIAGNOSTIC: {
    title: 'Share Diagnostic Link',
    description: 'Your unique diagnostic booking link',
    noun: 'diagnostic',
    message: 'Book a Maths diagnostic test with Eduport Plus:',
    icon: 'bg-green-500/15 text-green-600 dark:text-green-400',
    button: 'bg-green-600 text-white hover:bg-green-600/90 dark:hover:bg-green-500',
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
    description: 'Your unique booking link',
    noun: link.booking_type.toLowerCase(),
    message: '',
    icon: 'bg-muted text-foreground',
    button: '',
  };
  const urlRef = useRef(null);
  // 'copied' for a moment after a copy; 'manual' when the browser refused the
  // clipboard (e.g. an insecure origin): the link is then shown, selected.
  const [copyState, setCopyState] = useState('idle');

  useEffect(() => {
    if (copyState === 'manual' && urlRef.current) selectContents(urlRef.current);
    if (copyState !== 'copied') return undefined;
    const timer = setTimeout(() => setCopyState('idle'), 2000);
    return () => clearTimeout(timer);
  }, [copyState]);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(link.url);
      setCopyState('copied');
    } catch {
      setCopyState('manual');
    }
  };

  const whatsAppUrl = `https://wa.me/?text=${encodeURIComponent(`${copy.message} ${link.url}`)}`;
  const status = { copied: `${copy.title.replace('Share ', '')} copied.`, manual: MANUAL_COPY }[copyState] ?? '';

  return (
    <div className="bg-card flex items-start gap-4 rounded-xl border p-4">
      <span className={cn('flex size-11 shrink-0 items-center justify-center rounded-lg', copy.icon)}>
        <LinkIcon className="size-5" />
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-semibold">{copy.title}</p>
        <p className="text-muted-foreground mt-0.5 text-xs">{copy.description}</p>
        <ButtonGroup className="mt-3">
          <Button type="button" className={cn('min-w-36', copy.button)} onClick={handleCopy}>
            {copyState === 'copied' ? <CheckIcon /> : <CopyIcon />}
            {copyState === 'copied' ? 'Copied' : 'Copy Link'}
          </Button>
          <ButtonGroupSeparator className="bg-white/25" />
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button type="button" size="icon" className={copy.button} aria-label={`More ways to share the ${copy.noun} link`}>
                <ChevronDownIcon />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start">
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
              <DropdownMenuItem onSelect={handleCopy}>
                <CopyIcon />
                Copy Link
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </ButtonGroup>
        {copyState === 'manual' ? (
          <p ref={urlRef} className="bg-muted mt-2 rounded-md px-2 py-1 font-mono text-xs break-all">
            {link.url}
          </p>
        ) : null}
        {/* Always in the page so screen readers announce changes; only the
            manual-copy instruction needs to be seen. */}
        <p role="status" className={copyState === 'manual' ? 'text-muted-foreground mt-1 text-xs' : 'sr-only'}>
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
