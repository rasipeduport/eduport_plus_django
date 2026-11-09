import { ArrowRightIcon, BookOpenIcon, CalendarRangeIcon, GraduationCapIcon, LayersIcon } from 'lucide-react';

import { fromHalves, orderedPlanTypes, planTypeLabel, structureLabel, SUBTITLES, toHalves } from '@/lib/sales';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { SyllabusActions } from '@/components/sales/syllabus-actions';

/** The enquiry's syllabus choice, using only the catalogue's published revision. */
export function CatalogueSyllabusCard({ syllabus, enquiry, pending, onSelect }) {
  const bridge = syllabus.structure === 'BRIDGE_COURSE';
  const regular = toHalves(syllabus.totals.regular);
  const revision = toHalves(syllabus.totals.revision);
  const classes = bridge ? toHalves(syllabus.totals.bridge) : regular !== null && revision !== null ? regular + revision : null;

  return (
    <article className="bg-card flex min-w-0 flex-col gap-5 rounded-xl border p-4 sm:p-5 @[60rem]:flex-row @[60rem]:items-center">
      <div className="grid min-w-0 flex-1 grid-cols-[auto_minmax(0,1fr)] items-start gap-x-4 gap-y-4">
        <div className="bg-primary/10 text-primary flex size-11 items-center justify-center rounded-lg sm:size-14" aria-hidden="true">
          <BookOpenIcon className="size-6 sm:size-7" strokeWidth={1.75} />
        </div>
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
            <h2 className="text-lg font-semibold tracking-tight wrap-anywhere">{syllabus.title}</h2>
            <Badge variant="demo" className="font-medium">{structureLabel(syllabus.structure)}</Badge>
          </div>
          <p className="text-muted-foreground mt-1 text-sm wrap-anywhere">{syllabus.subtitle ?? SUBTITLES[syllabus.structure]}</p>
        </div>
        <div className="col-span-2 flex min-w-0 flex-col gap-4 sm:col-start-2 sm:col-span-1">
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <Badge variant="secondary" className="gap-1.5 font-normal"><GraduationCapIcon /> Grade {syllabus.grade}</Badge>
            <Badge variant="secondary" className="gap-1.5 font-normal"><LayersIcon /> {syllabus.board}</Badge>
            {classes !== null ? (
              <Badge variant="secondary" className="gap-1.5 font-normal tabular-nums">
                <CalendarRangeIcon /> {fromHalves(classes)} {classes === 2n ? 'class' : 'classes'}
              </Badge>
            ) : null}
            {!bridge ? (
              <span className="text-muted-foreground border-l pl-2 tabular-nums">
                {[
                  regular !== null ? `${fromHalves(regular)} Regular` : null,
                  revision !== null ? `${fromHalves(revision)} Revision` : null,
                ].filter(Boolean).join(' · ')}
              </span>
            ) : null}
          </div>
          {!bridge && syllabus.plan_types.length ? (
            <div className="flex flex-wrap items-center gap-1.5 text-xs" aria-label={`Plan options for ${syllabus.title}`}>
              <span className="mr-1 font-medium">Plan options:</span>
              {orderedPlanTypes(syllabus.plan_types).map((type) => (
                <Badge key={type} variant="secondary" className="font-normal">{planTypeLabel(type)}</Badge>
              ))}
            </div>
          ) : null}
        </div>
      </div>
      <div className="flex min-w-0 flex-col gap-4 border-t pt-4 sm:flex-row sm:flex-wrap sm:items-center sm:justify-between @[60rem]:shrink-0 @[60rem]:flex-nowrap @[60rem]:gap-6 @[60rem]:border-t-0 @[60rem]:pt-0">
        <div className="min-w-0 @[60rem]:border-l @[60rem]:pl-5">
          <p className="text-muted-foreground mb-2 text-xs font-medium">Syllabus PDF</p>
          <SyllabusActions key={`${syllabus.id}:${syllabus.revision}`} syllabus={syllabus} enquiry={enquiry} compact />
        </div>
        <Button className="w-full sm:w-auto" onClick={() => onSelect(syllabus)} disabled={pending} aria-label={`Select ${syllabus.title}`}>
          Select Syllabus <ArrowRightIcon />
        </Button>
      </div>
    </article>
  );
}
