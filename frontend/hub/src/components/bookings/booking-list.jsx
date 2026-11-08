import { CalendarCheck, ChevronRightIcon, ClipboardCheck, SearchXIcon, UserRoundPlusIcon, XIcon } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { EmptyState } from '@/components/page/page';
import { FilterSelect, SearchField } from '@/components/page/list-toolbar';
import { Pagination } from '@/components/page/pagination';
import { ResponsiveList } from '@/components/page/responsive-list';
import { ASSIGNMENT_FILTERS, DEFAULT_WHEN, REPORT_DUE, REPORT_FILTERS, tutorChangeable } from '@/lib/bookings';
import { SCHEDULE_OPTIONS } from '@/lib/bde-booking-filters';
import { CLEARED_ADMIN_FILTERS } from '@/lib/admin-booking-filters';
import { slotLabel, slotParts } from '@/lib/enquiries';
import { reportBadge } from '@/lib/reports';
import { showsStudentTime } from '@/lib/timezone';
import { BookingStateBadge, RedemoBadge, TutorName } from './booking-badges';
import { ClassDateFilter } from './class-date-filter';
import { StudentTimeCell } from './student-time';

// The schedule select offers its default, Upcoming, as its empty value.
const OTHER_SCHEDULES = SCHEDULE_OPTIONS.filter((option) => option.value !== DEFAULT_WHEN);
const ICONS = { DEMO: CalendarCheck, DIAGNOSTIC: ClipboardCheck };

/**
 * The administrators' Demo and Diagnostic Bookings filters: the class date
 * (ClassDateFilter, as a BDE's lists have it), then search, booking status
 * (`statuses`), tutor assignment, report and schedule, and Clear all filters
 * while any is off its default. Reports are due only on slots that are over:
 * choosing Report due turns Upcoming into Past, and choosing Upcoming drops
 * Report due, so the two never empty the list together. `filters` are
 * readAdminBookingFilters'; `onChange(updates)` takes URL values (null for a
 * default) and `onClear()` puts every one back.
 */
export function AdminBookingFilters({ filters, statuses, onChange, onClear }) {
  return (
    <div className="flex flex-col gap-3">
      <ClassDateFilter filters={filters} onChange={onChange} />
      <div className="flex flex-wrap items-center gap-2">
        <SearchField
          value={filters.q}
          onSearch={(text) => onChange({ q: text || null })}
          label="Search bookings"
          placeholder="Search student, parent or phone…"
        />
        <FilterSelect
          label="Filter by booking status"
          placeholder="All statuses"
          value={filters.status}
          onChange={(value) => onChange({ status: value || null })}
          options={statuses}
        />
        <FilterSelect
          label="Filter by tutor assignment"
          placeholder="All tutors"
          value={filters.assigned}
          onChange={(value) => onChange({ assigned: value || null })}
          options={ASSIGNMENT_FILTERS}
        />
        <FilterSelect
          label="Filter by report"
          placeholder="All reports"
          value={filters.report}
          onChange={(value) => {
            const report = value || null;
            onChange(report === REPORT_DUE && filters.when === DEFAULT_WHEN ? { report, when: 'past' } : { report });
          }}
          options={REPORT_FILTERS}
        />
        <FilterSelect
          label="Filter by schedule"
          placeholder="Upcoming"
          value={filters.when === DEFAULT_WHEN ? '' : filters.when}
          onChange={(value) => onChange(value || filters.report !== REPORT_DUE ? { when: value || null } : { when: null, report: null })}
          options={OTHER_SCHEDULES}
        />
        {filters.filtered ? (
          <Button variant="ghost" className="text-muted-foreground" onClick={onClear}>
            <XIcon className="size-4" />
            Clear all filters
          </Button>
        ) : null}
      </div>
    </div>
  );
}

function Report({ booking }) {
  const report = reportBadge(booking);
  return report ? <Badge variant={report.variant}>{report.label}</Badge> : <span className="text-muted-foreground">—</span>;
}

/**
 * A row's actions, in the BDE booking lists' outline buttons: Assign, for a
 * booking with no tutor that may still take one (holders of
 * accounts.assign_booking_tutor), and View, which opens the booking's
 * workspace -- where a tutor already assigned is changed.
 */
function Actions({ booking, canAssign, onOpen, onAssign, className }) {
  const assignable = canAssign && !booking.tutor && tutorChangeable(booking);
  return (
    <div className={className ?? 'flex justify-end gap-2'}>
      {assignable ? (
        <Button
          variant="outline"
          size="sm"
          onClick={() => onAssign(booking)}
          aria-label={`Assign the tutor for ${booking.student_name}`}
        >
          <UserRoundPlusIcon />
          Assign
        </Button>
      ) : null}
      <Button
        variant="outline"
        size="sm"
        onClick={() => onOpen(booking.id)}
        aria-label={`View the booking for ${booking.student_name}`}
      >
        View
        <ChevronRightIcon />
      </Button>
    </div>
  );
}

/**
 * Every booking of one type, as administrators manage them: when, the child
 * and parent, who teaches it, where it stands and its report (the version
 * submitted, or Report due), with a way to open it and, for holders of
 * accounts.assign_booking_tutor, to assign a tutor to one that has none (a
 * tutor already assigned is changed in the booking's workspace) -- a table
 * where it fits, a card per booking on a phone or a narrow screen. Beside the
 * Indian time, the student's own while any booking shown reads differently
 * (Student Time). Empty, it says why and offers the way on; the API pages it.
 * `noun` names the type's bookings ("demo classes"); `onChange` receives what
 * changed in the URL.
 */
export function BookingList({ rows, total, page, pageSize, filters, pending, canAssign, noun, onChange, onClear, onOpen, onAssign }) {
  const showStudentTime = showsStudentTime(rows, (booking) => booking.slot?.starts_at, (booking) => booking.student_timezone);
  const studentTime = (booking) => <StudentTimeCell startsAt={booking.slot?.starts_at} timezone={booking.student_timezone} />;
  const columns = [
    {
      key: 'when',
      header: 'Date & Time',
      className: 'whitespace-nowrap',
      cell: (booking) => {
        const when = slotParts(booking.slot.date, booking.slot.time);
        return (
          <>
            <p className="font-medium">{when.day}</p>
            <p className="text-muted-foreground text-xs">{when.time} IST</p>
          </>
        );
      },
    },
    ...(showStudentTime ? [{ key: 'student_time', header: 'Student Time', className: 'whitespace-nowrap', cell: studentTime }] : []),
    {
      key: 'student',
      header: 'Student',
      className: 'min-w-28 whitespace-normal',
      cell: (booking) => (
        <>
          <p className="font-medium break-words">{booking.student_name}</p>
          {booking.grade ? <p className="text-muted-foreground text-xs">{booking.grade}</p> : null}
          {booking.redemo_for_id ? <RedemoBadge /> : null}
        </>
      ),
    },
    {
      key: 'parent',
      header: 'Parent',
      className: 'min-w-32 whitespace-normal',
      cell: (booking) => (
        <>
          <p className="break-words">{booking.parent_name}</p>
          <p className="text-muted-foreground text-xs whitespace-nowrap tabular-nums">{booking.phone}</p>
        </>
      ),
    },
    { key: 'tutor', header: 'Tutor', className: 'whitespace-normal', cell: (booking) => <TutorName booking={booking} /> },
    { key: 'status', header: 'Status', cell: (booking) => <BookingStateBadge booking={booking} /> },
    { key: 'report', header: 'Report', cell: (booking) => <Report booking={booking} /> },
    {
      key: 'actions',
      header: { srOnly: 'Actions' },
      headerClassName: 'w-px',
      cell: (booking) => <Actions booking={booking} canAssign={canAssign} onOpen={onOpen} onAssign={onAssign} />,
    },
  ];

  const renderCard = (booking) => (
    <article className="bg-card flex h-full flex-col gap-3 rounded-xl border p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="truncate font-medium">{booking.student_name}</h2>
          <p className="text-muted-foreground truncate text-sm">
            {[booking.grade, booking.parent_name].filter(Boolean).join(' · ')}
          </p>
        </div>
        <span className="flex flex-wrap justify-end gap-1">
          <BookingStateBadge booking={booking} />
          {booking.redemo_for_id ? <RedemoBadge /> : null}
        </span>
      </div>
      <div className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
        <div className="col-span-2 min-w-0">
          <p className="text-muted-foreground text-xs">Date & Time</p>
          <p className="truncate">{slotLabel(booking.slot)}</p>
        </div>
        {showStudentTime ? (
          <div className="col-span-2 min-w-0">
            <p className="text-muted-foreground text-xs">Student Time</p>
            <p className="truncate">{studentTime(booking)}</p>
          </div>
        ) : null}
        <div className="min-w-0">
          <p className="text-muted-foreground text-xs">Tutor</p>
          <TutorName booking={booking} />
        </div>
        <div className="min-w-0">
          <p className="text-muted-foreground text-xs">Report</p>
          <Report booking={booking} />
        </div>
        <div className="col-span-2 min-w-0">
          <p className="text-muted-foreground text-xs">Parent&apos;s phone</p>
          <p className="truncate tabular-nums">{booking.phone}</p>
        </div>
      </div>
      <Actions
        booking={booking}
        canAssign={canAssign}
        onOpen={onOpen}
        onAssign={onAssign}
        className="mt-auto flex flex-wrap gap-2 border-t pt-3"
      />
    </article>
  );

  let body;
  if (rows.length) {
    body = (
      <ResponsiveList
        label={`${noun[0].toUpperCase()}${noun.slice(1)}`}
        columns={columns}
        rows={rows}
        pending={pending}
        minTableWidth={980}
        renderCard={renderCard}
      />
    );
  } else if (total > 0) {
    body = (
      <EmptyState
        icon={SearchXIcon}
        title="Nothing on this page"
        description="This page is past the last one."
        action={
          <Button variant="outline" onClick={() => onChange({ page: null })}>
            Go to the first page
          </Button>
        }
      />
    );
  } else if (filters.filtered) {
    body = (
      <EmptyState
        icon={SearchXIcon}
        title={`No ${noun} match these filters`}
        description="Try another search, status or dates, or clear the filters."
        action={
          <Button variant="outline" onClick={onClear}>
            Clear all filters
          </Button>
        }
      />
    );
  } else {
    body = (
      <EmptyState
        icon={ICONS[filters.type]}
        title={`No upcoming ${noun}`}
        description={`Upcoming ${noun} parents book appear here. Earlier ones are under All Schedules.`}
        action={
          <Button variant="outline" onClick={() => onChange({ ...CLEARED_ADMIN_FILTERS, when: 'all' })}>
            Show all schedules
          </Button>
        }
      />
    );
  }

  return (
    <>
      {body}
      {total > 0 ? (
        <Pagination
          page={page}
          pageSize={pageSize}
          total={total}
          pending={pending}
          onPageChange={(next) => onChange({ page: String(next) })}
        />
      ) : null}
    </>
  );
}
