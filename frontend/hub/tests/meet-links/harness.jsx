// Mounts every Join Meet entry point of a class or a chapter exam -- the Hub's
// Sessions table, Start Session, the admin/mentor Upcoming Sessions, the
// tutor's Today's Work, the student profile's header and Next Up, the Team
// page's Meet link field, and Learn's next-class, next-exam and exam cards --
// with only the API stood in for (api-stub.js).
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { MemoryRouter, RouterProvider, createMemoryRouter } from 'react-router-dom';
import SessionsPage from '@/pages/SessionsPage';
import TeamMemberPage from '@/pages/TeamMemberPage';
import { StartSessionButton } from '@/components/sessions/start-session-button';
import { UpcomingSessions } from '@/components/dashboard/upcoming-sessions';
import { TodaysWork } from '@/components/dashboard/tutor-work';
import { ProfileHeader } from '@/components/students/profile/profile-header';
import { OverviewTab } from '@/components/students/profile/overview-tab';
import { LiveClassCard } from '../../../learn/src/components/home/live-class-card';
import { LiveExamCard } from '../../../learn/src/components/home/live-exam-card';
import { ExamsList } from '../../../learn/src/components/exams/exams-list';
import { StudentContext } from '../../../learn/src/components/student/student-context';

const learn = (child) => <StudentContext.Provider value={{ timezone: 'Asia/Kolkata' }}>{child}</StudentContext.Provider>;

function content(kind, props) {
  switch (kind) {
    case 'start': return <StartSessionButton {...props} />;
    case 'upcoming': return <MemoryRouter><UpcomingSessions {...props} /></MemoryRouter>;
    case 'today': return <MemoryRouter><TodaysWork bookings={[]} bookingTotal={0} {...props} /></MemoryRouter>;
    case 'header': return <MemoryRouter><ProfileHeader {...props} /></MemoryRouter>;
    case 'overview': return <MemoryRouter><OverviewTab stats={{}} onOpenTab={() => {}} onSynced={() => {}} {...props} /></MemoryRouter>;
    case 'learn-class': return learn(<LiveClassCard loading={false} {...props} />);
    case 'learn-exam': return learn(<LiveExamCard {...props} />);
    case 'learn-exams': return learn(<MemoryRouter><ExamsList additionalExams={[]} {...props} /></MemoryRouter>);
    default: throw new Error(`unknown kind ${kind}`);
  }
}

export async function mount(kind, props = {}) {
  const container = document.createElement('div');
  document.body.appendChild(container);
  const root = createRoot(container);
  let tree;
  if (kind === 'sessions' || kind === 'team') {
    const router = createMemoryRouter(
      [
        { path: '/sessions', element: <SessionsPage user={props.user} /> },
        { path: '/team/:memberId', element: <TeamMemberPage user={props.user} /> },
      ],
      { initialEntries: [props.path] },
    );
    tree = <RouterProvider router={router} />;
  } else {
    tree = content(kind, props);
  }
  await act(async () => root.render(tree));
  return async () => { await act(async () => root.unmount()); container.remove(); };
}
export { act };
// The two Students tables' column lists, to show the student's own link is no longer a column.
export { createColumns } from '@/components/students/columns';
export { tutorColumns } from '@/components/students/tutor-columns';
