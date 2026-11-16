// Mounts the real lead pages at a URL, for a given signed-in account, the way
// App.jsx routes them -- the administrators' Leads (/leads, /leads/:leadId),
// a booking's workspace, which reads its lead (/bookings/<type>/:bookingId),
// and the Admissions Dashboard (/admissions), and a BDE's dashboard and My
// Enquiries (/dashboard, /enquiries, /enquiries/:enquiryId) -- with only the
// API a stand-in (api-stub.js); with `layout`, inside the Hub's own
// SidebarLayout, as App.jsx places every page.
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { RouterProvider, createMemoryRouter } from 'react-router-dom';
import AdmissionsDashboardPage from '@/pages/AdmissionsDashboardPage';
import BdeDashboardPage from '@/pages/BdeDashboardPage';
import BookingWorkspacePage from '@/pages/BookingWorkspacePage';
import EnquiriesPage from '@/pages/EnquiriesPage';
import EnquiryPage from '@/pages/EnquiryPage';
import LeadPage from '@/pages/LeadPage';
import LeadsPage from '@/pages/LeadsPage';
import SidebarLayout from '@/layout/SidebarLayout';

export async function mount(path, user, { layout = false } = {}) {
  const inLayout = (element) =>
    layout ? (
      <SidebarLayout user={user} logout={() => {}}>
        {element}
      </SidebarLayout>
    ) : (
      element
    );
  const container = document.createElement('div');
  document.body.appendChild(container);
  const root = createRoot(container);
  const router = createMemoryRouter(
    [
      { path: '/leads', element: inLayout(<LeadsPage user={user} />) },
      { path: '/leads/:leadId', element: inLayout(<LeadPage user={user} />) },
      { path: '/bookings/demo/:bookingId', element: inLayout(<BookingWorkspacePage key="DEMO" user={user} type="DEMO" />) },
      {
        path: '/bookings/diagnostic/:bookingId',
        element: inLayout(<BookingWorkspacePage key="DIAGNOSTIC" user={user} type="DIAGNOSTIC" />),
      },
      { path: '/admissions', element: inLayout(<AdmissionsDashboardPage />) },
      { path: '/dashboard', element: inLayout(<BdeDashboardPage user={user} />) },
      { path: '/enquiries', element: inLayout(<EnquiriesPage user={user} />) },
      { path: '/enquiries/:enquiryId', element: inLayout(<EnquiryPage user={user} />) },
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
