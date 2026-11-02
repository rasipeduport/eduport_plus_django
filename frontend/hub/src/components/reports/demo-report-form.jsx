import { reportFieldId } from '@/lib/reports';
import { ReportTextField } from './report-field';

const FIELDS = [
  {
    field: 'assessment_review',
    label: 'Assessment review',
    hint: 'How the student did in the assessment. Write the score here too, for example "Scored 9 out of 12".',
  },
  { field: 'class_observation_review', label: 'Class observation review' },
  { field: 'suggested_strategy', label: 'Suggested strategy' },
];

/**
 * The fields a tutor writes for a Demo report, in the Demo Report's order
 * (design F.2): assessment review, class observation review and suggested
 * strategy. There is no score field (P8 decision): the score goes in the
 * assessment review. Props as DiagnosticReportForm's.
 */
export function DemoReportForm({ values, errors, onChange, disabled }) {
  return (
    <div className="flex flex-col gap-6">
      {FIELDS.map(({ field, label, hint }) => (
        <ReportTextField
          key={field}
          id={reportFieldId(field)}
          field={field}
          label={label}
          hint={hint}
          value={values[field]}
          error={errors[field]}
          onChange={(value) => onChange(field, value)}
          rows={6}
          disabled={disabled}
        />
      ))}
    </div>
  );
}
