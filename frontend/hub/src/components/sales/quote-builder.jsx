import { ReceiptTextIcon } from 'lucide-react';

import { cn } from '@/lib/utils';
import { orderedPlanTypes, planTypeLabel, QUOTE_COLLECTION_MODES } from '@/lib/sales';
import { Button } from '@/components/ui/button';
import { WorkspaceCard } from '@/components/bookings/redemo-workspace/parts';
import { ChapterPicker } from '@/components/sales/bridge-day-picker';
import { QuoteFigures } from '@/components/sales/quote-parts';

// What each plan type of a chapter-wise course quotes, as a BDE chooses it.
const QUOTED_AS = {
  REGULAR: 'The full course: every chapter’s Regular classes.',
  REVISION: 'The exam-oriented course: every chapter’s Revision classes.',
  REGULAR_REVISION: 'Both courses together, as two packages.',
  CHAPTER_PLAN: 'Only the chapters you choose, their classes.',
};

/**
 * Quoting a chapter-wise plan on sale (`detail`, the catalogue's): one of the
 * plan types it is sold as (`planType`, `onPlanType`) -- a Chapter Plan with
 * the chapters ticked (`chapterIds`, `onChapterIds`) -- what that quote would
 * say (`preview`, lib/sales quotePreview) and Create quote (`onCreate`),
 * offered once it sells some classes and not while `locked` (a revision
 * replaced meanwhile: reload first).
 */
export function QuotePlanCard({
  detail,
  planType,
  onPlanType,
  chapterIds,
  onChapterIds,
  preview,
  onCreate,
  locked = false,
  bridgeMode,
  onBridgeMode,
  classMode = 'REGULAR',
  onClassMode,
  selectionError,
  collectionMode,
  onCollectionMode,
}) {
  const bridge = detail.structure === 'BRIDGE_COURSE';
  const chapterPlan = planType === 'CHAPTER_PLAN' || (bridge && bridgeMode === 'selected');
  const nothing = chapterPlan && chapterIds.length === 0;
  const noClasses = !nothing && preview?.classes === '0';
  const ready = Boolean(preview) && !nothing && !noClasses && Boolean(collectionMode) && !locked;

  let hint = null;
  if (selectionError) hint = selectionError;
  else if (nothing) hint = bridge ? 'Choose at least one chapter, or choose Full Bridge Course.' : 'Choose at least one chapter for the Chapter Plan.';
  else if (noClasses)
    hint = bridge
      ? 'The selected chapters have no classes: choose one that has some.'
      : chapterPlan
        ? `The chapters chosen have no ${classMode === 'REVISION' ? 'Revision' : 'Regular'} classes: choose one that has some.`
        : 'This plan has no classes to quote.';

  return (
    <WorkspaceCard icon={ReceiptTextIcon} title="2. Choose a plan">
      <fieldset className="grid gap-2 sm:grid-cols-2" disabled={locked}>
        <legend className="mb-2 text-sm font-medium">Plan</legend>
        {(bridge ? (detail.plan_types.includes('BRIDGE_COURSE') ? ['full', 'selected'] : []) : orderedPlanTypes(detail.plan_types)).map((value) => (
          <label
            key={value}
            className={cn(
              'hover:bg-muted/40 flex cursor-pointer items-start gap-3 rounded-md border p-3 text-sm',
              (bridge ? bridgeMode === value : planType === value) && 'border-primary bg-muted/40'
            )}
          >
            <input
              type="radio"
              name="quote-plan-type"
              value={value}
              checked={bridge ? bridgeMode === value : planType === value}
              onChange={() => (bridge ? onBridgeMode(value) : onPlanType(value))}
              className="mt-0.5"
            />
            <span className="min-w-0">
              <span className="block font-medium">
                {bridge
                  ? value === 'full'
                    ? 'Full Bridge Course'
                    : 'Selected Chapters'
                  : value === 'REGULAR'
                    ? 'Regular Only'
                    : value === 'REVISION'
                      ? 'Revision Only'
                      : planTypeLabel(value)}
              </span>
              <span className="text-muted-foreground block text-xs">
                {bridge
                  ? value === 'full'
                    ? 'Every chapter, with the configured class counts.'
                    : 'Choose chapters from this Bridge Course.'
                  : QUOTED_AS[value]}
              </span>
            </span>
          </label>
        ))}
      </fieldset>
      {chapterPlan ? (
        <ChapterPicker
          kind={bridge ? 'bridgeChapter' : 'chapter'}
          chapters={detail.chapters}
          selected={chapterIds}
          onChange={onChapterIds}
          classMode={classMode}
          onClassMode={onClassMode}
          disabled={locked}
        />
      ) : null}
      {hint ? <p className="text-muted-foreground text-sm wrap-anywhere">{hint}</p> : null}
      {preview?.fullCourse && chapterPlan && !nothing ? <p className="text-muted-foreground text-sm">All chapters selected · Full course</p> : null}
      {preview && !nothing ? <fieldset className="grid gap-2 md:grid-cols-3" disabled={locked}>
        <legend className="mb-2 text-sm font-medium">Collection intention <span className="text-muted-foreground">(required)</span></legend>
        {QUOTE_COLLECTION_MODES.map((option) => <label key={option.value} className={cn('flex cursor-pointer items-start gap-3 rounded-md border p-3 text-sm', collectionMode === option.value && 'border-primary bg-muted/40')}>
          <input type="radio" name="quote-collection-intention" aria-label={option.label} value={option.value} checked={collectionMode === option.value} onChange={() => onCollectionMode(option.value)} className="mt-0.5 accent-primary" required />
          <span><span className="block font-medium">{option.label}</span><span className="text-muted-foreground block text-xs">{option.hint}</span></span>
        </label>)}
      </fieldset> : null}
      {preview && !collectionMode ? <p className="text-muted-foreground text-sm">Choose how the parent intends to pay before creating the quote.</p> : null}
      {preview && !nothing ? <QuoteFigures figures={preview} currency={detail.pricing.currency} /> : null}
      <div>
        <Button onClick={onCreate} disabled={!ready}>
          <ReceiptTextIcon />
          Create quote…
        </Button>
      </div>
    </WorkspaceCard>
  );
}
