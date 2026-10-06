import { Link, useLocation } from 'react-router-dom';
import { Home, Calendar, ClipboardList, Folder, Trophy, User } from 'lucide-react';
import { cn } from '../../lib/utils';
import { useStudent } from '../student/student-context';
import { Avatar } from '../ui/avatar';

const navItems = [
  { href: '/dashboard', icon: Home, label: 'Home' },
  { href: '/sessions', icon: Calendar, label: 'Sessions' },
  { href: '/exams', icon: ClipboardList, label: 'Exams' },
  { href: '/scorecard', icon: Trophy, label: 'Scores' },
  { href: '/library', icon: Folder, label: 'Library' },
  { href: '/profile', icon: User, label: 'Profile' }
];

export function Sidebar() {
  const location = useLocation();
  const { selectedStudent } = useStudent();
  const pathname = location.pathname;

  return (
    <aside className="border-border bg-surface-elevated sticky top-0 hidden h-dvh w-[72px] shrink-0 flex-col border-r transition-[width] duration-200 ease-out md:flex lg:w-60">
      {/* Logo */}
      <div className="border-border-light flex h-16 items-center justify-center border-b px-3 lg:justify-start lg:px-5">
        {/* Collapsed: icon mark */}
        <img
          src="/brand/icon.png"
          alt="Eduport Plus"
          className="h-9 w-9 object-contain lg:hidden"
        />
        {/* Expanded: full wordmark */}
        <img
          src="/brand/logo.svg"
          alt="Eduport Plus"
          className="hidden h-7 w-auto lg:block"
        />
      </div>

      {/* Navigation */}
      <nav className="flex-1 space-y-1 p-2 lg:p-3">
        {navItems.map((item) => {
          const isActive = pathname === item.href || (item.href !== '/dashboard' && pathname.startsWith(item.href + '/'));
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              to={item.href}
              aria-label={item.label}
              aria-current={isActive ? 'page' : undefined}
            >
              <div
                className={cn(
                  'group relative flex items-center justify-center gap-3 rounded-xl px-3 py-2.5 transition-colors duration-150 lg:justify-start',
                  'hover:bg-surface-muted',
                  isActive
                    ? 'bg-accent-muted text-primary font-semibold'
                    : 'text-text-secondary'
                )}
              >
                <Icon
                  width={20}
                  height={20}
                  strokeWidth={isActive ? 2 : 1.75}
                  className="shrink-0"
                />
                <span className="hidden text-sm lg:block">
                  {item.label}
                </span>
                {/* Label tooltip for the icon-only rail (tablet width) */}
                <span className="bg-primary text-primary-foreground shadow-card pointer-events-none absolute top-1/2 left-full z-50 ml-2 -translate-y-1/2 rounded-lg px-2 py-1 text-xs font-medium whitespace-nowrap opacity-0 transition-opacity duration-150 group-hover:opacity-100 lg:hidden">
                  {item.label}
                </span>
              </div>
            </Link>
          );
        })}
      </nav>

      {/* User section */}
      {selectedStudent && (
        <div className="border-border-light border-t p-2 lg:p-3">
          <div className="flex items-center justify-center gap-3 rounded-xl px-3 py-2.5 lg:justify-start">
            <Avatar
              alt={selectedStudent.full_name || selectedStudent.student_name}
              size="sm"
              fallback={selectedStudent.full_name || selectedStudent.student_name}
              className="shrink-0 animate-fade-in"
            />
            <div className="hidden min-w-0 lg:block">
              <p className="text-text-primary truncate text-sm font-medium">
                {selectedStudent.full_name || selectedStudent.student_name}
              </p>
              {selectedStudent.grade && (
                <p className="text-text-muted truncate text-xs">
                  {selectedStudent.grade}
                </p>
              )}
            </div>
          </div>
        </div>
      )}
    </aside>
  );
}
