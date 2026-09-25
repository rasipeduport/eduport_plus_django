import { useState } from 'react';
import { format } from 'date-fns';
import { ChevronDown } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { actionLabel, describeActivity } from '@/lib/activity-format';
import { cn } from '@/lib/utils';
import { ChangesTable } from './changes-table';

/** A compact, expandable timeline of activity entries (e.g. one student). */
export function ActivityList({ rows, emptyMessage = 'No activity yet.' }) {
  if (rows.length === 0) {
    return <p className="text-muted-foreground text-sm">{emptyMessage}</p>;
  }
  return (
    <ol className="space-y-2">
      {rows.map((row) => (
        <ActivityListItem key={row.id} row={row} />
      ))}
    </ol>
  );
}

function ActivityListItem({ row }) {
  const [open, setOpen] = useState(false);
  const hasChanges = Object.keys(row.changes ?? {}).length > 0;

  return (
    <li className="rounded-md border">
      <button
        type="button"
        onClick={() => hasChanges && setOpen((value) => !value)}
        className={cn('flex w-full items-start gap-3 p-3 text-left', hasChanges && 'cursor-pointer')}
      >
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-medium">{row.actor_name ?? row.actor_email ?? 'Unknown'}</span>
            <Badge variant="secondary">{actionLabel(row.action)}</Badge>
          </div>
          <p className="text-muted-foreground mt-0.5 text-sm">{describeActivity(row)}</p>
        </div>
        <div className="text-muted-foreground flex items-center gap-1 text-xs whitespace-nowrap">
          {format(new Date(row.created_at), 'd MMM, h:mm a')}
          {hasChanges ? <ChevronDown className={cn('size-4 transition-transform', open && 'rotate-180')} /> : null}
        </div>
      </button>
      {open && hasChanges ? (
        <div className="border-t p-3">
          <ChangesTable changes={row.changes} />
        </div>
      ) : null}
    </li>
  );
}
