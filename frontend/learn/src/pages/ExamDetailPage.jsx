import { useCallback, useEffect, useState } from 'react';
import { Link, useLocation, useParams } from 'react-router-dom';
import { ArrowLeft, Clock, GraduationCap, Loader2, Play } from 'lucide-react';
import api from '../lib/api';
import { Card } from '../components/ui/card';
import { FileGallery } from '../components/exams/file-gallery';
import { cn } from '../lib/utils';
import { examStatusBadge } from '../lib/exam-status';
import { useRefreshOnFocus } from '../hooks/useRefreshOnFocus';

const FULL_DATE = new Intl.DateTimeFormat(undefined, { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric', hour: 'numeric', minute: '2-digit' });

/** Chapter exam detail (Learn /exams/[id]): score, recording, question paper. */
export default function ExamDetailPage() {
  const { id } = useParams();
  const location = useLocation();
  // Opened from the scorecard's recent list: the back link returns there.
  const fromScorecard = location.state?.from === '/scorecard';
  const backTo = fromScorecard ? '/scorecard' : '/exams';
  const backLabel = fromScorecard ? 'Scorecard' : 'Exams';
  const [exam, setExam] = useState(null);
  const [notFound, setNotFound] = useState(false);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const res = await api.get(`/api/exams/${id}/`);
      setExam(res.data.exam);
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
  const badge = examStatusBadge(exam);
  const hasScore = status === 'attended' && exam.score != null && exam.max_score != null;

  return (
    <div className="space-y-5 md:space-y-6">
      <Link to={backTo} className="text-text-muted hover:text-text-primary inline-flex items-center gap-1 text-sm">
        <ArrowLeft className="h-4 w-4" /> {backLabel}
      </Link>

      <section>
        <p className="text-text-muted text-[11px] font-semibold uppercase tracking-wide">Chapter Exam</p>
        <div className="mt-1 flex flex-wrap items-center gap-2">
          <h1 className="text-text-primary min-w-0 text-xl font-bold break-words md:text-2xl">{exam.chapter_name}</h1>
          <span className={cn('rounded-full border px-2 py-0.5 text-[11px] font-semibold', badge.className)}>{badge.label}</span>
        </div>
        <div className="text-text-muted mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
          <span className="inline-flex items-center gap-1">
            <Clock className="h-3.5 w-3.5" />
            {FULL_DATE.format(new Date(exam.start_time))}
          </span>
          {exam.mentor_profile?.full_name && (
            <span className="inline-flex items-center gap-1">
              <GraduationCap className="h-3.5 w-3.5" />
              {exam.mentor_profile.full_name}
            </span>
          )}
        </div>
      </section>

      {hasScore && (
        <Card padding="md" className="border-primary/15 bg-primary-subtle/40">
          <p className="text-text-secondary text-xs font-semibold uppercase tracking-wide">Your score</p>
          <p className="text-text-primary mt-1 text-3xl font-bold tabular-nums">
            {exam.score}
            <span className="text-text-muted text-lg font-semibold">/{exam.max_score}</span>
          </p>
        </Card>
      )}

      {exam.recording_link && (
        <a href={exam.recording_link} target="_blank" rel="noopener noreferrer" className="border-border-light bg-surface-elevated hover:bg-surface-muted flex items-center gap-3 rounded-2xl border px-4 py-3 transition-colors">
          <div className="bg-primary-subtle flex h-9 w-9 items-center justify-center rounded-xl">
            <Play className="text-primary h-4 w-4" />
          </div>
          <span className="text-text-primary text-sm font-semibold">Watch recording</span>
        </a>
      )}

      <section className="space-y-3">
        <h2 className="text-text-secondary text-xs font-semibold uppercase tracking-wide">Question paper</h2>
        <FileGallery files={exam.files} emptyText="No question paper uploaded." />
      </section>
    </div>
  );
}
