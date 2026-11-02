import { useEffect, useState } from 'react';
import { format } from 'date-fns';

import api from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { reportError, reportFieldsText, reportPdfFallbackName, reportPdfUrl } from '@/lib/reports';
import { PdfDownloadButton } from './pdf-download-button';
import { ReportFieldsView } from './report-fields-view';

/**
 * Every saved version of a report, newest first (GET <reportUrl>revisions/):
 * who saved it, when and what it changed, the version itself on request --
 * the fields it changed marked -- and its PDF (P7). Versions are append-only
 * (reports.0002): saving an edit adds one and never changes another.
 * ``reportUrl`` is the tutor's report or the Admin's (lib/reports); a change
 * of ``reloadKey`` reads them again (after a save). ``headingAs`` sets the
 * heading's level where the list sits under another heading (a sheet's).
 */
export function ReportVersions({ type, reportUrl, reloadKey, headingAs: Heading = 'h2' }) {
  const [data, setData] = useState(null);
  const [failure, setFailure] = useState(null);
  const [retryKey, setRetryKey] = useState(0);
  const [shown, setShown] = useState(() => new Set());

  useEffect(() => {
    let active = true;
    setFailure(null);
    api
      .get(`${reportUrl}revisions/`)
      .then((response) => {
        if (active) setData(response.data);
      })
      .catch((err) => {
        if (active) setFailure(reportError(err, 'Could not load the versions.'));
      });
    return () => {
      active = false;
    };
  }, [reportUrl, reloadKey, retryKey]);

  const toggle = (version) =>
    setShown((current) => {
      const next = new Set(current);
      if (next.has(version)) next.delete(version);
      else next.add(version);
      return next;
    });

  let body;
  if (failure) {
    body = (
      <div className="flex flex-wrap items-center gap-3">
        <p className="text-destructive text-sm">{failure.message}</p>
        <Button variant="outline" size="sm" onClick={() => setRetryKey((key) => key + 1)}>
          Try again
        </Button>
      </div>
    );
  } else if (!data) {
    body = <Skeleton className="h-20" aria-busy="true" />;
  } else {
    const versions = [...(data.results ?? [])].reverse();
    body = (
      <ol className="flex flex-col gap-3">
        {versions.map((row) => {
          const open = shown.has(row.version);
          const current = row.version === data.version;
          return (
            <li key={row.version} className="rounded-lg border p-3">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="min-w-0 text-sm">
                  <p className="font-medium">
                    Version {row.version}
                    {current ? <span className="text-muted-foreground font-normal"> · current</span> : null}
                  </p>
                  <p className="text-muted-foreground text-xs">
                    Saved {format(new Date(row.edited_at), 'd MMM yyyy, h:mm a')} by {row.edited_by?.name || '—'}
                  </p>
                  <p className="text-muted-foreground text-xs">
                    {row.version === 1 ? 'First version' : `Changed: ${reportFieldsText(row.changed_fields)}`}
                  </p>
                </div>
                <div className="flex flex-wrap items-start gap-2">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => toggle(row.version)}
                    aria-expanded={open}
                    aria-label={`${open ? 'Hide' : 'Show'} version ${row.version}`}
                  >
                    {open ? 'Hide' : 'Show'}
                  </Button>
                  <PdfDownloadButton
                    url={reportPdfUrl(reportUrl, row.version)}
                    fallbackName={reportPdfFallbackName(type, row.version)}
                    label={`PDF of version ${row.version}`}
                  >
                    PDF
                  </PdfDownloadButton>
                </div>
              </div>
              {open ? (
                <div className="mt-3 border-t pt-3">
                  <ReportFieldsView
                    type={type}
                    report={row}
                    changedFields={row.version === 1 ? [] : row.changed_fields}
                  />
                </div>
              ) : null}
            </li>
          );
        })}
      </ol>
    );
  }

  return (
    <section className="flex flex-col gap-3" aria-labelledby="report-versions-heading">
      <Heading id="report-versions-heading" className="text-base font-semibold">
        Versions
      </Heading>
      <p className="text-muted-foreground -mt-2 text-sm">
        Each save is kept as a version of its own. Earlier versions never change.
      </p>
      {body}
    </section>
  );
}
