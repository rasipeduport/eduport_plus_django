import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import LoginPage from '../../../learn/src/pages/LoginPage';
import ChangePasswordPage from '../../../learn/src/pages/ChangePasswordPage';
import AuthProvider from '../../../learn/src/context/AuthProvider';
import { InvitationsTable } from '@/components/invitations/invitations-table';

export async function mount(kind, props = {}) {
  const container = document.createElement('div'); document.body.appendChild(container);
  const root = createRoot(container);
  const content = kind === 'login' ? <LoginPage /> : kind === 'change' ? <ChangePasswordPage /> : kind === 'invitations' ? <InvitationsTable {...props} /> : <Routes>
    <Route path="/dashboard" element={<AuthProvider>{() => <p>Learning content</p>}</AuthProvider>} />
    <Route path="/change-password" element={<p>Password change required</p>} />
  </Routes>;
  await act(async () => root.render(<MemoryRouter initialEntries={['/dashboard']}>{content}</MemoryRouter>));
  return async () => { await act(async () => root.unmount()); container.remove(); };
}
export { act };
