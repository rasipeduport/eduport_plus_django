// Mounts the real Bookings page at a URL, for a given signed-in account, the
// way App.jsx routes it -- only the API is a stand-in (api-stub.js).
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { RouterProvider, createMemoryRouter } from 'react-router-dom';
import BookingsPage from '@/pages/BookingsPage';

export async function mount(path, user) {
  const container = document.createElement('div');
  document.body.appendChild(container);
  const root = createRoot(container);
  const router = createMemoryRouter([{ path: '/bookings', element: <BookingsPage user={user} /> }], {
    initialEntries: [path],
  });
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
