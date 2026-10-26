import { BookOpen, CalendarCheck, ClipboardList, GraduationCap, History, LayoutDashboard, Mail, UsersRound } from 'lucide-react';

import { NavMain } from '@/components/nav-main';
import { NavUser } from '@/components/nav-user';
import { Sidebar, SidebarContent, SidebarFooter, SidebarHeader, SidebarMenuButton, SidebarRail } from '@/components/ui/sidebar';
import { canOpenPage } from '@/lib/access';

const navMain = [
  { title: 'Dashboard', url: '/dashboard', icon: LayoutDashboard },
  { title: 'Students', url: '/students', icon: GraduationCap },
  { title: 'Sessions', url: '/sessions', icon: CalendarCheck },
  { title: 'Exams', url: '/exams', icon: ClipboardList },
  { title: 'Homework', url: '/homework', icon: BookOpen },
  // The single staff-management entry, for managers and holders of view_team.
  { title: 'Team', url: '/team', icon: UsersRound },
  { title: 'Invitations', url: '/invitations', icon: Mail },
  { title: 'Activity', url: '/activity', icon: History },
];

export function AppSidebar({ user, logout, ...props }) {
  // Exactly the pages the route guards in App.jsx open for this account
  // (lib/access): those its permissions open. An account holding none is
  // offered nothing.
  const items = navMain.filter((item) => canOpenPage(user, item.url));

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
