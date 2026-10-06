import { useState, useMemo } from 'react';
import { Play, FileText, BookOpen, ChevronRight, Folder } from 'lucide-react';
import { Link } from 'react-router-dom';
import { Card } from '../ui/card';
import { homeworkStatusBadge } from '../../lib/homework-status';
import { cn } from '../../lib/utils';
import { formatDate } from '../../lib/formatting';

const TAB_CONFIG = {
  recording: {
    label: 'Recordings',
    icon: Play,
    color: 'text-primary',
    bg: 'bg-primary-subtle',
    field: 'recording_link',
    emptyText: 'No recordings yet'
  },
  notes: {
    label: 'Notes',
    icon: FileText,
    color: 'text-info',
    bg: 'bg-info-subtle',
    field: 'notes_link',
    emptyText: 'No notes yet'
  },
  homework: {
    label: 'Homework',
    icon: BookOpen,
    color: 'text-warning',
    bg: 'bg-warning-subtle',
    field: 'homework_link',
    emptyText: 'No homework yet'
  }
};

const TABS = ['recording', 'notes', 'homework'];

export function LibraryTabs({ sessions }) {
  const [active, setActive] = useState('recording');
  const cfg = TAB_CONFIG[active];
  const Icon = cfg.icon;

  const items = useMemo(() => {
    if (!sessions) return [];
    // Homework rows live on the lifecycle entity, not only on the link.
    if (active === 'homework') return sessions.filter((s) => s.homework || s[cfg.field]);
    return sessions.filter((s) => s[cfg.field]);
  }, [sessions, cfg.field, active]);

  return (
    <div className="space-y-4 md:space-y-6">
      {/* Tabs */}
      <div role="tablist" className="border-border-light bg-surface-muted inline-flex w-full rounded-xl border p-1 sm:w-auto">
        {TABS.map((tab) => {
          const isActive = active === tab;
          return (
            <button
              key={tab}
              type="button"
              onClick={() => setActive(tab)}
              className={cn(
                'min-h-10 flex-1 rounded-lg px-4 py-1.5 text-sm font-semibold transition-all duration-150 cursor-pointer sm:flex-none lg:min-h-0',
                isActive
                  ? 'bg-surface-elevated text-text-primary shadow-card'
                  : 'text-text-muted hover:text-text-secondary'
              )}
            >
              {TAB_CONFIG[tab].label}
            </button>
          );
        })}
      </div>

      {/* Items */}
      {items.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-12 text-center">
          <div className="bg-surface-muted mb-3 flex h-12 w-12 items-center justify-center rounded-2xl">
            <Folder className="text-text-muted h-5 w-5" />
          </div>
          <p className="text-text-primary text-sm font-semibold">
            {cfg.emptyText}
          </p>
          <p className="text-text-muted mt-1 text-xs">
            Materials will appear here once your classes are completed.
          </p>
        </div>
      ) : (
        <div className="space-y-3 md:max-lg:grid md:max-lg:grid-cols-2 md:max-lg:items-start md:max-lg:gap-4 md:max-lg:space-y-0">
          {items.map((s) => {
            const hwBadge = active === 'homework' && s.homework ? homeworkStatusBadge(s.homework) : null;
            const Wrapper = hwBadge ? Link : 'a';
            const wrapperProps = hwBadge
              ? { to: `/homework/${s.homework.id}` }
              : { href: s[cfg.field], target: '_blank', rel: 'noopener noreferrer' };
            return (
            <Wrapper
              key={s.id}
              {...wrapperProps}
              className="block"
            >
              <Card interactive padding="md">
                <div className="flex items-center gap-3.5">
                  <div
                    className={cn(
                      'flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl',
                      cfg.bg
                    )}
                  >
                    <Icon className={cn('h-5 w-5', cfg.color)} />
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="text-text-primary truncate text-sm font-semibold">
                      {s.title}
                    </p>
                    <p className="text-text-muted mt-0.5 truncate text-xs">
                      {formatDate(s.start_time)}
                      {s.tutor_profile?.full_name && ` · ${s.tutor_profile.full_name}`}
                    </p>
                  </div>
                  {hwBadge && (
                    <span className={cn('shrink-0 rounded-full border px-2 py-0.5 text-[11px] font-semibold whitespace-nowrap', hwBadge.className)}>{hwBadge.label}</span>
                  )}
                  <ChevronRight className="text-text-muted h-5 w-5 shrink-0" />
                </div>
              </Card>
            </Wrapper>
            );
          })}
        </div>
      )}
    </div>
  );
}
