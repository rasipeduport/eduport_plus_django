import { Skeleton } from '@/components/ui/skeleton';

/**
 * Loading placeholder shaped like the Hub's DataTable: a filter/actions
 * toolbar above a bordered table with a header row and body rows.
 */
export function TableSkeleton({ rows = 8, columns = 5 }) {
  const cols = Array.from({ length: columns }, (_, i) => i);
  const bodyRows = Array.from({ length: rows }, (_, i) => i);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between gap-2">
        <Skeleton className="h-9 w-full max-w-xs" />
        <Skeleton className="h-9 w-28" />
      </div>
      <div className="overflow-hidden rounded-md border">
        <div className="bg-muted/50 flex items-center gap-4 border-b px-4 py-3">
          {cols.map((c) => (
            <Skeleton key={c} className="h-4 flex-1" />
          ))}
        </div>
        {bodyRows.map((r) => (
          <div key={r} className="flex items-center gap-4 border-b px-4 py-3 last:border-b-0">
            {cols.map((c) => (
              <Skeleton key={c} className="h-4 flex-1" />
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}
