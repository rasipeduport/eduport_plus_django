import { motion } from 'framer-motion';
import { BookOpen, ClipboardList } from 'lucide-react';
import { Card } from '../ui/card';

const META = {
  homework: { icon: BookOpen, color: 'text-info', bg: 'bg-info-subtle', bar: 'bg-info' },
  exam: { icon: ClipboardList, color: 'text-primary', bg: 'bg-primary-subtle', bar: 'bg-primary' },
};

/** Homework vs Chapter Exams average tiles (Learn CategoryBreakdown). */
export function CategoryBreakdown({ categories }) {
  return (
    <div className="grid grid-cols-2 gap-3">
      {categories.map((stat) => {
        const m = META[stat.category] || META.exam;
        const Icon = m.icon;
        return (
          <Card key={stat.category} padding="md">
            <div className="flex items-center gap-2">
              <div className={`${m.bg} flex h-8 w-8 items-center justify-center rounded-xl`}>
                <Icon className={`${m.color} h-4 w-4`} />
              </div>
              <span className="text-text-secondary text-xs font-semibold">{stat.label}</span>
            </div>
            <p className="text-text-primary mt-3 text-2xl font-bold tabular-nums">{stat.avg == null ? '–' : `${stat.avg}%`}</p>
            <p className="text-text-muted text-xs">{stat.count} scored</p>
            <div className="bg-surface-muted mt-3 h-1.5 overflow-hidden rounded-full">
              <motion.div className={`${m.bar} h-full rounded-full`} initial={{ width: 0 }} animate={{ width: `${stat.avg ?? 0}%` }} transition={{ duration: 0.8, ease: 'easeOut' }} />
            </div>
          </Card>
        );
      })}
    </div>
  );
}
