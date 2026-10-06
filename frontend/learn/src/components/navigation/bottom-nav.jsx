import { Link, useLocation } from 'react-router-dom';
import { motion } from 'framer-motion';
import { Home, Calendar, ClipboardList, Folder, Trophy, User } from 'lucide-react';
import { cn } from '../../lib/utils';

const navItems = [
  { href: '/dashboard', icon: Home, label: 'Home' },
  { href: '/sessions', icon: Calendar, label: 'Sessions' },
  { href: '/exams', icon: ClipboardList, label: 'Exams' },
  { href: '/scorecard', icon: Trophy, label: 'Scores' },
  { href: '/library', icon: Folder, label: 'Library' },
  { href: '/profile', icon: User, label: 'Profile' }
];

export function BottomNav() {
  const location = useLocation();
  const pathname = location.pathname;

  return (
    <nav className="safe-area-bottom fixed right-0 bottom-0 left-0 z-50 md:hidden">
      <div className="border-border-light/80 bg-surface-elevated/90 shadow-nav rounded-t-2xl border-t backdrop-blur-xl">
        <div className="mx-auto flex max-w-md items-stretch justify-around px-3 py-2 sm:px-6">
          {navItems.map((item) => {
            const isActive = pathname === item.href || (item.href !== '/dashboard' && pathname.startsWith(item.href + '/'));
            const Icon = item.icon;

            return (
              <Link
                key={item.href}
                to={item.href}
                className="flex-1"
              >
                <motion.div
                  className="relative flex flex-col items-center gap-0.5 py-1"
                  whileTap={{ scale: 0.92 }}
                >
                  {/* Active dot indicator */}
                  {isActive && (
                    <motion.span
                      className="bg-primary absolute -top-2 h-0.75 w-5 rounded-full"
                      layoutId="nav-indicator"
                      transition={{
                        type: 'spring',
                        stiffness: 400,
                        damping: 30
                      }}
                    />
                  )}

                  <div
                    className={cn(
                      'flex h-8 w-8 items-center justify-center rounded-xl transition-colors duration-150',
                      isActive
                        ? 'bg-accent text-accent-foreground'
                        : 'text-text-muted'
                    )}
                  >
                    <Icon
                      width={20}
                      height={20}
                      strokeWidth={isActive ? 2.25 : 1.75}
                    />
                  </div>

                  <span
                    className={cn(
                      'text-[11px] leading-tight transition-colors duration-150',
                      isActive
                        ? 'text-text-primary font-semibold'
                        : 'text-text-muted font-medium'
                    )}
                  >
                    {item.label}
                  </span>
                </motion.div>
              </Link>
            );
          })}
        </div>
      </div>
    </nav>
  );
}
