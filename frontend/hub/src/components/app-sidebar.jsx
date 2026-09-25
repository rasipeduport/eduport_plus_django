import { CalendarCheck, Compass, GraduationCap, History, LayoutDashboard, Mail, Presentation, ShieldCheck } from 'lucide-react';

import { NavMain } from '@/components/nav-main';
import { NavUser } from '@/components/nav-user';
import { Sidebar, SidebarContent, SidebarFooter, SidebarHeader, SidebarMenuButton, SidebarRail } from '@/components/ui/sidebar';

const navMain = [
  { title: 'Dashboard', url: '/dashboard', icon: LayoutDashboard },
  { title: 'Students', url: '/students', icon: GraduationCap },
  { title: 'Sessions', url: '/sessions', icon: CalendarCheck },
  { title: 'Admins', url: '/admins', icon: ShieldCheck },
  { title: 'Mentors', url: '/mentors', icon: Compass },
  { title: 'Tutors', url: '/tutors', icon: Presentation },
  { title: 'Invitations', url: '/invitations', icon: Mail },
  { title: 'Activity', url: '/activity', icon: History },
];

// Mentors and tutors only get the operational pages; staff management, the
// invitation queue and the audit log stay admin-only, matching the route guards
// in App.jsx and the backend permissions.
const STAFF_NAV_URLS = new Set(['/dashboard', '/students', '/sessions']);

export function AppSidebar({ user, logout, ...props }) {
  const items =
    user?.role === 'MENTOR' || user?.role === 'TUTOR'
      ? navMain.filter((item) => STAFF_NAV_URLS.has(item.url))
      : navMain;

  return (
    <Sidebar collapsible="icon" {...props}>
      <SidebarHeader>
        <SidebarMenuButton
          size="lg"
          className="data-[state=open]:bg-sidebar-accent data-[state=open]:text-sidebar-accent-foreground"
        >
          <div className="bg-sidebar-primary text-sidebar-primary-foreground flex aspect-square size-8 items-center justify-center rounded-lg">
            <img src="/icon-transparent.png" alt="Eduport Plus Icon" width={24} height={24} />
          </div>
          <div className="grid flex-1 text-left text-sm leading-tight">
            <span className="truncate font-medium">Eduport Plus</span>
            <span className="truncate text-xs">Hub</span>
          </div>
        </SidebarMenuButton>
      </SidebarHeader>
      <SidebarContent>
        <NavMain items={items} />
      </SidebarContent>
      <SidebarFooter>
        <NavUser user={user} logout={logout} />
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  );
}
