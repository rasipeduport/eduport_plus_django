import { AlertCircleIcon, CheckCircle2Icon, ShieldAlertIcon, XIcon } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

/**
 * What a page shows instead of, or above, its content: a load that failed
 * (ErrorState, with Try again), a page the account may not use
 * (AccessDeniedState), and the outcome of an action (Notice).
 */

/** A load that failed: the message, and Try again (`onRetry`) unless retrying cannot help. */
export function ErrorState({ message, onRetry, pending = false, className }) {
  return (
    <div
      role="alert"
      className={cn(
        'border-destructive/30 bg-destructive/5 flex flex-wrap items-center gap-3 rounded-xl border px-4 py-3',
        className
      )}
    >
      <AlertCircleIcon className="text-destructive size-4 shrink-0" aria-hidden="true" />
      <p className="min-w-0 flex-1 text-sm">{message}</p>
      {onRetry ? (
        <Button variant="outline" size="sm" onClick={onRetry} disabled={pending}>
          Try again
        </Button>
      ) : null}
    </div>
  );
}

/** A page the account may not use: why, as the API put it. */
export function AccessDeniedState({ title, message, className }) {
  return (
    <div className={cn('bg-card flex flex-col items-center gap-2 rounded-xl border px-6 py-12 text-center', className)}>
      <ShieldAlertIcon className="text-muted-foreground size-8" aria-hidden="true" />
      <p className="font-medium">{title}</p>
      {message ? <p className="text-muted-foreground max-w-md text-sm">{message}</p> : null}
    </div>
  );
}

/** The outcome of an action, announced to screen readers, with a way to dismiss it (`onDismiss`). */
export function Notice({ children, onDismiss, className }) {
  return (
    <div
      role="status"
      className={cn('bg-success/10 text-success flex items-start gap-2 rounded-xl px-3 py-2 text-sm', className)}
    >
      <CheckCircle2Icon className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
      <div className="min-w-0 flex-1">{children}</div>
      {onDismiss ? (
        <button type="button" onClick={onDismiss} className="shrink-0" aria-label="Dismiss">
          <XIcon className="size-4" />
        </button>
      ) : null}
    </div>
  );
}
