import { RefreshCwIcon } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

/**
 * Every page's Refresh: the page's own read again, on request. While that read
 * is under way (`pending`) the icon turns and the button is disabled, so a
 * second click never sends a second read; it is enabled again once the read is
 * done, answered or failed. Each page keeps its own look (`variant`, `size`,
 * `iconOnly`) and its own reading -- this only draws the button.
 */
export function RefreshButton({
  onClick,
  pending = false,
  disabled = false,
  label = 'Refresh',
  ariaLabel,
  iconOnly = false,
  variant = 'outline',
  size = 'sm',
  className,
}) {
  return (
    <Button
      type="button"
      variant={variant}
      size={iconOnly ? 'icon' : size}
      onClick={onClick}
      disabled={pending || disabled}
      aria-busy={pending || undefined}
      aria-label={ariaLabel ?? (iconOnly ? label : undefined)}
      title={iconOnly ? label : undefined}
      className={className}
    >
      <RefreshCwIcon className={cn(pending && 'animate-spin')} aria-hidden="true" />
      {iconOnly ? null : label}
    </Button>
  );
}
