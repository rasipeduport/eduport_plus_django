import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { AlertCircleIcon, ArrowLeftIcon, BadgePercentIcon, CalendarDaysIcon, FileTextIcon, ListOrderedIcon, SearchXIcon } from 'lucide-react';

import api from '@/lib/api';
import {
  bridgeSelection,
  cardPlanTypes,
  catalogueSelectionPdfUrl,
  catalogueUrl,
  formatAmount,
  planTypeLabel,
  salesError,
  structureLabel,
} from '@/lib/sales';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { EmptyState, Page, PageHeader } from '@/components/page/page';
import { AccessDeniedState, ErrorState } from '@/components/page/states';
import { Field, Fields, WorkspaceCard } from '@/components/bookings/redemo-workspace/parts';
import { BridgeDayPicker, SelectionSummary } from '@/components/sales/bridge-day-picker';
import { ChapterTable } from '@/components/sales/chapter-table';
import { PackageCards } from '@/components/sales/package-cards';
import { PlanTypeBadges } from '@/components/sales/syllabus-badges';
import { useSyllabusPdf } from '@/components/sales/syllabus-pdf';
import { SyllabusActions } from '@/components/sales/syllabus-actions';

/**
 * The single-payment privilege as it reaches this plan: the packages it prints (`planTypes`' cards) that the
 * pricing gives it to -- not the pricing's whole list, which may name packages this plan does not sell.
 */
function privilegeLine(pricing, planTypes) {
  const applies = cardPlanTypes(planTypes).filter((planType) => pricing.single_payment_plan_types.includes(planType));
  if (!(Number(pricing.single_payment_percent) > 0) || !applies.length) return 'None for this plan';
  return `${pricing.single_payment_percent}% off ${applies.map(planTypeLabel).join(' and ')} when paid in one instalment`;
}

const BackToPlans = () => (
  <Button variant="outline" asChild>
    <Link to="/plans">
      <ArrowLeftIcon />
      Plans & Pricing
    </Link>
  </Button>
);

/** A published syllabus to browse and share. Student quotes start in an enquiry. */
export default function PlanPage() {
  const { syllabusId } = useParams();
  const [detail, setDetail] = useState(null);
  const [failure, setFailure] = useState(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [selected, setSelected] = useState([]);
  const pdf = useSyllabusPdf();

  useEffect(() => {
    let active = true;
    api
      .get(catalogueUrl(syllabusId))
      .then((response) => {
        if (!active) return;
        setDetail(response.data);
        setFailure(null);
        // A choice survives a reload only where its days do: a new revision's days are new rows.
        const known = new Set(response.data.chapters.map((day) => day.id));
        setSelected((ids) => ids.filter((id) => known.has(id)));
      })
      .catch((err) => {
        if (active) setFailure(salesError(err, 'Could not load the plan.'));
      });
    return () => {
      active = false;
    };
  }, [syllabusId, reloadKey]);

  const reload = () => {
    pdf.clearError();
    setReloadKey((key) => key + 1);
  };

  if (failure?.status === 403) {
    return (
      <Page>
        <AccessDeniedState title="You don't have access to plans and pricing." message={failure.message} />
      </Page>
    );
  }
  if (failure?.status === 404 && !detail) {
    return (
      <Page>
        <EmptyState
          icon={SearchXIcon}
          title="This plan is not on sale"
          description="It may have been withdrawn or replaced. The plans on sale are listed in Plans & Pricing."
          action={<BackToPlans />}
        />
      </Page>
    );
  }
  if (failure && !detail) {
    return (
      <Page>
        <ErrorState message={failure.message} onRetry={reload} />
      </Page>
    );
  }
  if (!detail) {
    return (
      <Page>
        <Skeleton className="h-10 w-72" />
        <Skeleton className="h-64 w-full rounded-xl" />
      </Page>
    );
  }

  const bridge = detail.structure === 'BRIDGE_COURSE';
  const { pricing } = detail;
  const selection = bridge ? bridgeSelection(detail.chapters, selected, pricing) : null;
  // The days, as the API takes them: in the course's order, from the revision shown.
  const request = () => ({
    url: catalogueSelectionPdfUrl(syllabusId),
    data: { revision: detail.revision, chapter_ids: selection.days.map((day) => day.id) },
  });
  const refusal = pdf.refusal;
  const stale = refusal?.code === 'REVISION_CHANGED';
  const gone = refusal?.status === 404;
  return (
    <Page className="max-w-5xl">
      <PageHeader
        title={detail.title}
        description={[`Grade ${detail.grade}`, detail.board, detail.syllabus_version, structureLabel(detail.structure)].filter(Boolean).join(' · ')}
        actions={<BackToPlans />}
        actionsClassName="items-center"
      />

      {stale ? (
        <div role="alert" className="border-destructive/30 bg-destructive/5 flex flex-wrap items-center gap-3 rounded-xl border px-4 py-3">
          <AlertCircleIcon className="text-destructive size-4 shrink-0" aria-hidden="true" />
          <p className="min-w-0 flex-1 text-sm">
            This plan was updated{refusal.revision ? ` to revision ${refusal.revision}` : ''} since you opened it. Reload it and
            {bridge ? ' choose the days again.' : ' check the quote again.'}
          </p>
          <Button variant="outline" size="sm" onClick={reload}>
            Reload
          </Button>
        </div>
      ) : null}
      {gone ? <ErrorState message="This plan is no longer on sale." /> : null}
      {pdf.error && !stale && !gone ? <ErrorState message={pdf.error} /> : null}

      <SyllabusActions syllabus={detail} disabled={!pricing} />

      <WorkspaceCard icon={FileTextIcon} title="Plan">
        <Fields>
          <Field label="PDF title">
            {detail.title}
            <p className="text-muted-foreground text-xs font-normal">{detail.subtitle}</p>
          </Field>
          <Field label="Grade">Grade {detail.grade}</Field>
          <Field label="Board">{detail.board}</Field>
          {detail.syllabus_version ? <Field label="Syllabus version">{detail.syllabus_version}</Field> : null}
          <Field label="Sold as">
            <PlanTypeBadges planTypes={detail.plan_types} />
            {bridge ? <p className="text-muted-foreground text-xs font-normal">The whole course, or any of its days.</p> : null}
          </Field>
          {pricing ? (
            <>
              <Field label="Fee per class">
                <span className="tabular-nums">{formatAmount(pricing.offer_fee, pricing.currency)}</span>
                <span className="text-muted-foreground font-normal tabular-nums">
                  {' '}
                  (standard {formatAmount(pricing.standard_fee, pricing.currency)})
                </span>
              </Field>
              <Field label="Single payment">{privilegeLine(pricing, detail.plan_types)}</Field>
            </>
          ) : (
            <Field label="Pricing">Not set up yet: packages cannot be priced and PDFs cannot be drawn.</Field>
          )}
        </Fields>
      </WorkspaceCard>

      {bridge ? (
        <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_20rem]">
          {/* Before the days on a phone, beside them -- and in view while they are ticked -- on a wide screen. */}
          <div className="lg:sticky lg:top-20 lg:order-last">
            <SelectionSummary
              selection={selection}
              totalDays={detail.chapters.length}
              pricing={pricing}
              pdf={pdf}
              onPreview={() => pdf.preview(request())}
              onDownload={() => pdf.download(request())}
              locked={stale || gone}
            />
          </div>
          <WorkspaceCard icon={CalendarDaysIcon} title="Choose the days">
            <BridgeDayPicker days={detail.chapters} selected={selected} onChange={setSelected} disabled={stale} />
          </WorkspaceCard>
        </div>
      ) : (
        <>
          <WorkspaceCard icon={ListOrderedIcon} title="Chapters">
            <ChapterTable revision={detail} />
          </WorkspaceCard>
          <WorkspaceCard icon={BadgePercentIcon} title="Packages">
            {pricing ? (
              <PackageCards packages={detail.packages ?? []} currency={pricing.currency} />
            ) : (
              <p className="text-muted-foreground text-sm">Pricing is not set up yet, so the packages cannot be priced.</p>
            )}
          </WorkspaceCard>
        </>
      )}

      {detail.inclusions.length ? (
        <WorkspaceCard icon={BadgePercentIcon} title="Inclusions">
          <ul className="text-muted-foreground list-disc pl-5 text-sm">
            {detail.inclusions.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </WorkspaceCard>
      ) : null}
      <WorkspaceCard title="Choose this syllabus for a student">
        <p className="text-muted-foreground text-sm">Open the student's enquiry and select Plan Choosing to configure a plan and create a quote.</p>
        <div>
          <Button asChild>
            <Link to="/enquiries">My Enquiries</Link>
          </Button>
        </div>
      </WorkspaceCard>
      {pdf.dialog}
    </Page>
  );
}
