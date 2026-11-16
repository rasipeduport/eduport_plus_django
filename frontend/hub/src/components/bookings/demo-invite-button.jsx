import { useState } from 'react';
import { CheckIcon, ChevronDownIcon, Loader2Icon, SendIcon } from 'lucide-react';

import api from '@/lib/api';
import { bookingError } from '@/lib/bookings';
import { formatDay } from '@/lib/enquiries';
import { useLinkCopy } from '@/hooks/use-link-copy';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { CopyStatus, ShareLinkMenuItems } from '@/components/dashboard/share-link-buttons';

// What the parent reads before the link in WhatsApp.
const INVITE_MESSAGE = "Book your child's demo class with Eduport Plus. Just pick a date and time:";
// The Demo link's blue (components/dashboard/share-link-buttons.jsx): the invitation books a Demo.
const DEMO_BUTTON = 'bg-blue-600 text-white hover:bg-blue-600/90 dark:hover:bg-blue-500';
// Refusals that will not change by asking again: the child may not be invited now, or the booking is gone.
const FINAL = [404, 409];

/**
 * Send Demo Invitation, on a Diagnostic whose report is in (the API's
 * actions.demo_invite): a menu with the Demo link's own three ways to pass a
 * link on -- Copy Link, Send to the parent on WhatsApp (`recipient`: `{
 * dialCode, number }`) and Preview Link -- for the parent's invitation to
 * book a Demo (backend bookings.demo_invites).
 *
 * The link is fetched when the menu opens (POST `inviteUrl`): the API answers
 * the Diagnostic's active invitation, or issues one, so every open passes on
 * the same link until it expires seven days on. Opening it sends nothing: the
 * parent gets it only from the chat the BDE or administrator sends. A refusal
 * -- the child booked a Demo meanwhile, say -- is shown in the menu, and once
 * the menu closes `onRefused` lets the page read the booking again.
 */
export function DemoInviteButton({ inviteUrl, recipient = null, onRefused, size = 'sm' }) {
  const [invite, setInvite] = useState(null);
  const [failure, setFailure] = useState(null);
  const [pending, setPending] = useState(false);
  const { copied, manual, urlRef, copy } = useLinkCopy();

  const load = async () => {
    setPending(true);
    setFailure(null);
    // An earlier open's link is not offered again until the API confirms it: it may have been used meanwhile.
    setInvite(null);
    try {
      const response = await api.post(inviteUrl);
      setInvite(response.data?.invite ?? null);
    } catch (err) {
      setInvite(null);
      setFailure(bookingError(err, 'Could not prepare the invitation link.'));
    } finally {
      setPending(false);
    }
  };

  const onOpenChange = (open) => {
    if (open) {
      if (!pending) load();
    } else if (failure && FINAL.includes(failure.status)) {
      onRefused?.(failure);
    }
  };

  let content;
  if (invite) {
    content = (
      <>
        <DropdownMenuLabel className="text-muted-foreground text-xs font-normal">
          Link valid until {formatDay(invite.expires_at)}
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <ShareLinkMenuItems
          url={invite.url}
          message={INVITE_MESSAGE}
          recipient={recipient}
          onCopy={() => copy('invite', invite.url)}
        />
      </>
    );
  } else if (failure) {
    content = (
      <>
        <DropdownMenuLabel role="alert" className="text-destructive max-w-64 text-xs font-normal">
          {failure.message}
        </DropdownMenuLabel>
        {FINAL.includes(failure.status) ? null : (
          <DropdownMenuItem
            onSelect={(event) => {
              event.preventDefault();
              load();
            }}
          >
            Try again
          </DropdownMenuItem>
        )}
      </>
    );
  } else {
    content = (
      <DropdownMenuItem disabled>
        <Loader2Icon className="animate-spin" />
        Preparing the link…
      </DropdownMenuItem>
    );
  }

  return (
    // Wraps even in a table cell that does not (the BDE's bookings table), so a link shown to copy by hand stays narrow.
    <div className="flex max-w-72 min-w-0 flex-col gap-1.5 whitespace-normal sm:items-end">
      <DropdownMenu onOpenChange={onOpenChange}>
        <DropdownMenuTrigger asChild>
          <Button type="button" size={size} className={DEMO_BUTTON}>
            {copied ? <CheckIcon /> : <SendIcon />}
            {copied ? 'Copied' : 'Send Demo Invitation'}
            <ChevronDownIcon />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" aria-busy={pending || undefined}>
          {content}
        </DropdownMenuContent>
      </DropdownMenu>
      <CopyStatus manual={manual} urlRef={urlRef} copiedLabel={copied ? 'Invitation link' : null} />
    </div>
  );
}
