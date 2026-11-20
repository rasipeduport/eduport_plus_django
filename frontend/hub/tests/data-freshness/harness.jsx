// Mounts what the Hub reads again on its own -- the refresh hooks in bare
// probes, and the pages that use them (Follow-ups, the BDE dashboard, Sessions,
// an administrator's booking workspace), routed the way App.jsx routes them --
// with only the API stood in for (../sessions/api-stub.js).
import { act, useEffect } from 'react';
import { createRoot } from 'react-dom/client';
import { MemoryRouter, Route, Routes, RouterProvider, createMemoryRouter, useLocation, useNavigate } from 'react-router-dom';
import { useBookingCommunication } from '@/hooks/use-booking-communication';
import { useLiveRefresh } from '@/hooks/use-live-refresh';
import BdeDashboardPage from '@/pages/BdeDashboardPage';
import BookingWorkspacePage from '@/pages/BookingWorkspacePage';
import FollowUpsPage from '@/pages/FollowUpsPage';
import SessionsPage from '@/pages/SessionsPage';
import AdmissionsDashboardPage from '@/pages/AdmissionsDashboardPage';
import BdeBookingsPage from '@/pages/BdeBookingsPage';
import DashboardPage from '@/pages/DashboardPage';
import EnquiriesPage from '@/pages/EnquiriesPage';
import EnquiryPage from '@/pages/EnquiryPage';
import LeadPage from '@/pages/LeadPage';
import LeadsPage from '@/pages/LeadsPage';
import TutorBookingWorkspacePage from '@/pages/TutorBookingWorkspacePage';
import TutorMainDashboardPage from '@/pages/TutorMainDashboardPage';
import LearnAuthProvider from '../../../learn/src/context/AuthProvider';
import LearnStudentProvider from '../../../learn/src/context/StudentProvider';
import { useStudent } from '../../../learn/src/components/student/student-context';

function LiveProbe({ onRefresh, options }) {
  useLiveRefresh(onRefresh, options);
  return null;
}

/** useBookingCommunication for `type` and `id`, its state handed to `probe.state` after each render. */
function CommsProbe({ type, id, probe }) {
  const state = useBookingCommunication(type, id, 0);
  useEffect(() => {
    probe.state = state;
  });
  return null;
}

function page(path, user) {
  const router = createMemoryRouter(
    [
      { path: '/follow-ups', element: <FollowUpsPage /> },
      { path: '/dashboard', element: <BdeDashboardPage user={user} /> },
      { path: '/sessions', element: <SessionsPage user={user} /> },
      { path: '/bookings/demo/:bookingId', element: <BookingWorkspacePage key="DEMO" user={user} type="DEMO" /> },
      { path: '/my-bookings/demo/:bookingId', element: <TutorBookingWorkspacePage key="DEMO" type="DEMO" /> },
      { path: '/leads', element: <LeadsPage user={user} /> },
      { path: '/leads/:leadId', element: <LeadPage user={user} /> },
      { path: '/enquiries', element: <EnquiriesPage user={user} /> },
      { path: '/enquiries/:enquiryId', element: <EnquiryPage user={user} /> },
      { path: '/demo-bookings', element: <BdeBookingsPage key="DEMO" user={user} type="DEMO" /> },
      { path: '/tutor-dashboard', element: <TutorMainDashboardPage user={user} /> },
      { path: '/academics-dashboard', element: <DashboardPage user={user} /> },
      { path: '/admissions', element: <AdmissionsDashboardPage user={user} /> },
    ],
    { initialEntries: [path] }
  );
  // For tests that open another page in place, as a link would.
  globalThis.__dfRouter = router;
  return <RouterProvider router={router} />;
}

/** Learn's own state (useStudent) and where it is, handed to `probe` after each render. */
function LearnProbe({ probe }) {
  const student = useStudent();
  const navigate = useNavigate();
  const location = useLocation();
  useEffect(() => {
    probe.student = student;
    probe.navigate = navigate;
    probe.path = location.pathname;
  });
  return null;
}

/** Learn as App.jsx nests it -- AuthProvider, StudentProvider -- at `path`, every route a probe. */
function learn(path, probe) {
  return (
    <MemoryRouter initialEntries={[path]}>
      <LearnAuthProvider>
        {(props) => (
          <LearnStudentProvider {...props}>
            <Routes>
              <Route path="*" element={<LearnProbe probe={probe} />} />
            </Routes>
          </LearnStudentProvider>
        )}
      </LearnAuthProvider>
    </MemoryRouter>
  );
}

const trees = {
  live: (props) => <LiveProbe {...props} />,
  comms: (props) => <CommsProbe {...props} />,
  page: (props) => page(props.path, props.user),
  learn: (props) => learn(props.path, props.probe),
};

export async function mount(kind, props = {}) {
  const container = document.createElement('div');
  document.body.appendChild(container);
  const root = createRoot(container);
  await act(async () => root.render(trees[kind](props)));
  return {
    async rerender(next) {
      await act(async () => root.render(trees[kind](next)));
    },
    async unmount() {
      await act(async () => root.unmount());
      container.remove();
      for (const node of [...document.body.children]) node.remove();
    },
  };
}

export { act };
export { BDE_DASHBOARD_URL } from '@/lib/enquiries';
export { BDE_FOLLOW_UPS_URL } from '@/lib/follow-ups';
export { bookingCommunicationUrl } from '@/lib/communications';
