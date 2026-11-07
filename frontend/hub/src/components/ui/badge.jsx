import { Slot } from 'radix-ui';
import { cva } from 'class-variance-authority';

import { cn } from '@/lib/utils';

const badgeVariants = cva(
  'inline-flex w-fit shrink-0 items-center justify-center gap-1 overflow-hidden rounded-full border border-transparent px-2 py-0.5 text-xs font-medium whitespace-nowrap transition-[color,box-shadow] focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 aria-invalid:border-destructive aria-invalid:ring-destructive/20 dark:aria-invalid:ring-destructive/40 [&>svg]:pointer-events-none [&>svg]:size-3',
  {
    variants: {
      variant: {
        default: 'bg-primary text-primary-foreground [a&]:hover:bg-primary/90',
        secondary: 'bg-secondary text-secondary-foreground [a&]:hover:bg-secondary/90',
        destructive:
          'bg-destructive text-white focus-visible:ring-destructive/20 dark:bg-destructive/60 dark:focus-visible:ring-destructive/40 [a&]:hover:bg-destructive/90',
        outline: 'border-border text-foreground [a&]:hover:bg-accent [a&]:hover:text-accent-foreground',
        ghost: '[a&]:hover:bg-accent [a&]:hover:text-accent-foreground',
        link: 'text-link underline-offset-4 [a&]:hover:underline',
        success: 'bg-success/10 text-success dark:bg-success/15 [a&]:hover:bg-success/15',
        warning: 'bg-warning/10 text-warning dark:bg-warning/15 [a&]:hover:bg-warning/15',
        info: 'bg-info/10 text-info dark:bg-info/15 [a&]:hover:bg-info/15',
        // Each booking type's colour (index.css): the info and warning colours on the
        // current design, the brand blue and Diagnostic green on the refreshed one.
        demo: 'bg-demo/10 text-demo-text dark:bg-demo/15 [a&]:hover:bg-demo/15',
        diagnostic: 'bg-diagnostic/10 text-diagnostic-text dark:bg-diagnostic/15 [a&]:hover:bg-diagnostic/15',
        // The logo's yellow, for a note that should stand out ("Coming Soon").
        highlight: 'bg-highlight text-highlight-foreground [a&]:hover:bg-highlight/90',
      },
    },
    defaultVariants: {
      variant: 'default',
    },
  }
);

function Badge({ className, variant = 'default', asChild = false, ...props }) {
  const Comp = asChild ? Slot.Root : 'span';

  return (
    <Comp data-slot="badge" data-variant={variant} className={cn(badgeVariants({ variant }), className)} {...props} />
  );
}

export { Badge, badgeVariants };
