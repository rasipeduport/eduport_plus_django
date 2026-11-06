import { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { CheckCircle2Icon, PlusIcon, ShieldAlertIcon, XIcon } from 'lucide-react';

import api from '@/lib/api';
import { PERMISSIONS, can } from '@/lib/access';
import { LEAD_STATUSES, SOURCE_FILTERS, enquiryError } from '@/lib/enquiries';
import { LEADS_URL, LEAD_BDES_URL, UNASSIGNED, ownerOptions } from '@/lib/leads';
import { Button } from '@/components/ui/button';
import { TableSkeleton } from '@/components/table-skeleton';
import { AddEnquiryDialog } from '@/components/enquiries/add-enquiry-dialog';
import { EnquiryList } from '@/components/enquiries/enquiry-list';
import { AssignOwnerDialog } from '@/components/leads/assign-owner-dialog';

const PAGE_SIZE = 25;
const STATUS_VALUES = new Set(LEAD_STATUSES.map((status) => status.value));
const SOURCE_VALUES = new Set(SOURCE_FILTERS.map((source) => source.value));
const ID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/**
 * Leads, for administrators: every lead, whatever brought it in -- the
 * booking pages, the website's and landing page's forms, a BDE's own entry or
 * an administrator's -- with its status and owner BDE, searched and filtered
 * in the URL. Administrators add a lead by hand (accounts.add_lead) and give a
 * lead to a BDE or move it to another (accounts.assign_lead_owner); the BDE
 * then finds it in their My Leads. The API enforces each of these again.
 */
export default function LeadsPage({ user }) {
  const canAdd = can(user, PERMISSIONS.addLead);
  const canAssign = can(user, PERMISSIONS.assignLeadOwner);
  const [searchParams] = useSearchParams();
  const [data, setData] = useState(null);
  const [bdes, setBdes] = useState([]);
  const [failure, setFailure] = useState(null);
  const [pending, setPending] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const [notice, setNotice] = useState(null);
  const [addOpen, setAddOpen] = useState(false);
  const [assigning, setAssigning] = useState(null);

  const page = Math.max(1, parseInt(searchParams.get('page') || '1', 10) || 1);
  const q = (searchParams.get('q') ?? '').trim();
  const status = STATUS_VALUES.has(searchParams.get('status')) ? searchParams.get('status') : '';
  const source = SOURCE_VALUES.has(searchParams.get('source')) ? searchParams.get('source') : '';
  const ownerParam = searchParams.get('owner') ?? '';
  const owner = ownerParam === UNASSIGNED || ID_RE.test(ownerParam) ? ownerParam : '';

  useEffect(() => {
    let active = true;
    setPending(true);

    const params = { page, page_size: PAGE_SIZE };
    if (q) params.q = q;
    if (status) params.status = status;
    if (source) params.source = source;
    if (owner) params.owner = owner;

    api
      .get(LEADS_URL, { params })
      .then((response) => {
        if (!active) return;
        setData(response.data);
        setFailure(null);
      })
      .catch((err) => {
        if (active) setFailure(enquiryError(err, 'Could not load the leads.'));
      })
      .finally(() => {
        if (active) setPending(false);
      });

    return () => {
      active = false;
    };
  }, [page, q, status, source, owner, reloadKey]);

  // The BDE accounts to filter by and to assign to; without them only Unassigned is offered.
  useEffect(() => {
    let active = true;
    api
      .get(LEAD_BDES_URL)
      .then((response) => {
        if (active) setBdes(response.data?.results ?? []);
      })
      .catch(() => {});
    return () => {
      active = false;
    };
  }, []);

  // The lead being assigned follows the list as it reloads (after OWNER_CHANGED, say),
  // so the dialog shows -- and a second try sends -- the owner the list shows now.
  const [prevData, setPrevData] = useState(data);
  if (data !== prevData) {
    setPrevData(data);
    const fresh = assigning && data?.results?.find((row) => row.id === assigning.id);
    if (fresh) setAssigning(fresh);
  }

  const retry = () => setReloadKey((key) => key + 1);
  const changed = (text, lead) => {
    setNotice({ text, id: lead.id });
    retry();
  };

  let content;
  if (failure?.status === 403) {
    content = (
      <div className="flex flex-col items-center gap-2 rounded-md border px-6 py-12 text-center">
        <ShieldAlertIcon className="text-muted-foreground size-8" />
        <p className="font-medium">You don&apos;t have access to leads.</p>
        <p className="text-muted-foreground max-w-md text-sm">{failure.message}</p>
      </div>
    );
  } else if (!data && !failure) {
    content = <TableSkeleton />;
  } else if (!data) {
    content = (
      <div className="flex flex-wrap items-center gap-3">
        <p className="text-destructive text-sm">{failure.message}</p>
        <Button variant="outline" size="sm" onClick={retry} disabled={pending}>
          Try again
        </Button>
      </div>
    );
  } else {
    content = (
      <>
        {failure ? (
          <div className="mb-4 flex flex-wrap items-center gap-3">
            <p className="text-destructive text-sm">{failure.message}</p>
            <Button variant="outline" size="sm" onClick={retry} disabled={pending}>
              Try again
            </Button>
          </div>
        ) : null}
        <EnquiryList
          rows={data.results ?? []}
          total={data.count ?? 0}
          page={page}
          pageSize={PAGE_SIZE}
          filters={{ q, status, source, owner }}
          pending={pending}
          basePath="/leads"
          owners={ownerOptions(bdes)}
          onAssign={canAssign ? setAssigning : null}
          emptyMessage="No leads yet. Leads from the booking pages, the website and the landing page appear here."
        />
      </>
    );
  }

  return (
    <div className="container mx-auto px-4 py-16">
      <div className="mb-6 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">Leads</h1>
          <p className="text-muted-foreground text-sm">
            Every lead from the booking pages, the website, the landing page and manual entry, and the BDE who owns it.
          </p>
        </div>
        {canAdd ? (
          <Button onClick={() => setAddOpen(true)}>
            <PlusIcon />
            Add lead
          </Button>
        ) : null}
      </div>

      {notice ? (
        <div role="status" className="bg-success/10 text-success mb-4 flex items-start gap-2 rounded-md px-3 py-2 text-sm">
          <CheckCircle2Icon className="mt-0.5 size-4 shrink-0" />
          <p className="flex-1">
            {notice.text}{' '}
            <Link to={`/leads/${notice.id}`} className="font-medium underline">
              Open it
            </Link>
          </p>
          <button type="button" onClick={() => setNotice(null)} className="shrink-0" aria-label="Dismiss">
            <XIcon className="size-4" />
          </button>
        </div>
      ) : null}

      {content}

      {canAdd ? (
        <AddEnquiryDialog
          admin
          open={addOpen}
          onOpenChange={setAddOpen}
          onCreated={(lead) => changed(`Added the lead for ${lead.student_name}. Assign it to a BDE when you are ready.`, lead)}
        />
      ) : null}
      {canAssign ? (
        <AssignOwnerDialog
          lead={assigning}
          bdes={bdes}
          open={Boolean(assigning)}
          onOpenChange={(open) => {
            if (!open) setAssigning(null);
          }}
          onAssigned={(lead) => changed(`${lead.student_name}'s lead is now ${lead.owner?.full_name}'s.`, lead)}
          onStale={retry}
        />
      ) : null}
    </div>
  );
}
