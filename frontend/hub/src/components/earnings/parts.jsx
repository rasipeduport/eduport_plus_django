import { Link } from 'react-router-dom';
import {
  CalendarClockIcon,
  ListChecksIcon,
  MoreVerticalIcon,
  ReceiptIndianRupeeIcon,
  UserCheckIcon,
  WalletIcon,
} from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { Table, TableBody, TableCell, TableFooter, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Panel, PanelEmpty } from '@/components/dashboard/dashboard-primitives';
import { FilterSelect } from '@/components/page/list-toolbar';
import { Pagination } from '@/components/page/pagination';
import {
  CLASS_TYPES,
  CONVERSION,
  CONVERSION_NOTE,
  NOT_COUNTED_REASONS,
  balanceLabel,
  classSubject,
  classTypeLabel,
  dayLabel,
  formatInr,
  monthLabel,
  rateLabel,
  stampLabel,
  timeLabel,
  trimUnits,
  unitsLabel,
  whyItCounts,
} from '@/lib/earnings';
import { cn } from '@/lib/utils';

/**
 * The pieces the Tutor Earnings pages share -- the Admin's overview and one
 * tutor's page, and a tutor's My Earnings. Each shows what the API served;
 * the actions (`onVoid`, `onReverse`) are offered only where the caller passes them.
 */

/** Where a rate came from: the tutor's own, or the global one. */
export function RateSourceBadge({ source }) {
  if (source === 'TUTOR') return <Badge variant="info">Tutor rate</Badge>;
  if (source === 'GLOBAL') return <Badge variant="outline">Global rate</Badge>;
  return null;
}

/** What a tutor is owed: the amount pending, paid in full, overpaid, or nothing yet. */
export function BalanceBadge({ state, outstanding }) {
  const variant = { pending: 'warning', paid: 'success', overpaid: 'destructive' }[state] || 'outline';
  return <Badge variant={variant}>{balanceLabel(state, outstanding)}</Badge>;
}

/** The period: every month since the activation, or one (`value` "YYYY-MM", '' for all time). */
export function MonthFilter({ months, value, onChange }) {
  return (
    <FilterSelect
      label="Period"
      placeholder="All time"
      value={value}
      onChange={onChange}
      options={(months || []).map((month) => ({ value: month, label: monthLabel(month) }))}
    />
  );
}

/** When the sync last ran: earnings appear within 10 minutes of a class counting. */
export function SyncNote({ lastSync, className }) {
  return (
    <p className={cn('text-muted-foreground text-xs', className)}>
      Updated by the earnings sync every 10 minutes
      {lastSync?.finished_at ? ` · last run ${stampLabel(lastSync.finished_at)}` : ' · not run yet'}.
    </p>
  );
}

/**
 * Per class type: its classes, payable units, the rate (a line per rate --
 * and, for an administrator, per rate source) and what it earned; with the
 * period's adjustments and the total. Demo Conversion has a row of its own:
 * the Demos converted, the conversion rate they reached and only what that
 * added over the Demos' own earnings -- so no Demo is counted twice, and the
 * class total leaves the conversions out.
 */
export function BreakdownCard({ breakdown, adjustments, total, admin }) {
  const rows = breakdown.flatMap((type) =>
    (type.lines.length ? type.lines : [null]).map((line, index) => ({ type, line, first: index === 0 }))
  );
  const adjusted = Number(adjustments) !== 0;
  const classes = breakdown.filter((type) => type.class_type !== CONVERSION).reduce((sum, type) => sum + type.classes, 0);
  return (
    <Panel
      icon={ListChecksIcon}
      title="Earnings by class type"
      subtitle="Normal Sessions are paid per class hour. Demo Conversion adds the conversion rate less what the Demo earned."
    >
      <div className="overflow-x-auto">
        <Table aria-label="Earnings by class type">
          <TableHeader>
            <TableRow>
              <TableHead>Class type</TableHead>
              <TableHead className="text-right">Classes</TableHead>
              <TableHead className="text-right">Payable units</TableHead>
              <TableHead className="text-right">{admin ? 'Rate' : 'Your rate'}</TableHead>
              {admin ? <TableHead>Rate applied</TableHead> : null}
              <TableHead className="text-right">Earned</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map(({ type, line, first }) => {
              const conversion = type.class_type === CONVERSION;
              return (
                <TableRow key={`${type.class_type}-${line?.rate ?? 'none'}-${line?.rate_source ?? ''}`}>
                  <TableCell className="font-medium">
                    {first ? classTypeLabel(type.class_type) : null}
                    {first && conversion ? (
                      <span className="text-muted-foreground block text-xs font-normal">Converted Demos · rate − Demo earning</span>
                    ) : null}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">{line ? line.classes : 0}</TableCell>
                  <TableCell className="text-right tabular-nums">
                    {line ? unitsLabel(line.units, type.unit) : '—'}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">{line ? rateLabel(line.rate, type.unit) : '—'}</TableCell>
                  {admin ? <TableCell>{line ? <RateSourceBadge source={line.rate_source} /> : null}</TableCell> : null}
                  <TableCell className="text-right font-medium tabular-nums">
                    {formatInr(line ? line.amount : 0, { signed: conversion })}
                  </TableCell>
                </TableRow>
              );
            })}
            {adjusted ? (
              <TableRow>
                <TableCell className="font-medium">Adjustments</TableCell>
                <TableCell colSpan={admin ? 4 : 3} className="text-muted-foreground text-sm">
                  Added, deducted or reversed by an administrator, each with its reason.
                </TableCell>
                <TableCell className="text-right font-medium tabular-nums">{formatInr(adjustments, { signed: true })}</TableCell>
              </TableRow>
            ) : null}
          </TableBody>
          <TableFooter>
            <TableRow>
              <TableCell>Total</TableCell>
              <TableCell className="text-right tabular-nums" title="Classes taught; conversions are not classes">
                {classes}
              </TableCell>
              <TableCell colSpan={admin ? 3 : 2} />
              <TableCell className="text-right tabular-nums">{formatInr(total)}</TableCell>
            </TableRow>
          </TableFooter>
        </Table>
      </div>
      {breakdown.some((type) => type.class_type === CONVERSION) ? (
        <p className="text-muted-foreground mt-2 text-xs">Demo Conversion: {CONVERSION_NOTE}</p>
      ) : null}
    </Panel>
  );
}

/**
 * The Demos of a period and what converting them added: the eligible Demos
 * (by their scheduled end), the Demos converted (by the enrollment), the
 * Demos' own earnings, the conversion incentives on top of them -- never the
 * Demos again -- and the period's total earnings. Every figure is the API's.
 */
export function DemoConversionCard({ counts, total, period }) {
  const figures = [
    { label: 'Eligible Demos', value: counts.demo, hint: 'By the Demo’s scheduled end' },
    { label: 'Converted Demos', value: counts.conversions ?? 0, hint: 'By the enrollment date' },
    { label: 'Demo earnings', value: formatInr(counts.demo_earned ?? 0), hint: 'The Demos’ own rate' },
    {
      label: 'Conversion incentives',
      value: formatInr(counts.conversion_earned ?? 0, { signed: Number(counts.conversion_earned) > 0 }),
      hint: 'Conversion rate − Demo earning',
    },
    { label: 'Total earnings', value: formatInr(total), hint: 'Every class type and adjustment' },
  ];
  return (
    <Panel icon={UserCheckIcon} title="Demo conversions" subtitle={`${period} · a converted Demo earns the conversion rate in all`}>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-3 xl:grid-cols-5">
        {figures.map((figure) => (
          <div key={figure.label} className="min-w-0">
            <dt className="text-muted-foreground text-xs">{figure.label}</dt>
            <dd className="text-lg font-semibold tabular-nums">{figure.value}</dd>
            <dd className="text-muted-foreground text-xs">{figure.hint}</dd>
          </div>
        ))}
      </dl>
    </Panel>
  );
}

/**
 * By month (each class by its scheduled end, a Demo conversion by its
 * enrollment, India time): the classes that count, the conversions and what
 * was earned -- every entry of the month, so the months add up to the ledger.
 */
export function MonthsCard({ months, onPick }) {
  return (
    <Panel
      icon={CalendarClockIcon}
      title="By month"
      subtitle="Classes count in the month their scheduled end falls in; a Demo conversion in the month the student enrolled (India time)."
    >
      {months.length ? (
        <div className="overflow-x-auto">
          <Table aria-label="Earnings by month">
            <TableHeader>
              <TableRow>
                <TableHead>Month</TableHead>
                <TableHead className="text-right">Diagnostic</TableHead>
                <TableHead className="text-right">Demo</TableHead>
                <TableHead className="text-right">Sessions</TableHead>
                <TableHead className="text-right">Session hours</TableHead>
                <TableHead className="text-right">Conversions</TableHead>
                <TableHead className="text-right">Earned</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {months.map((row) => (
                <TableRow key={row.month}>
                  <TableCell className="font-medium">
                    {onPick ? (
                      <button type="button" className="underline-offset-4 hover:underline" onClick={() => onPick(row.month)}>
                        {monthLabel(row.month)}
                      </button>
                    ) : (
                      monthLabel(row.month)
                    )}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">{row.diagnostic}</TableCell>
                  <TableCell className="text-right tabular-nums">{row.demo}</TableCell>
                  <TableCell className="text-right tabular-nums">{row.sessions}</TableCell>
                  <TableCell className="text-right tabular-nums">{trimUnits(row.session_hours)} h</TableCell>
                  <TableCell className="text-right tabular-nums">
                    {row.conversions ?? 0}
                    {Number(row.conversions) > 0 ? (
                      <span className="text-muted-foreground block text-xs">{formatInr(row.conversion_earned, { signed: true })}</span>
                    ) : null}
                  </TableCell>
                  <TableCell className="text-right font-medium tabular-nums">{formatInr(row.earned)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      ) : (
        <PanelEmpty icon={CalendarClockIcon} message="Nothing earned yet." />
      )}
    </Panel>
  );
}

/** Where to act on a class not counted yet, for a tutor: their notes, or their booking's report. */
function notCountedAction(item) {
  if (item.reason === 'NOTES_DUE') return { to: '/sessions?tab=needs_action', label: 'Submit notes' };
  if (item.reason === 'REPORT_DUE') {
    const type = item.class_type === 'DIAGNOSTIC' ? 'diagnostic' : 'demo';
    return { to: `/my-bookings/${type}/${item.source_id}`, label: 'Write report' };
  }
  return null;
}

/** The classes not counted yet that may still count, and why; a tutor gets a way to act on their own. */
export function NotCountedCard({ items, tutorView = false }) {
  return (
    <Panel
      icon={CalendarClockIcon}
      title={items.length ? `${items.length} ${items.length === 1 ? 'class is' : 'classes are'} not counted yet` : 'Not counted yet'}
      subtitle="Not Started, No-show / Not Conducted and staff-only attendance never count, and are not listed."
    >
      {items.length ? (
        <ul className="flex flex-col divide-y text-sm">
          {items.map((item, index) => {
            const reason = NOT_COUNTED_REASONS[item.reason] || { label: item.reason, hint: '' };
            const action = tutorView ? notCountedAction(item) : null;
            // A tutor reads no source for a Demo conversion (its sale is an administrator's): keyed by place instead.
            return (
              <li
                key={`${item.class_type}-${item.source_id ?? index}`}
                className="flex flex-wrap items-center justify-between gap-2 py-2"
              >
                <div className="min-w-0">
                  <p className="font-medium">
                    {classTypeLabel(item.class_type, { singular: true })}
                    {item.is_redemo ? ' (Re-Demo)' : ''} · {classSubject(item)} · {dayLabel(item.class_start)},{' '}
                    {timeLabel(item.class_start)}
                  </p>
                  <p className="text-muted-foreground">
                    <span className="text-foreground font-medium">{reason.label}.</span> {reason.hint}
                  </p>
                </div>
                {action ? (
                  <Button asChild size="sm" variant="outline">
                    <Link to={action.to}>{action.label}</Link>
                  </Button>
                ) : null}
              </li>
            );
          })}
        </ul>
      ) : (
        <PanelEmpty icon={CalendarClockIcon} message="Every class taught is counted." />
      )}
    </Panel>
  );
}

const KIND_LABEL = { EARNING: 'Earning', REVERSAL: 'Reversal', ADJUSTMENT: 'Adjustment' };

/**
 * The ledger, newest first: every earning (with why it counts and its rate),
 * reversal and adjustment (with its reason). A Demo conversion is its own
 * line -- what it added over the Demo, signed -- and a Demo that converted is
 * marked so. `onReverse(entry)` offers the administrator's reversal of an
 * earning or adjustment not reversed yet.
 */
export function LedgerCard({ title = 'Earned classes', data, admin, classType, onClassType, onPage, onReverse, pending }) {
  const rows = data?.results || [];
  return (
    <Panel
      icon={ReceiptIndianRupeeIcon}
      title={title}
      subtitle="Each class counts once, at the rate in effect when it ended; a Demo conversion once, at the rate in effect when the student enrolled. Corrections are added, never edited."
      action={
        onClassType ? (
          <FilterSelect
            label="Class type"
            placeholder="All class types"
            value={classType}
            onChange={onClassType}
            options={CLASS_TYPES.map((type) => ({ value: type.value, label: type.label }))}
          />
        ) : null
      }
    >
      {rows.length ? (
        <div className="flex flex-col gap-3">
          <div className="overflow-x-auto">
            <Table aria-label={title} aria-busy={pending || undefined}>
              <TableHeader>
                <TableRow>
                  <TableHead>Class date</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead>Student / lead</TableHead>
                  <TableHead className="text-right">Units</TableHead>
                  <TableHead className="text-right">Rate</TableHead>
                  {admin ? <TableHead>Rate source</TableHead> : null}
                  <TableHead className="text-right">Amount</TableHead>
                  <TableHead>Why it counts</TableHead>
                  {onReverse ? (
                    <TableHead>
                      <span className="sr-only">Actions</span>
                    </TableHead>
                  ) : null}
                </TableRow>
              </TableHeader>
              <TableBody className={pending ? 'opacity-60' : undefined}>
                {rows.map((entry) => (
                  <TableRow key={entry.id} className={entry.reversed ? 'text-muted-foreground' : undefined}>
                    <TableCell className="whitespace-nowrap">
                      {entry.class_end ? (
                        <>
                          <span>{dayLabel(entry.class_start)}</span>
                          <span className="text-muted-foreground block text-xs">{timeLabel(entry.class_start)}</span>
                        </>
                      ) : (
                        <span>{monthLabel(entry.month)}</span>
                      )}
                    </TableCell>
                    <TableCell className="whitespace-nowrap">
                      {entry.kind === 'EARNING' ? classTypeLabel(entry.class_type, { singular: true }) : KIND_LABEL[entry.kind]}
                      {entry.details?.is_redemo ? ' (Re-Demo)' : ''}
                      {entry.conversion && !entry.conversion.reversed ? (
                        <Badge variant="success" className="ml-2" title={`Converted: ${formatInr(entry.conversion.amount, { signed: true })}`}>
                          Converted
                        </Badge>
                      ) : null}
                      {entry.reversed ? (
                        <Badge variant="secondary" className="ml-2">
                          Reversed
                        </Badge>
                      ) : null}
                    </TableCell>
                    <TableCell>{entry.class_type ? classSubject(entry) : '—'}</TableCell>
                    <TableCell className="text-right whitespace-nowrap tabular-nums">{unitsLabel(entry.units, entry.unit)}</TableCell>
                    <TableCell className="text-right whitespace-nowrap tabular-nums">
                      {entry.rate ? rateLabel(entry.rate, entry.unit) : '—'}
                    </TableCell>
                    {admin ? <TableCell>{entry.rate_source ? <RateSourceBadge source={entry.rate_source} /> : null}</TableCell> : null}
                    <TableCell
                      className={cn('text-right font-medium whitespace-nowrap tabular-nums', entry.reversed && 'line-through')}
                    >
                      {formatInr(entry.amount, { signed: entry.kind !== 'EARNING' || entry.class_type === CONVERSION })}
                    </TableCell>
                    <TableCell className="min-w-56 text-sm">
                      {whyItCounts(entry)}
                      {entry.reversal ? (
                        <span className="text-muted-foreground block text-xs">
                          Reversed {dayLabel(entry.reversal.created_at)}
                          {admin && entry.reversal.created_by ? ` by ${entry.reversal.created_by.name}` : ''}: {entry.reversal.reason}
                        </span>
                      ) : null}
                      {entry.kind !== 'EARNING' && admin && entry.created_by ? (
                        <span className="text-muted-foreground block text-xs">
                          {entry.created_by.name}, {stampLabel(entry.created_at)}
                        </span>
                      ) : null}
                    </TableCell>
                    {onReverse ? (
                      <TableCell className="text-right">
                        {entry.kind !== 'REVERSAL' && !entry.reversed ? (
                          <DropdownMenu>
                            <DropdownMenuTrigger asChild>
                              <Button variant="ghost" size="icon" aria-label={`Actions for this ${KIND_LABEL[entry.kind].toLowerCase()}`}>
                                <MoreVerticalIcon />
                              </Button>
                            </DropdownMenuTrigger>
                            <DropdownMenuContent align="end">
                              <DropdownMenuItem onSelect={() => onReverse(entry)}>
                                Reverse {KIND_LABEL[entry.kind].toLowerCase()}…
                              </DropdownMenuItem>
                            </DropdownMenuContent>
                          </DropdownMenu>
                        ) : null}
                      </TableCell>
                    ) : null}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
          {data.count > data.page_size ? (
            <Pagination page={data.page} pageSize={data.page_size} total={data.count} pending={pending} onPageChange={onPage} />
          ) : null}
        </div>
      ) : (
        <PanelEmpty icon={ReceiptIndianRupeeIcon} message="No earned classes in this period." />
      )}
    </Panel>
  );
}

/**
 * Every payment recorded for the tutor, newest first: a voided one struck
 * through with why it was voided. `onVoid(payment)` offers the administrator's
 * void of one still counting; `action` adds Record payment to the card.
 */
export function PaymentsCard({ payments, admin, onVoid, action }) {
  const live = payments.filter((payment) => !payment.voided);
  const total = live.reduce((sum, payment) => sum + Number(payment.amount), 0);
  return (
    <Panel
      icon={WalletIcon}
      title="Payment history"
      subtitle={
        admin
          ? 'Payments made outside Eduport Plus and recorded here. Nothing is transferred from here.'
          : 'Payments made to you and recorded by Admin.'
      }
      action={action}
    >
      {payments.length ? (
        <div className="overflow-x-auto">
          <Table aria-label="Payment history">
            <TableHeader>
              <TableRow>
                <TableHead>Payment date</TableHead>
                <TableHead className="text-right">Amount</TableHead>
                <TableHead>Method</TableHead>
                <TableHead>Reference</TableHead>
                <TableHead>Notes</TableHead>
                {admin ? <TableHead>Recorded by</TableHead> : null}
                {onVoid ? (
                  <TableHead>
                    <span className="sr-only">Actions</span>
                  </TableHead>
                ) : null}
              </TableRow>
            </TableHeader>
            <TableBody>
              {payments.map((payment) => (
                <TableRow key={payment.id} className={payment.voided ? 'text-muted-foreground' : undefined}>
                  <TableCell className="whitespace-nowrap">{dayLabel(payment.paid_on)}</TableCell>
                  <TableCell className={cn('text-right font-medium tabular-nums', payment.voided && 'line-through')}>
                    {formatInr(payment.amount)}
                  </TableCell>
                  <TableCell>{payment.method_label}</TableCell>
                  <TableCell className="font-mono text-xs">{payment.reference}</TableCell>
                  <TableCell className="min-w-48 text-sm">
                    {payment.notes || (payment.voided ? null : '—')}
                    {payment.voided ? (
                      <span className="block text-xs">
                        <Badge variant="secondary" className="mr-1">
                          Voided
                        </Badge>
                        {admin && payment.voided_by ? `by ${payment.voided_by.name}, ${stampLabel(payment.voided_at)}: ` : ''}
                        {payment.void_reason}
                      </span>
                    ) : null}
                  </TableCell>
                  {admin ? (
                    <TableCell className="text-sm">
                      {payment.recorded_by?.name}
                      <span className="text-muted-foreground block text-xs">{stampLabel(payment.recorded_at)}</span>
                    </TableCell>
                  ) : null}
                  {onVoid ? (
                    <TableCell className="text-right">
                      {payment.voided ? null : (
                        <DropdownMenu>
                          <DropdownMenuTrigger asChild>
                            <Button variant="ghost" size="icon" aria-label={`Actions for the payment of ${dayLabel(payment.paid_on)}`}>
                              <MoreVerticalIcon />
                            </Button>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="end">
                            <DropdownMenuItem onSelect={() => onVoid(payment)}>Void payment…</DropdownMenuItem>
                          </DropdownMenuContent>
                        </DropdownMenu>
                      )}
                    </TableCell>
                  ) : null}
                </TableRow>
              ))}
            </TableBody>
            <TableFooter>
              <TableRow>
                <TableCell>Total paid</TableCell>
                <TableCell className="text-right tabular-nums">{formatInr(total)}</TableCell>
                <TableCell colSpan={(admin ? 4 : 3) + (onVoid ? 1 : 0)} className="text-muted-foreground text-xs font-normal">
                  Voided payments are not counted.
                </TableCell>
              </TableRow>
            </TableFooter>
          </Table>
        </div>
      ) : (
        <PanelEmpty
          icon={WalletIcon}
          message="No payments recorded yet."
          hint={admin ? 'Record a payment once it has been made outside Eduport Plus.' : 'Payments appear here when Admin records them.'}
        />
      )}
    </Panel>
  );
}
