import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { HandCoinsIcon, HourglassIcon, InfoIcon, WalletIcon } from 'lucide-react';

import api from '@/lib/api';
import { EARNINGS_API, countsLine, dayLabel, earningsError, formatInr, monthLabel } from '@/lib/earnings';
import { Skeleton } from '@/components/ui/skeleton';
import { Tile } from '@/components/dashboard/kpi-cards';
import { Page, PageHeader } from '@/components/page/page';
import { AccessDeniedState, ErrorState } from '@/components/page/states';
import {
  BreakdownCard,
  LedgerCard,
  MonthsCard,
  NotCountedCard,
  PaymentsCard,
  SyncNote,
} from '@/components/earnings/parts';
import { cn } from '@/lib/utils';

/** The period as chips: all time, or one month since the activation. */
function MonthChips({ months, value, onChange }) {
  const chip = (key, label, active) => (
    <button
      key={key}
      type="button"
      aria-pressed={active}
      onClick={() => onChange(key)}
      className={cn(
        'h-9 rounded-full border px-3.5 text-sm transition-colors',
        active ? 'bg-foreground text-background border-foreground font-medium' : 'bg-card hover:bg-muted'
      )}
    >
      {label}
    </button>
  );
  return (
    <div role="group" aria-label="Month" className="flex flex-wrap items-center gap-2">
      {chip('', 'All time', !value)}
      {(months || []).map((month) => chip(month, monthLabel(month), value === month))}
    </div>
  );
}

/**
 * My Earnings, the Tutor Hub's: the signed-in tutor's own earnings for the
 * classes they completed, their rates, the classes not counted yet, the
 * ledger, the months, and the payments Admin recorded -- nobody else's, and
 * no rate, payment or correction can be changed here. The API (GET
 * /api/earnings/me/) always answers for the signed-in account.
 */
export default function MyEarningsPage() {
  const [params, setParams] = useSearchParams();
  const month = params.get('month') || '';
  const [page, setPage] = useState(1);
  const [data, setData] = useState(null);
  const [entries, setEntries] = useState(null);
  const [failure, setFailure] = useState(null);
  const [pending, setPending] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let active = true;
    setPending(true);
    const query = month ? { month } : {};
    Promise.all([
      api.get(`${EARNINGS_API}/me/`, { params: query }),
      api.get(`${EARNINGS_API}/me/entries/`, { params: { ...query, page } }),
    ])
      .then(([mine, ledger]) => {
        if (!active) return;
        setData(mine.data);
        setEntries(ledger.data);
        setFailure(null);
      })
      .catch((err) => {
        if (active) setFailure(earningsError(err, 'Could not load your earnings.'));
      })
      .finally(() => {
        if (active) setPending(false);
      });
    return () => {
      active = false;
    };
  }, [month, page, reloadKey]);

  const pickMonth = (value) => {
    const next = new URLSearchParams(params);
    if (value) next.set('month', value);
    else next.delete('month');
    setParams(next, { replace: true });
    setPage(1);
  };

  let content;
  if (failure?.status === 403) {
    content = <AccessDeniedState title="You don't have access to My Earnings." message={failure.message} />;
  } else if (failure && !data) {
    content = <ErrorState message={failure.message} onRetry={() => setReloadKey((key) => key + 1)} />;
  } else if (!data) {
    content = (
      <div className="flex flex-col gap-4" aria-busy="true">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-24 rounded-xl" />
          ))}
        </div>
        <Skeleton className="h-72 rounded-xl" />
      </div>
    );
  } else {
    const summary = data.summary;
    const owed = Number(summary.outstanding);
    const overpaid = summary.balance_state === 'overpaid';
    content = (
      <div className="flex flex-col gap-4">
        {!data.pricing ? (
          <p role="status" className="bg-card flex items-start gap-2 rounded-xl border px-4 py-3 text-sm">
            <InfoIcon className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
            Your earnings appear here once rates are set. The classes you complete are already counted.
          </p>
        ) : null}
        <MonthChips months={data.months} value={month} onChange={pickMonth} />
        <p className="text-muted-foreground -mt-2 text-xs">
          A month filters what you earned and were paid. Pending is always your full balance.
        </p>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <Tile icon={WalletIcon} tone="info" label="Total earned" value={formatInr(summary.earned)} hint={countsLine(summary)} />
          <Tile
            icon={HandCoinsIcon}
            tone="success"
            label="Total paid"
            value={formatInr(summary.paid)}
            hint={
              summary.last_paid_on
                ? `Last payment ${dayLabel(summary.last_paid_on)}`
                : month
                  ? `No payments in ${monthLabel(month)}`
                  : 'No payments yet'
            }
          />
          <Tile
            icon={HourglassIcon}
            tone={overpaid ? 'destructive' : 'warning'}
            label={overpaid ? 'Overpaid' : 'Pending amount'}
            value={formatInr(Math.abs(owed))}
            hint={overpaid ? 'Paid more than earned so far' : 'Earned but not yet paid'}
          />
        </div>

        <NotCountedCard items={data.not_counted} tutorView />

        <div className="grid gap-4 xl:grid-cols-2">
          <BreakdownCard breakdown={data.breakdown} adjustments={data.adjustments} total={summary.earned} />
          <MonthsCard months={data.months_breakdown} onPick={pickMonth} />
        </div>

        <LedgerCard title="Counted classes" data={entries} onPage={setPage} pending={pending} />
        <PaymentsCard payments={data.payments} />

        <details className="bg-card rounded-xl border px-4 py-3 text-sm" open>
          <summary className="cursor-pointer font-medium">How a class counts</summary>
          <ul className="text-muted-foreground mt-2 list-disc space-y-1 pl-5">
            <li>
              <strong className="text-foreground">Diagnostic and Demo:</strong> you started it, submitted its report, and
              its scheduled slot has ended. A Re-Demo counts on its own, for the tutor who teaches it.
            </li>
            <li>
              <strong className="text-foreground">Normal Session:</strong> it was started, and your own notes came in after
              it ended -- whenever they come in. It is paid for the hours it was booked for.
            </li>
            <li>
              <strong className="text-foreground">Never counted:</strong> a class nobody started, one recorded as No-show /
              Not Conducted, or one only marked attended by staff.
            </li>
          </ul>
        </details>
        <SyncNote lastSync={data.last_sync} />
      </div>
    );
  }

  return (
    <Page>
      <PageHeader
        title="My Earnings"
        description="What you have earned for the classes you completed, counted from the activation, and the payments Admin has recorded for you. In Indian rupees."
      />
      {content}
    </Page>
  );
}
