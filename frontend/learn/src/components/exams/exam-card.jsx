import { Link } from 'react-router-dom';
import { ChevronRight, Clock, GraduationCap, Play, Video, ClipboardList } from 'lucide-react';
import { Card } from '../ui/card';
import { Button } from '../ui/button';
import { cn } from '../../lib/utils';
import { formatSessionDateTime } from '../../lib/formatting';
import { examStatusBadge } from '../../lib/exam-status';

/** One chapter exam in the Exams list (Learn ExamCard). */
export function ExamCard({ exam, meetLink }) {
  const status = (exam.status || '').toLowerCase();
  const attended = status === 'attended';
  const scheduled = status === 'scheduled';
  const { dateLabel, timeLabel } = formatSessionDateTime(exam.start_time, exam.end_time, {
    relative: scheduled ? 'future' : 'past',
  });
  const badge = examStatusBadge(exam);

  const body = (
    <div className="flex items-start gap-3.5">
      <div className={cn('flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl', attended ? 'bg-primary-subtle' : 'bg-info-subtle')}>
        <ClipboardList className={cn('h-5 w-5', attended ? 'text-primary' : 'text-info')} />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div className="min-w-0 flex-1 basis-32">
            <p className="text-text-muted text-[11px] font-semibold uppercase tracking-wide">Chapter Exam</p>
            <p className="text-text-primary line-clamp-2 text-[15px] leading-snug font-semibold">{exam.chapter_name}</p>
            <div className="text-text-muted mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
              <span className="inline-flex items-center gap-1">
                <Clock className="h-3.5 w-3.5" />
                {dateLabel}, {timeLabel}
              </span>
              {exam.mentor_profile?.full_name && (
                <span className="inline-flex items-center gap-1">
                  <GraduationCap className="h-3.5 w-3.5" />
                  {exam.mentor_profile.full_name}
                </span>
              )}
            </div>
          </div>
          <div className="ml-auto flex shrink-0 items-center gap-2">
            <span className={cn('shrink-0 rounded-full border px-2 py-0.5 text-[11px] font-semibold whitespace-nowrap', badge.className)}>{badge.label}</span>
            {attended && <ChevronRight className="text-text-muted h-4 w-4" />}
          </div>
        </div>
      </div>
    </div>
  );

  if (attended) {
    return (
      <Link to={`/exams/${exam.id}`} className="block">
        <Card padding="md" interactive>
          {body}
        </Card>
      </Link>
    );
  }

  return (
    <Card padding="md">
      {body}
      {scheduled && (
        <div className="mt-4">
          <Button
            variant="primary"
            size="md"
            fullWidth
            icon={<Video className="h-4 w-4" />}
            disabled={!meetLink}
            onClick={() => meetLink && window.open(meetLink, '_blank')}
          >
            {meetLink ? 'Join Exam' : 'Link not available yet'}
          </Button>
        </div>
      )}
      {status === 'cancelled' && exam.recording_link && (
        <a
          href={exam.recording_link}
          target="_blank"
          rel="noopener noreferrer"
          className="text-primary-hover mt-3 inline-flex items-center gap-1.5 text-xs font-semibold"
        >
          <Play className="h-3.5 w-3.5" />
          Recording
        </a>
      )}
    </Card>
  );
}
