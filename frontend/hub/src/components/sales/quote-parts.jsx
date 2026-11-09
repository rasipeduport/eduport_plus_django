import { Badge } from '@/components/ui/badge';
import { Field, Fields } from '@/components/bookings/redemo-workspace/parts';
import { classesLabel, formatAmount, labelOf, QUOTE_STATUSES } from '@/lib/sales';
import { ResponsiveList } from '@/components/page/responsive-list';

const STATUS_VARIANTS = { ISSUED: 'success', CANCELLED: 'destructive' };

/** A quote's status: Issued, or Cancelled for good. */
export function QuoteStatusBadge({ status }) {
  return <Badge variant={STATUS_VARIANTS[status] ?? 'outline'}>{labelOf(QUOTE_STATUSES, status)}</Badge>;
}

/**
 * What a quote says, or would say (lib/sales quotePreview, as the API works
 * it out): each package, with its classes, fee per class, total and
 * single-payment price where it has one; then the total fee, the
 * single-payment saving (when there is one) and what is payable at once --
 * in `currency`.
 */
export function QuoteFigures({ figures, currency }) {
  const saving = Number(figures.single_payment_saving) > 0;
  return (
    <div className="flex flex-col gap-3">
      <ul className="flex flex-col gap-2">
        {figures.lines.map((line) => (
          <li key={line.plan_type} className="bg-muted/40 rounded-lg border p-3 text-sm">
            <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
              <span className="font-medium">{line.title}</span>
              <span className="font-semibold tabular-nums">{formatAmount(line.total, currency)}</span>
            </div>
            <p className="text-muted-foreground text-xs tabular-nums">
              {classesLabel(line.classes)} × {formatAmount(line.fee_per_class, currency)}
              {line.single_payment
                ? ` · single payment ${formatAmount(line.single_payment.price, currency)} (saves ${formatAmount(line.single_payment.saving, currency)})`
                : ''}
            </p>
          </li>
        ))}
      </ul>
      <Fields>
        <Field label="Classes">{classesLabel(figures.classes)}</Field>
        <Field label="Total fee">
          <span className="tabular-nums">{formatAmount(figures.total_fee, currency)}</span>
        </Field>
        {saving ? (
          <Field label="Single-payment saving">
            <span className="text-success tabular-nums">{formatAmount(figures.single_payment_saving, currency)}</span>
          </Field>
        ) : null}
        <Field label="Payable at once">
          <span className="font-semibold tabular-nums">{formatAmount(figures.payable_amount, currency)}</span>
        </Field>
      </Fields>
    </div>
  );
}

/** Saved chapter counts, including the Regular/Revision components quoted. */
export function QuoteChapters({ quote }) {
  const regular = ['REGULAR', 'REGULAR_REVISION'].includes(quote.plan_type) || (quote.plan_type === 'CHAPTER_PLAN' && quote.class_mode !== 'REVISION');
  const revision = ['REVISION', 'REGULAR_REVISION'].includes(quote.plan_type) || (quote.plan_type === 'CHAPTER_PLAN' && quote.class_mode === 'REVISION');
  const columns = [
    { key: 'position', header: 'No.', className: 'w-16 tabular-nums', cell: (row) => row.position },
    { key: 'name', header: 'Chapter', className: 'whitespace-normal', cell: (row) => row.name },
    ...(regular ? [{ key: 'regular', header: 'Regular classes', cell: (row) => row.regular_classes ?? '—' }] : []),
    ...(revision ? [{ key: 'revision', header: 'Revision classes', cell: (row) => row.revision_classes ?? '—' }] : []),
    { key: 'classes', header: 'Selected classes', className: 'tabular-nums', cell: (row) => row.classes },
  ];
  return (
    <ResponsiveList
      label="Selected chapters"
      columns={columns}
      rows={quote.chapters}
      minTableWidth={560}
      renderCard={(row) => (
        <div className="bg-card rounded-lg border p-3 text-sm">
          <p className="font-medium">
            {row.position}. {row.name}
          </p>
          <p className="text-muted-foreground">
            {classesLabel(row.classes)}
            {regular ? ` · Regular ${row.regular_classes ?? '—'}` : ''}
            {revision ? ` · Revision ${row.revision_classes ?? '—'}` : ''}
          </p>
        </div>
      )}
    />
  );
}
