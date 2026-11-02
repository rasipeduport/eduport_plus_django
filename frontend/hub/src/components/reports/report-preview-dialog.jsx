import { ExternalLinkIcon } from 'lucide-react';

import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';

/**
 * The PDF a report would make, before it is saved (POST .../report/preview/,
 * drawn by the same renderer as every saved version). ``url`` is an object
 * URL of the PDF, held in memory only; the caller frees it when this closes.
 * Some phones do not show a PDF inside a page, so it also opens in a tab.
 */
export function ReportPreviewDialog({ url, onOpenChange }) {
  return (
    <Dialog open={Boolean(url)} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[calc(100dvh-2rem)] flex-col sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>Report preview</DialogTitle>
          <DialogDescription>This is how the report will print. Nothing has been saved.</DialogDescription>
        </DialogHeader>
        {url ? (
          <iframe title="Report preview" src={url} className="h-[70dvh] w-full rounded-md border bg-white" />
        ) : null}
        <DialogFooter>
          {url ? (
            <Button asChild variant="outline">
              <a href={url} target="_blank" rel="noopener noreferrer">
                <ExternalLinkIcon className="size-4" />
                Open in a new tab
              </a>
            </Button>
          ) : null}
          <Button type="button" onClick={() => onOpenChange(false)}>
            Close
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
