import { Link } from 'react-router-dom';

/**
 * Sessions | Exams switcher shown when a list page is filtered on one student
 * (the Hub's StudentSectionTabs). Exams are mentor/admin-only, so the tab is
 * hidden when `canViewExams` is false (a tutor viewing sessions).
 */
export function StudentSectionTabs({ studentId, active, canViewExams = true }) {
  const tabs = [
    { key: 'sessions', label: 'Sessions', href: `/sessions?student_id=${studentId}` },
    ...(canViewExams ? [{ key: 'exams', label: 'Exams', href: `/exams?student_id=${studentId}` }] : []),
  ];
  return (
    <div className="flex gap-1 border-b border-zinc-200 dark:border-[rgba(255,255,255,0.08)]">
      {tabs.map((tab) => (
        <Link
          key={tab.key}
          to={tab.href}
          className={`-mb-px border-b-2 px-4 py-2 text-sm font-medium transition-colors ${
            active === tab.key
              ? 'border-zinc-900 text-zinc-900 dark:border-white dark:text-white'
              : 'border-transparent text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-300'
          }`}
        >
          {tab.label}
        </Link>
      ))}
    </div>
  );
}
