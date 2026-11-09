import { useEffect } from 'react';
import { DownloadIcon, FileSearchIcon, MessageCircleIcon } from 'lucide-react';

import { cataloguePdfUrl, salesPdfError, syllabusWhatsAppMessage } from '@/lib/sales';
import { whatsAppUrl } from '@/lib/enquiries';
import { canSharePdf } from '@/lib/reports';
import { Button } from '@/components/ui/button';
import { SharePdfButton } from '@/components/reports/share-pdf-button';
import { useSyllabusPdf } from '@/components/sales/syllabus-pdf';

/** The same authenticated PDF actions in both catalogue entry points. */
export function SyllabusActions({ syllabus, enquiry, disabled = false, onRefused }) {
  const pdf = useSyllabusPdf();
  const url = cataloguePdfUrl(syllabus.id);
  const params = { revision: syllabus.revision };
  const request = { url, params };
  useEffect(() => {
    if (pdf.refusal?.code === 'REVISION_CHANGED') onRefused?.(pdf.refusal);
  }, [pdf.refusal, onRefused]);
  const message = syllabusWhatsAppMessage([syllabus.title, syllabus.subtitle].filter(Boolean).join(' – '), enquiry?.parent_name);
  const whatsapp = whatsAppUrl(enquiry?.phone_dial_code, enquiry?.phone_number, message) ?? `https://wa.me/?text=${encodeURIComponent(message)}`;
  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap gap-2">
        <Button variant="outline" size="sm" disabled={disabled || Boolean(pdf.pending)} onClick={() => pdf.preview(request)}>
          <FileSearchIcon className="size-4" /> Preview syllabus PDF
        </Button>
        <Button variant="outline" size="sm" disabled={disabled || Boolean(pdf.pending)} onClick={() => pdf.download(request)}>
          <DownloadIcon className="size-4" /> Download syllabus PDF
        </Button>
        <Button variant="outline" size="sm" asChild>
          <a href={whatsapp} target="_blank" rel="noopener noreferrer" aria-label={`Share ${syllabus.title} through WhatsApp`}>
            <MessageCircleIcon className="size-4" /> WhatsApp
          </a>
        </Button>
        {!disabled && canSharePdf() ? (
          <SharePdfButton
            key={`${syllabus.id}:${syllabus.revision}`}
            url={url}
            params={params}
            title={syllabus.title}
            text={message}
            label={`Share PDF for ${syllabus.title}`}
            pdfError={salesPdfError}
            fallbackName="syllabus.pdf"
          />
        ) : null}
      </div>
      <p className="text-muted-foreground text-xs">
        Download and attach the PDF in WhatsApp, or use Share PDF on a supported device. A parent link is not available.
      </p>
      {pdf.error ? (
        <p role="alert" className="text-destructive text-xs">
          {pdf.error}
        </p>
      ) : null}
      {pdf.dialog}
    </div>
  );
}
