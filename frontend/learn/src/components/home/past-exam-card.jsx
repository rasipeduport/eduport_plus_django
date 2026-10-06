import { Link } from 'react-router-dom';
import { ChevronRight, ClipboardList, Clock } from 'lucide-react';
import { Card } from '../ui/card';
import { cn } from '../../lib/utils';
import { formatSessionDateTime } from '../../lib/formatting';
import { examStatusBadge } from '../../lib/exam-status';

/** "Recent" recap card for the last attended exam (Learn PastExamCard). */
export function PastExamCard({ exam }) {
  const { dateLabel, timeLabel } = formatSessionDateTime(exam.start_time, exam.end_time, { relative: 'past' });
  const badge = examStatusBadge(exam);
  return (
    <Link to={`/exams/${exam.id}`} className="block">
      <Card className="relative" interactive style={{ backgroundImage: 'radial-gradient(circle at top right, rgb(255 214 91 / 0.16), transparent 55%)' }}>
        <div className="mb-3 flex items-start justify-between">
          <div>
            <span className="border-primary/15 bg-primary-subtle text-primary-hover inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold">
              Chapter Exam · {dateLabel}
            </span>
            <p className="text-text-primary mt-1.5 line-clamp-2 text-2xl font-bold tracking-tight">{exam.chapter_name}</p>
          </div>
          <div className="bg-primary-subtle ml-4 flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl">
            <ClipboardList className="text-primary h-5 w-5" />
          </div>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
          <div className="text-text-primary inline-flex items-center gap-1.5 text-sm font-semibold">
            <Clock className="text-text-muted h-4 w-4" />
            {timeLabel}
          </div>
          <div className="ml-auto flex shrink-0 items-center gap-2">
            <span className={cn('rounded-full border px-2 py-0.5 text-[11px] font-semibold whitespace-nowrap', badge.className)}>{badge.label}</span>
            <ChevronRight className="text-text-muted h-4 w-4" />
          </div>
        </div>
      </Card>
    </Link>
  );
}
