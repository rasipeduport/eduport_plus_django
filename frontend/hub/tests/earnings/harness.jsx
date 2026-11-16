// Mounts the Hub's Tutor Earnings pages -- the Admin overview, one tutor's
// page, a tutor's My Earnings -- with only the API stood in for
// (api-stub.js); re-exports the helpers they format, gate and navigate with.
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { RouterProvider, createMemoryRouter } from 'react-router-dom';
import TutorEarningsPage from '@/pages/TutorEarningsPage';
import TutorEarningsDetailPage from '@/pages/TutorEarningsDetailPage';
import MyEarningsPage from '@/pages/MyEarningsPage';

export async function mount(kind, props = {}) {
  const container = document.createElement('div');
  document.body.appendChild(container);
  const root = createRoot(container);
  const routes = {
    overview: [{ path: '/tutor-earnings', element: <TutorEarningsPage user={props.user} /> }, '/tutor-earnings'],
    detail: [{ path: '/tutor-earnings/:tutorId', element: <TutorEarningsDetailPage user={props.user} /> }, `/tutor-earnings/${props.tutorId}`],
    mine: [{ path: '/my-earnings', element: <MyEarningsPage /> }, '/my-earnings'],
  };
  const [route, path] = routes[kind];
  const router = createMemoryRouter([route], { initialEntries: [props.path || path] });
  await act(async () => root.render(<RouterProvider router={router} />));
  return async () => { await act(async () => root.unmount()); container.remove(); };
}
export { act };
export * as earnings from '@/lib/earnings';
export * as access from '@/lib/access';
export * as navigation from '@/lib/navigation';
