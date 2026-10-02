import { useRef, useState } from 'react';
import { FileText, Image as ImageIcon, Paperclip, Undo2, X } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { EXAM_ACCEPT, EXAM_MAX_FILES, EXAM_MAX_FILE_BYTES, formatBytes, isAllowedExamMime } from '@/lib/exam-status';

/**
 * Picks up to 10 PDF / image files for an exam (question paper or answer
 * sheet). Mirrors the Hub's picker: unsupported types and oversized files are
 * dropped, duplicates (same name + size) collapse, and the list is capped.
 * When `existing` is given (editing), each stored file gets a Remove / Undo
 * toggle that the caller turns into `remove_file_ids`.
 */
export function MultiFileInput({
  files,
  onChange,
  existing = [],
  removedIds = [],
  onToggleRemove,
  disabled = false,
  label = 'Add files',
}) {
  const inputRef = useRef(null);
  const [notice, setNotice] = useState('');

  const pick = (list) => {
    const incoming = Array.from(list || []);
    const notices = [];
    const accepted = incoming.filter((f) => {
      if (!isAllowedExamMime(f.type)) {
        notices.push(`"${f.name}" is not a PDF or image.`);
        return false;
      }
      if (f.size === 0) {
        notices.push(`"${f.name}" is empty.`);
        return false;
      }
      if (f.size > EXAM_MAX_FILE_BYTES) {
        notices.push(`"${f.name}" exceeds the 25 MB limit.`);
        return false;
      }
      return true;
    });
    const merged = [...files];
    for (const f of accepted) {
      if (!merged.some((m) => m.name === f.name && m.size === f.size)) merged.push(f);
    }
    if (merged.length > EXAM_MAX_FILES) {
      notices.push(`At most ${EXAM_MAX_FILES} files.`);
    }
    onChange(merged.slice(0, EXAM_MAX_FILES));
    setNotice(notices.join(' '));
    if (inputRef.current) inputRef.current.value = '';
  };

  const removeNew = (index) => onChange(files.filter((_, i) => i !== index));

  const Icon = (type) => ((type || '').startsWith('image/') ? ImageIcon : FileText);

  return (
    <div className="flex flex-col gap-2">
      <input
        ref={inputRef}
        type="file"
        multiple
        accept={EXAM_ACCEPT}
        className="hidden"
        onChange={(e) => pick(e.target.files)}
        disabled={disabled}
      />
      {existing.length > 0 && (
        <ul className="flex flex-col gap-1">
          {existing.map((f) => {
            const removed = removedIds.includes(f.id);
            const FileIcon = Icon(f.content_type);
            return (
              <li
                key={f.id}
                className={cn(
                  'flex items-center gap-2 rounded-md border px-2 py-1.5 text-xs',
                  removed ? 'border-destructive/40 bg-destructive/5 text-muted-foreground line-through' : 'border-border bg-muted/40'
                )}
              >
                <FileIcon className="text-muted-foreground size-3.5 shrink-0" />
                <a href={f.url} target="_blank" rel="noopener noreferrer" className="min-w-0 flex-1 truncate hover:underline">
                  {f.file_name}
                </a>
                <span className="text-muted-foreground shrink-0">{formatBytes(f.size_bytes)}</span>
                <Button type="button" variant="ghost" size="sm" className="h-6 px-2 text-xs" onClick={() => onToggleRemove?.(f.id)} disabled={disabled}>
                  {removed ? (
                    <>
                      <Undo2 className="size-3" /> Undo
                    </>
                  ) : (
                    'Remove'
                  )}
                </Button>
              </li>
            );
          })}
        </ul>
      )}
      {files.length > 0 && (
        <ul className="flex flex-col gap-1">
          {files.map((f, i) => {
            const FileIcon = Icon(f.type);
            return (
              <li key={`${f.name}-${f.size}`} className="border-border bg-muted/40 flex items-center gap-2 rounded-md border px-2 py-1.5 text-xs">
                <FileIcon className="text-muted-foreground size-3.5 shrink-0" />
                <span className="min-w-0 flex-1 truncate">{f.name}</span>
                <span className="text-muted-foreground shrink-0">{formatBytes(f.size)}</span>
                <button type="button" onClick={() => removeNew(i)} className="text-muted-foreground hover:text-foreground" aria-label={`Remove ${f.name}`} disabled={disabled}>
                  <X className="size-3.5" />
                </button>
              </li>
            );
          })}
        </ul>
      )}
      <Button type="button" variant="outline" size="sm" onClick={() => inputRef.current?.click()} disabled={disabled || files.length >= EXAM_MAX_FILES} className="w-fit">
        <Paperclip className="size-4" />
        {label}
      </Button>
      <p className="text-muted-foreground text-xs">PDF or image, up to 25 MB each, at most {EXAM_MAX_FILES} files per upload.</p>
      {notice && <p className="text-destructive text-xs">{notice}</p>}
    </div>
  );
}
