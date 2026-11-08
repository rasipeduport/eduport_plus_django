import {
  BadgePercent,
  BookMarked,
  BookOpen,
  Briefcase,
  CalendarCheck,
  CalendarCheck2,
  CalendarClock,
  ChartColumn,
  ClipboardCheck,
  ClipboardList,
  ClipboardPen,
  GraduationCap,
  History,
  Inbox,
  LayoutDashboard,
  LayoutGrid,
  Mail,
  PhoneCall,
  ReceiptIndianRupee,
  School,
  Users,
  UsersRound,
  Wallet,
} from 'lucide-react';

import { canOpenPage, isAdmin, isBde, isTutor } from '@/lib/access';

// What the sidebar offers, workspace by workspace. Each workspace names itself
// under the logo and lists its sections: an optional `label`, and items of
// `title`, `url` and `icon`, plus `badge` (a note such as "Coming Soon") and
// `nested` (the item stays highlighted on the pages under its address, such as
// one enquiry under My Enquiries). An item may instead hold `children` (items
// of `title` and `url`), shown as a submenu that opens and closes under it,
// such as Bookings' Demo and Diagnostic. A `collapsible` workspace lets each
// labelled section fold away under its heading. The sidebar shows exactly the
// items whose pages the route guards open for the account (lib/access
// canOpenPage), an item with children while any child opens, and no section
// none of whose items open.

export const COMING_SOON = 'Coming Soon';

// The BDE workspace: their own enquiries, the Demo and Diagnostic bookings
// made for them and what to follow up, then what is still being built and the
// BDE's activity.
const BDE_WORKSPACE = {
  name: 'BDE Hub',
  sections: [
    {
      items: [
        { title: 'Dashboard', url: '/dashboard', icon: LayoutDashboard },
        { title: 'My Enquiries', url: '/enquiries', icon: Inbox, nested: true },
        { title: 'Demo Bookings', url: '/demo-bookings', icon: CalendarCheck },
        { title: 'Diagnostic Bookings', url: '/diagnostic-bookings', icon: ClipboardCheck },
        { title: 'Follow-ups', url: '/follow-ups', icon: PhoneCall },
      ],
    },
    {
      items: [
        { title: 'My Sales', url: '/sales', icon: ReceiptIndianRupee, badge: COMING_SOON },
        { title: 'Plans & Pricing', url: '/plans', icon: BadgePercent, badge: COMING_SOON },
        { title: 'Activity', url: '/activity', icon: History },
      ],
    },
  ],
};

// Everyone else's Hub, as it has been: the modules, then the Demo and
// Diagnostic bookings parents make -- each booking and its tutor, and the
// slots they are booked into -- for whoever may manage them.
const STAFF_WORKSPACE = {
  name: 'Hub',
  sections: [
    {
      items: [
        { title: 'Dashboard', url: '/dashboard', icon: LayoutDashboard },
        // Every lead, for administrators.
        { title: 'Leads', url: '/leads', icon: Users },
        { title: 'Students', url: '/students', icon: GraduationCap },
        { title: 'Sessions', url: '/sessions', icon: CalendarCheck },
        { title: 'Exams', url: '/exams', icon: ClipboardList },
        { title: 'Homework', url: '/homework', icon: BookOpen },
        // The single staff-management entry, for managers and holders of view_team.
        { title: 'Team', url: '/team', icon: UsersRound },
        { title: 'Invitations', url: '/invitations', icon: Mail },
        { title: 'Activity', url: '/activity', icon: History },
      ],
    },
    {
      label: 'Demo & Diagnostic',
      items: [
        { title: 'Bookings', url: '/bookings', icon: CalendarCheck2 },
        { title: 'Booking slots', url: '/booking-slots', icon: CalendarClock },
      ],
    },
  ],
};

// The Admin Hub: its common Dashboard (still to come) on top, then the
// admissions pipeline (its dashboard, every lead, the Demo and Diagnostic
// bookings and their slots), the Sales & Finance modules still to come, the
// academic modules with their dashboard, the staff and invitations, and the
// activity log.
const ADMIN_WORKSPACE = {
  name: 'Admin Hub',
  collapsible: true,
  sections: [
    {
      items: [{ title: 'Dashboard', url: '/dashboard', icon: LayoutDashboard }],
    },
    {
      label: 'Admissions',
      items: [
        { title: 'Admissions Dashboard', url: '/admissions', icon: LayoutGrid },
        { title: 'Leads', url: '/leads', icon: Users, nested: true },
        {
          title: 'Bookings',
          icon: CalendarCheck2,
          // Each stays highlighted on its bookings' own pages (/bookings/<type>/<id>).
          children: [
            { title: 'Demo', url: '/bookings/demo', nested: true },
            { title: 'Diagnostic', url: '/bookings/diagnostic', nested: true },
          ],
        },
        { title: 'Booking Slots', url: '/booking-slots', icon: CalendarClock },
      ],
    },
    {
      label: 'Sales & Finance',
      items: [
        { title: 'Sales Dashboard', url: '/sales-dashboard', icon: ChartColumn, badge: COMING_SOON },
        { title: 'Sales Module', url: '/sales-module', icon: Briefcase, badge: COMING_SOON },
        { title: 'Sales Punching', url: '/sales-punching', icon: ClipboardPen, badge: COMING_SOON },
        { title: 'Sales Syllabus', url: '/sales-syllabus', icon: BookMarked, badge: COMING_SOON },
        { title: 'Tutor Earnings', url: '/tutor-earnings', icon: Wallet, badge: COMING_SOON },
      ],
    },
    {
      label: 'Academics & Learning',
      items: [
        { title: 'Academics Dashboard', url: '/academics-dashboard', icon: School },
        { title: 'Enrolled Students', url: '/students', icon: GraduationCap, nested: true },
        { title: 'Sessions', url: '/sessions', icon: CalendarCheck },
        { title: 'Exams', url: '/exams', icon: ClipboardList },
        { title: 'Homework', url: '/homework', icon: BookOpen },
      ],
    },
    {
      label: 'Organization',
      items: [
        { title: 'Team', url: '/team', icon: UsersRound, nested: true },
        { title: 'Invitations', url: '/invitations', icon: Mail },
      ],
    },
    {
      label: 'Monitoring',
      items: [{ title: 'Activity Log', url: '/activity', icon: History }],
    },
  ],
};

// The Tutor Hub: their Dashboard and the Demo and Diagnostic bookings they are
// assigned to teach on top, then their regular teaching (Academics &
// Learning), their earnings still to come, and their own activity.
const TUTOR_WORKSPACE = {
  name: 'Tutor Hub',
  collapsible: true,
  sections: [
    {
      items: [
        { title: 'Dashboard', url: '/dashboard', icon: LayoutDashboard },
        {
          title: 'Bookings',
          icon: CalendarCheck2,
          // Each stays highlighted on its bookings' own pages (/my-bookings/<type>/<id>, and its report).
          children: [
            { title: 'Demo', url: '/my-bookings/demo', nested: true },
            { title: 'Diagnostic', url: '/my-bookings/diagnostic', nested: true },
          ],
        },
      ],
    },
    {
      label: 'Academics & Learning',
      items: [
        { title: 'My Students', url: '/students', icon: GraduationCap, nested: true },
        { title: 'Sessions', url: '/sessions', icon: CalendarCheck },
        // Shown only to a tutor granted an exam permission: the TUTOR role holds none.
        { title: 'Exams', url: '/exams', icon: ClipboardList },
        { title: 'Homework', url: '/homework', icon: BookOpen },
      ],
    },
    {
      label: 'Earnings',
      items: [{ title: 'Hourly Earnings', url: '/hourly-earnings', icon: Wallet, badge: COMING_SOON }],
    },
    {
      label: 'Monitoring',
      items: [{ title: 'Activity', url: '/activity', icon: History }],
    },
  ],
};

function workspaceOf(user) {
  if (isBde(user)) return BDE_WORKSPACE;
  if (isTutor(user)) return TUTOR_WORKSPACE;
  return isAdmin(user) ? ADMIN_WORKSPACE : STAFF_WORKSPACE;
}

/** `item` holding only what `user` may open, or null when that is nothing. */
function openable(user, item) {
  if (!item.children) return canOpenPage(user, item.url) ? item : null;
  const children = item.children.filter((child) => canOpenPage(user, child.url));
  return children.length > 0 ? { ...item, children } : null;
}

/** `{ name, collapsible, sections }`: the workspace `user` works in, holding only the items they may open. */
export function workspaceFor(user) {
  const workspace = workspaceOf(user);
  const sections = workspace.sections
    .map((section) => ({ ...section, items: section.items.map((item) => openable(user, item)).filter(Boolean) }))
    .filter((section) => section.items.length > 0);
  return { name: workspace.name, collapsible: Boolean(workspace.collapsible), sections };
}

/**
 * Whether `item` is the page at `pathname` -- or, for a `nested` item, a page
 * under it; for an item with children, whether one of them is. A page opened
 * from another page (`fromPath`, the way back a link passed: an enquiry opened
 * from Demo Bookings, say, or a tutor's report opened from its booking) keeps
 * the item of that page current.
 */
export function isCurrentItem(item, pathname, fromPath = null) {
  if (item.children) return item.children.some((child) => isCurrentItem(child, pathname, fromPath));
  const origin = fromPath ? fromPath.split('?')[0] : null;
  const here = origin && origin !== pathname ? origin : pathname;
  return here === item.url || (Boolean(item.nested) && here.startsWith(`${item.url}/`));
}
