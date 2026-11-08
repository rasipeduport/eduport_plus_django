import { ExternalLinkIcon, VideoIcon, VideoOffIcon } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { isHttpsUrl } from '@/lib/exam-status';
import { cn } from '@/lib/utils';

const NOT_CONFIGURED = 'Meet link not configured';

/**
 * Join Meet: the booking's Google Meet room (`link`, the booking's copy of its
 * tutor's own) as a button that opens it in a new tab, cut off from the Hub
 * (noopener). Only an https address the API returned is opened -- none is
 * ever made up -- so a booking without one shows "No Meet link" plainly
 * instead of a button that leads nowhere. `label` names it for screen
 * readers ("Join the Google Meet for Riya").
 */
export function JoinMeetButton({ link, label, size = 'sm', variant = 'outline', className }) {
  if (!isHttpsUrl(link)) {
    return (
      <span className={cn('text-muted-foreground inline-flex items-center gap-1.5 text-sm whitespace-nowrap', className)}>
        <VideoOffIcon className="size-4 shrink-0" aria-hidden="true" />
        No Meet link
      </span>
    );
  }
  return (
    <Button asChild size={size} variant={variant} className={className}>
      <a href={link.trim()} target="_blank" rel="noopener noreferrer" aria-label={label}>
        <VideoIcon />
        Join Meet
      </a>
    </Button>
  );
}

/**
 * A booking's Google Meet room -- the booking's own copy of its tutor's
 * permanent link (backend bookings.booking_service), opened in a new tab -- or
 * "Meet link not configured" when the tutor has none. Only the link the API
 * returns is shown; none is ever made up. `compact` shows "Open Meet" instead
 * of the address, for tables; `label` names the link for screen readers.
 */
export function MeetLink({ link, compact = false, label }) {
  if (!link) {
    return <span className="text-muted-foreground">{compact ? 'Not configured' : NOT_CONFIGURED}</span>;
  }
  return (
    <a
      href={link}
      target="_blank"
      rel="noopener noreferrer"
      aria-label={label}
      className="text-link inline-flex items-center gap-1 font-medium break-all underline-offset-4 hover:underline"
    >
      {compact ? 'Open Meet' : link.replace(/^https:\/\//, '')}
      <ExternalLinkIcon className="size-3.5 shrink-0" aria-hidden="true" />
    </a>
  );
}
