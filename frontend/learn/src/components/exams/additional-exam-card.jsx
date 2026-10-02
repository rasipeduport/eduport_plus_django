import { Link } from 'react-router-dom';
import { ChevronRight, FileCheck2 } from 'lucide-react';
import { Card } from '../ui/card';
import { cn } from '../../lib/utils';
import { additionalExamStatusBadge } from '../../lib/exam-status';
import { formatDate } from '../../lib/formatting';

/** One additional exam in the Exams list (Learn AdditionalExamCard); always opens the detail. */
export function AdditionalExamCard({ exam }) {
  const badge = additionalExamStatusBadge(exam);
  return (
    <Link to={`/exams/additional/${exam.id}`} className="block">
      <Card padding="md" interactive>
        <div className="flex items-start gap-3.5">
          <div className="bg-warning-subtle flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl">
            <FileCheck2 className="text-warning h-5 w-5" />
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex items-start justify-between gap-2">
              <div className="flex-1">
                <p className="text-text-muted text-[11px] font-semibold uppercase tracking-wide">Additional Exam</p>
                <p className="text-text-primary line-clamp-2 text-[15px] leading-snug font-semibold">{exam.title}</p>
                <p className="text-text-muted mt-1.5 text-xs">Assigned {formatDate(exam.created_at)}</p>
              </div>
              <div className="flex shrink-0 items-center gap-2">
                <span className={cn('shrink-0 rounded-full border px-2 py-0.5 text-[11px] font-semibold', badge.className)}>{badge.label}</span>
                <ChevronRight className="text-text-muted h-4 w-4" />
              </div>
            </div>
          </div>
        </div>
      </Card>
    </Link>
  );
}
