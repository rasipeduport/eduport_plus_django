import { ExternalLinkIcon } from 'lucide-react';

const NOT_CONFIGURED = 'Meet link not configured';

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
      className="text-primary inline-flex items-center gap-1 font-medium break-all underline-offset-4 hover:underline"
    >
      {compact ? 'Open Meet' : link.replace(/^https:\/\//, '')}
      <ExternalLinkIcon className="size-3.5 shrink-0" aria-hidden="true" />
    </a>
  );
}
