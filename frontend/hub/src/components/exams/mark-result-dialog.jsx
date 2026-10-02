import { useState } from 'react';

import { FormDialog } from '@/components/form-dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import api from '@/lib/api';
import { isHttpsUrl, isScoreValid } from '@/lib/exam-status';

import { MultiFileInput } from './multi-file-input';

/**
 * Record (scheduled -> attended) or edit (attended) a chapter exam's result:
 * score X/Y, optional https recording link, question-paper files with
 * Remove / Undo on existing ones. The Hub's MarkResultDialog.
 */
export function MarkResultDialog({ exam, open, onOpenChange, onSaved }) {
  const isEditing = (exam?.status || '').toLowerCase() === 'attended';

  const [score, setScore] = useState('');
  const [maxScore, setMaxScore] = useState('');
  const [recordingLink, setRecordingLink] = useState('');
  const [files, setFiles] = useState([]);
  const [removedIds, setRemovedIds] = useState([]);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');

  const [prevOpen, setPrevOpen] = useState(open);
  if (open !== prevOpen) {
    setPrevOpen(open);
    if (open && exam) {
      setScore(exam.score != null ? String(exam.score) : '');
      setMaxScore(exam.max_score != null ? String(exam.max_score) : '');
      setRecordingLink(exam.recording_link || '');
      setFiles([]);
      setRemovedIds([]);
      setError('');
    }
  }

  const scoreValid = isScoreValid(score, maxScore);
  const recordingValid = recordingLink.trim() === '' || isHttpsUrl(recordingLink);
  const canConfirm = scoreValid && recordingValid;

  const toggleRemove = (id) =>
    setRemovedIds((prev) => (prev.includes(id) ? prev.filter((v) => v !== id) : [...prev, id]));

  const handleConfirm = async () => {
    if (!scoreValid) {
      setError('Enter a valid score between 0 and the maximum.');
      return;
    }
    if (!recordingValid) {
      setError('Recording link must be an https URL.');
      return;
    }
    setPending(true);
    setError('');
    try {
      const form = new FormData();
      form.append('score', String(Number(score)));
      form.append('max_score', String(Number(maxScore)));
      // Always sent: the field is prefilled with the stored link, so a blank
      // value here means the mentor cleared it on purpose.
      form.append('recording_link', recordingLink.trim());
      files.forEach((f) => form.append('files', f));
      removedIds.forEach((id) => form.append('remove_file_ids', id));
      await api.post(`/api/exams/${exam.id}/result/`, form);
      onSaved?.();
      onOpenChange(false);
    } catch (err) {
      setError(err.response?.data?.error || err.response?.data?.message || 'Failed to save the exam result.');
    } finally {
      setPending(false);
    }
  };

  return (
    <FormDialog
      open={open}
      onOpenChange={(v) => !pending && onOpenChange(v)}
      title={isEditing ? 'Edit Result' : 'Record Result'}
      description={exam?.chapter_name}
      error={error}
      onConfirm={handleConfirm}
      confirmLabel={isEditing ? 'Save Changes' : 'Mark Attended'}
      pendingLabel="Saving…"
      confirmDisabled={!canConfirm}
      pending={pending}
      size="md"
    >
      <div className="flex flex-col gap-4">
        <div className="grid grid-cols-2 gap-3">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="exam-score">Score</Label>
            <Input id="exam-score" type="number" min={0} step={1} inputMode="numeric" value={score} onChange={(e) => setScore(e.target.value)} disabled={pending} />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="exam-max-score">Out of</Label>
            <Input id="exam-max-score" type="number" min={1} step={1} inputMode="numeric" value={maxScore} onChange={(e) => setMaxScore(e.target.value)} disabled={pending} />
          </div>
        </div>
        {!scoreValid && (score !== '' || maxScore !== '') && (
          <p className="text-destructive text-xs">Enter a valid score between 0 and the maximum.</p>
        )}

        <div className="flex flex-col gap-1.5">
          <Label htmlFor="exam-recording">Recording link (optional)</Label>
          <Input id="exam-recording" type="url" placeholder="https://drive.google.com/..." value={recordingLink} onChange={(e) => setRecordingLink(e.target.value)} disabled={pending} />
          {!recordingValid && <p className="text-destructive text-xs">Recording link must be an https URL.</p>}
        </div>

        <div className="flex flex-col gap-1.5">
          <Label>Question paper (optional)</Label>
          <MultiFileInput
            files={files}
            onChange={setFiles}
            existing={exam?.files || []}
            removedIds={removedIds}
            onToggleRemove={toggleRemove}
            disabled={pending}
            label="Add question paper files"
          />
        </div>
      </div>
    </FormDialog>
  );
}
