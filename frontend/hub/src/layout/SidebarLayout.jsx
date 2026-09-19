import { useState, useEffect, useRef } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { LayoutDashboard, GraduationCap, Compass, Presentation, Mail, LogOut, ShieldCheck, ChevronsUpDown, Sun, Moon, Monitor, History } from 'lucide-react';
import { useTheme } from '../hooks/useTheme';

// Protected Layout with Sidebar
export default function SidebarLayout({ user, logout, children }) {
  const location = useLocation();
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef(null);
  const { theme, setTheme: handleThemeChange } = useTheme();

  const menuItems = [
    { title: 'Dashboard', path: '/dashboard', icon: LayoutDashboard },
    { title: 'Students', path: '/students', icon: GraduationCap },
    { title: 'Sessions', path: '/sessions', icon: Presentation },
    { title: 'Admins', path: '/admins', icon: ShieldCheck },
    { title: 'Mentors', path: '/mentors', icon: Compass },
    { title: 'Tutors', path: '/tutors', icon: Presentation },
    { title: 'Invitations', path: '/invitations', icon: Mail },
    { title: 'Activity', path: '/activity', icon: History },
  ];

  useEffect(() => {
    function handleClickOutside(event) {
      if (menuRef.current && !menuRef.current.contains(event.target)) {
        setMenuOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  return (
    <div className="h-screen overflow-hidden flex bg-zinc-50 dark:bg-[#050505] text-zinc-900 dark:text-[#ffffff] font-sans antialiased transition-colors duration-200">
      {/* Sidebar */}
      <aside className="w-64 h-screen bg-white dark:bg-[#0a0a0a] border-r border-zinc-200 dark:border-[rgba(255,255,255,0.08)] flex flex-col shrink-0 transition-colors duration-200">
        {/* Brand */}
        <div className="h-16 flex items-center gap-2 px-4 border-b border-zinc-200 dark:border-[rgba(255,255,255,0.08)] bg-white dark:bg-[#0a0a0a] box-border transition-colors duration-200">
          <div className="w-8 h-8 rounded-lg bg-zinc-100 dark:bg-[rgba(255,255,255,0.03)] flex items-center justify-center shrink-0 border border-zinc-200/50 dark:border-transparent">
            <img src="/icon-transparent.png" alt="E+" className="w-6 h-6 object-contain" />
          </div>
          <div className="flex flex-col">
            <h1 className="font-semibold text-sm leading-none text-zinc-900 dark:text-white m-0">Eduport Plus</h1>
            <span className="text-xs text-zinc-400 dark:text-[#a1a1aa] leading-none mt-0.5">Hub</span>
          </div>
        </div>

        {/* Navigation */}
        <nav className="flex-1 px-2 py-4 space-y-1 bg-white dark:bg-[#0a0a0a] transition-colors duration-200">
          {menuItems
            .filter((item) => {
              if (user?.role === 'TUTOR' || user?.role === 'MENTOR') {
                // No '/activity': the audit log is admin-only.
                return ['/dashboard', '/students', '/sessions'].includes(item.path);
              }
              return true; // ADMIN see all
            })
            .map((item) => {
              const isActive = location.pathname === item.path;
              const Icon = item.icon;
              return (
                <Link
                  key={item.path}
                  to={item.path}
                  className={`flex items-center gap-3 px-3 h-9 rounded-lg text-sm font-medium transition-all ${
                    isActive
                      ? 'bg-zinc-100 dark:bg-[rgba(255,255,255,0.08)] text-zinc-900 dark:text-white border border-zinc-200/60 dark:border-[rgba(255,255,255,0.08)]'
                      : 'text-zinc-600 dark:text-[#d4d4d8] hover:bg-zinc-50 dark:hover:bg-[rgba(255,255,255,0.04)] hover:text-zinc-900 dark:hover:text-white border border-transparent'
                  }`}
                >
                  <Icon className="w-4 h-4 shrink-0" />
                  {item.title}
                </Link>
              );
            })}
        </nav>

        {/* User Info / Logout Button and Dropdown */}
        <div className="p-3 border-t border-zinc-200 dark:border-[rgba(255,255,255,0.08)] bg-white dark:bg-[#0a0a0a] relative transition-colors duration-200" ref={menuRef}>
          {menuOpen && (
            <div className="absolute bottom-[72px] left-3 right-3 bg-white dark:bg-[#111112] border border-zinc-200 dark:border-zinc-800 rounded-xl shadow-xl p-3 flex flex-col gap-2 z-50 animate-fadeIn">
              {/* User profile details in popover */}
              <div className="flex items-center gap-2.5 px-1 py-1">
                {user?.avatar_url ? (
                  <img src={user.avatar_url} alt="avatar" className="w-9 h-9 rounded-lg bg-zinc-800 object-cover border border-zinc-200 dark:border-zinc-800" />
                ) : (
                  <div className="w-9 h-9 rounded-lg bg-zinc-800 flex items-center justify-center font-semibold text-white shrink-0 text-sm border border-zinc-700">
                    {user?.full_name?.charAt(0) || 'U'}
                  </div>
                )}
                <div className="overflow-hidden flex flex-col gap-0.5">
                  <div className="flex items-center gap-1.5 min-w-0">
                    <span className="text-sm font-semibold text-zinc-900 dark:text-white truncate leading-none">{user?.full_name}</span>
                    <span className="bg-zinc-100 dark:bg-zinc-850 text-zinc-500 dark:text-zinc-400 shrink-0 rounded px-1 py-0.5 text-[10px] font-medium capitalize leading-none border border-zinc-200 dark:border-zinc-800">
                      {user?.role?.toLowerCase()}
                    </span>
                  </div>
                  <span className="text-[11px] text-zinc-500 dark:text-[#a1a1aa] truncate block leading-none">{user?.email}</span>
                </div>
              </div>

              {/* Divider */}
              <div className="border-t border-zinc-100 dark:border-zinc-800/80 my-1" />

              {/* Log out option */}
              <button
                onClick={logout}
                className="w-full flex items-center gap-2.5 px-2.5 py-2 text-sm text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-900 rounded-lg transition-colors text-left font-medium group"
              >
                <LogOut className="w-4 h-4 text-zinc-400 group-hover:text-zinc-600 dark:group-hover:text-zinc-200 transition-colors" />
                Log out
              </button>

              {/* Divider */}
              <div className="border-t border-zinc-100 dark:border-zinc-800/80 my-1" />

              {/* Theme switcher segment control */}
              <div className="grid grid-cols-3 bg-zinc-50 dark:bg-zinc-950 border border-zinc-200 dark:border-zinc-800/80 rounded-lg p-0.5">
                <button
                  type="button"
                  title="System Theme"
                  onClick={() => handleThemeChange('system')}
                  className={`flex items-center justify-center py-1.5 rounded-md transition-all ${
                    theme === 'system'
                      ? 'bg-white dark:bg-zinc-900 text-zinc-900 dark:text-white shadow-sm border border-zinc-200/50 dark:border-zinc-800'
                      : 'text-zinc-400 dark:text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-300'
                  }`}
                >
                  <Monitor className="w-4 h-4" />
                </button>
                <button
                  type="button"
                  title="Light Theme"
                  onClick={() => handleThemeChange('light')}
                  className={`flex items-center justify-center py-1.5 rounded-md transition-all ${
                    theme === 'light'
                      ? 'bg-white dark:bg-zinc-900 text-zinc-900 dark:text-white shadow-sm border border-zinc-200/50 dark:border-zinc-800'
                      : 'text-zinc-400 dark:text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-300'
                  }`}
                >
                  <Sun className="w-4 h-4" />
                </button>
                <button
                  type="button"
                  title="Dark Theme"
                  onClick={() => handleThemeChange('dark')}
                  className={`flex items-center justify-center py-1.5 rounded-md transition-all ${
                    theme === 'dark'
                      ? 'bg-white dark:bg-zinc-900 text-zinc-900 dark:text-white shadow-sm border border-zinc-200/50 dark:border-zinc-800'
                      : 'text-zinc-400 dark:text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-300'
                  }`}
                >
                  <Moon className="w-4 h-4" />
                </button>
              </div>
            </div>
          )}

          {/* Trigger button/card */}
          <button
            type="button"
            onClick={() => setMenuOpen(!menuOpen)}
            className="w-full flex items-center justify-between gap-2.5 p-2 rounded-xl border border-zinc-200 dark:border-[rgba(255,255,255,0.06)] bg-zinc-50/50 dark:bg-zinc-900/10 hover:bg-zinc-50 dark:hover:bg-zinc-900/40 hover:border-zinc-300 dark:hover:border-[rgba(255,255,255,0.12)] transition-all cursor-pointer select-none text-left"
          >
            <div className="flex items-center gap-2.5 overflow-hidden min-w-0">
              {user?.avatar_url ? (
                <img src={user.avatar_url} alt="avatar" className="w-8 h-8 rounded-lg bg-zinc-850 object-cover border border-zinc-200 dark:border-[rgba(255,255,255,0.08)]" />
              ) : (
                <div className="w-8 h-8 rounded-lg bg-zinc-800 flex items-center justify-center font-semibold text-white shrink-0 text-xs border border-zinc-700">
                  {user?.full_name?.charAt(0) || 'U'}
                </div>
              )}
              <div className="overflow-hidden flex flex-col gap-0.5">
                <div className="flex items-center gap-1.5 min-w-0">
                  <span className="text-sm font-medium text-zinc-900 dark:text-white truncate leading-none">{user?.full_name}</span>
                  <span className="bg-zinc-150 dark:bg-[#1e1e24] text-zinc-500 dark:text-[#a1a1aa] shrink-0 rounded px-1 py-px text-[10px] font-medium capitalize leading-none border border-zinc-200/50 dark:border-transparent">
                    {user?.role?.toLowerCase()}
                  </span>
                </div>
                <span className="text-[11px] text-zinc-500 dark:text-[#a1a1aa] truncate block leading-none">{user?.email}</span>
              </div>
            </div>
            <ChevronsUpDown className="w-4 h-4 text-zinc-400 dark:text-zinc-500 shrink-0" />
          </button>
        </div>
      </aside>

      {/* Main Content */}
      <div className="flex-1 flex flex-col overflow-hidden bg-zinc-50 dark:bg-[#050505] transition-colors duration-200">
        <header className="h-16 bg-white dark:bg-[#050505] border-b border-zinc-200 dark:border-[rgba(255,255,255,0.08)] flex items-center px-6 justify-between transition-colors duration-200">
          <h2 className="text-sm font-semibold text-zinc-900 dark:text-white m-0">
            {location.pathname === '/dashboard'
              ? 'Dashboard'
              : location.pathname === '/students'
                ? 'Students'
                : location.pathname === '/sessions'
                  ? 'Sessions'
                  : location.pathname === '/admins'
                    ? 'Admins'
                    : location.pathname === '/mentors'
                      ? 'Mentors'
                      : location.pathname === '/tutors'
                        ? 'Tutors'
                        : location.pathname === '/invitations'
                          ? 'Invitations'
                          : 'Activity'}
          </h2>
        </header>
        <main className="flex-1 overflow-y-auto p-6 bg-zinc-50 dark:bg-[#050505] transition-colors duration-200">{children}</main>
      </div>
    </div>
  );
}
