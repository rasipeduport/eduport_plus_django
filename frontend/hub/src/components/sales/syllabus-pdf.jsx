import { useEffect, useRef, useState } from 'react';

import api, { ensureCsrfToken } from '@/lib/api';
import { filenameFromDisposition } from '@/lib/reports';
import { isCsrfFailure, pdfErrorBody, saveBlob, salesPdfError } from '@/lib/sales';
import { ReportPreviewDialog } from '@/components/reports/report-preview-dialog';

/**
 * A syllabus's customer PDF, fetched with the signed-in session: `preview`
 * shows it in a dialog (inline), `download` saves it under the name the
 * server gives it. `preview` takes a URL to GET, or `{ url, data }` to POST
 * (content not yet saved, or the days of a Bridge Course). Both actions also
 * accept `{ url, params }` for a GET pinned to a catalogue revision. `pending` names
 * the action running ('preview' or 'download'); a refusal -- no pricing yet,
 * too many PDFs -- is `error`, and `refusal` says which ({ status, code,
 * revision }) for a page that answers one itself, such as a revision replaced
 * meanwhile.
 * A POST refused only for a stale CSRF token is sent once more with a fresh
 * one (lib/api does that for JSON answers, which a PDF's is not). Render
 * `dialog` once in the page.
 */
export function useSyllabusPdf({ snapshot = false } = {}) {
  const [pending, setPending] = useState(null);
  const [error, setError] = useState('');
  // Why the last request was refused, for a page that answers some refusals itself:
  // { status, code, revision } -- REVISION_CHANGED names the revision on sale now.
  const [refusal, setRefusal] = useState(null);
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
  useEffect(
    () => () => {
      if (previewUrl) URL.revokeObjectURL(previewUrl);
    },
    [previewUrl]
  );

  const fetchPdf = async (kind, request) => {
    if (pending) return null;
    setPending(kind);
    setError('');
    setRefusal(null);
    const config = { responseType: 'blob', params: kind === 'preview' ? { disposition: 'inline' } : undefined };
    const get = typeof request === 'string' || !('data' in request);
    const send = () => {
      if (typeof request === 'string') return api.get(request, config);
      if (get) return api.get(request.url, { ...config, params: { ...config.params, ...request.params } });
      return api.post(request.url, request.data, config);
    };
    try {
      try {
        return await send();
      } catch (err) {
        if (get || !(await isCsrfFailure(err))) throw err;
        await ensureCsrfToken(true);
        return await send();
      }
    } catch (err) {
      const message = await salesPdfError(err);
      const body = err?.response ? await pdfErrorBody(err) : {};
      if (alive.current) {
        setError(message);
        setRefusal({ status: err?.response?.status ?? null, code: body.error ?? null, revision: body.revision ?? null });
      }
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
      description={
        snapshot
          ? 'This quote PDF uses the saved plan and pricing snapshot.'
          : 'This is the PDF parents receive, priced at the pricing in effect now.'
      }
    />
  );

  const clearError = () => {
    setError('');
    setRefusal(null);
  };

  return { preview, download, pending, error, refusal, clearError, dialog };
}
