import { CheckCheckIcon, DownloadIcon, FileSearchIcon, Loader2Icon, ReceiptTextIcon, XIcon } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { ResponsiveList } from '@/components/page/responsive-list';
import { Field, Fields, WorkspaceCard } from '@/components/bookings/redemo-workspace/parts';
import { classesLabel, formatAmount, toHalves } from '@/lib/sales';

// What a picker chooses: a Bridge Course's days, or a Chapter Plan's chapters in its chosen class mode.
const KINDS = {
  day: { label: 'Day', plural: 'days', column: 'bridge_classes', list: 'Days of the Bridge Course' },
  chapter: { label: 'Chapter', plural: 'chapters', column: 'regular_classes', list: 'Chapters of the Chapter Plan' },
  bridgeChapter: { label: 'Chapter', plural: 'chapters', column: 'bridge_classes', list: 'Chapters of the Bridge Course' },
};

/**
 * A course's chapters to choose from, in the course's order under their own
 * numbers: a box to tick on each, and Select all and Clear. `kind` is 'day'
 * (a Bridge Course's days and their classes) or 'chapter' (a Chapter Plan's
 * chapters and their chosen class mode); `chapters` are the revision's rows;
 * `selected` the ids ticked; `onChange(ids)` gets the next choice, always in
 * the course's order. A table where it fits, a card per row on a narrow screen.
 */
export function ChapterPicker({ kind, chapters, selected, onChange, disabled = false, classMode = 'REGULAR', onClassMode }) {
  const { label, plural, list } = KINDS[kind];
  const modeLabel = classMode === 'REVISION' ? 'Revision' : 'Regular';
  const column = kind === 'chapter' ? `${classMode.toLowerCase()}_classes` : KINDS[kind].column;
  const chosen = new Set(selected);
  const toggle = (id) =>
    onChange(chapters.filter((row) => (row.id === id ? !chosen.has(id) : chosen.has(row.id))).map((row) => row.id));
  const box = (row) => (
    <input
      type="checkbox"
      className="accent-primary size-4 shrink-0"
      checked={chosen.has(row.id)}
      onChange={() => toggle(row.id)}
      disabled={disabled}
      aria-label={`${label} ${row.position}: ${row.name}`}
    />
  );
  const classes = (row) => kind === 'chapter' && toHalves(row[column]) === null ? null : row[column] ?? '0';
  const unavailable = <span className="text-muted-foreground text-xs">{modeLabel} unavailable</span>;
  const columns = [
    { key: 'pick', header: { srOnly: 'Chosen' }, headerClassName: 'w-10', cell: box },
    { key: 'number', header: kind === 'day' ? 'Day' : 'No.', className: 'w-16 tabular-nums', cell: (row) => row.position },
    { key: 'name', header: 'Chapter name', className: 'whitespace-normal', cell: (row) => row.name },
    { key: 'classes', header: kind === 'chapter' ? `${modeLabel} classes` : 'Classes', className: 'w-32 tabular-nums', cell: (row) => classes(row) ?? unavailable },
  ];
  const renderCard = (row) => (
    <label className="bg-card flex cursor-pointer items-start gap-3 rounded-xl border p-3 text-sm">
      {box(row)}
      <span className="min-w-0 flex-1">
        <span className="text-muted-foreground block text-xs tabular-nums">
          {label} {row.position}
        </span>
        <span className="block">{row.name}</span>
      </span>
      <span className="text-muted-foreground max-w-28 shrink-0 text-right tabular-nums">{classes(row) === null ? unavailable : classesLabel(classes(row))}</span>
    </label>
  );
  const count = chapters.filter((row) => chosen.has(row.id)).length;

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-muted-foreground text-sm" aria-live="polite">
          {count} of {chapters.length} {plural} chosen
        </p>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          {kind === 'chapter' && onClassMode ? (
            <fieldset className="flex shrink-0 items-center gap-2" disabled={disabled}>
              <legend className="sr-only">Chapter Plan class type</legend>
              <span className="text-sm font-medium" aria-hidden="true">Class type:</span>
              <div className="bg-muted inline-flex rounded-full border p-0.5">
                {['REGULAR', 'REVISION'].map((mode) => (
                  <label key={mode} className="cursor-pointer">
                    <input type="radio" name="chapter-class-mode" value={mode} checked={classMode === mode} onChange={() => onClassMode(mode)} className="peer sr-only" />
                    <span className="peer-checked:bg-primary peer-checked:text-primary-foreground peer-focus-visible:ring-ring inline-flex h-7 min-w-20 items-center justify-center rounded-full px-3 text-sm font-medium peer-focus-visible:ring-2 peer-disabled:opacity-50">
                      {mode === 'REGULAR' ? 'Regular' : 'Revision'}
                    </span>
                  </label>
                ))}
              </div>
            </fieldset>
          ) : null}
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => onChange(chapters.map((row) => row.id))}
              disabled={disabled || count === chapters.length}
            >
              <CheckCheckIcon className="size-4" />
              Select all
            </Button>
            <Button variant="ghost" size="sm" onClick={() => onChange([])} disabled={disabled || count === 0}>
              <XIcon className="size-4" />
              Clear
            </Button>
          </div>
        </div>
      </div>
      <ResponsiveList label={list} columns={columns} rows={chapters} minTableWidth={520} renderCard={renderCard} />
    </div>
  );
}

/** A Bridge Course's days to choose from (ChapterPicker of its days). */
export function BridgeDayPicker({ days, ...props }) {
  return <ChapterPicker kind="day" chapters={days} {...props} />;
}

/** "Days 2, 4 and 9" -- or, past a dozen, how many. */
function dayList(days) {
  if (days.length > 12) return `${days.length} days`;
  const numbers = days.map((day) => day.position);
  if (numbers.length === 1) return `Day ${numbers[0]}`;
  return `Days ${numbers.slice(0, -1).join(', ')} and ${numbers.at(-1)}`;
}

/**
 * What the days chosen cost (lib/sales bridgeSelection, as the API prices
 * them): the days, their classes, the fee per class, the total and -- when
 * the pricing gives a Bridge Course the privilege -- the single-payment
 * price; every day chosen is the whole course. With Preview and Download of
 * their PDF, and Create quote when `onQuote` is given (a BDE who may issue
 * one), offered once the choice sells some classes and there is pricing --
 * and not while it is `locked` (a revision replaced meanwhile: reload first).
 */
export function SelectionSummary({ selection, totalDays, pricing, pdf, onPreview, onDownload, onQuote, locked = false }) {
  const { days, fullCourse, classes, package: card } = selection;
  const nothing = days.length === 0;
  const noClasses = !nothing && classes === '0';
  const ready = !nothing && !noClasses && Boolean(card) && !locked;
  const currency = pricing?.currency;

  let hint = null;
  if (!pricing) hint = 'Pricing is not set up yet, so these days cannot be priced or drawn.';
  else if (nothing) hint = 'Choose at least one day, or Select all for the full course.';
  else if (noClasses) hint = 'The days chosen have no classes: choose a day that has some.';

  return (
    <WorkspaceCard icon={CheckCheckIcon} title={fullCourse ? 'Full course' : 'Your selection'}>
      {hint ? <p className="text-muted-foreground text-sm">{hint}</p> : null}
      {!nothing ? (
        <Fields>
          <Field label="Package">{card?.title ?? '—'}</Field>
          <Field label="Days">{fullCourse ? `All ${totalDays} days` : `${dayList(days)} of ${totalDays}`}</Field>
          <Field label="Classes">{classesLabel(classes)}</Field>
          {card ? (
            <>
              <Field label="Fee per class">
                <span className="tabular-nums">{formatAmount(card.fee_per_class, currency)}</span>
              </Field>
              <Field label="Total fee">
                <span className="font-semibold tabular-nums">{formatAmount(card.total, currency)}</span>
              </Field>
              {card.single_payment ? (
                <Field label="Single payment">
                  <span className="text-success font-semibold tabular-nums">{formatAmount(card.single_payment.price, currency)}</span>{' '}
                  <span className="text-muted-foreground tabular-nums">(saves {formatAmount(card.single_payment.saving, currency)})</span>
                </Field>
              ) : null}
            </>
          ) : null}
        </Fields>
      ) : null}
      <div className="flex flex-wrap gap-2">
        <Button variant="outline" size="sm" onClick={onPreview} disabled={!ready || Boolean(pdf.pending)}>
          {pdf.pending === 'preview' ? <Loader2Icon className="size-4 animate-spin" /> : <FileSearchIcon className="size-4" />}
          Preview PDF
        </Button>
        <Button size="sm" onClick={onDownload} disabled={!ready || Boolean(pdf.pending)}>
          {pdf.pending === 'download' ? <Loader2Icon className="size-4 animate-spin" /> : <DownloadIcon className="size-4" />}
          Download PDF
        </Button>
        {onQuote ? (
          <Button size="sm" variant="secondary" onClick={onQuote} disabled={!ready || Boolean(pdf.pending)}>
            <ReceiptTextIcon className="size-4" />
            Create quote…
          </Button>
        ) : null}
      </div>
    </WorkspaceCard>
  );
}
