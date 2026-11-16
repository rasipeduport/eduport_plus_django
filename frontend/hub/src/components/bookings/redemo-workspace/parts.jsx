import { Card } from '@/components/ui/card';
import { cn } from '@/lib/utils';

/**
 * One card of the Re-Demo workspace (pages/RedemoWorkspacePage): an icon and
 * a title, an action on the right of the title, then its content -- the
 * workspace's own spacious take on the Hub's Panel.
 */
export function WorkspaceCard({ icon: Icon, title, action, className, children }) {
  return (
    <Card className={cn('min-w-0 gap-3 px-5 py-5', className)}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="flex min-w-0 items-center gap-2.5 text-base font-semibold">
          {Icon ? <Icon className="text-muted-foreground size-5 shrink-0" aria-hidden="true" /> : null}
          <span className="truncate">{title}</span>
        </h2>
        {action}
      </div>
      {children}
    </Card>
  );
}

/** A label and its value on one line, as the workspace's detail lists read; a dash when there is none. */
export function Field({ label, children, className }) {
  return (
    <div className={cn('grid grid-cols-[8.5rem_minmax(0,1fr)] items-start gap-3 py-2.5 text-sm', className)}>
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="min-w-0 font-medium break-words">{children || <span className="text-muted-foreground">—</span>}</dd>
    </div>
  );
}

/** A list of Fields, ruled between them. */
export function Fields({ children }) {
  return <dl className="divide-y">{children}</dl>;
}
