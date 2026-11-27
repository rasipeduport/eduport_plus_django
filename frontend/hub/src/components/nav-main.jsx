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

// A live count (an item's `counter`) above this reads "99+"; the full number is still read out.
const MAX_COUNT_SHOWN = 99;

/** `item`'s live count from `counts`, or null while there is nothing to count (it is then not shown). */
function countedOf(item, counts) {
  const count = item.counter ? counts?.[item.counter.key] : undefined;
  return Number.isInteger(count) && count > 0 ? count : null;
}

/** The red badge with an item's live count; the item's own name reads it out instead. */
function CounterBadge({ item, count, className }) {
  return (
    <SidebarMenuBadge
      aria-hidden="true"
      data-counter={item.counter.key}
      className={cn(
        'bg-destructive dark:bg-destructive/60 rounded-full px-1.5 text-[11px] font-semibold text-white peer-hover/menu-button:text-white peer-data-[active=true]/menu-button:text-white',
        className
      )}
    >
      {count > MAX_COUNT_SHOWN ? `${MAX_COUNT_SHOWN}+` : count}
    </SidebarMenuBadge>
  );
}

function NavItem({ item, current, onNavigate, counts }) {
  // Shown only while there is something to count.
  const counted = countedOf(item, counts);
  // What the tooltip (the icon rail's only label) and a screen reader add to the item's name.
  const note = item.badge ?? (counted != null ? `${counted} ${item.counter.label}` : null);
  return (
    <SidebarMenuItem>
      <SidebarMenuButton
        asChild
        tooltip={note ? `${item.title} (${note})` : item.title}
        isActive={current(item)}
        className={cn(item.badge && 'pr-24', counted != null && 'pr-10')}
      >
        <Link to={item.url} onClick={onNavigate}>
          {item.icon && <item.icon />}
          <span>
            {item.title}
            {note ? <span className="sr-only"> ({note})</span> : null}
          </span>
        </Link>
      </SidebarMenuButton>
      {counted != null ? <CounterBadge item={item} count={counted} /> : null}
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

/** One page of a submenu, with its live count (its `counter`) beside it as a top-level item has. */
function NavSubItem({ item, current, onNavigate, counts }) {
  const counted = countedOf(item, counts);
  return (
    <SidebarMenuSubItem>
      <SidebarMenuSubButton asChild isActive={current(item)} className={cn(counted != null && 'pr-10')}>
        <Link to={item.url} onClick={onNavigate}>
          <span>
            {item.title}
            {counted != null ? <span className="sr-only"> ({`${counted} ${item.counter.label}`})</span> : null}
          </span>
        </Link>
      </SidebarMenuSubButton>
      {/* Centred on the submenu's shorter row (h-7), as the badge is on an item's. */}
      {counted != null ? <CounterBadge item={item} count={counted} className="top-1" /> : null}
    </SidebarMenuSubItem>
  );
}

/**
 * An item holding pages of its own (`item.children`, such as Bookings' Demo
 * and Diagnostic): a button that opens and closes them in a submenu. On the
 * icon rail there is no room for the submenu, so the item opens its first page
 * and shows as current while any of its pages is.
 */
function NavSubmenu({ item, current, rail, onNavigate, counts }) {
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
              <NavSubItem key={child.url} item={child} current={current} onNavigate={onNavigate} counts={counts} />
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
// an item's `counter` shows its live count from `counts` (keyed by the counter's `key`) the same way, while above zero;
// an item's `children` open in a submenu under it, each child's `counter` shown beside it likewise.
// With `closeOnNavigate`, picking a page on a phone closes the sidebar's sheet, so the page shows.
export function NavMain({ items, label, counts, collapsible = false, closeOnNavigate = false }) {
  const location = useLocation();
  const { isMobile, setOpenMobile, state } = useSidebar();
  const current = (item) => isCurrentItem(item, location.pathname, location.state?.from?.to);
  const onNavigate = closeOnNavigate && isMobile ? () => setOpenMobile(false) : undefined;
  const rail = state === 'collapsed' && !isMobile;

  const menu = (
    <SidebarMenu>
      {items.map((item) =>
        item.children ? (
          <NavSubmenu
            key={item.title}
            item={item}
            current={current}
            rail={rail}
            onNavigate={onNavigate}
            counts={counts}
          />
        ) : (
          <NavItem key={item.title} item={item} current={current} onNavigate={onNavigate} counts={counts} />
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
