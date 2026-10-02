import { Clock, GraduationCap, Link as LinkIcon, Video } from 'lucide-react';
import { Card } from '../ui/card';
import { Button } from '../ui/button';
import { formatSessionDateTime } from '../../lib/formatting';

/** "Up next — your exam" hero (Learn LiveExamCard): the exam joins the student's own meet room. */
export function LiveExamCard({ meetLink, exam }) {
  const { dateLabel, timeLabel } = formatSessionDateTime(exam.start_time, exam.end_time);
  return (
    <Card className="relative" style={{ backgroundImage: 'radial-gradient(circle at top right, rgb(255 214 91 / 0.16), transparent 55%)' }}>
      <div>
        <div className="mb-3 flex items-start justify-between">
          <div>
            <span className="border-info/15 bg-info-subtle text-info inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold">
              Chapter Exam · {dateLabel}
            </span>
            <p className="text-text-primary mt-1.5 line-clamp-2 text-2xl font-bold tracking-tight">{exam.chapter_name}</p>
          </div>
          <div className="bg-info-subtle ml-4 flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl">
            <Video className="text-info h-5 w-5" />
          </div>
        </div>

        <div className="mb-4 flex flex-wrap items-center gap-x-3 gap-y-1">
          <div className="text-text-primary inline-flex items-center gap-1.5 text-sm font-semibold">
            <Clock className="text-text-muted h-4 w-4" />
            {timeLabel}
          </div>
          {exam.mentor_profile?.full_name && (
            <div className="text-text-muted inline-flex items-center gap-1.5 text-xs">
              <GraduationCap className="h-3.5 w-3.5" />
              {exam.mentor_profile.full_name}
            </div>
          )}
        </div>

        <div className="border-border-light mb-4 border-t" />

        {meetLink ? (
          <div className="border-primary/10 bg-primary-subtle/70 mb-4 flex items-center gap-3 rounded-xl border px-4 py-3">
            <div className="bg-primary flex h-7 w-7 shrink-0 items-center justify-center rounded-lg">
              <LinkIcon className="h-3.5 w-3.5 text-white" />
            </div>
            <span className="text-text-secondary truncate text-sm">{meetLink.replace(/^https?:\/\//, '')}</span>
          </div>
        ) : (
          <div className="border-border-light bg-surface-muted mb-4 flex items-center gap-3 rounded-xl border px-4 py-3">
            <div className="bg-border flex h-7 w-7 shrink-0 items-center justify-center rounded-lg">
              <LinkIcon className="text-text-muted h-3.5 w-3.5" />
            </div>
            <span className="text-text-muted truncate text-sm italic">Link not available yet</span>
          </div>
        )}

        <Button variant="primary" size="lg" fullWidth icon={<Video className="h-5 w-5" />} disabled={!meetLink} onClick={() => meetLink && window.open(meetLink, '_blank')}>
          Join Exam
        </Button>
      </div>
    </Card>
  );
}
