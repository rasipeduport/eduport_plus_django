import { useRef, useState } from 'react';
import { AlertTriangle, Camera, CheckCircle2, Loader2, X } from 'lucide-react';
import api from '../../lib/api';
import { Button } from '../ui/button';
import { downscaleImage } from '../../lib/image';
import { EXAM_ACCEPT, EXAM_MAX_FILES, EXAM_MAX_FILE_BYTES, formatBytes, isAllowedExamMime } from '../../lib/exam-status';

/**
 * One-shot answer-sheet upload (Learn AdditionalSubmitForm): pick photos or
 * a PDF, confirm, POST once. Photos are downscaled in the browser first.
 */
export function AdditionalSubmitForm({ examId, onSubmitted, submitUrl, successLabel = 'Answer sheet submitted' }) {
  const inputRef = useRef(null);
  const [files, setFiles] = useState([]);
  const [error, setError] = useState('');
  const [confirming, setConfirming] = useState(false);
  const [preparing, setPreparing] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [done, setDone] = useState(false);

  const pick = async (list) => {
    setError('');
    setPreparing(true);
    try {
      const incoming = Array.from(list || []);
      const next = [...files];
      const problems = [];
      for (const raw of incoming) {
        const f = await downscaleImage(raw);
        if (!isAllowedExamMime(f.type)) {
          problems.push(`"${raw.name}" is not a photo or PDF.`);
          continue;
        }
        if (f.size === 0) {
          problems.push(`"${raw.name}" is empty.`);
          continue;
        }
        if (f.size > EXAM_MAX_FILE_BYTES) {
          problems.push(`"${raw.name}" is larger than 25 MB.`);
          continue;
        }
        if (!next.some((n) => n.name === f.name && n.size === f.size)) next.push(f);
      }
      if (next.length > EXAM_MAX_FILES) problems.push(`At most ${EXAM_MAX_FILES} files.`);
      setFiles(next.slice(0, EXAM_MAX_FILES));
      if (problems.length) setError(problems.join(' '));
    } finally {
      setPreparing(false);
      if (inputRef.current) inputRef.current.value = '';
    }
  };

  const submit = async () => {
    setSubmitting(true);
    setError('');
    try {
      const form = new FormData();
      files.forEach((f) => form.append('files', f));
      await api.post(submitUrl || `/api/additional-exams/${examId}/submit/`, form);
      setDone(true);
      onSubmitted?.();
    } catch (err) {
      setError(err.response?.data?.error || err.response?.data?.message || 'Failed to submit. Please try again.');
      setConfirming(false);
    } finally {
      setSubmitting(false);
    }
  };

  if (done) {
    return (
      <div className="border-primary/15 bg-primary-subtle flex items-center gap-3 rounded-xl border px-4 py-3">
        <CheckCircle2 className="text-primary h-5 w-5" />
        <p className="text-primary-hover text-sm font-semibold">{successLabel}</p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="border-warning/20 bg-warning-subtle flex items-start gap-2 rounded-xl border px-3 py-2.5">
        <AlertTriangle className="text-warning mt-0.5 h-4 w-4 shrink-0" />
        <p className="text-text-secondary text-xs">
          You can submit once. Add clear photos of every page before you submit — you can't change them afterwards.
        </p>
      </div>

      <input ref={inputRef} type="file" multiple accept={EXAM_ACCEPT} className="hidden" onChange={(e) => pick(e.target.files)} disabled={submitting || preparing} />

      {files.length > 0 && (
        <ul className="space-y-1.5">
          {files.map((f, i) => (
            <li key={`${f.name}-${f.size}`} className="border-border-light bg-surface-muted flex items-center gap-2 rounded-lg border px-3 py-2 text-xs">
              <span className="text-text-primary min-w-0 flex-1 truncate">{f.name}</span>
              <span className="text-text-muted shrink-0">{formatBytes(f.size)}</span>
              {!confirming && (
                <button type="button" aria-label={`Remove ${f.name}`} onClick={() => setFiles(files.filter((_, j) => j !== i))} className="text-text-muted hover:text-text-primary cursor-pointer">
                  <X className="h-3.5 w-3.5" />
                </button>
              )}
            </li>
          ))}
        </ul>
      )}

      {error && <p className="text-danger text-xs">{error}</p>}

      {!confirming ? (
        <div className="flex flex-col gap-2 sm:flex-row">
          <Button variant="outline" size="md" icon={preparing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Camera className="h-4 w-4" />} onClick={() => inputRef.current?.click()} disabled={preparing || files.length >= EXAM_MAX_FILES} className="flex-1">
            {files.length === 0 ? 'Add photos or PDF' : 'Add more'}
          </Button>
          <Button variant="primary" size="md" disabled={files.length === 0 || preparing} onClick={() => setConfirming(true)} className="flex-1">
            Submit answer sheet
          </Button>
        </div>
      ) : (
        <div className="border-border-light bg-surface-muted space-y-3 rounded-xl border px-4 py-3">
          <p className="text-text-primary text-sm font-semibold">
            Submit {files.length} {files.length === 1 ? 'file' : 'files'}? You can't change this afterwards.
          </p>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={() => setConfirming(false)} disabled={submitting} className="flex-1">
              Go back
            </Button>
            <Button variant="primary" size="sm" onClick={submit} disabled={submitting} icon={submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : null} className="flex-1">
              {submitting ? 'Submitting…' : 'Yes, submit'}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
