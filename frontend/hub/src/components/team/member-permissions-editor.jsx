import { useState } from 'react';
import {
  ChevronDownIcon,
  CircleAlertIcon,
  LockIcon,
  SearchIcon,
  ShieldCheckIcon,
  ShieldIcon,
  Trash2Icon,
} from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { cn } from '@/lib/utils';

// The API's own words when it refuses such a change (PERMISSION_NOT_GRANTABLE).
const NOT_HELD = 'You can only grant or revoke permissions you hold yourself.';
const NO_CATALOGUE = 'Load the permission catalogue to change this.';

const byModuleThenLabel = (a, b) => (a.module ?? '').localeCompare(b.module ?? '') || a.label.localeCompare(b.label);

/** Whether a permission matches a search, by its name, module or code. */
function matchesSearch(entry, search) {
  const needle = search.trim().toLowerCase();
  if (!needle) return true;
  return [entry.label, entry.module, entry.permission].some((value) => value?.toLowerCase().includes(needle));
}

/** Catalogue entries grouped by module; modules and names in alphabetical order. */
function groupByModule(entries) {
  const groups = new Map();
  for (const entry of [...entries].sort(byModuleThenLabel)) {
    if (!groups.has(entry.module)) groups.set(entry.module, []);
    groups.get(entry.module).push(entry);
  }
  return Array.from(groups, ([module, items]) => ({ module, items }));
}

function SearchField({ className, ...props }) {
  return (
    <div className={cn('relative', className)}>
      <SearchIcon className="text-muted-foreground pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2" />
      <Input className="pl-8" {...props} />
    </div>
  );
}

/** One module's permissions in the selector, each a checkbox. */
function PermissionGroup({ module, entries, assigned, picked, onToggle }) {
  return (
    <div role="group" aria-label={module} className="py-1">
      <p className="flex items-center gap-1.5 px-2 py-1.5">
        <ShieldIcon className="text-muted-foreground size-3.5" />
        <span className="text-muted-foreground text-xs font-semibold tracking-wider uppercase">{module}</span>
      </p>
      {entries.map((entry) => {
        const isAssigned = assigned.has(entry.permission);
        const locked = !isAssigned && !entry.can_grant;
        return (
          <label
            key={entry.permission}
            title={locked ? NOT_HELD : undefined}
            className={cn(
              'flex items-center gap-3 rounded-sm px-2 py-2 text-sm',
              isAssigned || locked ? 'text-muted-foreground cursor-not-allowed' : 'hover:bg-accent cursor-pointer'
            )}
          >
            <input
              type="checkbox"
              checked={isAssigned || picked.includes(entry.permission)}
              onChange={(event) => onToggle(entry.permission, event.target.checked)}
              disabled={isAssigned || locked}
              className="accent-primary size-4 shrink-0"
            />
            <span className="min-w-0 flex-1">{entry.label}</span>
            {isAssigned ? <span className="text-xs">Assigned</span> : null}
            {locked ? (
              <span className="flex items-center gap-1 text-xs">
                <LockIcon className="size-3" />
                Locked
              </span>
            ) : null}
          </label>
        );
      })}
    </div>
  );
}

/**
 * "Search or select permissions...": the catalogue grouped by module. Apply in
 * the list, or Assign Selected beside it, adds the checked permissions to the
 * assigned ones. Assigned permissions show as checked and cannot be picked
 * again; ones the viewer does not hold are locked.
 */
function PermissionPicker({ items, assigned, picked, onPickedChange, onAssign, disabled }) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState('');
  const groups = groupByModule(items.filter((entry) => matchesSearch(entry, search)));

  let summary = 'Search or select permissions...';
  if (picked.length === 1) summary = items.find((entry) => entry.permission === picked[0])?.label ?? picked[0];
  else if (picked.length > 1) summary = `${picked.length} permissions selected`;

  const toggle = (permission, checked) =>
    onPickedChange(checked ? [...picked, permission] : picked.filter((item) => item !== permission));

  const openChange = (next) => {
    setOpen(next);
    if (!next) setSearch('');
  };

  const assign = () => {
    onAssign();
    openChange(false);
  };

  return (
    <div className="flex flex-col gap-2 sm:flex-row">
      <Popover open={open} onOpenChange={openChange}>
        <PopoverTrigger asChild>
          <Button
            id="team-permission-picker"
            type="button"
            variant="outline"
            disabled={disabled}
            className="h-10 min-w-0 flex-1 justify-between px-3 font-normal"
          >
            <span className="flex min-w-0 items-center gap-2">
              <ShieldIcon className="text-muted-foreground size-4 shrink-0" />
              <span className={cn('truncate', !picked.length && 'text-muted-foreground')}>{summary}</span>
            </span>
            <ChevronDownIcon className="text-muted-foreground size-4 shrink-0" />
          </Button>
        </PopoverTrigger>
        <PopoverContent align="start" className="w-(--radix-popover-trigger-width) p-0">
          <div className="border-b p-2">
            <SearchField
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search permissions..."
              aria-label="Search permissions"
            />
          </div>
          <div className="max-h-72 overflow-y-auto p-1">
            {groups.length ? (
              groups.map((group) => (
                <PermissionGroup
                  key={group.module}
                  module={group.module}
                  entries={group.items}
                  assigned={assigned}
                  picked={picked}
                  onToggle={toggle}
                />
              ))
            ) : (
              <p className="text-muted-foreground px-2 py-6 text-center text-sm">
                {items.length ? `No permissions match “${search.trim()}”.` : 'There are no permissions to assign.'}
              </p>
            )}
          </div>
          <div className="flex items-center justify-between gap-2 border-t p-2">
            <span className="text-muted-foreground px-1 text-xs">{picked.length} selected</span>
            <Button type="button" size="sm" onClick={assign} disabled={!picked.length}>
              Apply
            </Button>
          </div>
        </PopoverContent>
      </Popover>
      <Button type="button" className="h-10" onClick={assign} disabled={disabled || !picked.length}>
        Assign Selected
      </Button>
    </div>
  );
}

/** Remove for a permission the viewer may revoke; for any other, a lock and the reason. */
function RemoveAction({ entry, reason, disabled, onRemove }) {
  if (reason) {
    return (
      <span title={reason} className="text-muted-foreground inline-flex size-8 items-center justify-center">
        <LockIcon className="size-4" />
        <span className="sr-only">{reason}</span>
      </span>
    );
  }
  return (
    <Button
      type="button"
      variant="ghost"
      size="icon"
      className="text-muted-foreground hover:text-destructive size-8"
      onClick={() => onRemove(entry.permission)}
      disabled={disabled}
      aria-label={`Remove ${entry.label}`}
    >
      <Trash2Icon className="size-4" />
    </Button>
  );
}

/** "Assigned Permissions": what the form will save, searchable; `added` are not saved yet. */
function AssignedPermissions({ rows, added, readOnly, disabled, lockReason, onRemove }) {
  const [search, setSearch] = useState('');
  const shown = rows.filter((entry) => matchesSearch(entry, search));

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <h3 className="text-sm font-semibold">
          Assigned Permissions <span className="text-muted-foreground font-normal">({rows.length})</span>
        </h3>
        <SearchField
          className="sm:w-72"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          // Enter would otherwise submit the details form around this field.
          onKeyDown={(event) => {
            if (event.key === 'Enter') event.preventDefault();
          }}
          placeholder="Search assigned permissions..."
          aria-label="Search assigned permissions"
          disabled={!rows.length}
        />
      </div>

      {rows.length ? (
        <div className="overflow-hidden rounded-md border">
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>Permission Name</TableHead>
                <TableHead>Module</TableHead>
                {readOnly ? null : <TableHead className="w-24 text-right">Remove</TableHead>}
              </TableRow>
            </TableHeader>
            <TableBody>
              {shown.length ? (
                shown.map((entry) => (
                  <TableRow key={entry.permission}>
                    <TableCell>
                      <span className="flex items-center gap-2">
                        <ShieldCheckIcon className="text-muted-foreground size-4 shrink-0" />
                        {entry.label}
                        {added.has(entry.permission) ? <Badge variant="warning">Unsaved</Badge> : null}
                      </span>
                    </TableCell>
                    <TableCell>
                      {entry.module ? (
                        <Badge variant="secondary">{entry.module}</Badge>
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </TableCell>
                    {readOnly ? null : (
                      <TableCell className="text-right">
                        <RemoveAction
                          entry={entry}
                          reason={lockReason(entry)}
                          disabled={disabled}
                          onRemove={onRemove}
                        />
                      </TableCell>
                    )}
                  </TableRow>
                ))
              ) : (
                <TableRow className="hover:bg-transparent">
                  <TableCell colSpan={readOnly ? 2 : 3} className="text-muted-foreground h-16 text-center text-sm">
                    No assigned permissions match “{search.trim()}”.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </div>
      ) : (
        <div className="text-muted-foreground flex flex-col items-center gap-1 rounded-md border border-dashed px-4 py-10 text-center text-sm">
          <ShieldIcon className="mb-1 size-6" />
          <p className="text-foreground font-medium">No permissions assigned</p>
          <p>They have only what their role allows.{readOnly ? '' : ' Select permissions above to add more.'}</p>
        </div>
      )}
    </div>
  );
}

/**
 * The Permissions section of /team/:memberId: extra access from the approved
 * catalogue (GET /api/team/permissions/), on top of what the role allows.
 * Nothing is sent from here: the details form saves the final set in one
 * request (PUT /api/team/<id>/permissions/), and Cancel there discards it. The
 * API refuses to grant or revoke what the caller does not hold, so those
 * permissions are locked.
 *
 * `selected` is the set the form would save and `saved` the set as last saved.
 * `picked` is what is checked in the selector but not assigned yet; the form
 * holds it, so Cancel clears it and saving waits until it is assigned.
 */
export function MemberPermissionsEditor({
  catalogue,
  selected,
  saved,
  picked,
  onChange,
  onPickedChange,
  onRetryCatalogue,
  readOnly = false,
  disabled = false,
  error,
}) {
  const entries = new Map(catalogue.items.map((entry) => [entry.permission, entry]));
  // Without the catalogue, an assigned permission is known only by its code.
  const describe = (permission) =>
    entries.get(permission) ?? { permission, label: permission, module: null, can_grant: false };
  const assigned = new Set(selected);
  const rows = selected.map(describe).sort(byModuleThenLabel);
  const added = new Set(selected.filter((permission) => !saved.includes(permission)));
  const removed = saved.filter((permission) => !assigned.has(permission)).map(describe);

  const lockReason = (entry) => {
    if (catalogue.status !== 'ready') return NO_CATALOGUE;
    return entry.can_grant ? null : NOT_HELD;
  };

  // Through a Set, so nothing is ever assigned twice.
  const assign = () => {
    onChange(Array.from(new Set([...selected, ...picked])));
    onPickedChange([]);
  };

  const remove = (permission) => onChange(selected.filter((item) => item !== permission));

  const undoRemove = (permission) => {
    onChange([...selected, permission]);
    if (picked.includes(permission)) onPickedChange(picked.filter((item) => item !== permission));
  };

  let picker = null;
  if (!readOnly && catalogue.status === 'loading') {
    picker = <Skeleton className="h-10 w-full" />;
  } else if (!readOnly && catalogue.status === 'ready') {
    picker = (
      <PermissionPicker
        items={catalogue.items}
        assigned={assigned}
        picked={picked}
        onPickedChange={onPickedChange}
        onAssign={assign}
        disabled={disabled}
      />
    );
  }

  return (
    <section aria-labelledby="team-permissions-heading" className="flex flex-col gap-5 border-t pt-8">
      <div>
        <h2 id="team-permissions-heading" className="text-base font-semibold">
          Permissions
        </h2>
        <p className="text-muted-foreground mt-1 text-sm">
          Manage individual permissions for this team member. They add to what their role already allows.
        </p>
      </div>

      {catalogue.status === 'error' ? (
        <div
          role="alert"
          className="border-destructive/40 flex flex-wrap items-center justify-between gap-3 rounded-md border px-3 py-2"
        >
          <p className="text-destructive flex items-center gap-2 text-sm">
            <CircleAlertIcon className="size-4 shrink-0" />
            {catalogue.error}
          </p>
          {onRetryCatalogue ? (
            <Button type="button" variant="outline" size="sm" onClick={onRetryCatalogue}>
              Try again
            </Button>
          ) : null}
        </div>
      ) : null}

      {picker}

      {catalogue.status === 'loading' ? (
        <Skeleton className="h-28 w-full" />
      ) : (
        <AssignedPermissions
          rows={rows}
          added={added}
          readOnly={readOnly}
          disabled={disabled}
          lockReason={lockReason}
          onRemove={remove}
        />
      )}

      {removed.length ? (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
          <span className="text-muted-foreground">Removed, not saved yet:</span>{' '}
          {removed.map((entry) => (
            <span key={entry.permission} className="flex items-center gap-1.5">
              <span className="line-through">{entry.label}</span>{' '}
              <Button
                type="button"
                variant="link"
                size="sm"
                className="h-auto p-0"
                onClick={() => undoRemove(entry.permission)}
                disabled={disabled}
                aria-label={`Undo removing ${entry.label}`}
              >
                Undo
              </Button>
            </span>
          ))}
        </div>
      ) : null}

      {error ? (
        <p role="alert" className="text-destructive flex items-start gap-2 text-sm">
          <CircleAlertIcon className="mt-0.5 size-4 shrink-0" />
          <span>
            {error.message}
            {error.permissions?.length
              ? ` (${error.permissions.map((permission) => describe(permission).label).join(', ')})`
              : null}
          </span>
        </p>
      ) : null}
    </section>
  );
}
