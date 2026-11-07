import { Link, useLocation } from 'react-router-dom';

import {
  SidebarGroup,
  SidebarGroupLabel,
  SidebarMenu,
  SidebarMenuBadge,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from '@/components/ui/sidebar';
import { isCurrentItem } from '@/lib/navigation';
import { cn } from '@/lib/utils';

// `label` names a section of the sidebar (e.g. "Demo & Diagnostic"); the main section has none.
// An item's `badge` (e.g. "Coming Soon") shows beside it, and is read out with its name.
// With `closeOnNavigate`, picking a page on a phone closes the sidebar's sheet, so the page shows.
export function NavMain({ items, label, closeOnNavigate = false }) {
  const location = useLocation();
  const { isMobile, setOpenMobile } = useSidebar();

  return (
    <SidebarGroup>
      {label ? <SidebarGroupLabel>{label}</SidebarGroupLabel> : null}
      <SidebarMenu>
        {items.map((item) => (
          <SidebarMenuItem key={item.title}>
            <SidebarMenuButton
              asChild
              tooltip={item.badge ? `${item.title} (${item.badge})` : item.title}
              isActive={isCurrentItem(item, location.pathname, location.state?.from?.to)}
              className={cn(item.badge && 'pr-24')}
            >
              <Link
                to={item.url}
                onClick={closeOnNavigate && isMobile ? () => setOpenMobile(false) : undefined}
              >
                {item.icon && <item.icon />}
                <span>
                  {item.title}
                  {item.badge ? <span className="sr-only"> ({item.badge})</span> : null}
                </span>
              </Link>
            </SidebarMenuButton>
            {item.badge ? (
              <SidebarMenuBadge
                aria-hidden="true"
                className="bg-highlight text-highlight-foreground peer-hover/menu-button:text-highlight-foreground peer-data-[active=true]/menu-button:text-highlight-foreground rounded-full px-2 text-[10px] font-semibold"
              >
                {item.badge}
              </SidebarMenuBadge>
            ) : null}
          </SidebarMenuItem>
        ))}
      </SidebarMenu>
    </SidebarGroup>
  );
}
