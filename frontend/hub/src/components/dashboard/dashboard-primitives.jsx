import { useLayoutEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { cn } from '@/lib/utils';

/**
 * A dashboard panel: the student profile's FieldCard shape (gap-4 py-4, px-4
 * header and body, text-sm title) with an icon, an optional subtitle and a
 * "View all" style link on the right.
 */
export function Panel({ icon: Icon, title, subtitle, action, actionTo, className, children }) {
  return (
    <Card className={cn('h-full min-w-0 gap-4 py-4', className)}>
      <CardHeader className="px-4">
        <div className="flex min-w-0 items-center gap-2">
          {Icon ? (
            <span className="bg-muted text-muted-foreground flex size-7 shrink-0 items-center justify-center rounded-md">
              <Icon className="size-4" />
            </span>
          ) : null}
          <div className="min-w-0">
            <CardTitle className="truncate text-sm">{title}</CardTitle>
            {subtitle ? <p className="text-muted-foreground mt-0.5 truncate text-xs">{subtitle}</p> : null}
          </div>
        </div>
        {action || actionTo ? (
          <div className="col-start-2 row-span-2 row-start-1 justify-self-end">
            {action ??
              (actionTo ? (
                <Button variant="outline" size="sm" asChild>
                  <Link to={actionTo}>View all</Link>
                </Button>
              ) : null)}
          </div>
        ) : null}
      </CardHeader>
      <CardContent className="flex min-h-0 flex-1 flex-col px-4">{children}</CardContent>
    </Card>
  );
}

/** Compact empty state for inside a panel (the profile's EmptyState, scaled down). */
export function PanelEmpty({ icon: Icon, message, hint }) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center rounded-lg border border-dashed px-4 py-8 text-center">
      {Icon ? <Icon className="text-muted-foreground mx-auto mb-2 size-5" /> : null}
      <p className="text-muted-foreground text-sm">{message}</p>
      {hint ? <p className="text-muted-foreground/80 mt-1 text-xs">{hint}</p> : null}
    </div>
  );
}

/**
 * A list that shows at most `maxRows` rows and scrolls inside the card for the
 * rest, so a long list never makes the dashboard taller. The cap is measured
 * from the rendered rows (not a fixed pixel height), so a row that wraps onto
 * two lines on a phone is still shown whole. `total` is how many rows the list
 * holds; the hint under it tells the reader there is more to scroll to.
 */
export function ScrollList({ maxRows = 5, total, className, children }) {
  const ref = useRef(null);
  const [maxHeight, setMaxHeight] = useState(null);
  const overflowing = total > maxRows;

  useLayoutEffect(() => {
    const list = ref.current;
    if (!list || !overflowing) {
      setMaxHeight(null);
      return undefined;
    }
    const measure = () => {
      const rows = Array.from(list.children).slice(0, maxRows);
      if (rows.length === 0) return;
      const first = rows[0].getBoundingClientRect();
      const last = rows[rows.length - 1].getBoundingClientRect();
      setMaxHeight(Math.ceil(last.bottom - first.top));
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(list);
    return () => observer.disconnect();
  }, [overflowing, maxRows, total]);

  return (
    <div className="flex min-h-0 flex-col">
      <ul
        ref={ref}
        className={cn('min-h-0', overflowing && 'overflow-y-auto overscroll-contain pr-1', className)}
        style={maxHeight != null ? { maxHeight } : undefined}
      >
        {children}
      </ul>
      {overflowing ? (
        <p className="text-muted-foreground mt-2 text-center text-xs">
          Showing {maxRows} of {total} · scroll for more
        </p>
      ) : null}
    </div>
  );
}

/** A tinted icon square, the accent the KPI tiles and list rows share. */
export function ToneIcon({ icon: Icon, tone = 'default', className }) {
  return (
    <span
      className={cn(
        'flex size-10 shrink-0 items-center justify-center rounded-lg',
        tone === 'default' && 'bg-muted text-foreground',
        tone === 'info' && 'bg-info/10 text-info',
        tone === 'success' && 'bg-success/10 text-success',
        tone === 'warning' && 'bg-warning/10 text-warning',
        tone === 'destructive' && 'bg-destructive/10 text-destructive',
        className
      )}
    >
      <Icon className="size-5" />
    </span>
  );
}
