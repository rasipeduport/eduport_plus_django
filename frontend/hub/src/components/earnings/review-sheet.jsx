import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';

import api from '@/lib/api';
import { EARNINGS_API, classSubject, classTypeLabel, dayLabel, earningsError, formatInr, reviewDetail } from '@/lib/earnings';
import { Button } from '@/components/ui/button';
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { Skeleton } from '@/components/ui/skeleton';
import { ErrorState } from '@/components/page/states';
import { KeepEarningDialog, ReverseEntryDialog } from './dialogs';

/**
 * The earnings whose class changed after it earned (GET
 * /api/earnings/review/) -- only edits outside the Hub can do that. Nothing
 * changes on its own: an administrator holding the corrections permission
 * (`canCorrect`) reverses the earning or keeps it as earned. An adjustment,
 * from the tutor's page, leaves it here.
 */
export function ReviewSheet({ open, onOpenChange, canCorrect, onChanged }) {
  const [items, setItems] = useState(null);
  const [failure, setFailure] = useState(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [reversing, setReversing] = useState(null);
  const [keeping, setKeeping] = useState(null);

  useEffect(() => {
    if (!open) return undefined;
    let active = true;
    api
      .get(`${EARNINGS_API}/review/`)
      .then((response) => {
        if (!active) return;
        setItems(response.data.items);
        setFailure(null);
      })
      .catch((err) => {
        if (active) setFailure(earningsError(err, 'Could not load what needs review.'));
      });
    return () => {
      active = false;
    };
  }, [open, reloadKey]);

  let body;
  if (failure && !items) body = <ErrorState message={failure.message} onRetry={() => setReloadKey((key) => key + 1)} />;
  else if (!items) body = <Skeleton className="h-40 w-full rounded-xl" />;
  else if (!items.length) body = <p className="text-muted-foreground text-sm">Nothing needs review.</p>;
  else {
    body = (
      <ul className="flex flex-col gap-3">
        {items.map((item) => {
          const entry = item.entry;
          return (
            <li key={entry.id} className="border-warning/40 bg-warning/5 grid gap-2 rounded-lg border p-3 text-sm">
              <p className="font-medium">
                <Link to={`/tutor-earnings/${item.tutor.id}`} className="underline-offset-4 hover:underline">
                  {item.tutor.name}
                </Link>{' '}
                · {classTypeLabel(entry.class_type, { singular: true })} · {classSubject(entry)} · {dayLabel(entry.class_start)}
              </p>
              <p>
                Earned <strong>{formatInr(entry.amount)}</strong>. {reviewDetail(item)}
              </p>
              {canCorrect ? (
                <div className="flex flex-wrap gap-2">
                  <Button size="sm" variant="outline" onClick={() => setReversing({ entry, tutor: item.tutor })}>
                    Reverse earning…
                  </Button>
                  <Button size="sm" variant="outline" onClick={() => setKeeping(item)}>
                    Keep as earned…
                  </Button>
                  <Button size="sm" variant="ghost" asChild>
                    <Link to={`/tutor-earnings/${item.tutor.id}`}>Open tutor to adjust</Link>
                  </Button>
                </div>
              ) : null}
            </li>
          );
        })}
      </ul>
    );
  }

  return (
    <>
      <Sheet open={open} onOpenChange={onOpenChange}>
        <SheetContent className="w-full overflow-y-auto sm:max-w-lg">
          <SheetHeader>
            <SheetTitle>Needs review</SheetTitle>
            <SheetDescription>
              Earnings whose class changed after it earned. The sync never changes an earning: reverse it or keep it as
              earned, with a reason. An adjustment alone leaves it here.
            </SheetDescription>
          </SheetHeader>
          <div className="px-4 pb-6">{body}</div>
        </SheetContent>
      </Sheet>
      <ReverseEntryDialog
        entry={reversing?.entry ?? null}
        tutorName={reversing?.tutor?.name}
        open={Boolean(reversing)}
        onOpenChange={(next) => !next && setReversing(null)}
        onSaved={() => {
          setReloadKey((key) => key + 1);
          onChanged?.();
        }}
      />
      <KeepEarningDialog
        item={keeping}
        tutorName={keeping?.tutor?.name}
        open={Boolean(keeping)}
        onOpenChange={(next) => !next && setKeeping(null)}
        onSaved={() => {
          setReloadKey((key) => key + 1);
          onChanged?.();
        }}
        onStale={() => {
          setReloadKey((key) => key + 1);
          onChanged?.();
        }}
      />
    </>
  );
}
