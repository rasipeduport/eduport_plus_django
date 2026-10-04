import { useState } from 'react';
import { Download, FileText } from 'lucide-react';
import { format } from 'date-fns';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { DOCUMENT_SOURCES, documentTypeLabel } from '@/lib/documents';
import { formatBytes } from '@/lib/exam-status';
import { EMPTY, EmptyState, ProfileTable, SectionHeading, Td } from './profile-primitives';

const COLUMNS = [
  { key: 'name', label: 'File' },
  { key: 'kind', label: 'Attached to' },
  { key: 'type', label: 'Type' },
  { key: 'size', label: 'Size' },
  { key: 'added', label: 'Added' },
  { key: 'actions', label: '', className: 'w-24' },
];

/**
 * Documents tab: every file attached to this student, gathered from the
 * classes, exams and homework the caller can already see (see lib/documents).
 * One flat ledger beats hunting through three other tabs for "the file we
 * sent them in March".
 */
export function DocumentsTab({ documents, sources }) {
  const [source, setSource] = useState('all');
  const available = DOCUMENT_SOURCES.filter((entry) => sources.includes(entry.key));
  const rows = source === 'all' ? documents : documents.filter((document) => document.source === source);

  const counts = available.reduce((accumulator, entry) => {
    accumulator[entry.key] = documents.filter((document) => document.source === entry.key).length;
    return accumulator;
  }, {});

  return (
    <div className="flex flex-col gap-4">
      <SectionHeading
        title={`${documents.length} ${documents.length === 1 ? 'file' : 'files'}`}
        description="Uploads from the student's classes, exams and homework. Pasted links stay on the class itself."
      />

      {available.length > 1 ? (
        <div className="flex flex-wrap gap-2">
          <Button
            variant={source === 'all' ? 'secondary' : 'ghost'}
            size="sm"
            onClick={() => setSource('all')}
            aria-pressed={source === 'all'}
          >
            All
            <span className="text-muted-foreground ml-1 text-xs tabular-nums">{documents.length}</span>
          </Button>
          {available.map((entry) => (
            <Button
              key={entry.key}
              variant={source === entry.key ? 'secondary' : 'ghost'}
              size="sm"
              onClick={() => setSource(entry.key)}
              aria-pressed={source === entry.key}
            >
              {entry.label}
              <span className="text-muted-foreground ml-1 text-xs tabular-nums">{counts[entry.key] ?? 0}</span>
            </Button>
          ))}
        </div>
      ) : null}

      {documents.length === 0 ? (
        <EmptyState
          icon={FileText}
          message="No files uploaded for this student yet."
          hint="Notes, recordings, question papers and homework submissions all land here."
        />
      ) : (
        <ProfileTable
          columns={COLUMNS}
          rows={rows}
          keyOf={(document) => document.id}
          emptyMessage="No files from this source."
          renderRow={(document) => (
            <>
              <Td>
                <span className="block max-w-72 truncate font-medium" title={document.name}>
                  {document.name}
                </span>
                {document.context ? (
                  <span className="text-muted-foreground block max-w-72 truncate text-xs" title={document.context}>
                    {document.context}
                  </span>
                ) : null}
              </Td>
              <Td>
                <Badge variant="outline">{document.kind}</Badge>
              </Td>
              <Td className="text-muted-foreground text-sm whitespace-nowrap">
                {documentTypeLabel(document.contentType)}
              </Td>
              <Td className="text-muted-foreground text-sm whitespace-nowrap tabular-nums">
                {document.sizeBytes != null ? formatBytes(document.sizeBytes) : EMPTY}
              </Td>
              <Td className="text-muted-foreground text-sm whitespace-nowrap">
                {document.createdAt ? format(new Date(document.createdAt), 'd MMM yyyy') : EMPTY}
              </Td>
              <Td className="text-right">
                <Button variant="outline" size="sm" asChild>
                  <a href={document.url} target="_blank" rel="noopener noreferrer">
                    <Download className="size-3.5" />
                    Open
                  </a>
                </Button>
              </Td>
            </>
          )}
        />
      )}
    </div>
  );
}
