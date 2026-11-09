import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { BadgePercentIcon, HistoryIcon, PencilIcon } from 'lucide-react';

import api from '@/lib/api';
import { formatDay } from '@/lib/enquiries';
import { PRICING_URL, formatAmount, planTypeLabel, salesError } from '@/lib/sales';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { Page, PageHeader, EmptyState } from '@/components/page/page';
import { ResponsiveList } from '@/components/page/responsive-list';
import { AccessDeniedState, ErrorState, Notice } from '@/components/page/states';
import { Field, Fields, WorkspaceCard } from '@/components/bookings/redemo-workspace/parts';
import { PricingDialog } from '@/components/sales/pricing-dialog';

const offersPrivilege = (version) => Number(version.single_payment_percent) > 0;
const privilege = (version) =>
  offersPrivilege(version)
    ? `${version.single_payment_percent}% off ${version.single_payment_plan_types.map(planTypeLabel).join(', ')}`
    : 'Off';

/**
 * Global Pricing, for administrators (Sales & Finance): the one per-class
 * rate every plan is sold at -- a standard fee, the offer fee packages are
 * priced at, and the single-payment privilege -- and every version it has
 * had. A change is the next version, in effect at once (D3); no version is
 * ever changed or removed, so what was quoted from one keeps its prices.
 */
export default function SalesPricingPage() {
  const [data, setData] = useState(null);
  const [failure, setFailure] = useState(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [editing, setEditing] = useState(false);
  const [notice, setNotice] = useState(null);

  useEffect(() => {
    let active = true;
    api
      .get(PRICING_URL)
      .then((response) => {
        if (!active) return;
        setData(response.data);
        setFailure(null);
      })
      .catch((err) => {
        if (active) setFailure(salesError(err, 'Could not load the pricing.'));
      });
    return () => {
      active = false;
    };
  }, [reloadKey]);

  const current = data?.current ?? null;

  let content;
  if (failure?.status === 403) {
    content = <AccessDeniedState title="You don't have access to the pricing." message={failure.message} />;
  } else if (failure && !data) {
    content = <ErrorState message={failure.message} onRetry={() => setReloadKey((key) => key + 1)} />;
  } else if (!data) {
    content = <Skeleton className="h-64 w-full rounded-xl" />;
  } else if (!current) {
    content = (
      <EmptyState
        icon={BadgePercentIcon}
        title="No pricing yet"
        description="Set the standard and offer fee per class. Syllabus packages and PDFs are priced from it."
        action={<Button onClick={() => setEditing(true)}>Set up the pricing</Button>}
      />
    );
  } else {
    const columns = [
      {
        key: 'version',
        header: 'Version',
        cell: (row) => (
          <span className="inline-flex items-center gap-2">
            v{row.version}
            {row.version === current.version ? <Badge variant="success">In effect</Badge> : null}
          </span>
        ),
      },
      {
        key: 'effective',
        header: 'Effective',
        className: 'whitespace-nowrap',
        cell: (row) => `${formatDay(row.effective_from)} – ${row.effective_until ? formatDay(row.effective_until) : 'now'}`,
      },
      { key: 'standard', header: 'Standard / class', className: 'tabular-nums', cell: (row) => formatAmount(row.standard_fee, row.currency) },
      { key: 'offer', header: 'Offer / class', className: 'tabular-nums', cell: (row) => formatAmount(row.offer_fee, row.currency) },
      { key: 'privilege', header: 'Single-payment privilege', className: 'whitespace-normal', cell: privilege },
      { key: 'note', header: 'Reason', className: 'text-muted-foreground whitespace-normal', cell: (row) => row.note || '—' },
      { key: 'by', header: 'By', className: 'text-muted-foreground', cell: (row) => row.created_by?.name ?? '—' },
    ];
    const renderCard = (row) => (
      <article className="bg-card flex flex-col gap-2 rounded-xl border p-4 text-sm">
        <div className="flex items-center justify-between gap-2">
          <span className="font-medium">Version {row.version}</span>
          {row.version === current.version ? <Badge variant="success">In effect</Badge> : null}
        </div>
        <p className="tabular-nums">
          {formatAmount(row.offer_fee, row.currency)} offer · {formatAmount(row.standard_fee, row.currency)} standard
        </p>
        <p className="text-muted-foreground">{privilege(row)}</p>
        <p className="text-muted-foreground text-xs">
          From {formatDay(row.effective_from)}
          {row.effective_until ? ` to ${formatDay(row.effective_until)}` : ''} · {row.created_by?.name ?? '—'}
        </p>
      </article>
    );
    content = (
      <>
        <WorkspaceCard
          icon={BadgePercentIcon}
          title={`In effect: version ${current.version}`}
          action={
            <Button size="sm" onClick={() => setEditing(true)}>
              <PencilIcon />
              Change pricing
            </Button>
          }
        >
          <Fields>
            <Field label="Standard fee">{`${formatAmount(current.standard_fee, current.currency)} per class`}</Field>
            <Field label="Offer fee">{`${formatAmount(current.offer_fee, current.currency)} per class — every package is priced at it`}</Field>
            <Field label="Single payment">
              {offersPrivilege(current)
                ? `${privilege(current)}, rounded to the nearest whole ${current.currency} — the PDFs show the Single-Payment Privilege box`
                : 'Off — the PDFs show no Single-Payment Privilege box'}
            </Field>
            <Field label="Since">{`${formatDay(current.effective_from)} · ${current.created_by?.name ?? '—'}`}</Field>
            {current.note ? <Field label="Reason">{current.note}</Field> : null}
          </Fields>
        </WorkspaceCard>
        <WorkspaceCard icon={HistoryIcon} title="History">
          <ResponsiveList label="Pricing versions" columns={columns} rows={data.versions} minTableWidth={900} renderCard={renderCard} />
          <p className="text-muted-foreground text-xs">
            Versions are never changed or removed: sales and quotes keep the prices of the version they were made at.
          </p>
        </WorkspaceCard>
      </>
    );
  }

  return (
    <Page className="max-w-5xl">
      <PageHeader
        title="Global Pricing"
        description="One per-class rate for every plan. Each change is a new version, in effect at once; earlier versions keep their prices."
        actions={
          <Button variant="outline" asChild>
            <Link to="/sales-syllabus">Syllabus & Plans</Link>
          </Button>
        }
      />
      {notice ? <Notice onDismiss={() => setNotice(null)}>{notice}</Notice> : null}
      {content}
      <PricingDialog
        open={editing}
        onOpenChange={setEditing}
        current={current}
        onSaved={(saved) => {
          setData(saved);
          setNotice(`Pricing version ${saved.current.version} is in effect.`);
        }}
      />
    </Page>
  );
}
