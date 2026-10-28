import { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { CheckCircle2Icon, PlusIcon, ShieldAlertIcon, XIcon } from 'lucide-react';

import api from '@/lib/api';
import { PERMISSIONS, can } from '@/lib/access';
import { ENQUIRIES_URL, ENQUIRY_STATUSES, SOURCE_FILTERS, enquiryError } from '@/lib/enquiries';
import { Button } from '@/components/ui/button';
import { TableSkeleton } from '@/components/table-skeleton';
import { AddEnquiryDialog } from '@/components/enquiries/add-enquiry-dialog';
import { EnquiryList } from '@/components/enquiries/enquiry-list';

const PAGE_SIZE = 25;
const STATUS_VALUES = new Set(ENQUIRY_STATUSES.map((status) => status.value));
const SOURCE_VALUES = new Set(SOURCE_FILTERS.map((source) => source.value));

function AccessDenied({ failure }) {
  return (
    <div className="flex flex-col items-center gap-2 rounded-md border px-6 py-12 text-center">
      <ShieldAlertIcon className="text-muted-foreground size-8" />
      <p className="font-medium">
        {failure.code === 'NOT_A_BDE' ? 'Enquiries belong to BDE accounts.' : "You don't have access to enquiries."}
      </p>
      <p className="text-muted-foreground max-w-md text-sm">{failure.message}</p>
    </div>
  );
}

/**
 * My Enquiries: the BDE's own leads -- the ones their booking links brought in
 * and the ones they added by hand. The API serves each BDE only theirs.
 */
export default function EnquiriesPage({ user }) {
  const canAdd = can(user, PERMISSIONS.addEnquiry);
  const [searchParams] = useSearchParams();
  const [data, setData] = useState(null);
  const [failure, setFailure] = useState(null);
  const [pending, setPending] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const [added, setAdded] = useState(null);
  const [addOpen, setAddOpen] = useState(false);

  const page = Math.max(1, parseInt(searchParams.get('page') || '1', 10) || 1);
  const q = (searchParams.get('q') ?? '').trim();
  const status = STATUS_VALUES.has(searchParams.get('status')) ? searchParams.get('status') : '';
  const source = SOURCE_VALUES.has(searchParams.get('source')) ? searchParams.get('source') : '';

  useEffect(() => {
    let active = true;
    setPending(true);

    const params = { page, page_size: PAGE_SIZE };
    if (q) params.q = q;
    if (status) params.status = status;
    if (source) params.source = source;

    api
      .get(ENQUIRIES_URL, { params })
      .then((response) => {
        if (!active) return;
        setData(response.data);
        setFailure(null);
      })
      .catch((err) => {
        if (active) setFailure(enquiryError(err, 'Could not load your enquiries.'));
      })
      .finally(() => {
        if (active) setPending(false);
      });

    return () => {
      active = false;
    };
  }, [page, q, status, source, reloadKey]);

  const retry = () => setReloadKey((key) => key + 1);
  const handleAdded = (enquiry) => {
    setAdded(enquiry);
    retry();
  };

  let content;
  if (failure?.status === 403) {
    content = <AccessDenied failure={failure} />;
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
          filters={{ q, status, source }}
          pending={pending}
        />
      </>
    );
  }

  return (
    <div className="container mx-auto px-4 py-16">
      <div className="mb-6 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">My Enquiries</h1>
          <p className="text-muted-foreground text-sm">
            Parents who reached you through your booking links, and the enquiries you added yourself.
          </p>
        </div>
        {canAdd ? (
          <Button onClick={() => setAddOpen(true)}>
            <PlusIcon />
            Add enquiry
          </Button>
        ) : null}
      </div>

      {added ? (
        <div role="status" className="bg-success/10 text-success mb-4 flex items-start gap-2 rounded-md px-3 py-2 text-sm">
          <CheckCircle2Icon className="mt-0.5 size-4 shrink-0" />
          <p className="flex-1">
            Added the enquiry for {added.student_name}.{' '}
            <Link to={`/enquiries/${added.id}`} className="font-medium underline">
              Open it
            </Link>
          </p>
          <button type="button" onClick={() => setAdded(null)} className="shrink-0" aria-label="Dismiss">
            <XIcon className="size-4" />
          </button>
        </div>
      ) : null}

      {content}

      {canAdd ? <AddEnquiryDialog open={addOpen} onOpenChange={setAddOpen} onCreated={handleAdded} /> : null}
    </div>
  );
}
