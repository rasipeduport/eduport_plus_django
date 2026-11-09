import { useEffect, useRef, useState } from 'react';

import api, { ensureCsrfToken } from '@/lib/api';
import { filenameFromDisposition } from '@/lib/reports';
import { isCsrfFailure, saveBlob, salesPdfError } from '@/lib/sales';
import { ReportPreviewDialog } from '@/components/reports/report-preview-dialog';

/**
 * A syllabus's customer PDF, fetched with the signed-in session: `preview`
 * shows it in a dialog (inline), `download` saves it under the name the
 * server gives it. `preview` takes a URL to GET, or `{ url, data }` to POST
 * (content not yet saved). `pending` names the action running ('preview' or
 * 'download'); a refusal -- no pricing yet, too many PDFs -- is `error`.
 * A POST refused only for a stale CSRF token is sent once more with a fresh
 * one (lib/api does that for JSON answers, which a PDF's is not). Render
 * `dialog` once in the page.
 */
export function useSyllabusPdf() {
  const [pending, setPending] = useState(null);
  const [error, setError] = useState('');
  const [previewUrl, setPreviewUrl] = useState(null);
  // A PDF that arrives after the page has gone is dropped, not kept in memory.
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  // The preview lives in memory only: freed when it is replaced or closed.
  useEffect(() => () => {
    if (previewUrl) URL.revokeObjectURL(previewUrl);
  }, [previewUrl]);

  const fetchPdf = async (kind, request) => {
    if (pending) return null;
    setPending(kind);
    setError('');
    const config = { responseType: 'blob', params: kind === 'preview' ? { disposition: 'inline' } : undefined };
    const send = () => (typeof request === 'string' ? api.get(request, config) : api.post(request.url, request.data, config));
    try {
      try {
        return await send();
      } catch (err) {
        if (typeof request === 'string' || !(await isCsrfFailure(err))) throw err;
        await ensureCsrfToken(true);
        return await send();
      }
    } catch (err) {
      if (alive.current) setError(await salesPdfError(err));
      return null;
    } finally {
      if (alive.current) setPending(null);
    }
  };

  const preview = async (request) => {
    const response = await fetchPdf('preview', request);
    if (response && alive.current) setPreviewUrl(URL.createObjectURL(new Blob([response.data], { type: 'application/pdf' })));
  };

  const download = async (url, fallbackName = 'syllabus.pdf') => {
    const response = await fetchPdf('download', url);
    if (response && alive.current) {
      saveBlob(response.data, filenameFromDisposition(response.headers?.['content-disposition']) || fallbackName);
    }
  };

  const dialog = (
    <ReportPreviewDialog
      url={previewUrl}
      onOpenChange={(open) => {
        if (!open) setPreviewUrl(null);
      }}
      title="PDF preview"
      description="This is the PDF parents receive, priced at the pricing in effect now."
    />
  );

  return { preview, download, pending, error, clearError: () => setError(''), dialog };
}
