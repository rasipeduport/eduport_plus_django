import { FileText } from 'lucide-react';

import { formatBytes } from '@/lib/exam-status';

/** Thumbnails for an exam's files; each opens the authenticated download in a new tab. */
export function FileGallery({ files, emptyText = 'No files.' }) {
  if (!files || files.length === 0) {
    return <p className="text-muted-foreground text-sm">{emptyText}</p>;
  }
  return (
    <div className="grid grid-cols-3 gap-2 sm:grid-cols-4">
      {files.map((f) => {
        const isImage = (f.content_type || '').startsWith('image/');
        return (
          <a
            key={f.id}
            href={f.url}
            target="_blank"
            rel="noopener noreferrer"
            title={`${f.file_name} (${formatBytes(f.size_bytes)})`}
            className="border-border bg-muted/40 hover:bg-muted group flex aspect-square flex-col items-center justify-center overflow-hidden rounded-lg border text-center transition-colors"
          >
            {isImage ? (
              <img src={f.url} alt={f.file_name} className="h-full w-full object-cover" loading="lazy" />
            ) : (
              <>
                <FileText className="text-muted-foreground mb-1 size-7" />
                <span className="text-muted-foreground line-clamp-2 px-1 text-[10px] leading-tight">{f.file_name}</span>
              </>
            )}
          </a>
        );
      })}
    </div>
  );
}
