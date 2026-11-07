import {
  BadgePercent,
  BookOpen,
  CalendarCheck,
  CalendarCheck2,
  CalendarClock,
  CalendarDays,
  ClipboardCheck,
  ClipboardList,
  GraduationCap,
  History,
  Inbox,
  LayoutDashboard,
  Mail,
  PhoneCall,
  ReceiptIndianRupee,
  Users,
  UsersRound,
} from 'lucide-react';

import { canOpenPage, isBde } from '@/lib/access';

// What the sidebar offers, workspace by workspace. Each workspace names itself
// under the logo and lists its sections: an optional `label`, and items of
// `title`, `url` and `icon`, plus `badge` (a note such as "Coming Soon") and
// `nested` (the item stays highlighted on the pages under its address, such as
// one enquiry under My Enquiries). The sidebar shows exactly the items whose
// pages the route guards open for the account (lib/access canOpenPage), and no
// section none of whose items open.

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
// Diagnostic bookings parents make -- for administrators each booking and its
// tutor, and the slots they are booked into; for a tutor the bookings they are
// assigned to teach.
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
        { title: 'My Bookings', url: '/my-bookings', icon: CalendarDays },
      ],
    },
  ],
};

/** `{ name, sections }`: the workspace `user` works in, holding only the items they may open. */
export function workspaceFor(user) {
  const workspace = isBde(user) ? BDE_WORKSPACE : STAFF_WORKSPACE;
  const sections = workspace.sections
    .map((section) => ({ ...section, items: section.items.filter((item) => canOpenPage(user, item.url)) }))
    .filter((section) => section.items.length > 0);
  return { name: workspace.name, sections };
}

/**
 * Whether `item` is the page at `pathname` -- or, for a `nested` item, a page
 * under it. A page opened from another list (`fromPath`, the way back a link
 * passed: an enquiry opened from Demo Bookings, say) keeps that list current.
 */
export function isCurrentItem(item, pathname, fromPath = null) {
  const origin = fromPath ? fromPath.split('?')[0] : null;
  if (origin && origin !== pathname) return origin === item.url;
  return pathname === item.url || (Boolean(item.nested) && pathname.startsWith(`${item.url}/`));
}
