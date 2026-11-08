import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { PlusIcon } from 'lucide-react';

import api from '@/lib/api';
import { PERMISSIONS, can } from '@/lib/access';
import { LEAD_STATUSES, SOURCE_FILTERS, enquiryError } from '@/lib/enquiries';
import { LEADS_URL, LEAD_BDES_URL, UNASSIGNED, ownerOptions } from '@/lib/leads';
import { useListParams } from '@/hooks/use-list-params';
import { Button } from '@/components/ui/button';
import { TableSkeleton } from '@/components/table-skeleton';
import { AddEnquiryDialog } from '@/components/enquiries/add-enquiry-dialog';
import { AssignOwnerDialog } from '@/components/leads/assign-owner-dialog';
import { LeadFilters, LeadList } from '@/components/leads/lead-list';
import { Page, PageHeader } from '@/components/page/page';
import { AccessDeniedState, ErrorState, Notice } from '@/components/page/states';

const PAGE_SIZE = 25;
const STATUS_VALUES = new Set(LEAD_STATUSES.map((status) => status.value));
const SOURCE_VALUES = new Set(SOURCE_FILTERS.map((source) => source.value));
const ID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

/**
 * Leads, for administrators: every lead, whatever brought it in -- the
 * booking pages, the website's and landing page's forms, a BDE's own entry or
 * an administrator's -- with its status and owner BDE, searched and filtered
 * (status, source, owner, the dates it came in on) in the URL. Administrators
 * add a lead by hand (accounts.add_lead) and give a lead to a BDE or move it
 * to another (accounts.assign_lead_owner); the BDE then finds it in their My
 * Enquiries. The API enforces each of these again.
 */
export default function LeadsPage({ user }) {
  const canAdd = can(user, PERMISSIONS.addLead);
  const canAssign = can(user, PERMISSIONS.assignLeadOwner);
  const { searchParams, update, clear } = useListParams();
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
  const date = (name) => (DATE_RE.test(searchParams.get(name) ?? '') ? searchParams.get(name) : '');
  const from = date('from');
  const to = from && date('to') && date('to') < from ? '' : date('to');
  const filters = { q, status, source, owner, from, to };

  useEffect(() => {
    let active = true;
    setPending(true);

    const params = { page, page_size: PAGE_SIZE };
    if (q) params.q = q;
    if (status) params.status = status;
    if (source) params.source = source;
    if (owner) params.owner = owner;
    if (from) params.from = from;
    if (to) params.to = to;

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
  }, [page, q, status, source, owner, from, to, reloadKey]);

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
    content = <AccessDeniedState title="You don't have access to leads." message={failure.message} />;
  } else {
    let list;
    if (!data && !failure) {
      list = <TableSkeleton toolbar={false} />;
    } else if (!data) {
      list = <ErrorState message={failure.message} onRetry={retry} pending={pending} />;
    } else {
      list = (
        <>
          {failure ? <ErrorState message={failure.message} onRetry={retry} pending={pending} /> : null}
          <LeadList
            rows={data.results ?? []}
            total={data.count ?? 0}
            page={page}
            pageSize={PAGE_SIZE}
            filtered={Object.values(filters).some(Boolean)}
            pending={pending}
            onAssign={canAssign ? setAssigning : null}
            onChange={update}
            onClear={clear}
          />
        </>
      );
    }
    content = (
      <div className="flex flex-col gap-4">
        <LeadFilters filters={filters} owners={ownerOptions(bdes)} onChange={update} onClear={clear} />
        {list}
      </div>
    );
  }

  return (
    <Page>
      <PageHeader
        title="Leads"
        description="Every lead from the booking pages, the website, the landing page and manual entry, and the BDE who owns it."
        actions={
          canAdd ? (
            <Button onClick={() => setAddOpen(true)}>
              <PlusIcon />
              Add Lead
            </Button>
          ) : null
        }
      />

      {notice ? (
        <Notice onDismiss={() => setNotice(null)}>
          {notice.text}{' '}
          <Link to={`/leads/${notice.id}`} className="font-medium underline">
            Open it
          </Link>
        </Notice>
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
    </Page>
  );
}
