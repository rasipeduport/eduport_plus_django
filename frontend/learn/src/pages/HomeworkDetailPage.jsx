import { useCallback, useEffect, useState } from 'react';
import { Link, useLocation, useParams } from 'react-router-dom';
import { ArrowLeft, BookOpen, CheckCircle2, ExternalLink, Loader2 } from 'lucide-react';
import api from '../lib/api';
import { Card } from '../components/ui/card';
import { FileGallery } from '../components/exams/file-gallery';
import { AdditionalSubmitForm } from '../components/exams/additional-submit-form';
import { useStudent } from '../components/student/student-context';
import { cn } from '../lib/utils';
import { formatDate } from '../lib/formatting';
import { homeworkStatusBadge } from '../lib/homework-status';
import { useRefreshOnFocus } from '../hooks/useRefreshOnFocus';

/** Homework detail (Learn /homework/[id]): the assignment, the one-shot submit, the status, the score. */
export default function HomeworkDetailPage() {
  const { id } = useParams();
  const location = useLocation();
  // Opened from the scorecard's recent list: the back link returns there.
  const fromScorecard = location.state?.from === '/scorecard';
  const backTo = fromScorecard ? '/scorecard' : '/sessions';
  const backLabel = fromScorecard ? 'Scorecard' : 'Sessions';
  const { reloadStats, timezone: zone } = useStudent();
  const [hw, setHw] = useState(null);
  const [notFound, setNotFound] = useState(false);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const res = await api.get(`/api/homework/${id}/`);
      setHw(res.data.homework);
      setNotFound(false);
    } catch (err) {
      if (err.response?.status === 404) setNotFound(true);
      else console.error('Failed to load homework', err);
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

  if (notFound || !hw) {
    return (
      <div className="space-y-4">
        <Link to={backTo} className="text-text-muted inline-flex items-center gap-1 text-sm">
          <ArrowLeft className="h-4 w-4" /> {backLabel}
        </Link>
        <p className="text-text-primary text-sm font-semibold">Homework not found.</p>
      </div>
    );
  }

  const status = (hw.status || '').toLowerCase();
  const badge = homeworkStatusBadge(hw);
  const assignmentUrl = (hw.assignment?.url || '').trim();

  return (
    <div className="space-y-5 md:space-y-6">
      <Link to={backTo} className="text-text-muted hover:text-text-primary inline-flex items-center gap-1 text-sm">
        <ArrowLeft className="h-4 w-4" /> {backLabel}
      </Link>

      <section>
        <p className="text-text-muted text-[11px] font-semibold uppercase tracking-wide">Homework</p>
        <div className="mt-1 flex flex-wrap items-center gap-2">
          <h1 className="text-text-primary min-w-0 text-xl font-bold break-words md:text-2xl">{hw.session?.title}</h1>
          <span className={cn('rounded-full border px-2 py-0.5 text-[11px] font-semibold', badge.className)}>{badge.label}</span>
        </div>
        {hw.session?.start_time && <p className="text-text-muted mt-1 text-xs">Class on {formatDate(hw.session.start_time, zone)}</p>}
      </section>

      <section className="space-y-3">
        <h2 className="text-text-secondary text-xs font-semibold uppercase tracking-wide">Your assignment</h2>
        {assignmentUrl ? (
          <a href={assignmentUrl} target="_blank" rel="noopener noreferrer" className="border-border-light bg-surface-elevated hover:bg-surface-muted flex items-center gap-3 rounded-2xl border px-4 py-3 transition-colors">
            <div className="bg-warning-subtle flex h-9 w-9 shrink-0 items-center justify-center rounded-xl">
              <BookOpen className="text-warning h-4 w-4" />
            </div>
            <span className="text-text-primary min-w-0 flex-1 truncate text-sm font-semibold">
              {hw.assignment?.file ? hw.assignment.file.file_name : 'Open homework'}
            </span>
            <ExternalLink className="text-text-muted h-4 w-4 shrink-0" />
          </a>
        ) : (
          <p className="text-text-muted text-sm">No assignment material yet.</p>
        )}
      </section>

      {status === 'assigned' && (
        <section className="space-y-3">
          <h2 className="text-text-secondary text-xs font-semibold uppercase tracking-wide">Your submission</h2>
          <AdditionalSubmitForm
            examId={hw.id}
            submitUrl={`/api/homework/${hw.id}/submit/`}
            successLabel="Homework submitted"
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
              <p className="text-text-secondary text-xs">Your tutor will review it and add a score soon.</p>
            </div>
          </div>
        </Card>
      )}

      {status === 'scored' && (
        <Card padding="md" className="border-primary/15 bg-primary-subtle/40">
          <p className="text-text-secondary text-xs font-semibold uppercase tracking-wide">Your score</p>
          <p className="text-text-primary mt-1 text-3xl font-bold tabular-nums">
            {hw.score}
            <span className="text-text-muted text-lg font-semibold">/{hw.max_score}</span>
          </p>
          {hw.feedback && <p className="text-text-secondary mt-3 text-sm whitespace-pre-wrap">{hw.feedback}</p>}
        </Card>
      )}

      {hw.submission && hw.submission.length > 0 && (
        <section className="space-y-3">
          <h2 className="text-text-secondary text-xs font-semibold uppercase tracking-wide">Your submission</h2>
          <FileGallery files={hw.submission} />
        </section>
      )}
    </div>
  );
}
