import { useEffect, useState } from 'react';
import { EyeIcon, Loader2Icon } from 'lucide-react';

import api from '@/lib/api';
import { Button } from '@/components/ui/button';
import { reportPdfError } from '@/lib/reports';
import { ReportPreviewDialog } from './report-preview-dialog';

/**
 * Opens a report's PDF inside the page (ReportPreviewDialog): the very file
 * PdfDownloadButton saves from the same ``url`` -- the tutor's or the Admin's
 * route, as last saved or at one version (lib/reports reportPdfUrl), drawn by
 * the server's own renderer -- read with the signed-in session and held in
 * memory as an object URL until the dialog closes. ``title`` and
 * ``description`` head the dialog. A refusal is said under the button, as a
 * download's is (the downloads' rate limit counts each view too).
 */
export function ViewPdfButton({
  url,
  title,
  description,
  children = 'View PDF',
  label,
  variant = 'outline',
  size = 'sm',
  className,
}) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [objectUrl, setObjectUrl] = useState(null);

  // The PDF is freed when the dialog closes, and if the page goes first.
  useEffect(
    () => () => {
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    },
    [objectUrl]
  );

  const view = async () => {
    if (pending) return;
    setPending(true);
    setError('');
    try {
      const response = await api.get(url, { responseType: 'blob' });
      setObjectUrl(URL.createObjectURL(new Blob([response.data], { type: 'application/pdf' })));
    } catch (err) {
      setError(await reportPdfError(err));
    } finally {
      setPending(false);
    }
  };

  return (
    <div className="flex flex-col items-start gap-1">
      <Button
        type="button"
        variant={variant}
        size={size}
        className={className}
        onClick={view}
        disabled={pending}
        aria-busy={pending || undefined}
        aria-label={pending ? undefined : label}
      >
        {pending ? <Loader2Icon className="size-4 animate-spin" /> : <EyeIcon className="size-4" />}
        {pending ? 'Opening…' : children}
      </Button>
      {error ? (
        <p role="alert" className="text-destructive text-xs">
          {error}
        </p>
      ) : null}
      <ReportPreviewDialog
        url={objectUrl}
        title={title}
        description={description}
        onOpenChange={(open) => {
          if (!open) setObjectUrl(null);
        }}
      />
    </div>
  );
}
