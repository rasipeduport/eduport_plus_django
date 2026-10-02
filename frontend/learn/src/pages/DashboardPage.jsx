import { Loader2 } from 'lucide-react';
import { useStudent } from '../components/student/student-context';
import { WelcomeSection } from '../components/home/welcome-section';
import { ClassesSection } from '../components/home/classes-section';
import { LiveClassCard } from '../components/home/live-class-card';
import { LastClassCard } from '../components/home/last-class-card';
import { LiveExamCard } from '../components/home/live-exam-card';
import { PastExamCard } from '../components/home/past-exam-card';
import { ScorecardHero } from '../components/scorecard/scorecard-hero';

export default function DashboardPage() {
  const { selectedStudent, dashboardStats } = useStudent();

  if (!dashboardStats) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="h-6 w-6 animate-spin text-primary" />
      </div>
    );
  }

  // The "next live" slot shows whichever of the next session/exam is sooner;
  // the "last recap" slot shows whichever attended one is more recent.
  const nextSession = dashboardStats.next_session;
  const nextExam = dashboardStats.next_exam;
  const lastSession = dashboardStats.last_session;
  const lastExam = dashboardStats.last_exam;
  const nextIsExam = nextExam != null && (nextSession == null || nextExam.start_time < nextSession.start_time);
  const lastIsExam = lastExam != null && (lastSession == null || lastExam.start_time > lastSession.start_time);

  return (
    <div className="space-y-5 md:space-y-6">
      {/* Welcome Header */}
      <WelcomeSection studentName={selectedStudent?.full_name} />

      {/* Class Credits */}
      <ClassesSection
        totalClassQuota={selectedStudent?.total_class_quota || 0}
        scheduledCount={dashboardStats.scheduled_count}
        attendedCount={dashboardStats.attended_count}
        loading={false}
      />

      {/* Progress */}
      <ScorecardHero refreshKey={`${lastExam?.id ?? ''}-${lastSession?.id ?? ''}`} />

      {/* Live Class / Exam */}
      <section>
        <h2 className="text-text-primary text-base font-semibold">
          {nextIsExam ? 'Up next — your exam' : 'Your Next Live Class'}
        </h2>
        <p className="text-text-secondary mt-1 mb-3 text-sm">
          {nextIsExam ? 'Join the chapter exam with your mentor.' : 'Join your scheduled one-on-one learning session.'}
        </p>
        {nextIsExam ? (
          <LiveExamCard meetLink={selectedStudent?.meet_link} exam={nextExam} />
        ) : (
          <LiveClassCard
            meetLink={selectedStudent?.meet_link}
            nextSession={nextSession}
            loading={false}
          />
        )}
      </section>

      {/* Last Class / Exam Recap */}
      {(lastSession || lastExam) && (
        <section>
          <h2 className="text-text-primary text-base font-semibold">
            {lastIsExam ? 'Recent' : 'Last Class Recap'}
          </h2>
          <p className="text-text-secondary mt-1 mb-3 text-sm">
            {lastIsExam ? 'Your latest exam result.' : 'Review resources and rate your previous session.'}
          </p>
          {lastIsExam ? <PastExamCard exam={lastExam} /> : <LastClassCard session={lastSession} />}
        </section>
      )}
    </div>
  );
}
