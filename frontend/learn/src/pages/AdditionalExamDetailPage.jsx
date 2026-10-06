import { useCallback, useEffect, useState } from 'react';
import { Link, useLocation, useParams } from 'react-router-dom';
import { ArrowLeft, CheckCircle2, Loader2 } from 'lucide-react';
import api from '../lib/api';
import { Card } from '../components/ui/card';
import { FileGallery } from '../components/exams/file-gallery';
import { AdditionalSubmitForm } from '../components/exams/additional-submit-form';
import { useStudent } from '../components/student/student-context';
import { cn } from '../lib/utils';
import { additionalExamStatusBadge } from '../lib/exam-status';
import { useRefreshOnFocus } from '../hooks/useRefreshOnFocus';

/** Additional exam detail (Learn /exams/additional/[id]): question paper, one-shot submit, score + feedback. */
export default function AdditionalExamDetailPage() {
  const { id } = useParams();
  const location = useLocation();
  // Opened from the scorecard's recent list: the back link returns there.
  const fromScorecard = location.state?.from === '/scorecard';
  const backTo = fromScorecard ? '/scorecard' : '/exams';
  const backLabel = fromScorecard ? 'Scorecard' : 'Exams';
  const { reloadStats } = useStudent();
  const [exam, setExam] = useState(null);
  const [notFound, setNotFound] = useState(false);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const res = await api.get(`/api/additional-exams/${id}/`);
      setExam(res.data.additional_exam);
      setNotFound(false);
    } catch (err) {
      if (err.response?.status === 404) setNotFound(true);
      else console.error('Failed to load exam', err);
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    load();
  }, [load]);
  useRefreshOnFocus(load);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="h-6 w-6 animate-spin text-primary" />
      </div>
    );
  }

  if (notFound || !exam) {
    return (
      <div className="space-y-4">
        <Link to={backTo} className="text-text-muted inline-flex items-center gap-1 text-sm">
          <ArrowLeft className="h-4 w-4" /> {backLabel}
        </Link>
        <p className="text-text-primary text-sm font-semibold">Exam not found.</p>
      </div>
    );
  }

  const status = (exam.status || '').toLowerCase();
  const badge = additionalExamStatusBadge(exam);

  return (
    <div className="space-y-5 md:space-y-6">
      <Link to={backTo} className="text-text-muted hover:text-text-primary inline-flex items-center gap-1 text-sm">
        <ArrowLeft className="h-4 w-4" /> {backLabel}
      </Link>

      <section>
        <p className="text-text-muted text-[11px] font-semibold uppercase tracking-wide">Additional Exam</p>
        <div className="mt-1 flex flex-wrap items-center gap-2">
          <h1 className="text-text-primary text-xl font-bold md:text-2xl">{exam.title}</h1>
          <span className={cn('rounded-full border px-2 py-0.5 text-[11px] font-semibold', badge.className)}>{badge.label}</span>
        </div>
      </section>

      <section className="space-y-3">
        <h2 className="text-text-secondary text-xs font-semibold uppercase tracking-wide">Question paper</h2>
        <FileGallery files={exam.question_paper} emptyText="No question paper uploaded." />
      </section>

      {status === 'assigned' && (
        <section className="space-y-3">
          <h2 className="text-text-secondary text-xs font-semibold uppercase tracking-wide">Your answer sheet</h2>
          <AdditionalSubmitForm
            examId={exam.id}
            onSubmitted={() => {
              load();
              reloadStats?.();
            }}
          />
        </section>
      )}

      {status === 'submitted' && (
        <Card padding="md" className="border-info/15 bg-info-subtle/40">
          <div className="flex items-start gap-3">
            <CheckCircle2 className="text-info mt-0.5 h-5 w-5 shrink-0" />
            <div>
              <p className="text-text-primary text-sm font-semibold">Submitted</p>
              <p className="text-text-secondary text-xs">Your mentor will review it and add a score soon.</p>
            </div>
          </div>
        </Card>
      )}

      {status === 'scored' && (
        <Card padding="md" className="border-primary/15 bg-primary-subtle/40">
          <p className="text-text-secondary text-xs font-semibold uppercase tracking-wide">Your score</p>
          <p className="text-text-primary mt-1 text-3xl font-bold tabular-nums">
            {exam.score}
            <span className="text-text-muted text-lg font-semibold">/{exam.max_score}</span>
          </p>
          {exam.feedback && <p className="text-text-secondary mt-3 text-sm whitespace-pre-wrap">{exam.feedback}</p>}
        </Card>
      )}

      {exam.answer_sheet && exam.answer_sheet.length > 0 && (
        <section className="space-y-3">
          <h2 className="text-text-secondary text-xs font-semibold uppercase tracking-wide">Your answer sheet</h2>
          <FileGallery files={exam.answer_sheet} />
        </section>
      )}
    </div>
  );
}
