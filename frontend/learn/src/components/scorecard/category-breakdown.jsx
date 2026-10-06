import { motion } from 'framer-motion';
import { BookOpen, ClipboardCheck, ClipboardList } from 'lucide-react';
import { Card } from '../ui/card';

const META = {
  homework: { icon: BookOpen, color: 'text-info', bg: 'bg-info-subtle', bar: 'bg-info' },
  exam: { icon: ClipboardList, color: 'text-primary', bg: 'bg-primary-subtle', bar: 'bg-primary' },
  additional_exam: { icon: ClipboardCheck, color: 'text-warning', bg: 'bg-warning-subtle', bar: 'bg-warning' },
};

/** Homework / Chapter Exams / Additional Exams marks-based tiles (Learn CategoryBreakdown). */
export function CategoryBreakdown({ categories }) {
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
      {categories.map((stat) => {
        const m = META[stat.category] || META.exam;
        const Icon = m.icon;
        return (
          // Phones: one row per category (icon · label + number · bar).
          // From sm up: the original stacked tile, three across.
          <Card key={stat.category} padding="md" className="flex items-center gap-3 sm:block">
            <div className="flex shrink-0 items-center gap-2">
              <div className={`${m.bg} flex h-9 w-9 items-center justify-center rounded-xl sm:h-8 sm:w-8`}>
                <Icon className={`${m.color} h-4 w-4`} />
              </div>
              <span className="text-text-secondary hidden text-xs font-semibold sm:inline">{stat.label}</span>
            </div>
            <div className="min-w-0 flex-1">
              <span className="text-text-secondary block truncate text-xs font-semibold sm:hidden">{stat.label}</span>
              <div className="flex items-baseline justify-between gap-2 sm:mt-3 sm:block">
                <p className="text-text-primary text-xl font-bold tabular-nums sm:text-2xl">{stat.avg == null ? '–' : `${stat.avg}%`}</p>
                <p className="text-text-muted text-xs">{stat.count} scored</p>
              </div>
              <div className="bg-surface-muted mt-2 h-1.5 overflow-hidden rounded-full sm:mt-3">
                <motion.div className={`${m.bar} h-full rounded-full`} initial={{ width: 0 }} animate={{ width: `${stat.avg ?? 0}%` }} transition={{ duration: 0.8, ease: 'easeOut' }} />
              </div>
            </div>
          </Card>
        );
      })}
    </div>
  );
}
