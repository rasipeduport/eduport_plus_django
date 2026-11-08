import { useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { Collapsible } from 'radix-ui';
import { ChevronDownIcon } from 'lucide-react';

import {
  SidebarGroup,
  SidebarGroupLabel,
  SidebarMenu,
  SidebarMenuBadge,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarMenuSub,
  SidebarMenuSubButton,
  SidebarMenuSubItem,
  useSidebar,
} from '@/components/ui/sidebar';
import { isCurrentItem } from '@/lib/navigation';
import { cn } from '@/lib/utils';

// What the reader has folded away in the sidebar (sections and submenus, by
// name), remembered on this device only. Storage may be unavailable (a private
// window, blocked site data): the sidebar then simply opens everything again.
const FOLDED_KEY = 'hub.sidebar.folded';

function readFolded() {
  try {
    return new Set(JSON.parse(window.localStorage.getItem(FOLDED_KEY) ?? '[]'));
  } catch {
    return new Set();
  }
}

function writeFolded(name, folded) {
  try {
    const names = readFolded();
    if (folded) names.add(name);
    else names.delete(name);
    window.localStorage.setItem(FOLDED_KEY, JSON.stringify([...names]));
  } catch {
    // Not remembered: the choice lasts until the page is reloaded.
  }
}

/**
 * Whether the part of the sidebar called `name` is open, and a way to open or
 * fold it: open unless the reader folded it, and opened again whenever they
 * arrive at one of its pages (`current`).
 */
function useFold(name, current) {
  const [open, setOpen] = useState(() => current || !readFolded().has(name));
  const [wasCurrent, setWasCurrent] = useState(current);
  if (current !== wasCurrent) {
    setWasCurrent(current);
    if (current && !open) setOpen(true);
  }
  const change = (next) => {
    setOpen(next);
    writeFolded(name, !next);
  };
  return [open, change];
}

function NavItem({ item, current, onNavigate }) {
  return (
    <SidebarMenuItem>
      <SidebarMenuButton
        asChild
        tooltip={item.badge ? `${item.title} (${item.badge})` : item.title}
        isActive={current(item)}
        className={cn(item.badge && 'pr-24')}
      >
        <Link to={item.url} onClick={onNavigate}>
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
  );
}

/**
 * An item holding pages of its own (`item.children`, such as Bookings' Demo
 * and Diagnostic): a button that opens and closes them in a submenu. On the
 * icon rail there is no room for the submenu, so the item opens its first page
 * and shows as current while any of its pages is.
 */
function NavSubmenu({ item, current, rail, onNavigate }) {
  const active = current(item);
  const [open, setOpen] = useFold(`item:${item.title}`, active);

  if (rail) {
    return (
      <SidebarMenuItem>
        <SidebarMenuButton asChild tooltip={item.title} isActive={active}>
          <Link to={item.children[0].url} onClick={onNavigate}>
            {item.icon && <item.icon />}
            <span>{item.title}</span>
          </Link>
        </SidebarMenuButton>
      </SidebarMenuItem>
    );
  }

  return (
    <Collapsible.Root asChild open={open} onOpenChange={setOpen}>
      <SidebarMenuItem className="group/submenu">
        <Collapsible.Trigger asChild>
          <SidebarMenuButton>
            {item.icon && <item.icon />}
            <span className="truncate">{item.title}</span>
            <ChevronDownIcon
              aria-hidden="true"
              className="text-sidebar-foreground/60 ml-auto transition-transform group-data-[state=closed]/submenu:-rotate-90"
            />
          </SidebarMenuButton>
        </Collapsible.Trigger>
        <Collapsible.Content>
          <SidebarMenuSub className="mt-1">
            {item.children.map((child) => (
              <SidebarMenuSubItem key={child.url}>
                <SidebarMenuSubButton asChild isActive={current(child)}>
                  <Link to={child.url} onClick={onNavigate}>
                    <span>{child.title}</span>
                  </Link>
                </SidebarMenuSubButton>
              </SidebarMenuSubItem>
            ))}
          </SidebarMenuSub>
        </Collapsible.Content>
      </SidebarMenuItem>
    </Collapsible.Root>
  );
}

/**
 * A labelled section that folds away under its heading. On the icon rail its
 * heading is hidden, so its items always show there.
 */
function FoldingSection({ label, current, rail, children }) {
  const [open, setOpen] = useFold(`section:${label}`, current);
  return (
    <Collapsible.Root asChild open={open || rail} onOpenChange={setOpen}>
      <SidebarGroup className="group/section py-1">
        <SidebarGroupLabel
          asChild
          className="hover:bg-sidebar-accent hover:text-sidebar-accent-foreground h-7 w-full text-[11px] font-semibold tracking-wider uppercase group-data-[collapsible=icon]:pointer-events-none"
        >
          <Collapsible.Trigger>
            <span className="truncate">{label}</span>
            <ChevronDownIcon
              aria-hidden="true"
              className="ml-auto transition-transform group-data-[state=closed]/section:-rotate-90"
            />
          </Collapsible.Trigger>
        </SidebarGroupLabel>
        <Collapsible.Content>{children}</Collapsible.Content>
      </SidebarGroup>
    </Collapsible.Root>
  );
}

// `label` names a section of the sidebar (e.g. "Demo & Diagnostic"); the main section has none.
// With `collapsible`, a labelled section folds away under its heading (the Admin Hub's).
// An item's `badge` (e.g. "Coming Soon") shows beside it, and is read out with its name;
// an item's `children` open in a submenu under it.
// With `closeOnNavigate`, picking a page on a phone closes the sidebar's sheet, so the page shows.
export function NavMain({ items, label, collapsible = false, closeOnNavigate = false }) {
  const location = useLocation();
  const { isMobile, setOpenMobile, state } = useSidebar();
  const current = (item) => isCurrentItem(item, location.pathname, location.state?.from?.to);
  const onNavigate = closeOnNavigate && isMobile ? () => setOpenMobile(false) : undefined;
  const rail = state === 'collapsed' && !isMobile;

  const menu = (
    <SidebarMenu>
      {items.map((item) =>
        item.children ? (
          <NavSubmenu key={item.title} item={item} current={current} rail={rail} onNavigate={onNavigate} />
        ) : (
          <NavItem key={item.title} item={item} current={current} onNavigate={onNavigate} />
        )
      )}
    </SidebarMenu>
  );

  if (collapsible && label) {
    return (
      <FoldingSection label={label} current={items.some(current)} rail={rail}>
        {menu}
      </FoldingSection>
    );
  }
  return (
    <SidebarGroup>
      {label ? <SidebarGroupLabel>{label}</SidebarGroupLabel> : null}
      {menu}
    </SidebarGroup>
  );
}
