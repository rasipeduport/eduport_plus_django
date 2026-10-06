import { useState, useMemo } from 'react';
import { SessionCard } from './session-card';
import { cn } from '../../lib/utils';

const tabs = ['Scheduled', 'Attended'];

export function SessionsList({ sessions }) {
  const [activeTab, setActiveTab] = useState('Scheduled');
  const [expandedSessionId, setExpandedSessionId] = useState(null);

  const filtered = useMemo(() => {
    if (!sessions) return [];
    if (activeTab === 'Attended') {
      return sessions.filter((s) => s.status === 'attended');
    }
    return sessions.filter((s) => s.status === 'scheduled');
  }, [sessions, activeTab]);

  return (
    <div className="space-y-4 md:space-y-6">
      {/* Tabs */}
      <div role="tablist" className="border-border-light bg-surface-muted inline-flex w-full rounded-xl border p-1 sm:w-auto">
        {tabs.map((tab) => (
          <button
            key={tab}
            type="button"
            onClick={() => setActiveTab(tab)}
            className={cn(
              'min-h-10 flex-1 rounded-lg px-4 py-1.5 text-sm font-semibold transition-all duration-150 cursor-pointer sm:flex-none lg:min-h-0',
              activeTab === tab
                ? 'bg-surface-elevated text-text-primary shadow-card'
                : 'text-text-muted hover:text-text-secondary'
            )}
          >
            {tab}
          </button>
        ))}
      </div>

      {/* Session list */}
      {filtered.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-12 text-center">
          <p className="text-text-primary text-sm font-semibold">
            {activeTab === 'Attended'
              ? 'No attended sessions yet'
              : 'No scheduled sessions'}
          </p>
          <p className="text-text-muted mt-1 text-xs">
            {activeTab === 'Attended'
              ? 'Sessions you complete will appear here.'
              : 'Your upcoming sessions will show up here.'}
          </p>
        </div>
      ) : (
        <div className="space-y-3 md:max-lg:grid md:max-lg:grid-cols-2 md:max-lg:items-start md:max-lg:gap-4 md:max-lg:space-y-0">
          {filtered.map((session) => (
            <SessionCard
              key={session.id}
              session={session}
              isExpanded={expandedSessionId === session.id}
              onToggle={() =>
                setExpandedSessionId(
                  expandedSessionId === session.id ? null : session.id
                )
              }
            />
          ))}
        </div>
      )}
    </div>
  );
}
