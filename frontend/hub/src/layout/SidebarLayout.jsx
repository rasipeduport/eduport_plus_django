import { useLocation } from 'react-router-dom';

import { AppSidebar } from '@/components/app-sidebar';
import AppHeader from '@/components/app-header';
import { SidebarInset, SidebarProvider } from '@/components/ui/sidebar';
import { getInitials } from '@/lib/utils';

// Routes already migrated to the shadcn design system. Everything else still
// hardcodes dark hex colours, so it gets wrapped in `.legacy-ui` to keep the
// compatibility overrides in legacy.css applying to it. Remove a path from this
// set's complement — i.e. add it here — as each page is ported.
const PORTED_PATHS = new Set([
  '/dashboard',
  '/students',
  '/admins',
  '/mentors',
  '/tutors',
  '/invitations',
  '/activity',
]);

// Below the lg breakpoint (tablets) the sidebar starts collapsed to its icon
// rail so the content keeps the width; it can still be expanded. Desktop
// keeps the full sidebar. Phones use the sheet and ignore this value.
const defaultSidebarOpen = () => (typeof window === 'undefined' ? true : window.innerWidth >= 1024);

// Protected layout: collapsible sidebar + breadcrumb header.
export default function SidebarLayout({ user, logout, children }) {
  const { pathname } = useLocation();

  const userData = {
    name: user?.full_name ?? '',
    email: user?.email ?? '',
    avatar: user?.avatar_url || '',
    initials: getInitials(user?.full_name, user?.email),
    role: user?.role ?? null,
  };

  // The student profile (/students/<id>) is built on the design tokens like
  // the students list it opens from, so it takes the raw layout too.
  const isPorted = PORTED_PATHS.has(pathname) || pathname.startsWith('/students/');

  return (
    <SidebarProvider defaultOpen={defaultSidebarOpen()}>
      <AppSidebar user={userData} logout={logout} />
      <SidebarInset className="min-w-0">
        <AppHeader />
        {isPorted ? children : <div className="legacy-ui px-4 pt-22 pb-6 sm:px-6">{children}</div>}
      </SidebarInset>
    </SidebarProvider>
  );
}
