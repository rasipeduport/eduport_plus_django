import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { cn } from '@/lib/utils';

/** Em dash for an empty value, so a sparse card still reads as a table. */
export const EMPTY = '—';

export function StudentStatusBadge({ status, note, className }) {
  const key = (status || 'active').toLowerCase();
  const variant = key === 'active' ? 'success' : key === 'inactive' ? 'warning' : 'secondary';
  const label = key.charAt(0).toUpperCase() + key.slice(1);
  const badge = (
    <Badge variant={variant} className={className}>
      {label}
    </Badge>
  );
  // Inactive and expired students carry the reason they were set that way.
  if (key !== 'active' && note) {
    return (
      <Tooltip>
        <TooltipTrigger asChild>
          <span className="cursor-help">{badge}</span>
        </TooltipTrigger>
        <TooltipContent>
          <p className="max-w-xs">{note}</p>
        </TooltipContent>
      </Tooltip>
    );
  }
  return badge;
}

/**
 * One headline number. Deliberately plain: the Overview is a summary, not a
 * dashboard, so a tile is a number, a label and at most one line of context.
 */
export function StatTile({ label, value, hint, tone = 'default' }) {
  return (
    <div className="bg-card rounded-xl border p-4">
      <p className="text-muted-foreground text-xs font-medium">{label}</p>
      <p
        className={cn(
          'mt-1 text-2xl font-semibold tabular-nums',
          tone === 'warning' && 'text-warning',
          tone === 'destructive' && 'text-destructive'
        )}
      >
        {value}
      </p>
      {hint ? <p className="text-muted-foreground mt-0.5 text-xs text-pretty">{hint}</p> : null}
    </div>
  );
}

/**
 * A labelled card holding a definition list. `fields` entries are
 * `{ label, value, mono, full, hidden }`; a hidden entry is dropped entirely
 * (the caller's role cannot see it) rather than shown as empty.
 */
export function FieldCard({ title, action, fields, children, className }) {
  const visible = fields?.filter((field) => !field.hidden) ?? [];
  return (
    <Card className={cn('gap-4 py-4', className)}>
      <CardHeader className="px-4">
        <CardTitle className="text-sm">{title}</CardTitle>
        {action ? <div className="col-start-2 row-span-2 row-start-1 justify-self-end">{action}</div> : null}
      </CardHeader>
      <CardContent className="px-4">
        {visible.length > 0 ? (
          <dl className="grid grid-cols-1 gap-x-6 gap-y-3 sm:grid-cols-2">
            {visible.map((field) => (
              <div key={field.label} className={cn('min-w-0', field.full && 'sm:col-span-2')}>
                <dt className="text-muted-foreground text-xs">{field.label}</dt>
                <dd className={cn('mt-0.5 truncate text-sm', field.mono && 'font-mono')} title={field.title}>
                  {field.value || EMPTY}
                </dd>
              </div>
            ))}
          </dl>
        ) : null}
        {children}
      </CardContent>
    </Card>
  );
}

/** A section heading inside a tab panel. */
export function SectionHeading({ title, description, action }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-2">
      <div>
        <h2 className="text-sm font-semibold">{title}</h2>
        {description ? <p className="text-muted-foreground mt-0.5 text-xs">{description}</p> : null}
      </div>
      {action}
    </div>
  );
}

/** Shared empty state for a tab panel or a table. */
export function EmptyState({ icon: Icon, message, hint }) {
  return (
    <div className="rounded-xl border px-6 py-12 text-center">
      {Icon ? <Icon className="text-muted-foreground mx-auto mb-3 size-6" /> : null}
      <p className="text-muted-foreground text-sm">{message}</p>
      {hint ? <p className="text-muted-foreground/80 mt-1 text-xs">{hint}</p> : null}
    </div>
  );
}

export function TabSkeleton({ rows = 5 }) {
  return (
    <div className="flex flex-col gap-2">
      {Array.from({ length: rows }, (_, index) => (
        <Skeleton key={index} className="h-12 w-full" />
      ))}
    </div>
  );
}

/**
 * A plain bordered table for the profile's tab panels. The students list uses
 * the TanStack DataTable for its filtering and column controls; a profile tab
 * is already one student's short, pre-filtered list, so it gets the same
 * visual table without the toolbar.
 */
export function ProfileTable({ columns, rows, renderRow, keyOf, emptyMessage }) {
  return (
    <div className="overflow-x-auto rounded-md border">
      <table className="w-full border-collapse text-left text-sm">
        <thead>
          <tr className="bg-muted/50 border-b">
            {columns.map((column) => (
              <th
                key={column.key}
                className={cn(
                  'text-muted-foreground h-10 px-3 align-middle text-xs font-medium whitespace-nowrap',
                  column.className
                )}
              >
                {column.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td colSpan={columns.length} className="text-muted-foreground h-24 px-3 text-center">
                {emptyMessage}
              </td>
            </tr>
          ) : (
            rows.map((row) => (
              <tr key={keyOf(row)} className="hover:bg-muted/40 border-b transition-colors last:border-0">
                {renderRow(row)}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}

/** A body cell for ProfileTable, so every tab pads its rows the same way. */
export function Td({ className, children, ...props }) {
  return (
    <td className={cn('px-3 py-2.5 align-middle', className)} {...props}>
      {children}
    </td>
  );
}
