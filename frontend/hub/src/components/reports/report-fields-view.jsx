import { Badge } from '@/components/ui/badge';
import { DIAGNOSTIC_ASSESSMENT_TYPE, REPORT_SUBJECT, performanceLevelLabel } from '@/lib/reports';

function Changed({ show }) {
  return show ? (
    <Badge variant="info" className="font-normal">
      Changed
    </Badge>
  ) : null;
}

function Detail({ label, changed, children }) {
  return (
    <div className="grid grid-cols-[8rem_1fr] gap-3 py-2">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="flex min-w-0 flex-wrap items-center gap-2 font-medium break-words">
        {children || <span className="text-muted-foreground">—</span>}
        <Changed show={changed} />
      </dd>
    </div>
  );
}

function Block({ title, changed, children }) {
  return (
    <section className="flex flex-col gap-1.5">
      <h4 className="flex items-center gap-2 font-semibold">
        {title}
        <Changed show={changed} />
      </h4>
      {children}
    </section>
  );
}

function Items({ items }) {
  if (!items?.length) return <p className="text-muted-foreground">—</p>;
  return (
    <ul className="list-disc space-y-1 pl-5">
      {items.map((item, index) => (
        <li key={index} className="break-words">
          {item}
        </li>
      ))}
    </ul>
  );
}

function Text({ value }) {
  return value ? (
    <p className="break-words whitespace-pre-line">{value}</p>
  ) : (
    <p className="text-muted-foreground">—</p>
  );
}

/**
 * One report, read-only, as its PDF prints it: the student, class, subject
 * and tutor, then its sections in the PDF's order. ``report`` is a report as
 * the API answers it (or one of its revisions): ``fields`` (what the tutor
 * wrote), ``student_name``, ``grade`` and ``tutor_name`` (as printed).
 * ``changedFields`` marks what one version changed (a revision's
 * changed_fields).
 */
export function ReportFieldsView({ type, report, changedFields = [] }) {
  const fields = report?.fields ?? {};
  const changed = new Set(changedFields);
  const any = (...names) => names.some((name) => changed.has(name));

  return (
    <div className="flex flex-col gap-4 text-sm">
      <dl className="divide-y">
        <Detail label="Student Name" changed={any('student_name_snapshot')}>
          {report?.student_name}
        </Detail>
        <Detail label="Grade" changed={any('grade_snapshot')}>
          {report?.grade}
        </Detail>
        <Detail label="Subject">{REPORT_SUBJECT}</Detail>
        {type === 'DIAGNOSTIC' ? <Detail label="Assessment Type">{DIAGNOSTIC_ASSESSMENT_TYPE}</Detail> : null}
        <Detail label="Tutor Name" changed={any('tutor_name_snapshot')}>
          {report?.tutor_name}
        </Detail>
      </dl>

      {type === 'DIAGNOSTIC' ? (
        <>
          <Block title="Summary" changed={any('score', 'max_score', 'performance_level')}>
            <p>
              Score: {fields.score ?? '—'}/{fields.max_score ?? '—'}
            </p>
            <p>Performance Level: {performanceLevelLabel(fields.performance_level) || '—'}</p>
          </Block>
          <Block title="Strength Areas" changed={any('strength_areas')}>
            <Items items={fields.strength_areas} />
          </Block>
          <Block title="Skills to Strengthen" changed={any('skills_to_strengthen')}>
            <Items items={fields.skills_to_strengthen} />
          </Block>
          <Block title="Teacher’s Remarks" changed={any('teacher_remarks')}>
            <Text value={fields.teacher_remarks} />
          </Block>
          <Block title="Suggested Plan" changed={any('suggested_plan')}>
            <Text value={fields.suggested_plan} />
          </Block>
        </>
      ) : (
        <>
          <Block title="Assessment Review" changed={any('assessment_review')}>
            <Text value={fields.assessment_review} />
          </Block>
          <Block title="Class Observation Review" changed={any('class_observation_review')}>
            <Text value={fields.class_observation_review} />
          </Block>
          <Block title="Suggested Strategy" changed={any('suggested_strategy')}>
            <Text value={fields.suggested_strategy} />
          </Block>
        </>
      )}
    </div>
  );
}
