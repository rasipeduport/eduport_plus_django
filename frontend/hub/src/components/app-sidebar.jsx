import { BookOpen, CalendarCheck, ClipboardList, GraduationCap, History, LayoutDashboard, Mail, UsersRound } from 'lucide-react';

import { NavMain } from '@/components/nav-main';
import { NavUser } from '@/components/nav-user';
import { Sidebar, SidebarContent, SidebarFooter, SidebarHeader, SidebarMenuButton, SidebarRail } from '@/components/ui/sidebar';
import { canViewTeam } from '@/lib/team';

const navMain = [
  { title: 'Dashboard', url: '/dashboard', icon: LayoutDashboard },
  { title: 'Students', url: '/students', icon: GraduationCap },
  { title: 'Sessions', url: '/sessions', icon: CalendarCheck },
  { title: 'Exams', url: '/exams', icon: ClipboardList },
  { title: 'Homework', url: '/homework', icon: BookOpen },
  // The single staff-management entry: admins, mentors and tutors alike.
  { title: 'Team', url: '/team', icon: UsersRound },
  { title: 'Invitations', url: '/invitations', icon: Mail },
  { title: 'Activity', url: '/activity', icon: History },
];

// Mentors and tutors get the operational pages and the activity log (the API
// pins it to their own entries); staff management and the invitation queue
// stay admin-only, matching the route guards in App.jsx and the backend
// permissions.
const STAFF_NAV_URLS = new Set(['/dashboard', '/students', '/sessions', '/exams', '/homework', '/activity']);
// Exams are mentor/admin only -- tutors are not involved.
const TUTOR_NAV_URLS = new Set(['/dashboard', '/students', '/sessions', '/homework', '/activity']);

export function AppSidebar({ user, logout, ...props }) {
  // Mentors and tutors granted accounts.view_team also get the read-only Team
  // directory (the same rule as the /team route guard).
  const allowed = (urls) => (item) => urls.has(item.url) || (item.url === '/team' && canViewTeam(user));
  const items =
    user?.role === 'TUTOR'
      ? navMain.filter(allowed(TUTOR_NAV_URLS))
      : user?.role === 'MENTOR'
        ? navMain.filter(allowed(STAFF_NAV_URLS))
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
