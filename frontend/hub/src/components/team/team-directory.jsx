import { useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { ChevronRightIcon, XIcon } from 'lucide-react';

import { Avatar, AvatarFallback } from '@/components/ui/avatar';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { getInitials } from '@/lib/utils';
import { TEAM_ROLES, roleLabel } from '@/lib/team';
import { MemberBadges } from './member-badges';

const ALL = '__all__';

const STATUSES = [
  { value: 'active', label: 'Active' },
  { value: 'deactivated', label: 'Deactivated' },
];

/**
 * The staff directory: search, role and status filters, and paging, all kept
 * in the URL (like the activity log) and applied by the API. Students are
 * never part of it; the API returns staff accounts only. Each row opens the
 * member's details page (/team/:memberId), where every change is made.
 */
export function TeamDirectory({ rows, total, page, pageSize, filters, pending, viewer, canManage }) {
  const [searchParams, setSearchParams] = useSearchParams();
  const [q, setQ] = useState(filters.q);

  // Keep the box in step when the URL changes underneath it (Clear, back).
  const [prevQ, setPrevQ] = useState(filters.q);
  if (filters.q !== prevQ) {
    setPrevQ(filters.q);
    setQ(filters.q);
  }

  const navigate = (updates) => {
    const params = new URLSearchParams(searchParams);
    for (const [key, value] of Object.entries(updates)) {
      if (value === null || value === '') params.delete(key);
      else params.set(key, value);
    }
    // Any filter change (anything but paging) resets to the first page.
    if (!('page' in updates)) params.delete('page');
    setSearchParams(params);
  };

  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const startRow = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const endRow = Math.min(page * pageSize, total);
  const hasFilters = Boolean(filters.q || filters.role || filters.status);

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <form
          className="min-w-0 flex-1 basis-full sm:flex-none sm:basis-auto"
          onSubmit={(event) => {
            event.preventDefault();
            navigate({ q: q.trim() || null });
          }}
        >
          <Input
            placeholder="Search name, username or email…"
            value={q}
            onChange={(event) => setQ(event.target.value)}
            className="w-full sm:w-72"
            aria-label="Search staff"
          />
        </form>
        <FilterSelect
          placeholder="All roles"
          label="Filter by role"
          value={filters.role || ALL}
          onChange={(value) => navigate({ role: value === ALL ? null : value })}
          options={TEAM_ROLES}
        />
        <FilterSelect
          placeholder="All statuses"
          label="Filter by status"
          value={filters.status || ALL}
          onChange={(value) => navigate({ status: value === ALL ? null : value })}
          options={STATUSES}
        />
        {hasFilters ? (
          <Button
            variant="ghost"
            size="sm"
            className="text-muted-foreground"
            onClick={() => setSearchParams(new URLSearchParams())}
          >
            <XIcon className="size-4" />
            Clear
          </Button>
        ) : null}
      </div>

      <div className="overflow-hidden rounded-md border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Username</TableHead>
              <TableHead>Email</TableHead>
              <TableHead>Role</TableHead>
              <TableHead>Status</TableHead>
              <TableHead className="w-10">
                <span className="sr-only">Open</span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody className={pending ? 'opacity-60' : undefined}>
            {rows.length === 0 ? (
              <TableRow>
                <TableCell colSpan={6} className="h-24 text-center">
                  {hasFilters ? 'No staff match these filters.' : 'No staff accounts yet.'}
                </TableCell>
              </TableRow>
            ) : (
              rows.map((member) => (
                <TableRow key={member.id}>
                  <TableCell>
                    <Link
                      to={`/team/${member.id}`}
                      className="flex w-fit items-center gap-2 font-medium hover:underline"
                    >
                      <Avatar className="size-8 rounded-full">
                        <AvatarFallback className="size-8 rounded-full">
                          {getInitials(member.full_name, member.email)}
                        </AvatarFallback>
                      </Avatar>
                      <span>{member.full_name || member.username}</span>
                      {member.id === viewer?.id ? <Badge variant="outline">You</Badge> : null}
                    </Link>
                  </TableCell>
                  <TableCell className="text-muted-foreground">{member.username}</TableCell>
                  <TableCell>{member.email}</TableCell>
                  <TableCell>{roleLabel(member.role)}</TableCell>
                  <TableCell>
                    <MemberBadges
                      member={member}
                      viewer={viewer}
                      detailed={canManage}
                      withRole={false}
                      withSelf={false}
                    />
                  </TableCell>
                  <TableCell>
                    <Button variant="ghost" size="icon" className="size-8" asChild>
                      <Link to={`/team/${member.id}`} aria-label={`Open ${member.full_name || member.username}`}>
                        <ChevronRightIcon className="size-4" />
                      </Link>
                    </Button>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-muted-foreground text-sm whitespace-nowrap">
          {total === 0 ? 'No results' : `Showing ${startRow}–${endRow} of ${total}`}
        </p>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            disabled={page <= 1 || pending}
            onClick={() => navigate({ page: String(page - 1) })}
          >
            Previous
          </Button>
          <span className="text-sm whitespace-nowrap">
            Page {page} of {totalPages}
          </span>
          <Button
            variant="outline"
            size="sm"
            disabled={page >= totalPages || pending}
            onClick={() => navigate({ page: String(page + 1) })}
          >
            Next
          </Button>
        </div>
      </div>
    </div>
  );
}

function FilterSelect({ placeholder, label, value, onChange, options }) {
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger
        size="sm"
        aria-label={label}
        className="min-w-0 flex-1 basis-36 sm:w-[160px] sm:flex-none sm:basis-auto"
      >
        <SelectValue placeholder={placeholder} />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={ALL}>{placeholder}</SelectItem>
        {options.map((option) => (
          <SelectItem key={option.value} value={option.value}>
            {option.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
