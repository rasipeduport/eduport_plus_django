import { useRef } from 'react';
import { ExternalLink, FileText, Image as ImageIcon, Paperclip, Video, X } from 'lucide-react';

import { cn } from '@/lib/utils';

// One session content field (notes / recording / homework) can be filled two
// ways that land in the same link column: paste a URL, or upload a file --
// the API stores the file and writes its authenticated download URL into
// that column. This component owns the "Enter URL | Upload File" switch and
// the per-mode inputs; the dialogs own submission.

// Mirrors CONTENT_TYPES and SESSION_CONTENT_MAX_BYTES on the backend
// (sessions/services.py, config/settings.py). Keep the two in step.
const KIND_BY_TYPE = {
  'application/pdf': 'document',
  'image/png': 'image',
  'image/jpeg': 'image',
  'image/webp': 'image',
  'image/gif': 'image',
  'image/heic': 'image',
  'image/heif': 'image',
  'video/mp4': 'video',
  'video/webm': 'video',
  'video/quicktime': 'video',
  'video/x-matroska': 'video',
};
const MiB = 1024 * 1024;
const MAX_BYTES = { document: 50 * MiB, image: 50 * MiB, video: 500 * MiB };

export const CONTENT_ACCEPT = Object.keys(KIND_BY_TYPE).join(',');

export const isHttpsUrl = (value) => /^https:\/\/\S+$/i.test((value || '').trim());

export const contentKind = (contentType) => KIND_BY_TYPE[(contentType || '').toLowerCase()] || null;

export function formatBytes(bytes) {
  if (bytes == null) return '';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < MiB) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / MiB).toFixed(1)} MB`;
}

const KIND_LABEL = { document: 'PDF', image: 'Image', video: 'Video' };
const KIND_ICON = { document: FileText, image: ImageIcon, video: Video };

/**
 * Dialog state for one content field of a session. Starts in file mode when
 * an upload already stands behind the link, otherwise in URL mode with the
 * stored link prefilled.
 */
export function contentStateFor(session, field) {
  const existing = session?.content_files?.[field] || null;
  const link = existing ? '' : session?.[`${field}_link`] || '';
  return { field, mode: existing ? 'file' : 'url', url: link, initialUrl: link, file: null, existing };
}

const EMPTY_STATE = { mode: 'url', url: '', initialUrl: '', file: null, existing: null };

/** A user-facing validation message for the state, or null when it is fine. */
export function contentError(state, { required = false, label = 'Content' } = {}) {
  const s = state || EMPTY_STATE;
  if (s.mode === 'url') {
    const value = s.url.trim();
    if (!value) return required && !s.existing ? `${label}: enter a link or upload a file.` : null;
    // Only newly typed links are checked, so a legacy value can be re-saved untouched.
    if (value !== s.initialUrl && !isHttpsUrl(value)) return `${label}: enter a valid https:// link.`;
    return null;
  }
  if (s.file) {
    const kind = contentKind(s.file.type);
    if (!kind) return `${label}: "${s.file.name}" is not a PDF, image, or video.`;
    if (s.file.size > MAX_BYTES[kind]) {
      return `${label}: "${s.file.name}" is over the ${MAX_BYTES[kind] / MiB} MB limit for ${kind}s.`;
    }
    return null;
  }
  return required && !s.existing ? `${label}: choose a file or enter a link.` : null;
}

/**
 * What the dialog should send for this field:
 *   { kind: 'file', file }        -> POST the file to the field's upload endpoint
 *   { kind: 'url', value|null }   -> include `<field>_link` in the PUT
 *   { kind: 'keep' }              -> nothing (an existing upload stays as is)
 */
export function contentPayload(state) {
  const s = state || EMPTY_STATE;
  if (s.mode === 'file') return s.file ? { kind: 'file', file: s.file } : { kind: 'keep' };
  const value = s.url.trim();
  if (!value && s.existing) return { kind: 'keep' };
  return { kind: 'url', value: value || null };
}

// Colours come from the design tokens (border/muted/foreground) so the card
// reads correctly in both themes; the Sessions page's legacy light-mode
// overrides only know a fixed list of hardcoded dark classes.
function FileCard({ name, contentType, size, url, onRemove, pending, disabled }) {
  const kind = contentKind(contentType);
  const Icon = KIND_ICON[kind] || FileText;
  return (
    <div className="flex items-center gap-2.5 rounded-lg border border-border bg-muted/30 px-3 py-2">
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-muted">
        <Icon className="h-4 w-4 text-foreground" />
      </div>
      <div className="min-w-0 flex-1">
        <p className="m-0 truncate text-sm text-foreground" title={name}>{name}</p>
        <p className="m-0 text-[11px] text-muted-foreground">
          {KIND_LABEL[kind] || contentType || 'File'}
          {size != null ? ` · ${formatBytes(size)}` : ''}
          {pending ? ' · ready to upload' : ' · uploaded'}
        </p>
      </div>
      {url ? (
        <a
          href={url}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex h-7 items-center gap-1 rounded-md border border-white/10 bg-zinc-800 px-2 text-xs font-medium text-zinc-200 hover:bg-zinc-700 hover:text-zinc-50"
        >
          Open
          <ExternalLink className="h-3 w-3 text-zinc-400" />
        </a>
      ) : null}
      <button
        type="button"
        onClick={onRemove}
        disabled={disabled}
        aria-label={pending ? 'Remove chosen file' : 'Remove uploaded file'}
        className="flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground disabled:opacity-40"
      >
        <X className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}

export function ContentInput({ label, optional = false, placeholder, value, onChange, disabled = false }) {
  const state = value || EMPTY_STATE;
  const inputRef = useRef(null);
  const update = (patch) => onChange({ ...state, ...patch });

  const pick = (fileList) => {
    const file = fileList && fileList[0];
    if (file) update({ file });
    if (inputRef.current) inputRef.current.value = '';
  };

  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between gap-3">
        <label className="block text-xs font-bold text-zinc-400 uppercase tracking-widest">
          {label}
          {optional ? <span className="text-muted-foreground normal-case tracking-normal font-medium"> (optional)</span> : null}
        </label>
        <div role="tablist" aria-label={`${label} source`} className="inline-flex shrink-0 rounded-md border border-border bg-muted/50 p-0.5">
          {[
            ['url', 'Enter URL'],
            ['file', 'Upload File'],
          ].map(([mode, text]) => (
            <button
              key={mode}
              type="button"
              role="tab"
              aria-selected={state.mode === mode}
              disabled={disabled}
              onClick={() => update({ mode })}
              className={cn(
                'rounded px-2 py-0.5 text-[11px] font-semibold whitespace-nowrap transition-colors',
                state.mode === mode ? 'bg-foreground text-background shadow-sm' : 'text-muted-foreground hover:text-foreground'
              )}
            >
              {text}
            </button>
          ))}
        </div>
      </div>

      {state.mode === 'url' ? (
        <input
          type="url"
          placeholder={placeholder}
          value={state.url}
          onChange={(e) => update({ url: e.target.value })}
          disabled={disabled}
          className="w-full px-3 py-2 bg-white/[0.04] border border-white/10 rounded-lg text-sm text-white placeholder-zinc-600 focus:outline-none focus:ring-2 focus:ring-white/20"
        />
      ) : (
        <div className="space-y-2">
          {state.file ? (
            <FileCard
              name={state.file.name}
              contentType={state.file.type}
              size={state.file.size}
              pending
              disabled={disabled}
              onRemove={() => update({ file: null })}
            />
          ) : state.existing ? (
            <FileCard
              name={state.existing.file_name}
              contentType={state.existing.content_type}
              size={state.existing.size_bytes}
              url={state.existing.url}
              disabled={disabled}
              onRemove={() => update({ existing: null, mode: 'url', url: '', initialUrl: '' })}
            />
          ) : null}

          {!state.file ? (
            <button
              type="button"
              onClick={() => inputRef.current?.click()}
              disabled={disabled}
              className="flex w-full items-center justify-center gap-2 rounded-lg border border-dashed border-input px-3 py-2 text-xs font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground disabled:opacity-40"
            >
              <Paperclip className="h-3.5 w-3.5" />
              {state.existing ? 'Replace with another file' : 'Choose a PDF, image, or video'}
            </button>
          ) : null}
          <p className="m-0 text-[10px] text-muted-foreground">PDF or image up to 50 MB, video up to 500 MB.</p>
          <input
            ref={inputRef}
            type="file"
            accept={CONTENT_ACCEPT}
            className="hidden"
            disabled={disabled}
            onChange={(e) => pick(e.target.files)}
          />
        </div>
      )}
    </div>
  );
}
