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
import { usesRefreshedDesign } from '@/lib/design';
import { workspaceFor } from '@/lib/navigation';

export function AppSidebar({ user, logout, ...props }) {
  // Exactly the pages the route guards in App.jsx open for this account
  // (lib/navigation, lib/access): those its permissions open. An account
  // holding none is offered nothing, and a section none of whose pages open is
  // not shown.
  const workspace = workspaceFor(user);
  // The refreshed design (lib/design) closes the phone's sidebar sheet once a page is picked.
  const closeOnNavigate = usesRefreshedDesign(user);

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
            <NavMain label={section.label} items={section.items} closeOnNavigate={closeOnNavigate} />
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
