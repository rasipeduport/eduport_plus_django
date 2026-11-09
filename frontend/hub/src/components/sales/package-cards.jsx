import { BadgeCheckIcon } from 'lucide-react';

import { classesLabel, formatAmount } from '@/lib/sales';

/**
 * The packages a syllabus's PDF prints (`packages`, from the API or worked
 * out by lib/sales packagePrices), in `currency`: each package's classes, fee
 * per class and total, and its single-payment price where the pricing gives
 * one. Empty, it says why: a Chapter Plan has no card yet. With no
 * single-payment price on any, it says the PDF has no privilege box either.
 */
export function PackageCards({ packages, currency }) {
  if (!packages.length) {
    return (
      <p className="text-muted-foreground text-sm">
        No package card: a Chapter Plan is priced from the chapters a BDE chooses when selling.
      </p>
    );
  }
  return (
    <div className="grid gap-3 md:grid-cols-2">
      {packages.some((item) => item.single_payment) ? null : (
        <p className="text-muted-foreground text-sm md:col-span-2">
          The pricing in effect gives {packages.length === 1 ? 'this package' : 'these packages'} no single-payment
          privilege, so the PDF shows no Single-Payment Privilege box.
        </p>
      )}
      {packages.map((item) => (
        <article key={item.plan_type} className="bg-muted/40 rounded-lg border p-4 text-sm">
          <h3 className="font-medium">{item.title}</h3>
          <p className="text-muted-foreground text-xs">{classesLabel(item.classes)}</p>
          <dl className="mt-3 grid grid-cols-[1fr_auto] gap-x-4 gap-y-1.5">
            <dt className="text-muted-foreground">Fee per class</dt>
            <dd className="text-right font-medium tabular-nums">{formatAmount(item.fee_per_class, currency)}</dd>
            <dt className="text-muted-foreground">Total fee</dt>
            <dd className="text-right font-semibold tabular-nums">{formatAmount(item.total, currency)}</dd>
          </dl>
          {item.single_payment ? (
            <div className="bg-success/10 text-success mt-3 flex items-start gap-2 rounded-md px-3 py-2">
              <BadgeCheckIcon className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
              <p>
                Single payment: <span className="font-semibold tabular-nums">{formatAmount(item.single_payment.price, currency)}</span>{' '}
                <span className="tabular-nums">(saves {formatAmount(item.single_payment.saving, currency)})</span>
              </p>
            </div>
          ) : null}
        </article>
      ))}
    </div>
  );
}
