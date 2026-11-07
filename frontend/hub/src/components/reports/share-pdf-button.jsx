import { useState } from 'react';
import { Loader2Icon, Share2Icon } from 'lucide-react';

import api from '@/lib/api';
import { Button } from '@/components/ui/button';
import { filenameFromDisposition, reportPdfError } from '@/lib/reports';

/**
 * Hands a report's PDF to the device's share sheet (the Web Share API with
 * files), where the BDE picks WhatsApp -- or another app -- and then the
 * parent's chat: the sheet cannot choose the chat itself. Offered only where
 * the browser can share files (lib/reports canSharePdf). `onShared` hears when
 * the sheet took the PDF; nothing here can tell whether it reached the parent.
 *
 * A browser shares only straight after a tap, and the PDF is fetched first,
 * from ``url`` (named as the server names it, else ``fallbackName``). When the
 * fetch took too long for the browser, the file is kept and the next tap
 * shares it at once.
 */
export function SharePdfButton({ url, fallbackName = 'report.pdf', title, label, onShared }) {
  const [file, setFile] = useState(null);
  const [fetching, setFetching] = useState(false);
  const [sharing, setSharing] = useState(false);
  const [notice, setNotice] = useState(null);

  const share = async () => {
    if (fetching || sharing) return;
    setNotice(null);
    let ready = file;
    if (!ready) {
      setFetching(true);
      try {
        const response = await api.get(url, { responseType: 'blob' });
        const name = filenameFromDisposition(response.headers?.['content-disposition']) || fallbackName;
        ready = new File([response.data], name, { type: 'application/pdf' });
        setFile(ready);
      } catch (err) {
        setNotice({ error: true, text: await reportPdfError(err) });
        return;
      } finally {
        setFetching(false);
      }
    }
    setSharing(true);
    try {
      await navigator.share({ files: [ready], title });
      onShared?.();
    } catch (err) {
      if (err?.name === 'AbortError') return; // the share sheet was closed without sharing
      setNotice(
        err?.name === 'NotAllowedError'
          ? { error: false, text: 'The PDF is ready. Tap Share PDF again to share it.' }
          : { error: true, text: 'This device could not share the PDF. Download it and attach it instead.' }
      );
    } finally {
      setSharing(false);
    }
  };

  return (
    <div className="flex flex-col items-start gap-1">
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={share}
        disabled={fetching || sharing}
        aria-busy={fetching || undefined}
        aria-label={fetching ? undefined : label}
      >
        {fetching ? <Loader2Icon className="size-4 animate-spin" /> : <Share2Icon className="size-4" />}
        {fetching ? 'Preparing…' : 'Share PDF'}
      </Button>
      {notice ? (
        <p role={notice.error ? 'alert' : 'status'} className={notice.error ? 'text-destructive text-xs' : 'text-muted-foreground text-xs'}>
          {notice.text}
        </p>
      ) : null}
    </div>
  );
}
