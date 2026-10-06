import { useState } from 'react';
import { FileText, X } from 'lucide-react';
import { formatBytes } from '../../lib/exam-status';

/**
 * Thumbnails for an exam's files with a full-screen viewer (images inline,
 * PDFs in a frame). Port of the Learn app's FileGallery + MediaViewer.
 */
export function FileGallery({ files, emptyText = 'No files.' }) {
  const [active, setActive] = useState(null);

  if (!files || files.length === 0) {
    return <p className="text-text-muted text-sm">{emptyText}</p>;
  }

  return (
    <>
      <div className="grid grid-cols-3 gap-2 sm:grid-cols-4">
        {files.map((f) => {
          const isImage = (f.content_type || '').startsWith('image/');
          return (
            <button
              key={f.id}
              type="button"
              onClick={() => setActive(f)}
              title={`${f.file_name} (${formatBytes(f.size_bytes)})`}
              className="border-border-light bg-surface-muted hover:bg-surface-inset flex aspect-square flex-col items-center justify-center overflow-hidden rounded-xl border text-center transition-colors cursor-pointer"
            >
              {isImage ? (
                <img src={f.url} alt={f.file_name} className="h-full w-full object-cover" loading="lazy" />
              ) : (
                <>
                  <FileText className="text-text-muted mb-1 h-7 w-7" />
                  <span className="text-text-muted line-clamp-2 px-1 text-[10px] leading-tight">{f.file_name}</span>
                </>
              )}
            </button>
          );
        })}
      </div>

      {active && (
        <div className="safe-area-top safe-area-bottom fixed inset-0 z-[60] flex flex-col bg-black/90" onClick={() => setActive(null)}>
          <div className="flex items-center justify-between px-4 py-3 text-white">
            <span className="min-w-0 flex-1 truncate text-sm">{active.file_name}</span>
            <div className="flex shrink-0 items-center gap-1">
              <a href={active.url} target="_blank" rel="noopener noreferrer" className="px-2 py-2 text-xs underline" onClick={(e) => e.stopPropagation()}>
                Open
              </a>
              <button type="button" aria-label="Close" onClick={() => setActive(null)} className="flex h-9 w-9 items-center justify-center rounded-full cursor-pointer">
                <X className="h-5 w-5" />
              </button>
            </div>
          </div>
          <div className="flex flex-1 items-center justify-center overflow-auto p-2" onClick={(e) => e.stopPropagation()}>
            {(active.content_type || '').startsWith('image/') ? (
              <img src={active.url} alt={active.file_name} className="max-h-full max-w-full object-contain" />
            ) : (
              <iframe src={active.url} title={active.file_name} className="h-full w-full rounded-lg bg-white" />
            )}
          </div>
        </div>
      )}
    </>
  );
}
