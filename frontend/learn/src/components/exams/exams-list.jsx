import { useMemo, useState } from 'react';
import { ExamCard } from './exam-card';
import { AdditionalExamCard } from './additional-exam-card';
import { cn } from '../../lib/utils';

const tabs = ['Scheduled', 'Past'];

/**
 * Scheduled / Past tabs over both exam kinds (Learn ExamsList). Scheduled:
 * chapter exams still scheduled plus additional exams assigned or submitted.
 * Past: attended or cancelled chapter exams plus scored additional exams.
 */
export function ExamsList({ exams, additionalExams, meetLink }) {
  const [activeTab, setActiveTab] = useState('Scheduled');

  const filteredExams = useMemo(() => {
    const rows = exams || [];
    if (activeTab === 'Past') return rows.filter((e) => ['attended', 'cancelled'].includes((e.status || '').toLowerCase()));
    return rows.filter((e) => (e.status || '').toLowerCase() === 'scheduled');
  }, [exams, activeTab]);

  const filteredAdditional = useMemo(() => {
    const rows = additionalExams || [];
    if (activeTab === 'Past') return rows.filter((e) => (e.status || '').toLowerCase() === 'scored');
    return rows.filter((e) => ['assigned', 'submitted'].includes((e.status || '').toLowerCase()));
  }, [additionalExams, activeTab]);

  const showHeaders = filteredExams.length > 0 && filteredAdditional.length > 0;
  const empty = filteredExams.length === 0 && filteredAdditional.length === 0;

  return (
    <div className="space-y-4 md:space-y-6">
      <div role="tablist" className="border-border-light bg-surface-muted inline-flex w-full rounded-xl border p-1 sm:w-auto">
        {tabs.map((tab) => (
          <button
            key={tab}
            type="button"
            onClick={() => setActiveTab(tab)}
            className={cn(
              'min-h-10 flex-1 rounded-lg px-4 py-1.5 text-sm font-semibold transition-all duration-150 cursor-pointer sm:flex-none lg:min-h-0',
              activeTab === tab ? 'bg-surface-elevated text-text-primary shadow-card' : 'text-text-muted hover:text-text-secondary'
            )}
          >
            {tab}
          </button>
        ))}
      </div>

      {empty ? (
        <div className="flex flex-col items-center justify-center py-12 text-center">
          <p className="text-text-primary text-sm font-semibold">{activeTab === 'Past' ? 'No past exams yet' : 'No exams scheduled'}</p>
          <p className="text-text-muted mt-1 text-xs">
            {activeTab === 'Past' ? 'Exams you complete will appear here with their scores.' : 'Chapter and additional exams set by your mentor will show up here.'}
          </p>
        </div>
      ) : (
        <div className="space-y-5">
          {filteredExams.length > 0 && (
            <section className="space-y-3">
              {showHeaders && <h2 className="text-text-secondary text-xs font-semibold uppercase tracking-wide">Chapter Exams</h2>}
              <div className="space-y-3 md:max-lg:grid md:max-lg:grid-cols-2 md:max-lg:items-start md:max-lg:gap-4 md:max-lg:space-y-0">
                {filteredExams.map((exam) => (
                  <ExamCard key={exam.id} exam={exam} meetLink={meetLink} />
                ))}
              </div>
            </section>
          )}
          {filteredAdditional.length > 0 && (
            <section className="space-y-3">
              {showHeaders && <h2 className="text-text-secondary text-xs font-semibold uppercase tracking-wide">Additional Exams</h2>}
              <div className="space-y-3 md:max-lg:grid md:max-lg:grid-cols-2 md:max-lg:items-start md:max-lg:gap-4 md:max-lg:space-y-0">
                {filteredAdditional.map((exam) => (
                  <AdditionalExamCard key={exam.id} exam={exam} />
                ))}
              </div>
            </section>
          )}
        </div>
      )}
    </div>
  );
}
