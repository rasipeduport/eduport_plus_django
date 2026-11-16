import { useState } from 'react';
import { DownloadIcon, Loader2Icon } from 'lucide-react';

import api from '@/lib/api';
import { Button } from '@/components/ui/button';
import { filenameFromDisposition, reportPdfError } from '@/lib/reports';

/** Save ``blob`` as ``name``: a link to an object URL, clicked once, then freed. */
function saveBlob(blob, name) {
  const href = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = href;
  link.download = name;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(href), 1000);
}

/**
 * Downloads a report PDF (P7) from ``url`` -- the tutor's or the Admin's
 * route, as last saved or at one version (lib/reports reportPdfUrl) -- with
 * the signed-in session, and saves it under the name the server gives it
 * (``fallbackName`` when the header cannot be read). A refusal is said under
 * the button: signed out, no access, no such version, or too many downloads.
 * A second click while one runs does nothing. ``label`` names the button for
 * assistive technology when several sit together ("PDF of version 2").
 */
export function PdfDownloadButton({
  url,
  fallbackName = 'report.pdf',
  children = 'Download PDF',
  label,
  variant = 'outline',
  size = 'sm',
  className,
}) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');

  const download = async () => {
    if (pending) return;
    setPending(true);
    setError('');
    try {
      const response = await api.get(url, { responseType: 'blob' });
      saveBlob(response.data, filenameFromDisposition(response.headers?.['content-disposition']) || fallbackName);
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
        onClick={download}
        disabled={pending}
        aria-busy={pending || undefined}
        aria-label={pending ? undefined : label}
      >
        {pending ? <Loader2Icon className="size-4 animate-spin" /> : <DownloadIcon className="size-4" />}
        {pending ? 'Downloading…' : children}
      </Button>
      {error ? (
        <p role="alert" className="text-destructive text-xs">
          {error}
        </p>
      ) : null}
    </div>
  );
}
