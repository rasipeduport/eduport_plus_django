// Mounts the real Demo and Diagnostic Bookings pages (/bookings/demo,
// /bookings/diagnostic; the former /bookings sends on to them), the tutor's My Bookings page
// (/my-bookings), their Demo and Diagnostic Bookings (/my-bookings/demo,
// /my-bookings/diagnostic) and a booking's workspace (/my-bookings/<type>/:bookingId),
// a BDE's enquiry (/enquiries/:enquiryId), follow-ups (/follow-ups) or Demo and Diagnostic
// Bookings (/demo-bookings, /diagnostic-bookings), the Booking Slots
// page (/booking-slots) or a Team member's page (/team/:memberId, for a
// tutor's permanent Meet link) at a URL, for a given signed-in account, the
// way App.jsx routes them -- only the API is a stand-in (api-stub.js). The
// administrators' booking workspace is mounted by tests/leads.
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { Navigate, RouterProvider, createMemoryRouter, useLocation } from 'react-router-dom';
import BookingSlotsPage from '@/pages/BookingSlotsPage';
import BookingsPage from '@/pages/BookingsPage';
import BookingWorkspacePage from '@/pages/BookingWorkspacePage';
import BdeBookingsPage from '@/pages/BdeBookingsPage';
import TutorBookingsPage from '@/pages/TutorBookingsPage';
import TutorBookingWorkspacePage from '@/pages/TutorBookingWorkspacePage';
import EnquiryPage from '@/pages/EnquiryPage';
import FollowUpsPage from '@/pages/FollowUpsPage';
import TeamMemberPage from '@/pages/TeamMemberPage';
import { legacyBookingsPath } from '@/lib/bookings';

function LegacyBookings() {
  const { search } = useLocation();
  return <Navigate to={legacyBookingsPath(search)} replace />;
}

export async function mount(path, user) {
  const container = document.createElement('div');
  document.body.appendChild(container);
  const root = createRoot(container);
  const router = createMemoryRouter(
    [
      { path: '/bookings', element: <LegacyBookings /> },
      { path: '/bookings/demo', element: <BookingsPage key="DEMO" user={user} type="DEMO" /> },
      { path: '/bookings/diagnostic', element: <BookingsPage key="DIAGNOSTIC" user={user} type="DIAGNOSTIC" /> },
      // An administrator's booking workspace, as App.jsx routes it: each booking a page of its own.
      { path: '/bookings/demo/:bookingId', element: <BookingWorkspacePage key="DEMO" user={user} type="DEMO" /> },
      { path: '/bookings/diagnostic/:bookingId', element: <BookingWorkspacePage key="DIAGNOSTIC" user={user} type="DIAGNOSTIC" /> },
      { path: '/my-bookings', element: <TutorBookingsPage /> },
      { path: '/my-bookings/demo', element: <TutorBookingsPage key="DEMO" type="DEMO" /> },
      { path: '/my-bookings/diagnostic', element: <TutorBookingsPage key="DIAGNOSTIC" type="DIAGNOSTIC" /> },
      { path: '/my-bookings/demo/:bookingId', element: <TutorBookingWorkspacePage key="DEMO" type="DEMO" /> },
      { path: '/my-bookings/diagnostic/:bookingId', element: <TutorBookingWorkspacePage key="DIAGNOSTIC" type="DIAGNOSTIC" /> },
      { path: '/enquiries/:enquiryId', element: <EnquiryPage user={user} /> },
      { path: '/follow-ups', element: <FollowUpsPage /> },
      { path: '/demo-bookings', element: <BdeBookingsPage key="DEMO" user={user} type="DEMO" /> },
      { path: '/diagnostic-bookings', element: <BdeBookingsPage key="DIAGNOSTIC" user={user} type="DIAGNOSTIC" /> },
      { path: '/booking-slots', element: <BookingSlotsPage /> },
      { path: '/team/:memberId', element: <TeamMemberPage user={user} /> },
    ],
    { initialEntries: [path] }
  );
  await act(async () => {
    root.render(<RouterProvider router={router} />);
  });
  return {
    container,
    location: () => router.state.location,
    async unmount() {
      await act(async () => root.unmount());
      container.remove();
      // Whatever React did not own (focus guards, closed portals) goes too.
      for (const node of [...document.body.children]) {
        if (node.parentNode === document.body) document.body.removeChild(node);
      }
    },
  };
}

export { act };
export { canOpenPage, homePage } from '@/lib/access';
export { ACTION_LABELS, actionLabel, describeActivity } from '@/lib/activity-format';
export { meetLinkProblem, planMemberSave } from '@/lib/team';
