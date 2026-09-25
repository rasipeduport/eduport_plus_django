import { ChevronsUpDown, LogOut } from 'lucide-react';

import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { SidebarMenu, SidebarMenuButton, SidebarMenuItem, useSidebar } from '@/components/ui/sidebar';
import ThemeToggle from './theme-toggle';

function RoleBadge({ role }) {
  return (
    <span className="bg-muted text-muted-foreground shrink-0 rounded px-1 py-px text-[10px] font-medium capitalize">
      {role}
    </span>
  );
}

export function NavUser({ user, logout }) {
  const { isMobile } = useSidebar();

  const showBadge = !!user.role && user.role !== 'student';

  return (
    <SidebarMenu>
      <SidebarMenuItem>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <SidebarMenuButton
              size="lg"
              className="data-[state=open]:bg-sidebar-accent data-[state=open]:text-sidebar-accent-foreground"
            >
              <Avatar className="h-8 w-8 shrink-0 rounded-lg">
                <AvatarImage src={user.avatar} alt={user.name} />
                <AvatarFallback className="rounded-lg">{user.initials}</AvatarFallback>
              </Avatar>
              <div className="flex min-w-0 flex-1 flex-col gap-0.5 text-left">
                <div className="flex min-w-0 items-center gap-1.5">
                  <span className="truncate text-sm leading-none font-medium">{user.name}</span>
                  {showBadge && <RoleBadge role={user.role} />}
                </div>
                <span className="text-muted-foreground truncate text-xs leading-none">{user.email}</span>
              </div>
              <ChevronsUpDown className="ml-auto size-4 shrink-0" />
            </SidebarMenuButton>
          </DropdownMenuTrigger>
          <DropdownMenuContent
            className="w-(--radix-dropdown-menu-trigger-width) min-w-56 rounded-lg"
            side={isMobile ? 'bottom' : 'right'}
            align="end"
            sideOffset={4}
          >
            <DropdownMenuLabel className="p-0 font-normal">
              <div className="flex items-center gap-3 px-2 py-2.5">
                <Avatar className="h-9 w-9 shrink-0 rounded-lg">
                  <AvatarImage src={user.avatar} alt={user.name} />
                  <AvatarFallback className="rounded-lg">{user.initials}</AvatarFallback>
                </Avatar>
                <div className="flex min-w-0 flex-col gap-0.5">
                  <div className="flex min-w-0 items-center gap-1.5">
                    <span className="truncate text-sm leading-none font-medium">{user.name}</span>
                    {showBadge && <RoleBadge role={user.role} />}
                  </div>
                  <span className="text-muted-foreground truncate text-xs leading-none">{user.email}</span>
                </div>
              </div>
            </DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuItem asChild>
              <button className="w-full" onClick={logout}>
                <LogOut />
                Log out
              </button>
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <div className="px-1 py-1">
              <ThemeToggle />
            </div>
          </DropdownMenuContent>
        </DropdownMenu>
      </SidebarMenuItem>
    </SidebarMenu>
  );
}
