import { CalendarCheck, CalendarClock, ClipboardList, Mail, Phone } from 'lucide-react';
import { format } from 'date-fns';

import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { DEFAULT_TIMEZONE } from '@/lib/timezone';
import { EMPTY, FieldCard, StatTile } from './profile-primitives';

const DATE_TIME = "d MMM yyyy, h:mm a";

/** At most one decimal, and no trailing ".0" — how the quota is written. */
function formatNumber(value) {
  if (value == null) return EMPTY;
  const rounded = Math.round(value * 10) / 10;
  return Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(1);
}

function plural(count, singular, pluralForm = `${singular}s`) {
  return `${count} ${count === 1 ? singular : pluralForm}`;
}

function formatDay(value) {
  if (!value) return EMPTY;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? EMPTY : format(date, 'd MMM yyyy');
}

function formatMoment(value) {
  if (!value) return EMPTY;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? EMPTY : format(date, DATE_TIME);
}

/**
 * Purchased comes from the enrolment sheet's "No of classes paid for" column
 * (synced hourly); used and remaining are hours of booked classes, exactly as
 * the scheduling sheet shows them.
 */
function QuotaBar({ quota }) {
  const purchased = quota.purchased || 0;
  const used = quota.used_hours || 0;
  const over = quota.remaining_hours < 0;
  const pct = purchased > 0 ? Math.min(100, (used / purchased) * 100) : 0;

  return (
    <FieldCard
      title="Class quota"
      fields={[
        { label: 'Purchased', value: `${formatNumber(purchased)} hrs` },
        { label: 'Used', value: `${formatNumber(used)} hrs` },
        {
          label: 'Remaining',
          value: (
            <span className={cn('font-medium', over ? 'text-destructive' : 'text-foreground')}>
              {formatNumber(quota.remaining_hours)} hrs
            </span>
          ),
        },
      ]}
    >
      <div className="mt-4">
        <div className="bg-muted h-2 w-full overflow-hidden rounded-full">
          <div
            className={cn('h-full rounded-full transition-all', over ? 'bg-destructive' : 'bg-primary')}
            style={{ width: `${over ? 100 : pct}%` }}
          />
        </div>
        <p className="text-muted-foreground mt-2 text-xs">
          {purchased === 0
            ? 'Nothing paid for yet — set "No of classes paid for" in the enrolment sheet before booking classes.'
            : over
              ? `Over the purchased quota by ${formatNumber(Math.abs(quota.remaining_hours))} hrs.`
              : `${formatNumber(used)} of ${formatNumber(purchased)} hrs booked. Cancelled classes are not counted.`}
        </p>
      </div>
    </FieldCard>
  );
}

/** The next class, the last one held and the next exam, when there are any. */
function NextUp({ highlights, onOpenTab }) {
  const rows = [
    highlights.next_session && {
      key: 'next_session',
      icon: CalendarClock,
      label: 'Next class',
      title: highlights.next_session.title,
      when: formatMoment(highlights.next_session.start_time),
      tab: 'sessions',
    },
    highlights.last_session && {
      key: 'last_session',
      icon: CalendarCheck,
      label: 'Last class held',
      title: highlights.last_session.title,
      when: formatMoment(highlights.last_session.start_time),
      tab: 'sessions',
    },
    highlights.next_exam && {
      key: 'next_exam',
      icon: ClipboardList,
      label: 'Next exam',
      title: highlights.next_exam.chapter_name,
      when: formatMoment(highlights.next_exam.start_time),
      tab: 'exams',
    },
  ].filter(Boolean);

  if (rows.length === 0) return null;

  // With nothing booked ahead, "Next up" would be a lie: the card then just
  // reports the last class that happened.
  const ahead = Boolean(highlights.next_session || highlights.next_exam);

  return (
    <FieldCard title={ahead ? 'Next up' : 'Most recent'} fields={[]} className="sm:col-span-2">
      <ul className="divide-y">
        {rows.map((row) => (
          <li key={row.key} className="flex items-center gap-3 py-2.5 first:pt-0 last:pb-0">
            <row.icon className="text-muted-foreground size-4 shrink-0" />
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium">{row.title}</p>
              <p className="text-muted-foreground text-xs">{row.label}</p>
            </div>
            <span className="text-muted-foreground shrink-0 text-xs whitespace-nowrap">{row.when}</span>
            <Button variant="ghost" size="sm" className="shrink-0" onClick={() => onOpenTab(row.tab)}>
              Open
            </Button>
          </li>
        ))}
      </ul>
    </FieldCard>
  );
}

function StaffLine({ profile }) {
  if (!profile) return <span className="text-muted-foreground">Not assigned</span>;
  const name = profile.full_name || profile.email;
  return (
    <span className="block truncate" title={profile.email}>
      {name}
      {profile.full_name && profile.email ? (
        <span className="text-muted-foreground"> · {profile.email}</span>
      ) : null}
    </span>
  );
}

/**
 * Overview tab: the whole student on one screen, without becoming a
 * dashboard. Four counters, then the enrolment facts as definition lists,
 * then quota and what happens next. Fields the caller's role is not served
 * (a tutor gets no contact details or quota) are dropped, not blanked.
 */
export function OverviewTab({ student, stats, highlights, role, onOpenTab }) {
  const isAdmin = role === 'admin';
  const has = (key) => key in student;
  const quota = stats.quota ?? null;
  const exams = stats.exams ?? null;
  const sessions = stats.sessions ?? {};
  const homework = stats.homework ?? {};

  const toReview = homework.submitted ?? 0;
  const missingContent = sessions.pending ?? 0;

  // Four counters, each a different question. The quota tile is the headline
  // where there is a quota to report; a tutor, who is served none, leads with
  // the classes instead — never the same number twice.
  const tiles = [
    quota
      ? {
          label: 'Quota remaining',
          value: `${formatNumber(quota.remaining_hours)} hrs`,
          hint: `of ${formatNumber(quota.purchased)} hrs purchased`,
          tone: quota.remaining_hours <= 0 ? 'destructive' : quota.remaining_hours <= 2 ? 'warning' : 'default',
        }
      : {
          label: 'Classes booked',
          value: sessions.total ?? 0,
          hint: `${sessions.cancelled ?? 0} cancelled`,
        },
    {
      label: 'Classes attended',
      value: sessions.attended ?? 0,
      hint: `${sessions.upcoming ?? 0} upcoming`,
    },
    exams
      ? {
          label: 'Exam average',
          value: exams.chapter.average_pct != null ? `${formatNumber(exams.chapter.average_pct)}%` : EMPTY,
          hint: `${exams.chapter.scored} of ${plural(exams.chapter.total, 'exam')} scored`,
        }
      : {
          label: 'Homework scored',
          value: homework.scored ?? 0,
          hint: `of ${plural(homework.total ?? 0, 'assignment')}`,
        },
    {
      label: 'Needs attention',
      value: toReview + missingContent,
      hint: `${plural(toReview, 'homework', 'homework')} to review · ${plural(missingContent, 'class', 'classes')} missing content`,
      tone: toReview + missingContent > 0 ? 'warning' : 'default',
    },
  ];

  const contactFields = [
    {
      label: 'Email',
      value: student.profile?.email,
      // Email is an admin column on the students table; the profile keeps it so.
      hidden: !isAdmin || !student.profile,
      title: student.profile?.email,
    },
    { label: 'Mobile', value: student.mobile_number, hidden: !has('mobile_number') },
    { label: 'Country', value: student.country, hidden: !has('country') },
    // State is an admin column too.
    { label: 'State', value: student.state, hidden: !isAdmin || !has('state') },
  ];
  const showContact = contactFields.some((field) => !field.hidden);

  const academicFields = [
    { label: 'School', value: student.school_name, hidden: !has('school_name') },
    { label: 'Grade', value: student.grade },
    { label: 'Syllabus', value: student.syllabus },
    { label: 'Admission date', value: formatDay(student.admission_date), hidden: !has('admission_date') },
    { label: 'Joined', value: formatDay(student.created_at) },
    {
      label: 'Time zone',
      value: student.timezone || `${DEFAULT_TIMEZONE} (default)`,
    },
  ];

  const staffFields = [
    { label: 'Mentor', value: <StaffLine profile={student.mentor_profile} />, full: true },
    { label: 'Tutor', value: <StaffLine profile={student.tutor_profile} />, full: true },
  ];

  return (
    <div className="flex flex-col gap-6">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {tiles.map((tile) => (
          <StatTile key={tile.label} {...tile} />
        ))}
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        {showContact ? (
          <FieldCard
            title="Contact"
            fields={contactFields}
            action={
              student.mobile_number || student.profile?.email ? (
                <div className="text-muted-foreground flex gap-1">
                  {student.profile?.email && isAdmin ? (
                    <Button variant="ghost" size="icon" className="size-7" asChild>
                      <a href={`mailto:${student.profile.email}`} aria-label="Email student">
                        <Mail className="size-3.5" />
                      </a>
                    </Button>
                  ) : null}
                  {student.mobile_number ? (
                    <Button variant="ghost" size="icon" className="size-7" asChild>
                      <a href={`tel:${student.mobile_number}`} aria-label="Call student">
                        <Phone className="size-3.5" />
                      </a>
                    </Button>
                  ) : null}
                </div>
              ) : null
            }
          />
        ) : null}
        <FieldCard title="Academic" fields={academicFields} />
        <FieldCard title="Assigned staff" fields={staffFields} />
        {quota ? <QuotaBar quota={quota} /> : null}
        <NextUp highlights={highlights} onOpenTab={onOpenTab} />
        {has('remarks_for_mentor') && student.remarks_for_mentor ? (
          <FieldCard title="Remarks for mentor" fields={[]} className="sm:col-span-2">
            <p className="text-sm leading-relaxed whitespace-pre-wrap">{student.remarks_for_mentor}</p>
          </FieldCard>
        ) : null}
        {student.status !== 'active' && student.status_note ? (
          <FieldCard
            title={`Why this student is ${student.status}`}
            fields={[]}
            className="sm:col-span-2"
          >
            <p className="text-sm leading-relaxed whitespace-pre-wrap">{student.status_note}</p>
          </FieldCard>
        ) : null}
      </div>
    </div>
  );
}
