import { CalendarDaysIcon, CheckIcon, FileTextIcon } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Card } from '@/components/ui/card';
import { istMoment } from '@/lib/communications';
import { formatDay, slotLabel } from '@/lib/enquiries';
import { bookingReportUrl, reportPdfUrl } from '@/lib/reports';
import { cn } from '@/lib/utils';
import { ViewPdfButton } from '@/components/reports/view-pdf-button';
import { RedemoStatusBadge } from '../booking-badges';
import { StudentTimeLine } from '../student-time';

/** A fact beside the request's name: an icon in a tile, a label, then what it says. */
function Aside({ icon: Icon, label, children }) {
  return (
    <div className="flex min-w-0 items-start gap-3">
      <span className="bg-muted text-muted-foreground flex size-10 shrink-0 items-center justify-center rounded-lg">
        <Icon className="size-5" aria-hidden="true" />
      </span>
      <div className="min-w-0 text-sm">
        <p className="text-muted-foreground">{label}</p>
        {children}
      </div>
    </div>
  );
}

/**
 * The Re-Demo request's header (the API's request in full, `redemo`): the
 * student, their class and syllabus, where the request stands and which
 * Re-Demo of the chain it is, with anything that needs a look; who owns the
 * lead and when it was asked for; then the Demo it repeats -- its slot in IST
 * with the student's own time -- and that Demo's report, to read as a PDF.
 */
export function RedemoHeader({ redemo }) {
  const lead = redemo.lead ?? {};
  const original = redemo.original;
  return (
    <Card className="gap-0 px-5 py-5 sm:px-6">
      <div className="flex flex-col gap-5 lg:flex-row lg:items-center lg:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="truncate text-2xl font-semibold tracking-tight">{redemo.student_name}</h1>
            <RedemoStatusBadge status={redemo.status} />
            <Badge variant="info">Re-Demo {redemo.number ?? 1}</Badge>
            {(redemo.attention ?? []).map((flag) => (
              <Badge key={flag.code} variant="warning">
                {flag.label}
              </Badge>
            ))}
          </div>
          <p className="text-muted-foreground mt-1 text-sm">
            {[lead.grade ?? redemo.grade, lead.syllabus ?? redemo.syllabus].filter(Boolean).join(' • ')}
          </p>
          <p className="text-muted-foreground mt-3 flex flex-wrap gap-x-3 gap-y-1 text-sm">
            <span>BDE: {redemo.owner_bde?.full_name ?? 'No BDE'}</span>
            <span aria-hidden="true">|</span>
            <span>Requested: {istMoment(redemo.requested_at)}</span>
          </p>
        </div>

        <div className="flex flex-col gap-4 sm:flex-row sm:gap-0 lg:shrink-0">
          <div className="sm:pr-6 lg:border-l lg:pl-6">
            <Aside icon={CalendarDaysIcon} label="Original Demo">
              <p className="font-semibold">{slotLabel(original?.slot)}</p>
              <StudentTimeLine startsAt={original?.slot?.starts_at} timezone={redemo.student_timezone} />
              <p className="text-muted-foreground text-sm">Tutor: {original?.tutor?.full_name ?? '—'}</p>
            </Aside>
          </div>
          <div className="sm:border-l sm:pl-6">
            <Aside
              icon={FileTextIcon}
              label={original?.has_report ? `Report (v${original.report_version})` : 'Report'}
            >
              {original?.has_report ? (
                <ViewPdfButton
                  url={reportPdfUrl(bookingReportUrl('DEMO', original.id))}
                  title="Original Demo report"
                  description={`${redemo.student_name} · ${slotLabel(original.slot)}`}
                  variant="link"
                  size="sm"
                  className="h-auto p-0"
                >
                  View PDF
                </ViewPdfButton>
              ) : (
                <p className="text-muted-foreground">No report</p>
              )}
            </Aside>
          </div>
        </div>
      </div>
    </Card>
  );
}

/**
 * Where the request has got to, step by step, as the API reads it from its
 * rows (`progress`): requested, scheduled, the parent's confirmation, taught,
 * reported on, shared -- each done with its date, or still to come. Never
 * worked out here: a step is done because the backend says so.
 */
export function RedemoProgress({ steps }) {
  const shown = steps ?? [];
  return (
    <Card className="px-5 py-5 sm:px-6">
      <div className="overflow-x-auto">
        <ol className="flex min-w-[40rem]" aria-label="Re-Demo progress">
          {shown.map((step, index) => {
            const next = shown[index + 1];
            return (
              <li key={step.key} className="relative flex flex-1 flex-col items-center gap-1.5 text-center">
                {/* The line to the next step: solid once both ends are done. */}
                {next ? (
                  <span
                    className={cn(
                      'absolute top-3.5 left-[calc(50%+1.25rem)] h-0.5 w-[calc(100%-2.5rem)]',
                      step.done && next.done ? 'bg-primary' : 'bg-border'
                    )}
                    aria-hidden="true"
                  />
                ) : null}
                <span
                  className={cn(
                    'relative flex size-7 items-center justify-center rounded-full border-2',
                    step.done ? 'border-primary bg-primary text-primary-foreground' : 'border-border bg-background'
                  )}
                  aria-hidden="true"
                >
                  {step.done ? <CheckIcon className="size-4" /> : null}
                </span>
                <span className={cn('text-sm', step.done ? 'font-medium' : 'text-muted-foreground')}>
                  {step.label}
                  <span className="sr-only">{step.done ? ', done' : ', not yet'}</span>
                </span>
                {step.at ? <span className="text-muted-foreground text-xs">{formatDay(step.at)}</span> : null}
              </li>
            );
          })}
        </ol>
      </div>
    </Card>
  );
}
