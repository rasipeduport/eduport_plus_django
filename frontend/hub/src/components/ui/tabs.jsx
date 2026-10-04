import { Tabs as TabsPrimitive } from 'radix-ui';

import { cn } from '@/lib/utils';

/**
 * Underlined tab bar.
 *
 * The look is the Hub's existing in-page switcher (students/section-tabs.jsx,
 * the /homework status tabs); Radix is underneath it so the bar also behaves
 * like a tab list — arrow-key navigation, roving focus and the right ARIA
 * roles, which the hand-rolled button rows never had.
 */
function Tabs({ className, ...props }) {
  return <TabsPrimitive.Root data-slot="tabs" className={cn('flex flex-col gap-6', className)} {...props} />;
}

function TabsList({ className, ...props }) {
  return (
    <TabsPrimitive.List
      data-slot="tabs-list"
      className={cn('-mb-px flex min-w-0 gap-1 overflow-x-auto border-b', className)}
      {...props}
    />
  );
}

function TabsTrigger({ className, ...props }) {
  return (
    <TabsPrimitive.Trigger
      data-slot="tabs-trigger"
      className={cn(
        'text-muted-foreground hover:text-foreground focus-visible:ring-ring/50 data-[state=active]:border-foreground data-[state=active]:text-foreground inline-flex shrink-0 cursor-pointer items-center gap-2 border-b-2 border-transparent px-3 py-2 text-sm font-medium whitespace-nowrap transition-colors focus-visible:ring-[3px] focus-visible:outline-none disabled:pointer-events-none disabled:opacity-50',
        className
      )}
      {...props}
    />
  );
}

/** A count chip for a trigger: muted, and quiet when it is zero. */
function TabsCount({ value, className }) {
  if (value == null) return null;
  return (
    <span className={cn('text-muted-foreground text-xs tabular-nums', value === 0 && 'opacity-60', className)}>
      {value}
    </span>
  );
}

function TabsContent({ className, ...props }) {
  return (
    <TabsPrimitive.Content
      data-slot="tabs-content"
      className={cn('focus-visible:outline-none', className)}
      {...props}
    />
  );
}

export { Tabs, TabsList, TabsTrigger, TabsCount, TabsContent };
