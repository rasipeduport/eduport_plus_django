import { cn } from '@/lib/utils';

/**
 * Error block for the scheduling forms. `error` is either a plain string or
 * the object `describeApiError` returns; a scheduling conflict then shows a
 * heading (Tutor unavailable / Session conflict), the API's explanation, and
 * the blocking session's time so the mentor knows what to change.
 *
 * `legacy` keeps the SessionsPage's hardcoded dark palette (that page is not
 * on the design system yet); the default uses design tokens for the sheet.
 */
export function SchedulingError({ error, legacy = false, className }) {
  if (!error) return null;
  const { title, message, conflict } = typeof error === 'string' ? { message: error } : error;

  return (
    <div
      role="alert"
      className={cn(
        'm-0 rounded border p-2 text-xs',
        legacy
          ? 'border-red-900/50 bg-red-950/40 text-red-400'
          : 'border-destructive/30 bg-destructive/10 text-destructive sm:text-sm',
        className
      )}
    >
      {title && <p className="m-0 font-semibold">{title}</p>}
      <p className={cn('m-0', title && 'mt-1')}>{message}</p>
      {conflict && (
        <p className={cn('m-0 mt-1 opacity-80', legacy ? 'text-red-300' : null)}>
          {conflict.title ? `“${conflict.title}”` : 'Existing session'}
          {conflict.who ? ` · ${conflict.who}` : ''}
          {` · ${conflict.when}`}
        </p>
      )}
    </div>
  );
}
