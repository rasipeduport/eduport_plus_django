import { ITEM_CHARS, MAX_ITEMS, MAX_SCORE, reportFieldId } from '@/lib/reports';
import { PerformanceLevelField, ReportListField, ReportTextField, ScoreField } from './report-field';

function Part({ title, children }) {
  return (
    <section className="flex flex-col gap-4">
      <h2 className="text-base font-semibold">{title}</h2>
      {children}
    </section>
  );
}

/**
 * The fields a tutor writes for a Diagnostic report, in the Academic Report's
 * order (design F.2): the summary -- score out of a maximum and the
 * performance level -- the strength areas and skills to strengthen, the
 * teacher's remarks and the suggested plan. ``values`` is the form
 * (lib/reports reportForm); ``errors`` names each field's problem; each change
 * is handed to ``onChange(field, value)``.
 */
export function DiagnosticReportForm({ values, errors, onChange, disabled }) {
  const id = reportFieldId;
  return (
    <div className="flex flex-col gap-8">
      <Part title="Summary">
        <div className="grid gap-4 sm:grid-cols-3">
          <ScoreField
            id={id('score')}
            label="Score"
            value={values.score}
            error={errors.score}
            onChange={(value) => onChange('score', value)}
            disabled={disabled}
          />
          <ScoreField
            id={id('max_score')}
            label="Maximum score"
            value={values.max_score}
            error={errors.max_score}
            onChange={(value) => onChange('max_score', value)}
            disabled={disabled}
          />
          <PerformanceLevelField
            id={id('performance_level')}
            value={values.performance_level}
            error={errors.performance_level}
            onChange={(value) => onChange('performance_level', value)}
            disabled={disabled}
          />
        </div>
        <p className="text-muted-foreground -mt-2 text-xs">
          Whole numbers from 0 to {MAX_SCORE}; the score cannot be more than the maximum.
        </p>
      </Part>

      <Part title="Strengths and skills">
        <ReportListField
          id={id('strength_areas')}
          label="Strength areas"
          hint={`One area per line, up to ${MAX_ITEMS}, each at most ${ITEM_CHARS} characters. Enter starts the next.`}
          items={values.strength_areas}
          error={errors.strength_areas}
          onChange={(items) => onChange('strength_areas', items)}
          disabled={disabled}
        />
        <ReportListField
          id={id('skills_to_strengthen')}
          label="Skills to strengthen"
          hint={`One skill per line, up to ${MAX_ITEMS}, each at most ${ITEM_CHARS} characters.`}
          items={values.skills_to_strengthen}
          error={errors.skills_to_strengthen}
          onChange={(items) => onChange('skills_to_strengthen', items)}
          disabled={disabled}
        />
      </Part>

      <Part title="Remarks and plan">
        <ReportTextField
          id={id('teacher_remarks')}
          field="teacher_remarks"
          label="Teacher’s remarks"
          value={values.teacher_remarks}
          error={errors.teacher_remarks}
          onChange={(value) => onChange('teacher_remarks', value)}
          rows={7}
          disabled={disabled}
        />
        <ReportTextField
          id={id('suggested_plan')}
          field="suggested_plan"
          label="Suggested plan"
          hint="Line breaks are kept as you type them."
          value={values.suggested_plan}
          error={errors.suggested_plan}
          onChange={(value) => onChange('suggested_plan', value)}
          rows={4}
          disabled={disabled}
        />
      </Part>
    </div>
  );
}
