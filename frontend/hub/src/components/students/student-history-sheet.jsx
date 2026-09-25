import { useEffect, useState } from 'react';

import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { ActivityList } from '@/components/activity/activity-list';
import api from '@/lib/api';

export function StudentHistorySheet({ studentId, studentName, open, onOpenChange }) {
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!open) return undefined;
    let active = true;

    (async () => {
      try {
        const res = await api.get('/api/activity/', { params: { student_id: studentId, page_size: 200 } });
        if (!active) return;
        setError(null);
        setRows(res.data.results ?? []);
      } catch {
        if (!active) return;
        setError('Failed to load history.');
      }
    })();

    return () => {
      active = false;
    };
  }, [open, studentId]);

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full sm:max-w-lg">
        <SheetHeader>
          <SheetTitle>Activity history</SheetTitle>
          <SheetDescription>
            {studentName ? `Changes to ${studentName} and their sessions` : 'Changes to this student and their sessions'}
          </SheetDescription>
        </SheetHeader>
        <div className="min-h-0 flex-1 overflow-y-auto px-4 pb-4">
          {error ? (
            <p className="text-destructive text-sm">{error}</p>
          ) : rows === null ? (
            <p className="text-muted-foreground text-sm">Loading…</p>
          ) : (
            <ActivityList rows={rows} emptyMessage="No activity recorded yet." />
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}
