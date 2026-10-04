import { ClipboardList, ExternalLink, FileText, Video } from 'lucide-react';
import { Link } from 'react-router-dom';
import { format } from 'date-fns';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import {
  ADDITIONAL_STATUS_VARIANT,
  EXAM_STATUS_VARIANT,
  additionalExamStatusLabel,
  examStatusLabel,
  isHttpsUrl,
} from '@/lib/exam-status';
import { EMPTY, EmptyState, ProfileTable, SectionHeading, Td } from './profile-primitives';

const CHAPTER_COLUMNS = [
  { key: 'when', label: 'When' },
  { key: 'chapter', label: 'Chapter' },
  { key: 'status', label: 'Status' },
  { key: 'result', label: 'Result' },
  { key: 'paper', label: 'Question paper' },
  { key: 'recording', label: 'Recording' },
];

const ADDITIONAL_COLUMNS = [
  { key: 'title', label: 'Title' },
  { key: 'status', label: 'Status' },
  { key: 'result', label: 'Result' },
  { key: 'submitted', label: 'Submitted' },
  { key: 'actions', label: '', className: 'w-24' },
];

function pct(score, maxScore) {
  if (score == null || !maxScore) return null;
  return Math.round((score / maxScore) * 100);
}

function ResultCell({ score, maxScore }) {
  const percentage = pct(score, maxScore);
  if (percentage == null) return <span className="text-muted-foreground">{EMPTY}</span>;
  return (
    <span className="whitespace-nowrap tabular-nums">
      {score}/{maxScore}
      <span className="text-muted-foreground ml-1.5 text-xs">{percentage}%</span>
    </span>
  );
}

/**
 * Exams tab: the chapter exams the mentor ran with this student and the
 * additional exams they were set. Mentor/admin only — tutors are not part of
 * the exam flow, so the tab is never rendered for them.
 */
export function ExamsTab({ exams, additionalExams, stats, studentId, onOpenAdditional }) {
  const average = stats?.chapter?.average_pct;

  return (
    <div className="flex flex-col gap-8">
      <section className="flex flex-col gap-4">
        <SectionHeading
          title="Chapter exams"
          description={
            average != null
              ? `${stats.chapter.scored} scored, averaging ${average}%.`
              : 'Live exams between the mentor and the student, scored out of a maximum.'
          }
          action={
            <Button variant="outline" size="sm" asChild>
              <Link to={`/exams?student_id=${studentId}`}>Manage in Exams</Link>
            </Button>
          }
        />
        {exams.length === 0 ? (
          <EmptyState icon={ClipboardList} message="No chapter exams yet." />
        ) : (
          <ProfileTable
            columns={CHAPTER_COLUMNS}
            rows={exams}
            keyOf={(exam) => exam.id}
            emptyMessage="No chapter exams yet."
            renderRow={(exam) => {
              const status = (exam.status || '').toLowerCase();
              const recording = (exam.recording_link || '').trim();
              const badge = (
                <Badge variant={EXAM_STATUS_VARIANT[status] || 'secondary'}>{examStatusLabel(exam)}</Badge>
              );
              return (
                <>
                  <Td className="whitespace-nowrap">
                    <span className="block text-sm">{format(new Date(exam.start_time), 'd MMM yyyy')}</span>
                    <span className="text-muted-foreground text-xs">
                      {format(new Date(exam.start_time), 'h:mm a')}
                    </span>
                  </Td>
                  <Td>
                    <span className="block max-w-56 truncate font-medium" title={exam.chapter_name}>
                      {exam.chapter_name}
                    </span>
                  </Td>
                  <Td>
                    {status === 'cancelled' && exam.cancellation_reason ? (
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <span className="cursor-help">{badge}</span>
                        </TooltipTrigger>
                        <TooltipContent>
                          <p className="max-w-xs">{exam.cancellation_reason}</p>
                        </TooltipContent>
                      </Tooltip>
                    ) : (
                      badge
                    )}
                  </Td>
                  <Td>
                    <ResultCell score={exam.score} maxScore={exam.max_score} />
                  </Td>
                  <Td className="text-muted-foreground text-sm whitespace-nowrap">
                    {exam.file_count > 0 ? (
                      <span className="inline-flex items-center gap-1">
                        <FileText className="size-3.5" />
                        {exam.file_count} {exam.file_count === 1 ? 'file' : 'files'}
                      </span>
                    ) : (
                      EMPTY
                    )}
                  </Td>
                  <Td>
                    {recording && isHttpsUrl(recording) ? (
                      <a
                        href={recording}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="hover:bg-accent inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-xs transition-colors"
                      >
                        <Video className="size-3" />
                        Open
                      </a>
                    ) : (
                      <span className="text-muted-foreground">{EMPTY}</span>
                    )}
                  </Td>
                </>
              );
            }}
          />
        )}
      </section>

      <section className="flex flex-col gap-4">
        <SectionHeading
          title="Additional exams"
          description="Question paper from the mentor, answer sheet from the student, scored with feedback."
        />
        {additionalExams.length === 0 ? (
          <EmptyState icon={ExternalLink} message="No additional exams assigned." />
        ) : (
          <ProfileTable
            columns={ADDITIONAL_COLUMNS}
            rows={additionalExams}
            keyOf={(exam) => exam.id}
            emptyMessage="No additional exams assigned."
            renderRow={(exam) => (
              <>
                <Td>
                  <span className="block max-w-56 truncate font-medium" title={exam.title}>
                    {exam.title}
                  </span>
                  <span className="text-muted-foreground text-xs">
                    Assigned {format(new Date(exam.created_at), 'd MMM yyyy')}
                  </span>
                </Td>
                <Td>
                  <Badge variant={ADDITIONAL_STATUS_VARIANT[(exam.status || '').toLowerCase()] || 'secondary'}>
                    {additionalExamStatusLabel(exam)}
                  </Badge>
                </Td>
                <Td>
                  <ResultCell score={exam.score} maxScore={exam.max_score} />
                </Td>
                <Td className="text-muted-foreground text-sm whitespace-nowrap">
                  {exam.submitted_at ? format(new Date(exam.submitted_at), 'd MMM, h:mm a') : EMPTY}
                </Td>
                <Td className="text-right">
                  <Button variant="outline" size="sm" onClick={() => onOpenAdditional(exam.id)}>
                    {(exam.status || '').toLowerCase() === 'submitted' ? 'Score' : 'View'}
                  </Button>
                </Td>
              </>
            )}
          />
        )}
      </section>
    </div>
  );
}
