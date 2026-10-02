import { useEffect, useState } from 'react';
import { ExternalLink, Loader2 } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Separator } from '@/components/ui/separator';
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { FileGallery } from '@/components/exams/file-gallery';
import api from '@/lib/api';
import { isScoreValid, formatBytes } from '@/lib/exam-status';
import { HOMEWORK_STATUS_VARIANT, homeworkStatusLabel } from '@/lib/homework-status';

/**
 * Homework review / grade drawer (the Hub's GradeSheet): the assignment the
 * mentor set on the session, the student's submission, and the score form --
 * which only a tutor (or admin) gets, while the homework is submitted.
 */
export function HomeworkGradeSheet({ homeworkId, open, onOpenChange, onSaved, canScore = false }) {
  const [hw, setHw] = useState(null);
  const [loading, setLoading] = useState(false);
  const [score, setScore] = useState('');
  const [maxScore, setMaxScore] = useState('');
  const [feedback, setFeedback] = useState('');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!open || !homeworkId) return;
    let cancelled = false;
    setLoading(true);
    setError('');
    setScore('');
    setMaxScore('');
    setFeedback('');
    api
      .get(`/api/homework/${homeworkId}/`)
      .then((res) => {
        if (!cancelled) setHw(res.data.homework);
      })
      .catch((err) => {
        if (!cancelled) setError(err.response?.data?.error || 'Failed to load the homework.');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open, homeworkId]);

  const status = (hw?.status || '').toLowerCase();
  const scoreValid = isScoreValid(score, maxScore);
  const assignment = hw?.assignment || {};
  const assignmentUrl = (assignment.url || '').trim();

  const handleScore = async (e) => {
    e.preventDefault();
    if (!scoreValid) {
      setError('Enter a valid score between 0 and the maximum.');
      return;
    }
    setPending(true);
    setError('');
    try {
      const res = await api.post(`/api/homework/${hw.id}/score/`, {
        score: Number(score),
        max_score: Number(maxScore),
        feedback: feedback.trim() || undefined,
      });
      setHw(res.data.homework);
      onSaved?.();
    } catch (err) {
      setError(err.response?.data?.error || err.response?.data?.message || 'Failed to score the homework.');
    } finally {
      setPending(false);
    }
  };

  return (
    <Sheet open={open} onOpenChange={(v) => !pending && onOpenChange(v)}>
      <SheetContent side="right" className="flex flex-col sm:max-w-md">
        <SheetHeader>
          <SheetTitle>{hw?.session?.title || 'Homework'}</SheetTitle>
          <SheetDescription>
            {hw ? (
              <span className="flex flex-wrap items-center gap-2">
                <span>
                  {hw.students?.full_name}
                  {hw.students?.student_code ? ` · ${hw.students.student_code}` : ''}
                </span>
                <Badge variant={HOMEWORK_STATUS_VARIANT[status] || 'secondary'}>{homeworkStatusLabel(hw)}</Badge>
              </span>
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

          {hw && !loading && (
            <>
              <section className="flex flex-col gap-2">
                <Label>Assignment</Label>
                {assignmentUrl ? (
                  <a
                    href={assignmentUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="border-border bg-muted/40 hover:bg-muted flex items-center justify-between gap-3 rounded-md border px-3 py-2 text-sm transition-colors"
                  >
                    <span className="min-w-0 truncate">
                      {assignment.file ? `${assignment.file.file_name} (${formatBytes(assignment.file.size_bytes)})` : assignmentUrl}
                    </span>
                    <ExternalLink className="text-muted-foreground size-4 shrink-0" />
                  </a>
                ) : (
                  <p className="text-muted-foreground text-sm">No homework material on the session yet.</p>
                )}
                {hw.assigned_by_profile && (
                  <p className="text-muted-foreground text-xs">
                    Assigned by {hw.assigned_by_profile.full_name || hw.assigned_by_profile.email}
                    {hw.assigned_at ? ` on ${new Date(hw.assigned_at).toLocaleDateString()}` : ''}
                  </p>
                )}
              </section>

              <Separator />

              <section className="flex flex-col gap-2">
                <Label>Submission</Label>
                {status === 'assigned' ? (
                  <p className="text-muted-foreground text-sm">Awaiting the student's submission.</p>
                ) : hw.submission_visible ? (
                  <FileGallery files={hw.submission} emptyText="No submission files." />
                ) : (
                  <p className="text-muted-foreground text-sm">The submission becomes visible once the tutor has scored it.</p>
                )}
                {hw.submitted_at && <p className="text-muted-foreground text-xs">Submitted {new Date(hw.submitted_at).toLocaleString()}</p>}
              </section>

              <Separator />

              {status === 'submitted' && !canScore && <p className="text-muted-foreground text-sm">Awaiting tutor review.</p>}

              {status === 'submitted' && canScore && (
                <form id="score-homework" onSubmit={handleScore} className="flex flex-col gap-3">
                  <Label>Score</Label>
                  <div className="grid grid-cols-2 gap-3">
                    <Input type="number" min={0} step={1} inputMode="numeric" placeholder="Score" value={score} onChange={(e) => setScore(e.target.value)} disabled={pending} aria-label="Score" />
                    <Input type="number" min={1} step={1} inputMode="numeric" placeholder="Out of" value={maxScore} onChange={(e) => setMaxScore(e.target.value)} disabled={pending} aria-label="Maximum" />
                  </div>
                  {!scoreValid && (score !== '' || maxScore !== '') && (
                    <p className="text-destructive text-xs">Enter a valid score between 0 and the maximum.</p>
                  )}
                  <Label htmlFor="homework-feedback">Feedback (optional)</Label>
                  <textarea
                    id="homework-feedback"
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
                    {hw.score}/{hw.max_score}
                  </p>
                  {hw.feedback && <p className="text-muted-foreground text-sm whitespace-pre-wrap">{hw.feedback}</p>}
                  {hw.scored_by_profile && (
                    <p className="text-muted-foreground text-xs">
                      Scored by {hw.scored_by_profile.full_name || hw.scored_by_profile.email}
                      {hw.scored_at ? ` on ${new Date(hw.scored_at).toLocaleDateString()}` : ''}
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
          {status === 'submitted' && canScore && (
            <Button type="submit" form="score-homework" className="flex-1" disabled={pending || !scoreValid}>
              {pending ? 'Saving…' : 'Save Score'}
            </Button>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}
