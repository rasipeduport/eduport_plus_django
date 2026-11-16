import {
  BookOpenIcon,
  ChartColumnIcon,
  CircleCheckIcon,
  CircleUserRoundIcon,
  ClipboardCheckIcon,
  ClipboardListIcon,
  EyeIcon,
  FileTextIcon,
  GraduationCapIcon,
  LightbulbIcon,
  ListChecksIcon,
  MessageSquareTextIcon,
  TargetIcon,
  UserRoundIcon,
} from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { DIAGNOSTIC_ASSESSMENT_TYPE, REPORT_SUBJECT, performanceLevelLabel } from '@/lib/reports';
import { cn } from '@/lib/utils';

// Each performance level's badge: the better the level, the calmer its colour.
const LEVEL_BADGES = {
  EXCELLENT: { variant: 'success' },
  GOOD: { variant: 'info' },
  AVERAGE: { variant: 'warning' },
  BELOW_AVERAGE: { variant: 'outline', className: 'border-destructive/30 bg-destructive/10 text-destructive' },
};

// A section's icon tile, tinted lightly in either theme.
const TONES = {
  info: 'bg-info/10 text-info',
  violet: 'bg-violet-500/10 text-violet-600 dark:text-violet-400',
  warning: 'bg-warning/10 text-warning',
};

const Missing = () => <span className="text-muted-foreground">—</span>;

function Text({ value }) {
  return value ? <p className="break-words whitespace-pre-line">{value}</p> : <Missing />;
}

/**
 * The facts the report's PDF heads it with, in one strip: the student, grade,
 * subject, the assessment (a Diagnostic's) and the tutor. Two or three to a
 * row on a narrow screen; one row, divided, where they all fit.
 */
function InfoStrip({ report, diagnostic }) {
  const facts = [
    { key: 'student', icon: CircleUserRoundIcon, label: 'Student Name', value: report?.student_name },
    { key: 'grade', icon: GraduationCapIcon, label: 'Grade', value: report?.grade },
    { key: 'subject', icon: BookOpenIcon, label: 'Subject', value: REPORT_SUBJECT },
    diagnostic ? { key: 'assessment', icon: ClipboardListIcon, label: 'Assessment Type', value: DIAGNOSTIC_ASSESSMENT_TYPE } : null,
    { key: 'tutor', icon: UserRoundIcon, label: 'Tutor Name', value: report?.tutor_name },
  ].filter(Boolean);
  return (
    <dl
      className={cn(
        'bg-muted/50 grid grid-cols-2 gap-y-4 rounded-lg border px-1 py-3.5 sm:grid-cols-3',
        diagnostic ? 'xl:grid-cols-5 xl:gap-y-0 xl:divide-x' : 'lg:grid-cols-4 lg:gap-y-0 lg:divide-x'
      )}
    >
      {facts.map(({ key, icon: Icon, label, value }) => (
        <div key={key} className="flex min-w-0 items-center gap-3 px-3 lg:px-4">
          <Icon className="text-muted-foreground size-5 shrink-0" aria-hidden="true" />
          <div className="min-w-0">
            <dt className="text-muted-foreground text-xs">{label}</dt>
            <dd className="truncate text-sm font-semibold" title={value || undefined}>
              {value || <Missing />}
            </dd>
          </div>
        </div>
      ))}
    </dl>
  );
}

/** A part of the report: a bordered block under a heading band. */
function DocSection({ icon: Icon, iconClassName, title, bodyClassName, children }) {
  return (
    <section className="bg-card min-w-0 overflow-hidden rounded-lg border">
      <h4 className="bg-muted/40 flex items-center gap-2.5 border-b px-4 py-3 text-sm font-semibold">
        <Icon className={cn('text-muted-foreground size-4 shrink-0', iconClassName)} aria-hidden="true" />
        {title}
      </h4>
      <div className={bodyClassName}>{children}</div>
    </section>
  );
}

/** One written part of the report inside a DocSection: its icon, heading and text. */
function Entry({ icon: Icon, tone, title, children }) {
  return (
    <div className="flex gap-4 px-4 py-4 sm:px-5">
      <span className={cn('flex size-9 shrink-0 items-center justify-center rounded-lg', TONES[tone])}>
        <Icon className="size-4" aria-hidden="true" />
      </span>
      <div className="min-w-0 flex-1">
        <h5 className="text-sm font-semibold">{title}</h5>
        <div className="mt-1 text-sm leading-relaxed">{children}</div>
      </div>
    </div>
  );
}

function Items({ items, dotClassName }) {
  if (!items?.length) return <Missing />;
  return (
    <ul className="space-y-2 text-sm">
      {items.map((item, index) => (
        <li key={index} className="flex gap-2.5">
          <span className={cn('mt-[7px] size-1.5 shrink-0 rounded-full', dotClassName)} aria-hidden="true" />
          <span className="min-w-0 break-words">{item}</span>
        </li>
      ))}
    </ul>
  );
}

/** A Diagnostic's score out of its maximum, and its performance level's badge. */
function ScorePanel({ fields }) {
  const level = fields.performance_level;
  const badge = LEVEL_BADGES[level] ?? { variant: 'secondary' };
  return (
    <dl className="bg-diagnostic/5 border-diagnostic/15 divide-diagnostic/15 grid divide-y rounded-lg border sm:grid-cols-2 sm:divide-x sm:divide-y-0">
      <div className="px-4 py-3">
        <dt className="text-muted-foreground text-xs">Score</dt>
        <dd className="mt-1.5 text-3xl leading-none font-semibold tabular-nums">
          {fields.score ?? '—'}
          <span className="text-muted-foreground text-base font-normal"> / {fields.max_score ?? '—'}</span>
        </dd>
      </div>
      <div className="px-4 py-3">
        <dt className="text-muted-foreground text-xs">Performance Level</dt>
        <dd className="mt-2">
          {level ? (
            <Badge variant={badge.variant} className={badge.className}>
              {performanceLevelLabel(level)}
            </Badge>
          ) : (
            <Missing />
          )}
        </dd>
      </div>
    </dl>
  );
}

/**
 * One saved report, read-only, as a document: the facts its PDF heads it with
 * in one strip (InfoStrip), then what the tutor wrote. A Demo's feedback: its
 * Assessment Review, Class Observation Review and Suggested Strategy, one
 * after another under Feedback Details. A Diagnostic's results: the score and
 * performance level (Results Summary), Strength Areas and Skills to
 * Strengthen side by side, then Teacher's Remarks and Suggested Plan. Every
 * field the PDF prints, in its order and words; how it looks on screen is this
 * page's own -- the PDF stays the server's (ViewPdfButton, PdfDownloadButton).
 * ``report`` is a report as the API answers it: ``fields`` (what the tutor
 * wrote), and ``student_name``, ``grade`` and ``tutor_name`` as printed.
 */
export function ReportDocument({ type, report }) {
  const fields = report?.fields ?? {};
  const diagnostic = type === 'DIAGNOSTIC';

  return (
    <div className="flex flex-col gap-4">
      <InfoStrip report={report} diagnostic={diagnostic} />

      {diagnostic ? (
        <>
          <DocSection icon={ChartColumnIcon} title="Results Summary" bodyClassName="p-4">
            <ScorePanel fields={fields} />
          </DocSection>
          <div className="grid min-w-0 gap-4 lg:grid-cols-2">
            <DocSection icon={CircleCheckIcon} iconClassName="text-success" title="Strength Areas" bodyClassName="p-4">
              <Items items={fields.strength_areas} dotClassName="bg-success" />
            </DocSection>
            <DocSection icon={TargetIcon} iconClassName="text-warning" title="Skills to Strengthen" bodyClassName="p-4">
              <Items items={fields.skills_to_strengthen} dotClassName="bg-warning" />
            </DocSection>
          </div>
          <DocSection icon={FileTextIcon} title="Additional Feedback" bodyClassName="divide-y">
            <Entry icon={MessageSquareTextIcon} tone="violet" title="Teacher’s Remarks">
              <Text value={fields.teacher_remarks} />
            </Entry>
            <Entry icon={ListChecksIcon} tone="info" title="Suggested Plan">
              <Text value={fields.suggested_plan} />
            </Entry>
          </DocSection>
        </>
      ) : (
        <DocSection icon={FileTextIcon} title="Feedback Details" bodyClassName="divide-y">
          <Entry icon={ClipboardCheckIcon} tone="info" title="Assessment Review">
            <Text value={fields.assessment_review} />
          </Entry>
          <Entry icon={EyeIcon} tone="violet" title="Class Observation Review">
            <Text value={fields.class_observation_review} />
          </Entry>
          <Entry icon={LightbulbIcon} tone="warning" title="Suggested Strategy">
            <Text value={fields.suggested_strategy} />
          </Entry>
        </DocSection>
      )}
    </div>
  );
}
