import { useEffect, useLayoutEffect, useRef, useState } from 'react';

import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { useIsMobile } from '@/hooks/use-mobile';
import { cn } from '@/lib/utils';

/**
 * Whether the element in `ref` is laid out narrower than `minWidth` pixels --
 * false until it is measured, and always when there is no `minWidth` or the
 * browser lays nothing out (a width of 0, as in tests).
 */
function useNarrowerThan(ref, minWidth) {
  const [narrow, setNarrow] = useState(false);
  useLayoutEffect(() => {
    const element = ref.current;
    if (!element || !minWidth) return undefined;
    const measure = () => {
      const width = element.clientWidth;
      setNarrow(width > 0 && width < minWidth);
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [ref, minWidth]);
  return narrow;
}

/**
 * One list, two layouts: a table where it fits, and cards where a wide table
 * would scroll sideways -- on a phone, and wherever the list's own area is
 * narrower than `minTableWidth` (a tablet, or a laptop with the sidebar open).
 * Only one is rendered; the phone's is chosen from the first paint
 * (hooks/use-mobile), the narrow area's once it is measured.
 *
 * `columns` define the table: `{ key, header, cell(row), className, headerClassName }`,
 * where a header that should only be read out (an actions column) is given as
 * `{ srOnly: 'Open' }`. `renderCard(row)` draws a row's card. `pending` dims
 * the rows while the next page loads. The row whose key is `highlightedKey`
 * (e.g. the booking a link was opened for) is marked in the highlight colour
 * and scrolled into view. The page shows its own empty state when there are
 * no rows; `label` names the list for screen readers.
 */
export function ResponsiveList({
  columns,
  rows,
  rowKey = (row) => row.id,
  renderCard,
  pending = false,
  label,
  minTableWidth,
  highlightedKey,
}) {
  const isMobile = useIsMobile();
  const ref = useRef(null);
  const highlightedRef = useRef(null);
  const narrow = useNarrowerThan(ref, minTableWidth);
  const isHighlighted = (row) => highlightedKey != null && rowKey(row) === highlightedKey;

  // Bring the highlighted row into view once it is laid out, and again if the layout switches.
  useEffect(() => {
    const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches;
    highlightedRef.current?.scrollIntoView?.({ block: 'center', behavior: reduce ? 'auto' : 'smooth' });
  }, [highlightedKey, isMobile, narrow]);

  return (
    <div ref={ref} className="min-w-0">
      {isMobile || narrow ? (
        <ul
          aria-label={label}
          aria-busy={pending || undefined}
          className={cn('grid gap-3 sm:grid-cols-2', pending && 'opacity-60')}
        >
          {rows.map((row) => (
            <li
              key={rowKey(row)}
              ref={isHighlighted(row) ? highlightedRef : undefined}
              data-highlighted={isHighlighted(row) || undefined}
              className={cn(isHighlighted(row) && 'ring-highlight ring-offset-background rounded-xl ring-2 ring-offset-2')}
            >
              {renderCard(row)}
            </li>
          ))}
        </ul>
      ) : (
        <div className="overflow-hidden rounded-md border">
          <Table aria-label={label} aria-busy={pending || undefined}>
            <TableHeader>
              <TableRow>
                {columns.map((column) => (
                  <TableHead key={column.key} className={column.headerClassName}>
                    {column.header?.srOnly ? <span className="sr-only">{column.header.srOnly}</span> : column.header}
                  </TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody className={pending ? 'opacity-60' : undefined}>
              {rows.map((row) => (
                <TableRow
                  key={rowKey(row)}
                  ref={isHighlighted(row) ? highlightedRef : undefined}
                  data-highlighted={isHighlighted(row) || undefined}
                  className={cn(isHighlighted(row) && 'bg-highlight/20 hover:bg-highlight/25')}
                >
                  {columns.map((column) => (
                    <TableCell key={column.key} className={column.className}>
                      {column.cell(row)}
                    </TableCell>
                  ))}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}
