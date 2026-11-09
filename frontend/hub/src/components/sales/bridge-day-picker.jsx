import { CheckCheckIcon, DownloadIcon, FileSearchIcon, Loader2Icon, ReceiptTextIcon, XIcon } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { ResponsiveList } from '@/components/page/responsive-list';
import { Field, Fields, WorkspaceCard } from '@/components/bookings/redemo-workspace/parts';
import { classesLabel, formatAmount } from '@/lib/sales';

// What a picker chooses: a Bridge Course's days (their Bridge classes), or a Chapter Plan's chapters (their Regular ones).
const KINDS = {
  day: { label: 'Day', plural: 'days', column: 'bridge_classes', list: 'Days of the Bridge Course' },
  chapter: { label: 'Chapter', plural: 'chapters', column: 'regular_classes', list: 'Chapters of the Chapter Plan' },
  bridgeChapter: { label: 'Chapter', plural: 'chapters', column: 'bridge_classes', list: 'Chapters of the Bridge Course' },
};

/**
 * A course's chapters to choose from, in the course's order under their own
 * numbers: a box to tick on each, and Select all and Clear. `kind` is 'day'
 * (a Bridge Course's days and their classes) or 'chapter' (a Chapter Plan's
 * chapters and their Regular classes); `chapters` are the revision's rows;
 * `selected` the ids ticked; `onChange(ids)` gets the next choice, always in
 * the course's order. A table where it fits, a card per row on a narrow screen.
 */
export function ChapterPicker({ kind, chapters, selected, onChange, disabled = false }) {
  const { label, plural, column, list } = KINDS[kind];
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
  const classes = (row) => row[column] ?? '0';
  const columns = [
    { key: 'pick', header: { srOnly: 'Chosen' }, headerClassName: 'w-10', cell: box },
    { key: 'number', header: kind === 'day' ? 'Day' : 'No.', className: 'w-16 tabular-nums', cell: (row) => row.position },
    { key: 'name', header: 'Chapter name', className: 'whitespace-normal', cell: (row) => row.name },
    { key: 'classes', header: kind === 'chapter' ? 'Regular classes' : 'Classes', className: 'w-28 tabular-nums', cell: classes },
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
      <span className="text-muted-foreground shrink-0 tabular-nums">{classesLabel(classes(row))}</span>
    </label>
  );
  const count = chapters.filter((row) => chosen.has(row.id)).length;

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-muted-foreground text-sm" aria-live="polite">
          {count} of {chapters.length} {plural} chosen
        </p>
        <div className="flex flex-wrap gap-2">
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
