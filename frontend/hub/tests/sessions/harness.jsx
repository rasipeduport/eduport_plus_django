// Mounts the Hub's Sessions page and its outcome dialogs, and Learn's
// sessions list, with only the API stood in for (api-stub.js); re-exports the
// lifecycle helpers the Hub and Learn derive a class's state with.
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { RouterProvider, createMemoryRouter } from 'react-router-dom';
import SessionsPage from '@/pages/SessionsPage';
import { SessionsList } from '../../../learn/src/components/sessions/sessions-list';
import { StudentContext } from '../../../learn/src/components/student/student-context';

export async function mount(kind, props = {}) {
  const container = document.createElement('div');
  document.body.appendChild(container);
  const root = createRoot(container);
  let tree;
  if (kind === 'sessions') {
    const router = createMemoryRouter([{ path: '/sessions', element: <SessionsPage user={props.user} /> }], {
      initialEntries: [props.path || '/sessions'],
    });
    tree = <RouterProvider router={router} />;
  } else if (kind === 'learn-sessions') {
    tree = (
      <StudentContext.Provider value={{ timezone: 'Asia/Kolkata' }}>
        <SessionsList sessions={props.sessions} />
      </StudentContext.Provider>
    );
  } else {
    throw new Error(`unknown kind ${kind}`);
  }
  await act(async () => root.render(tree));
  return async () => { await act(async () => root.unmount()); container.remove(); };
}
export { act };
export * as hub from '@/lib/session-lifecycle';
export * as learn from '../../../learn/src/lib/session-state';
