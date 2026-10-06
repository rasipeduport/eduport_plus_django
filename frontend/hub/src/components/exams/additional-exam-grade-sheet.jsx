import { useEffect, useState } from 'react';
import { Loader2 } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Separator } from '@/components/ui/separator';
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import api from '@/lib/api';
import { ADDITIONAL_STATUS_VARIANT, additionalExamStatusLabel, isScoreValid } from '@/lib/exam-status';
import { ResultCell } from './result-cell';

import { FileGallery } from './file-gallery';

/**
 * Review / score drawer for an additional exam (the Hub's
 * AdditionalExamGradeSheet): question paper always, the answer sheet once
 * submitted, the score form only while submitted, the score once scored.
 */
export function AdditionalExamGradeSheet({ examId, open, onOpenChange, onSaved }) {
  const [exam, setExam] = useState(null);
  const [loading, setLoading] = useState(false);
  const [score, setScore] = useState('');
  const [maxScore, setMaxScore] = useState('');
  const [feedback, setFeedback] = useState('');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!open || !examId) return;
    let cancelled = false;
    setLoading(true);
    setError('');
    setScore('');
    setMaxScore('');
    setFeedback('');
    api
      .get(`/api/additional-exams/${examId}/`)
      .then((res) => {
        if (!cancelled) setExam(res.data.additional_exam);
      })
      .catch((err) => {
        if (!cancelled) setError(err.response?.data?.error || 'Failed to load the exam.');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open, examId]);

  const status = (exam?.status || '').toLowerCase();
  const scoreValid = isScoreValid(score, maxScore);

  const handleScore = async (e) => {
    e.preventDefault();
    if (!scoreValid) {
      setError('Enter a valid score between 0 and the maximum.');
      return;
    }
    setPending(true);
    setError('');
    try {
      const res = await api.post(`/api/additional-exams/${exam.id}/score/`, {
        score: Number(score),
        max_score: Number(maxScore),
        feedback: feedback.trim() || undefined,
      });
      setExam(res.data.additional_exam);
      onSaved?.();
    } catch (err) {
      setError(err.response?.data?.error || err.response?.data?.message || 'Failed to score the exam.');
    } finally {
      setPending(false);
    }
  };

  return (
    <Sheet open={open} onOpenChange={(v) => !pending && onOpenChange(v)}>
      <SheetContent side="right" className="flex flex-col sm:max-w-md">
        <SheetHeader>
          <SheetTitle>{exam?.title || 'Additional Exam'}</SheetTitle>
          <SheetDescription>
            {exam ? (
              <Badge variant={ADDITIONAL_STATUS_VARIANT[status] || 'secondary'}>{additionalExamStatusLabel(exam)}</Badge>
            ) : (
              'Loading…'
            )}
          </SheetDescription>
        </SheetHeader>

        <div className="flex flex-1 flex-col gap-5 overflow-y-auto px-4 py-2">
          {loading && (
            <div className="flex justify-center py-10">
              <Loader2 className="text-muted-foreground size-6 animate-spin" />
            </div>
          )}

          {exam && !loading && (
            <>
              <section className="flex flex-col gap-2">
                <Label>Question paper</Label>
                <FileGallery files={exam.question_paper} emptyText="No question paper uploaded." />
              </section>

              <Separator />

              <section className="flex flex-col gap-2">
                <Label>Answer sheet</Label>
                {status === 'assigned' ? (
                  <p className="text-muted-foreground text-sm">Awaiting the student's answer sheet.</p>
                ) : (
                  <FileGallery files={exam.answer_sheet} emptyText="No answer sheet uploaded." />
                )}
                {exam.submitted_at && (
                  <p className="text-muted-foreground text-xs">Submitted {new Date(exam.submitted_at).toLocaleString()}</p>
                )}
              </section>

              <Separator />

              {status === 'submitted' && (
                <form id="score-additional-exam" onSubmit={handleScore} className="flex flex-col gap-3">
                  <Label>Score</Label>
                  <div className="grid grid-cols-2 gap-3">
                    <Input type="number" min={0} step={1} inputMode="numeric" placeholder="Score" value={score} onChange={(e) => setScore(e.target.value)} disabled={pending} aria-label="Score" />
                    <Input type="number" min={1} step={1} inputMode="numeric" placeholder="Out of" value={maxScore} onChange={(e) => setMaxScore(e.target.value)} disabled={pending} aria-label="Maximum" />
                  </div>
                  {!scoreValid && (score !== '' || maxScore !== '') && (
                    <p className="text-destructive text-xs">Enter a valid score between 0 and the maximum.</p>
                  )}
                  <Label htmlFor="additional-feedback">Feedback (optional)</Label>
                  <textarea
                    id="additional-feedback"
                    value={feedback}
                    onChange={(e) => setFeedback(e.target.value)}
                    maxLength={2000}
                    rows={3}
                    className="border-input bg-transparent placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-ring/50 w-full rounded-md border px-3 py-2 text-sm shadow-xs outline-none focus-visible:ring-[3px]"
                    disabled={pending}
                  />
                </form>
              )}

              {status === 'scored' && (
                <section className="flex flex-col gap-2">
                  <Label>Result</Label>
                  <p className="text-2xl font-semibold tabular-nums">
                    <ResultCell score={exam.score} maxScore={exam.max_score} className="font-semibold" />
                  </p>
                  {exam.feedback && <p className="text-muted-foreground text-sm whitespace-pre-wrap">{exam.feedback}</p>}
                  {exam.scored_by_profile && (
                    <p className="text-muted-foreground text-xs">
                      Scored by {exam.scored_by_profile.full_name || exam.scored_by_profile.email}
                      {exam.scored_at ? ` on ${new Date(exam.scored_at).toLocaleDateString()}` : ''}
                    </p>
                  )}
                </section>
              )}
            </>
          )}

          {error && <p className="text-destructive text-sm">{error}</p>}
        </div>

        <div className="mt-auto flex gap-2 border-t px-4 py-3">
          <Button type="button" variant="outline" className="flex-1" onClick={() => onOpenChange(false)} disabled={pending}>
            Close
          </Button>
          {status === 'submitted' && (
            <Button type="submit" form="score-additional-exam" className="flex-1" disabled={pending || !scoreValid}>
              {pending ? 'Saving…' : 'Save Score'}
            </Button>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}
