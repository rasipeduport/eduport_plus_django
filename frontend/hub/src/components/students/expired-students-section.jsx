import { useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';

import { DataTable } from '@/components/data-table';

export function ExpiredStudentsSection({ columns, data }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="mt-8">
      <button
        onClick={() => setExpanded((value) => !value)}
        className="text-muted-foreground hover:bg-muted hover:text-foreground flex items-center gap-2 rounded-md px-2 py-1.5 text-sm font-medium transition-colors"
      >
        {expanded ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
        Expired Students ({data.length})
      </button>

      {expanded && (
        <div className="mt-3">
          <DataTable
            columns={columns}
            data={data}
            filterColumn="full_name"
            filterPlaceholder="Filter by name…"
            emptyMessage="No expired students."
            initialSorting={[{ id: 'student_code', desc: false }]}
            initialColumnPinning={{ right: ['actions'] }}
          />
        </div>
      )}
    </div>
  );
}
