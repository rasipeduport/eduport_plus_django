import { useEffect, useState } from 'react';
import api from '../lib/api';
import { AuthScreen, authInputClass, authButtonClass } from './LoginPage';

export default function ChangePasswordPage() {
  const [ready, setReady] = useState(false);
  const [current, setCurrent] = useState('');
  const [password, setPassword] = useState('');
  const [confirmation, setConfirmation] = useState('');
  const [error, setError] = useState('');
  const [pending, setPending] = useState(false);
  useEffect(() => {
    let mounted = true;
    api.get('/api/auth/me/').then(({ data }) => {
      if (!data.must_change_password) window.location.replace('/dashboard');
      else if (mounted) setReady(true);
    }).catch(() => window.location.replace('/login'));
    return () => { mounted = false; };
  }, []);
  const submit = async (event) => {
    event.preventDefault(); setError('');
    if (password !== confirmation) { setError('The new passwords do not match.'); return; }
    setPending(true);
    try {
      await api.post('/api/auth/change-password/', { current_password: current, new_password: password });
      setCurrent(''); setPassword(''); setConfirmation('');
      window.location.replace('/dashboard');
    } catch (err) {
      setError(err.response?.data?.details?.join(' ') || err.response?.data?.message || 'Could not change your password.');
    } finally { setPending(false); }
  };
  return <AuthScreen><h1 className="text-2xl font-semibold">Set your own password</h1>
    <p className="mt-3 text-sm leading-6 text-[#a9b1c4]">Replace your temporary password before accessing Learn. Use a strong password you have not used elsewhere.</p>
    {ready ? <form onSubmit={submit} className="mt-6 space-y-5">
      <label className="block text-sm">Temporary password<input type="password" autoComplete="current-password" required className={authInputClass} value={current} onChange={(e) => setCurrent(e.target.value)} /></label>
      <label className="block text-sm">New password<input type="password" autoComplete="new-password" required className={authInputClass} value={password} onChange={(e) => setPassword(e.target.value)} /></label>
      <label className="block text-sm">Confirm new password<input type="password" autoComplete="new-password" required className={authInputClass} value={confirmation} onChange={(e) => setConfirmation(e.target.value)} /></label>
      {error ? <p role="alert" className="text-sm text-red-300">{error}</p> : null}
      <button className={authButtonClass} disabled={pending}>{pending ? 'Saving…' : 'Change password'}</button>
      <button type="button" className="w-full text-sm text-[#a9b1c4]" onClick={async () => { await api.post('/api/auth/logout/'); window.location.replace('/login'); }}>Sign out</button>
    </form> : <p role="status" className="mt-6">Checking your account…</p>}
  </AuthScreen>;
}
