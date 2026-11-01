// Mounts the real Bookings page (/bookings), the tutor's My Bookings page
// (/my-bookings), a BDE's enquiry (/enquiries/:enquiryId) or the Booking
// Slots page (/booking-slots) at a URL, for a given signed-in account, the way
// App.jsx routes them -- only the API is a stand-in (api-stub.js).
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { RouterProvider, createMemoryRouter } from 'react-router-dom';
import BookingSlotsPage from '@/pages/BookingSlotsPage';
import BookingsPage from '@/pages/BookingsPage';
import TutorBookingsPage from '@/pages/TutorBookingsPage';
import EnquiryPage from '@/pages/EnquiryPage';

export async function mount(path, user) {
  const container = document.createElement('div');
  document.body.appendChild(container);
  const root = createRoot(container);
  const router = createMemoryRouter(
    [
      { path: '/bookings', element: <BookingsPage user={user} /> },
      { path: '/my-bookings', element: <TutorBookingsPage /> },
      { path: '/enquiries/:enquiryId', element: <EnquiryPage /> },
      { path: '/booking-slots', element: <BookingSlotsPage /> },
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
