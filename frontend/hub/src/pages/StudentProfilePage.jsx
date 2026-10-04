import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { Loader2 } from 'lucide-react';

import api from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Tabs, TabsContent, TabsCount, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { HomeworkGradeSheet } from '@/components/homework/homework-grade-sheet';
import { AdditionalExamGradeSheet } from '@/components/exams/additional-exam-grade-sheet';
import { collectDocuments } from '@/lib/documents';
import { ProfileHeader } from '@/components/students/profile/profile-header';
import { OverviewTab } from '@/components/students/profile/overview-tab';
import { SessionsTab } from '@/components/students/profile/sessions-tab';
import { ExamsTab } from '@/components/students/profile/exams-tab';
import { HomeworkTab } from '@/components/students/profile/homework-tab';
import { DocumentsTab } from '@/components/students/profile/documents-tab';
import { ActivityTab } from '@/components/students/profile/activity-tab';
import { NotesTab } from '@/components/students/profile/notes-tab';
import { TabSkeleton } from '@/components/students/profile/profile-primitives';

// What each tab needs loaded before it can render. The Overview is served by
// the profile request itself; Documents is assembled from the other tabs'
// payloads, so opening it pulls all of them in. Activity and Notes own their
// own fetching, since both paginate.
//
// A tutor is refused the exam endpoints outright (403), so their Documents
// tab must not ask for them -- it is built from classes and homework alone.
const TAB_RESOURCES = {
  overview: [],
  sessions: ['sessions'],
  exams: ['exams', 'additionalExams'],
  homework: ['homework'],
  documents: ['sessions', 'exams', 'additionalExams', 'homework'],
  activity: [],
  notes: [],
};

const TUTOR_SKIPPED_RESOURCES = new Set(['exams', 'additionalExams']);

const RESOURCE_REQUESTS = {
  sessions: { url: '/api/sessions/', key: 'sessions' },
  exams: { url: '/api/exams/', key: 'exams' },
  additionalExams: { url: '/api/additional-exams/', key: 'additional_exams' },
  homework: { url: '/api/homework/', key: 'homework' },
};

const EMPTY_RESOURCES = { sessions: null, exams: null, additionalExams: null, homework: null };

/**
 * /students/:studentId — one student's complete record.
 *
 * The header and the Overview come from GET /api/students/<id>/profile/, which
 * is also where the cross-module counters (quota balance, status counts) are
 * worked out. Every other tab reads its own module's list endpoint with
 * ?student_id=, lazily on first open, so each module keeps owning its own
 * access rules and opening a profile does not fetch what nobody looked at.
 */
export default function StudentProfilePage({ role: userRole = 'ADMIN' }) {
  const { studentId } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();

  const role = (userRole || 'ADMIN').toLowerCase();
  const isTutor = role === 'tutor';
  const canScoreHomework = role === 'admin' || role === 'tutor';

  const [profile, setProfile] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [resources, setResources] = useState(EMPTY_RESOURCES);
  // Requests already in flight, so a tab switch cannot fire the same fetch twice.
  const inFlight = useRef(new Set());

  const [homeworkSheetId, setHomeworkSheetId] = useState(null);
  const [additionalExamId, setAdditionalExamId] = useState(null);

  // Exams are a mentor <-> student affair; the API tells us so by sending no
  // exam stats at all, which keeps the tab list and the API in step.
  const tabs = useMemo(() => {
    const showExams = !isTutor && profile?.stats?.exams != null;
    return [
      { key: 'overview', label: 'Overview' },
      { key: 'sessions', label: 'Sessions', count: profile?.stats?.sessions?.total },
      ...(showExams
        ? [
            {
              key: 'exams',
              label: 'Exams',
              count: (profile.stats.exams.chapter.total ?? 0) + (profile.stats.exams.additional.total ?? 0),
            },
          ]
        : []),
      { key: 'homework', label: 'Homework', count: profile?.stats?.homework?.total },
      { key: 'documents', label: 'Documents' },
      { key: 'activity', label: 'Activity' },
      { key: 'notes', label: 'Notes' },
    ];
  }, [isTutor, profile]);

  const requested = searchParams.get('tab') || 'overview';
  const tab = tabs.some((entry) => entry.key === requested) ? requested : 'overview';

  const setTab = useCallback(
    (next) => {
      const params = new URLSearchParams(searchParams);
      if (next === 'overview') params.delete('tab');
      else params.set('tab', next);
      setSearchParams(params, { replace: true });
    },
    [searchParams, setSearchParams]
  );

  const fetchProfile = useCallback(async () => {
    try {
      const res = await api.get(`/api/students/${studentId}/profile/`);
      setProfile(res.data);
      setError('');
    } catch (err) {
      const code = err.response?.status;
      setError(
        code === 404
          ? 'This student does not exist, or is not one of yours.'
          : err.response?.data?.message || 'Failed to load this student.'
      );
    } finally {
      setLoading(false);
    }
  }, [studentId]);

  useEffect(() => {
    setLoading(true);
    setProfile(null);
    setResources(EMPTY_RESOURCES);
    inFlight.current = new Set();
    fetchProfile();
  }, [fetchProfile]);

  const loadResource = useCallback(
    async (name) => {
      if (inFlight.current.has(name)) return;
      inFlight.current.add(name);
      const request = RESOURCE_REQUESTS[name];
      try {
        const res = await api.get(request.url, { params: { student_id: studentId } });
        setResources((current) => ({ ...current, [name]: res.data[request.key] ?? [] }));
      } catch {
        // An empty list keeps the tab usable; the counters on the Overview
        // still come from the profile request.
        setResources((current) => ({ ...current, [name]: [] }));
      }
    },
    [studentId]
  );

  const resourcesFor = useCallback(
    (name) => (TAB_RESOURCES[name] ?? []).filter((resource) => !(isTutor && TUTOR_SKIPPED_RESOURCES.has(resource))),
    [isTutor]
  );

  // Fetch what the open tab needs, once.
  useEffect(() => {
    if (!profile) return;
    for (const name of resourcesFor(tab)) {
      if (resources[name] === null) loadResource(name);
    }
  }, [tab, profile, resources, resourcesFor, loadResource]);

  /** After a mutation: re-read the profile and drop the cached tab payloads. */
  const refresh = useCallback(() => {
    inFlight.current = new Set();
    setResources(EMPTY_RESOURCES);
    fetchProfile();
  }, [fetchProfile]);

  const documents = useMemo(
    () =>
      collectDocuments({
        sessions: resources.sessions ?? [],
        exams: resources.exams ?? [],
        additionalExams: resources.additionalExams ?? [],
        homework: resources.homework ?? [],
      }),
    [resources]
  );

  if (loading) {
    return (
      <div className="flex h-96 items-center justify-center">
        <Loader2 className="text-muted-foreground size-8 animate-spin" />
      </div>
    );
  }

  if (error || !profile) {
    return (
      <div className="container mx-auto px-4 py-16">
        <div className="rounded-xl border px-6 py-12 text-center">
          <p className="text-sm">{error || 'Failed to load this student.'}</p>
          <Button variant="outline" className="mt-4" asChild>
            <Link to="/students">Back to Students</Link>
          </Button>
        </div>
      </div>
    );
  }

  const { student, stats, highlights } = profile;
  const waiting = (name) => resources[name] === null;

  return (
    <div className="container mx-auto flex flex-col gap-6 px-4 py-16">
        <ProfileHeader student={student} role={role} onChanged={refresh} />

        <Tabs value={tab} onValueChange={setTab}>
          <TabsList>
            {tabs.map((entry) => (
              <TabsTrigger key={entry.key} value={entry.key}>
                {entry.label}
                <TabsCount value={entry.count} />
              </TabsTrigger>
            ))}
          </TabsList>

          <TabsContent value="overview">
            <OverviewTab
              student={student}
              stats={stats}
              highlights={highlights}
              role={role}
              onOpenTab={setTab}
            />
          </TabsContent>

          <TabsContent value="sessions">
            {waiting('sessions') ? (
              <TabSkeleton />
            ) : (
              <SessionsTab
                sessions={resources.sessions}
                studentId={studentId}
                onOpenHomework={setHomeworkSheetId}
              />
            )}
          </TabsContent>

          {stats.exams != null && !isTutor ? (
            <TabsContent value="exams">
              {waiting('exams') || waiting('additionalExams') ? (
                <TabSkeleton />
              ) : (
                <ExamsTab
                  exams={resources.exams}
                  additionalExams={resources.additionalExams}
                  stats={stats.exams}
                  studentId={studentId}
                  onOpenAdditional={setAdditionalExamId}
                />
              )}
            </TabsContent>
          ) : null}

          <TabsContent value="homework">
            {waiting('homework') ? (
              <TabSkeleton />
            ) : (
              <HomeworkTab
                homework={resources.homework}
                stats={stats.homework}
                canScore={canScoreHomework}
                onOpen={setHomeworkSheetId}
              />
            )}
          </TabsContent>

          <TabsContent value="documents">
            {resourcesFor('documents').some(waiting) ? (
              <TabSkeleton />
            ) : (
              <DocumentsTab
                documents={documents}
                sources={isTutor ? ['session', 'homework'] : ['session', 'exam', 'additional_exam', 'homework']}
              />
            )}
          </TabsContent>

          <TabsContent value="activity">
            <ActivityTab studentId={studentId} role={role} />
          </TabsContent>

          <TabsContent value="notes">
            <NotesTab studentId={studentId} studentName={student.full_name} />
          </TabsContent>
        </Tabs>

      <HomeworkGradeSheet
        homeworkId={homeworkSheetId}
        open={Boolean(homeworkSheetId)}
        onOpenChange={(open) => !open && setHomeworkSheetId(null)}
        onSaved={refresh}
        canScore={canScoreHomework}
      />
      <AdditionalExamGradeSheet
        examId={additionalExamId}
        open={Boolean(additionalExamId)}
        onOpenChange={(open) => !open && setAdditionalExamId(null)}
        onSaved={refresh}
      />
    </div>
  );
}
