import { cn } from '@/lib/utils';

/**
 * The building blocks every page of the refreshed design shares: the page's
 * frame (Page), its heading row (PageHeader) and the state a page shows when
 * it has nothing to list yet (EmptyState). They hold no data of their own.
 */

/** A page's frame under the Hub's fixed header: centred, padded, its sections evenly spaced. */
export function Page({ className, children }) {
  return <div className={cn('container mx-auto flex flex-col gap-6 px-4 pt-20 pb-12 sm:px-6', className)}>{children}</div>;
}

/**
 * The page's title and what it is for, with its main actions on the right
 * (below it on a phone); `actionsClassName` adds to the actions' row.
 */
export function PageHeader({ title, description, actions, className, actionsClassName }) {
  return (
    <div className={cn('flex flex-wrap items-start justify-between gap-x-6 gap-y-3', className)}>
      <div className="min-w-0 max-w-3xl">
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {description ? <p className="text-muted-foreground mt-1 text-sm">{description}</p> : null}
      </div>
      {actions ? <div className={cn('flex flex-wrap items-start gap-2 sm:justify-end', actionsClassName)}>{actions}</div> : null}
    </div>
  );
}

/** A page-sized empty state: an icon, what is (not) here, and what to do instead. */
export function EmptyState({ icon: Icon, title, description, action, className }) {
  return (
    <div
      className={cn('bg-card flex flex-col items-center rounded-xl border border-dashed px-6 py-14 text-center', className)}
    >
      {Icon ? (
        <span className="bg-muted text-muted-foreground mb-4 flex size-12 items-center justify-center rounded-full">
          <Icon className="size-6" aria-hidden="true" />
        </span>
      ) : null}
      <p className="font-medium">{title}</p>
      {description ? <p className="text-muted-foreground mt-1 max-w-md text-sm text-pretty">{description}</p> : null}
      {action ? <div className="mt-5">{action}</div> : null}
    </div>
  );
}
