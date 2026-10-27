import { useEffect, useRef, useState } from 'react';
import { CheckIcon, CopyIcon, Link2Icon, MessageCircleIcon, ShieldAlertIcon } from 'lucide-react';

import api from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';

const BOOKING_LINKS_URL = '/api/bde/booking-links/';
const MANUAL_COPY = 'Copying is blocked here, so the link is selected: press Ctrl+C (⌘C on a Mac).';

// What each link is for, keyed by the API's booking_type. The API returns the
// links in this order (Demo, then Diagnostic).
const LINK_COPY = {
  DEMO: {
    title: 'Demo class',
    description: 'Parents open this link to book a demo class.',
    message: 'Book a demo class with Eduport Plus:',
  },
  DIAGNOSTIC: {
    title: 'Diagnostic test',
    description: 'Parents open this link to book a Maths diagnostic test.',
    message: 'Book a Maths diagnostic test with Eduport Plus:',
  },
};

function loadError(err) {
  const response = err?.response;
  return {
    status: response?.status ?? null,
    code: typeof response?.data?.error === 'string' ? response.data.error : null,
    message: response
      ? response.data?.message || response.data?.detail || 'Could not load your booking links.'
      : 'Could not reach the server. Check your connection and try again.',
  };
}

function selectContents(element) {
  const selection = window.getSelection();
  const range = document.createRange();
  range.selectNodeContents(element);
  selection.removeAllRanges();
  selection.addRange(range);
}

function LinkCard({ link }) {
  const copy = LINK_COPY[link.booking_type] ?? { title: link.booking_type, description: '', message: '' };
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

  const shareUrl = `https://wa.me/?text=${encodeURIComponent(`${copy.message} ${link.url}`)}`;
  const status = { copied: `${copy.title} link copied.`, manual: MANUAL_COPY }[copyState] ?? '';

  return (
    <Card className="gap-4">
      <CardHeader>
        <CardTitle>{copy.title}</CardTitle>
        <CardDescription>{copy.description}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <p ref={urlRef} className="bg-muted rounded-md px-3 py-2 font-mono text-xs break-all sm:text-sm">
          {link.url}
        </p>
        <div className="flex flex-col gap-2 sm:flex-row">
          <Button type="button" variant="outline" className="sm:flex-1" onClick={handleCopy}>
            {copyState === 'copied' ? <CheckIcon /> : <CopyIcon />}
            {copyState === 'copied' ? 'Copied' : 'Copy link'}
          </Button>
          <Button asChild className="sm:flex-1">
            <a href={shareUrl} target="_blank" rel="noopener noreferrer">
              <MessageCircleIcon />
              Share on WhatsApp
            </a>
          </Button>
        </div>
        {/* Always in the page so screen readers announce changes; only the
            manual-copy instruction needs to be seen. */}
        <p role="status" className={copyState === 'manual' ? 'text-muted-foreground text-xs' : 'sr-only'}>
          {status}
        </p>
      </CardContent>
    </Card>
  );
}

function LinksSkeleton() {
  return (
    <div className="grid gap-4 xl:grid-cols-2" aria-busy="true">
      {[0, 1].map((key) => (
        <div key={key} className="flex flex-col gap-3 rounded-xl border p-6">
          <Skeleton className="h-5 w-32" />
          <Skeleton className="h-4 w-64 max-w-full" />
          <Skeleton className="h-9 w-full" />
          <div className="flex gap-2">
            <Skeleton className="h-9 flex-1" />
            <Skeleton className="h-9 flex-1" />
          </div>
        </div>
      ))}
    </div>
  );
}

function NoLinks({ failure }) {
  const notABde = failure.code === 'NOT_A_BDE';
  const Icon = notABde ? Link2Icon : ShieldAlertIcon;
  return (
    <div className="flex flex-col items-center gap-2 rounded-md border px-6 py-12 text-center">
      <Icon className="text-muted-foreground size-8" />
      <p className="font-medium">
        {notABde ? 'Booking links are issued to BDE accounts.' : "You don't have access to booking links."}
      </p>
      <p className="text-muted-foreground max-w-md text-sm">
        {notABde ? 'This account is not a BDE, so it has none.' : failure.message}
      </p>
    </div>
  );
}

/**
 * The BDE workspace: the caller's own permanent Demo and Diagnostic booking
 * links, to copy or share with parents. The API issues them on the first
 * visit and returns the same two every time after; it only ever returns the
 * caller's own.
 */
export default function BookingLinksPage() {
  const [links, setLinks] = useState(null);
  const [failure, setFailure] = useState(null);
  const [pending, setPending] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let active = true;
    setPending(true);

    api
      .get(BOOKING_LINKS_URL)
      .then((response) => {
        if (!active) return;
        setLinks(response.data?.links ?? []);
        setFailure(null);
      })
      .catch((err) => {
        if (active) setFailure(loadError(err));
      })
      .finally(() => {
        if (active) setPending(false);
      });

    return () => {
      active = false;
    };
  }, [reloadKey]);

  const retry = () => setReloadKey((key) => key + 1);

  let content;
  if (failure?.status === 403) {
    content = <NoLinks failure={failure} />;
  } else if (failure) {
    content = (
      <div className="flex flex-wrap items-center gap-3">
        <p className="text-destructive text-sm">{failure.message}</p>
        <Button variant="outline" size="sm" onClick={retry} disabled={pending}>
          Try again
        </Button>
      </div>
    );
  } else if (!links) {
    content = <LinksSkeleton />;
  } else {
    content = (
      <div className="grid gap-4 xl:grid-cols-2">
        {links.map((link) => (
          <LinkCard key={link.booking_type} link={link} />
        ))}
      </div>
    );
  }

  return (
    <div className="container mx-auto px-4 py-16">
      <div className="mb-6">
        <h1 className="text-2xl font-semibold">Booking links</h1>
        <p className="text-muted-foreground text-sm">
          Share these with parents to book a demo class or a diagnostic test. Each link is yours alone and never
          changes, so you can share it as often as you like.
        </p>
      </div>

      {content}
    </div>
  );
}
