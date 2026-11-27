import { Fragment } from 'react';

import { NavMain } from '@/components/nav-main';
import { NavUser } from '@/components/nav-user';
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
  SidebarMenuButton,
  SidebarRail,
  SidebarSeparator,
} from '@/components/ui/sidebar';
import { useFollowUpsDueToday } from '@/hooks/use-follow-ups-due-today';
import { PENDING_ASSIGNMENT_COUNTERS, usePendingAssignmentCounts } from '@/hooks/use-pending-assignment-counts';
import { canOpenPage } from '@/lib/access';
import { usesRefreshedDesign } from '@/lib/design';
import { FOLLOW_UPS_DUE_TODAY, counterKeys, workspaceFor } from '@/lib/navigation';

export function AppSidebar({ user, logout, ...props }) {
  // Exactly the pages the route guards in App.jsx open for this account
  // (lib/navigation, lib/access): those its permissions open. An account
  // holding none is offered nothing, and a section none of whose pages open is
  // not shown.
  const workspace = workspaceFor(user);
  // The refreshed design (lib/design) closes the phone's sidebar sheet once a page is picked.
  const closeOnNavigate = usesRefreshedDesign(user);
  // The live counts beside items that carry a `counter`. The BDE's follow-ups due today, read only
  // for whoever may open the Follow-ups page (a BDE who may see their leads' communication).
  const followUpsDueToday = useFollowUpsDueToday(canOpenPage(user, '/follow-ups'));
  // The Admin Hub's assignments still to make (bookings needing a tutor, students missing a mentor
  // or tutor), read only for the items of this workspace that show them: those its pages open.
  const shownCounters = counterKeys(workspace);
  const pendingAssignments = usePendingAssignmentCounts(
    PENDING_ASSIGNMENT_COUNTERS.filter((key) => shownCounters.includes(key))
  );
  const counts = { ...pendingAssignments, [FOLLOW_UPS_DUE_TODAY]: followUpsDueToday };

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
            <span className="truncate text-xs">{workspace.name}</span>
          </div>
        </SidebarMenuButton>
      </SidebarHeader>
      <SidebarContent>
        {workspace.sections.map((section, index) => (
          <Fragment key={section.label ?? index}>
            {/* A section with no heading of its own is set apart by a rule. */}
            {index > 0 && !section.label ? <SidebarSeparator /> : null}
            <NavMain
              label={section.label}
              items={section.items}
              counts={counts}
              collapsible={workspace.collapsible}
              closeOnNavigate={closeOnNavigate}
            />
          </Fragment>
        ))}
      </SidebarContent>
      <SidebarFooter>
        <NavUser user={user} logout={logout} />
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  );
}
