import { ChevronLeftIcon, ChevronRightIcon } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

const GAP = 'gap';

/**
 * The page numbers to offer around `page` of `pages`: every page when there
 * are few, else the first, the last and the current one's neighbours, with a
 * gap marker wherever two or more pages are skipped -- e.g. 1 … 5 6 7 … 12
 * (a single skipped page is shown instead: 1 2 3 4 … 12).
 */
function pageItems(page, pages) {
  if (pages <= 7) return Array.from({ length: pages }, (_, i) => i + 1);
  const shown = new Set([1, pages, page - 1, page, page + 1].filter((n) => n >= 1 && n <= pages));
  if (page <= 3) [2, 3, 4].forEach((n) => shown.add(n));
  if (page >= pages - 2) [pages - 3, pages - 2, pages - 1].forEach((n) => shown.add(n));
  const sorted = [...shown].sort((a, b) => a - b);
  return sorted.flatMap((n, i) => {
    const skipped = i > 0 ? n - sorted[i - 1] - 1 : 0;
    if (skipped === 1) return [n - 1, n];
    return skipped > 1 ? [GAP, n] : [n];
  });
}

/**
 * Paging for a list the API pages (pages count from 1): which rows are shown
 * of how many, Previous and Next, and the page numbers from a small screen up
 * ("Page 2 of 6" on a phone). `onPageChange(page)` moves; `pending` holds the
 * controls while a page loads.
 */
export function Pagination({ page, pageSize, total, onPageChange, pending = false, className }) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const first = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const last = Math.min(page * pageSize, total);

  return (
    <nav aria-label="Pagination" className={cn('flex flex-wrap items-center justify-between gap-x-4 gap-y-2', className)}>
      <p role="status" className="text-muted-foreground text-sm whitespace-nowrap">
        {total === 0 ? 'No results' : first > last ? `Nothing on this page · ${total} in all` : `Showing ${first}–${last} of ${total}`}
      </p>
      <div className="flex items-center gap-1">
        <Button variant="outline" size="sm" disabled={page <= 1 || pending} onClick={() => onPageChange(page - 1)}>
          <ChevronLeftIcon />
          Previous
        </Button>
        <span className="px-2 text-sm whitespace-nowrap sm:hidden">
          Page {page} of {pages}
        </span>
        <ol className="hidden items-center gap-1 sm:flex">
          {pageItems(page, pages).map((item, index) =>
            item === GAP ? (
              <li key={`gap-${index}`} aria-hidden="true" className="text-muted-foreground px-1 text-sm">
                …
              </li>
            ) : (
              <li key={item}>
                <Button
                  variant={item === page ? 'secondary' : 'ghost'}
                  size="icon-sm"
                  aria-label={`Page ${item}`}
                  aria-current={item === page ? 'page' : undefined}
                  disabled={pending}
                  onClick={() => {
                    if (item !== page) onPageChange(item);
                  }}
                  className="tabular-nums"
                >
                  {item}
                </Button>
              </li>
            )
          )}
        </ol>
        <Button variant="outline" size="sm" disabled={page >= pages || pending} onClick={() => onPageChange(page + 1)}>
          Next
          <ChevronRightIcon />
        </Button>
      </div>
    </nav>
  );
}
