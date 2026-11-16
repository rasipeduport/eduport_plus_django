import { Fragment, useState } from 'react';
import { format, isToday, isYesterday } from 'date-fns';
import {
  BookOpen,
  CalendarCheck,
  CalendarCheck2,
  CalendarClock,
  ChevronDown,
  ClipboardList,
  FileText,
  GraduationCap,
  History,
  Inbox,
  Link2,
  Mail,
  RotateCcw,
  SearchXIcon,
  Send,
  StickyNote,
  UserRound,
  XIcon,
} from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { EmptyState } from '@/components/page/page';
import { DateRangeFilter } from '@/components/page/date-range-filter';
import { FilterSelect, SearchField } from '@/components/page/list-toolbar';
import { Pagination } from '@/components/page/pagination';
import { useListParams } from '@/hooks/use-list-params';
import {
  ACTION_LABELS,
  ACTIVITY_ENTITY_TYPES,
  ENTITY_NOUN,
  actionLabel,
  actorLabel,
  describeActivity,
} from '@/lib/activity-format';
import { fromPickerDate, toPickerDate } from '@/lib/date-range';
import { cn } from '@/lib/utils';
import { ChangesTable } from './changes-table';

const ENTITY_ICON = {
  student: GraduationCap,
  student_note: StickyNote,
  session: CalendarCheck,
  exam: ClipboardList,
  additional_exam: ClipboardList,
  homework: BookOpen,
  invitation: Mail,
  profile: UserRound,
  lead: Inbox,
  booking_link: Link2,
  booking: CalendarCheck2,
  booking_slot: CalendarClock,
  booking_schedule: CalendarClock,
  demo_invite: Send,
  redemo_request: RotateCcw,
  report: FileText,
};
const ACTION_OPTIONS = Object.keys(ACTION_LABELS).map((action) => ({ value: action, label: ACTION_LABELS[action] }));

// The log's `from` and `to` are instants (the API compares them with each
// entry's time); the calendar picks days on this device. A day runs from its
// midnight to its last millisecond, so the last day picked is included whole.
const dayOf = (iso) => (iso ? fromPickerDate(new Date(iso)) : '');
const startOf = (day) => toPickerDate(day).toISOString();
const endOf = (day) => {
  const date = toPickerDate(day);
  return new Date(date.getFullYear(), date.getMonth(), date.getDate(), 23, 59, 59, 999).toISOString();
};

function dayHeading(date) {
  if (isToday(date)) return 'Today';
  if (isYesterday(date)) return 'Yesterday';
  return format(date, 'EEEE, d MMM yyyy');
}

function Entry({ row, open, onToggle }) {
  const Icon = ENTITY_ICON[row.entity_type] || History;
  const hasChanges = Object.keys(row.changes ?? {}).length > 0;
  return (
    <li className="flex gap-3 px-4 py-3">
      <span className="bg-muted text-muted-foreground mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-full">
        <Icon className="size-4" aria-hidden="true" />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
          <p className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-sm">
            <span className="font-medium">{actorLabel(row)}</span>
            {row.actor_role ? (
              <span className="text-muted-foreground text-xs capitalize">{row.actor_role.toLowerCase()}</span>
            ) : null}
            <Badge variant="secondary">{actionLabel(row.action)}</Badge>
          </p>
          <time dateTime={row.created_at} className="text-muted-foreground shrink-0 text-xs whitespace-nowrap">
            {format(new Date(row.created_at), 'h:mm a')}
          </time>
        </div>
        <p className="mt-1 text-sm break-words">{describeActivity(row)}</p>
        {row.entity_label ? (
          <p className="text-muted-foreground text-xs break-words">
            {ENTITY_NOUN[row.entity_type] ?? 'Item'}: {row.entity_label}
          </p>
        ) : null}
        {hasChanges ? (
          <>
            <Button
              variant="ghost"
              size="sm"
              className="text-muted-foreground -ml-2 mt-1 h-7"
              aria-expanded={open}
              onClick={onToggle}
            >
              {open ? 'Hide changes' : 'Show changes'}
              <ChevronDown className={cn('transition-transform', open && 'rotate-180')} aria-hidden="true" />
            </Button>
            {open ? (
              <div className="bg-muted/30 mt-2 overflow-x-auto rounded-lg border p-2">
                <ChangesTable changes={row.changes} />
              </div>
            ) : null}
          </>
        ) : null}
      </div>
    </li>
  );
}

/**
 * The activity log in the refreshed design: who did what, newest first, under
 * a heading per day -- each entry with what it was about and, where the entry
 * kept them, the changes it made, shown on request. Searched and filtered by
 * action, type, actor (`canFilterByActor`: whoever may see everyone's) and
 * dates, all kept in the URL as the API takes them; the API scopes the rows
 * and pages them.
 */
export function ActivityLog({ rows, total, page, pageSize, actorOptions, filters, pending = false, canFilterByActor = false }) {
  const { update, clear } = useListParams();
  const [expanded, setExpanded] = useState(null);
  const filtered = Boolean(filters.q || filters.action || filters.entity || filters.actor || filters.from || filters.to);
  // Newest first, whatever order the page arrived in.
  const sorted = [...rows].sort((a, b) => new Date(b.created_at) - new Date(a.created_at));

  let body;
  if (sorted.length) {
    let shownDay = null;
    body = (
      <ol aria-label="Activity" aria-busy={pending || undefined} className={cn('bg-card divide-y overflow-hidden rounded-xl border', pending && 'opacity-60')}>
        {sorted.map((row) => {
          const heading = dayHeading(new Date(row.created_at));
          const newDay = heading !== shownDay;
          shownDay = heading;
          return (
            <Fragment key={row.id}>
              {newDay ? (
                <li className="bg-muted/40 text-muted-foreground px-4 py-2 text-xs font-medium">{heading}</li>
              ) : null}
              <Entry row={row} open={expanded === row.id} onToggle={() => setExpanded(expanded === row.id ? null : row.id)} />
            </Fragment>
          );
        })}
      </ol>
    );
  } else if (total > 0) {
    body = (
      <EmptyState
        icon={SearchXIcon}
        title="Nothing on this page"
        description="This page is past the last one."
        action={
          <Button variant="outline" onClick={() => update({ page: null })}>
            Go to the first page
          </Button>
        }
      />
    );
  } else if (filtered) {
    body = (
      <EmptyState
        icon={SearchXIcon}
        title="No activity matches these filters"
        description="Try another search, action, type or dates, or clear the filters."
        action={
          <Button variant="outline" onClick={clear}>
            Clear all filters
          </Button>
        }
      />
    );
  } else {
    body = <EmptyState icon={History} title="No activity recorded yet" />;
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <SearchField
          value={filters.q}
          onSearch={(text) => update({ q: text || null })}
          label="Search activity"
          placeholder="Search actor or target…"
        />
        <FilterSelect
          label="Filter by action"
          placeholder="All actions"
          value={filters.action}
          onChange={(value) => update({ action: value || null })}
          options={ACTION_OPTIONS}
        />
        <FilterSelect
          label="Filter by type"
          placeholder="All types"
          value={filters.entity}
          onChange={(value) => update({ entity: value || null })}
          options={ACTIVITY_ENTITY_TYPES}
        />
        {canFilterByActor ? (
          <FilterSelect
            label="Filter by actor"
            placeholder="All actors"
            value={filters.actor}
            onChange={(value) => update({ actor: value || null })}
            options={actorOptions.map((actor) => ({ value: actor.id, label: actor.name }))}
          />
        ) : null}
        <DateRangeFilter
          from={dayOf(filters.from)}
          to={dayOf(filters.to)}
          anyLabel="Any date"
          onChange={(range) =>
            update(range.from ? { from: startOf(range.from), to: endOf(range.to) } : { from: null, to: null })
          }
        />
        {filtered ? (
          <Button variant="ghost" className="text-muted-foreground" onClick={clear}>
            <XIcon className="size-4" />
            Clear all filters
          </Button>
        ) : null}
      </div>
      {body}
      {total > 0 ? (
        <Pagination
          page={page}
          pageSize={pageSize}
          total={total}
          pending={pending}
          onPageChange={(next) => update({ page: String(next) })}
        />
      ) : null}
    </div>
  );
}
