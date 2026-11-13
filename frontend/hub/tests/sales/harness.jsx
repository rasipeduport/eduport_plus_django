// Mounts the real Sales Management pages at a URL, for a given signed-in
// account, the way App.jsx routes them -- Syllabus & Plans (/sales-syllabus,
// /sales-syllabus/new, /sales-syllabus/:syllabusId and .../edit), Global
// Pricing (/sales-pricing), the BDE's Plans & Pricing (/plans,
// /plans/:syllabusId), Quotes (/quotes, /quotes/:quoteId) and a student's
// profile (/students/:studentId, for its Purchases tab) -- with only the API a
// stand-in (api-stub.js).
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { RouterProvider, createMemoryRouter } from 'react-router-dom';
import PlanPage from '@/pages/PlanPage';
import PlansPage from '@/pages/PlansPage';
import AutopayActionPage from '@/pages/AutopayActionPage';
import EnquiryPage from '@/pages/EnquiryPage';
import QuotePage from '@/pages/QuotePage';
import QuotesPage from '@/pages/QuotesPage';
import SalesPricingPage from '@/pages/SalesPricingPage';
import SalesSyllabiPage from '@/pages/SalesSyllabiPage';
import SalesSyllabusEditorPage from '@/pages/SalesSyllabusEditorPage';
import SalesSyllabusPage from '@/pages/SalesSyllabusPage';
import StudentProfilePage from '@/pages/StudentProfilePage';
import SidebarLayout from '@/layout/SidebarLayout';

// With `layout`, inside the Hub's own SidebarLayout, as App.jsx places every page.
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
      { path: '/sales-syllabus', element: inLayout(<SalesSyllabiPage user={user} />) },
      { path: '/sales-syllabus/new', element: inLayout(<SalesSyllabusEditorPage key="new" />) },
      { path: '/sales-syllabus/:syllabusId', element: inLayout(<SalesSyllabusPage />) },
      { path: '/sales-syllabus/:syllabusId/edit', element: inLayout(<SalesSyllabusEditorPage key="edit" />) },
      { path: '/sales-pricing', element: inLayout(<SalesPricingPage />) },
      { path: '/plans', element: inLayout(<PlansPage />) },
      { path: '/autopay/confirm/:token', element: <AutopayActionPage /> },
      { path: '/plans/:syllabusId', element: inLayout(<PlanPage user={user} />) },
      { path: '/enquiries/:enquiryId', element: inLayout(<EnquiryPage user={user} />) },
      { path: '/quotes', element: inLayout(<QuotesPage user={user} />) },
      { path: '/quotes/:quoteId', element: inLayout(<QuotePage user={user} />) },
      { path: '/students/:studentId', element: inLayout(<StudentProfilePage user={user} />) },
    ],
    { initialEntries: [path] }
  );
  await act(async () => {
    root.render(<RouterProvider router={router} />);
  });
  return {
    container,
    location: () => router.state.location,
    // Leaves for another page, as a link or the browser's Back would.
    async go(to) {
      await act(async () => {
        await router.navigate(to);
      });
    },
    async unmount() {
      await act(async () => root.unmount());
      container.remove();
      for (const node of [...document.body.children]) {
        if (node.parentNode === document.body) document.body.removeChild(node);
      }
    },
  };
}

export { act };
export { canOpenPage } from '@/lib/access';
export { workspaceFor } from '@/lib/navigation';
// (the labels re-exported lower-case: an upper-case export reads as a component to the fast-refresh lint rule)
export { ACTION_LABELS as actionLabels, describeActivity } from '@/lib/activity-format';
export {
  // (re-exported lower-case: an upper-case export reads as a component to the fast-refresh lint rule)
  SELECTED_DAYS_TITLE as selectedDaysTitle,
  CHAPTER_PLAN_TITLE as chapterPlanTitle,
  apiFieldErrors,
  bridgeSelection,
  chapterPlanSelection,
  enquiryLabel,
  formErrors,
  formatAmount,
  packagePrices,
  payloadOf,
  quotePlanLabel,
  quotePreview,
  toHalves,
  syllabusWhatsAppMessage,
} from '@/lib/sales';
