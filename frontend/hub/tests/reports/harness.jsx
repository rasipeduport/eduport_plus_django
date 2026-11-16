// The report building blocks (lib/reports, components/reports and the
// Textarea), mounted one at a time in jsdom for run.mjs, and the tutor's
// report page (src/pages/TutorReportPage.jsx) at a URL, routed as App.jsx
// routes it -- only the API is a stand-in (api-stub.js).
import { act, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { RouterProvider, createMemoryRouter } from 'react-router-dom';
import TutorReportPage from '@/pages/TutorReportPage';
import { CharCounter } from '@/components/reports/char-counter';
import { ItemListInput } from '@/components/reports/item-list-input';
import { PdfDownloadButton } from '@/components/reports/pdf-download-button';
import { ReportFieldsView } from '@/components/reports/report-fields-view';
import { Textarea } from '@/components/ui/textarea';
import { confirmLeave, installLeaveGuard } from '@/hooks/use-leave-guard';

// As main.jsx does before the app renders: Back and Forward reach the page's guard before any router.
installLeaveGuard();

export async function render(element) {
  const container = document.createElement('div');
  document.body.appendChild(container);
  const root = createRoot(container);
  await act(async () => {
    root.render(element);
  });
  return {
    container,
    async unmount() {
      await act(async () => root.unmount());
      container.remove();
    },
  };
}

/**
 * The tutor's report page at ``path`` for ``user``. The bookings lists and a
 * booking's workspace are markers here: where Back and Cancel lead is read
 * from the router's location.
 */
export async function mountPage(path, user) {
  const container = document.createElement('div');
  document.body.appendChild(container);
  const root = createRoot(container);
  const router = createMemoryRouter(
    [
      { path: '/my-bookings', element: <p>My Bookings</p> },
      { path: '/my-bookings/:bookingType', element: <p>Bookings</p> },
      { path: '/my-bookings/:bookingType/:bookingId', element: <p>Booking</p> },
      { path: '/my-bookings/:bookingType/:bookingId/report', element: <TutorReportPage user={user} /> },
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
      for (const node of [...document.body.children]) {
        if (node.parentNode === document.body) document.body.removeChild(node);
      }
    },
  };
}

/** An item list that keeps its own rows, as a form does, and hands each change to ``onItems``. */
export function ItemListHost({ initial, onItems, ...props }) {
  const [items, setItems] = useState(initial);
  return (
    <ItemListInput
      items={items}
      onChange={(next) => {
        setItems(next);
        onItems?.(next);
      }}
      {...props}
    />
  );
}

export { act, CharCounter, confirmLeave, ItemListInput, PdfDownloadButton, ReportFieldsView, Textarea };
export { createElement as h, Fragment } from 'react';
export * as reports from '@/lib/reports';
