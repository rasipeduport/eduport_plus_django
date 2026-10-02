import { useState } from 'react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import api from '@/lib/api';

import { MultiFileInput } from './multi-file-input';

/** "New Additional Exam" drawer: a title plus the question paper (the Hub's NewAdditionalExamSheet). */
export function NewAdditionalExamSheet({ student, open, onOpenChange, onCreated }) {
  const [title, setTitle] = useState('');
  const [files, setFiles] = useState([]);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState('');

  const [prevOpen, setPrevOpen] = useState(open);
  if (open !== prevOpen) {
    setPrevOpen(open);
    if (open) {
      setTitle('');
      setFiles([]);
      setError('');
    }
  }

  const canConfirm = title.trim().length > 0 && files.length > 0;

  const handleOpenChange = (value) => {
    if (isSaving) return;
    onOpenChange(value);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!canConfirm) {
      setError('A title and at least one question paper file are required.');
      return;
    }
    setIsSaving(true);
    setError('');
    try {
      const form = new FormData();
      form.append('student_id', student.id);
      form.append('title', title.trim());
      files.forEach((f) => form.append('files', f));
      await api.post('/api/additional-exams/', form);
      onCreated?.();
      onOpenChange(false);
    } catch (err) {
      setError(err.response ? err.response.data?.error || err.response.data?.message || 'Failed to create the exam.' : 'Network error. Please try again.');
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <Sheet open={open} onOpenChange={handleOpenChange}>
      <SheetContent side="right" className="flex flex-col sm:max-w-md">
        <SheetHeader>
          <SheetTitle>New Additional Exam</SheetTitle>
          <SheetDescription>Upload a question paper; the student submits an answer sheet once and you score it.</SheetDescription>
        </SheetHeader>

        <form id="new-additional-exam-form" onSubmit={handleSubmit} className="flex flex-1 flex-col gap-6 overflow-y-auto px-4 py-2">
          <div className="flex flex-col gap-2">
            <Label htmlFor="additional-exam-title">Title</Label>
            <Input id="additional-exam-title" value={title} onChange={(e) => setTitle(e.target.value)} maxLength={200} placeholder="e.g. Chapter 3 worksheet" disabled={isSaving} />
          </div>

          <div className="flex flex-col gap-2">
            <Label>Question paper</Label>
            <MultiFileInput files={files} onChange={setFiles} disabled={isSaving} label="Add question paper files" />
          </div>

          {error && <p className="text-destructive text-sm">{error}</p>}
        </form>

        <div className="mt-auto flex gap-2 border-t px-4 py-3">
          <Button type="button" variant="outline" className="flex-1" onClick={() => handleOpenChange(false)} disabled={isSaving}>
            Cancel
          </Button>
          <Button type="submit" form="new-additional-exam-form" className="flex-1" disabled={isSaving || !canConfirm}>
            {isSaving ? 'Creating…' : 'Create Exam'}
          </Button>
        </div>
      </SheetContent>
    </Sheet>
  );
}
