import { useState } from 'react';
import { Loader2 } from 'lucide-react';
import api from '../lib/api';

export function AuthScreen({ children }) {
  return <main className="flex min-h-dvh items-center justify-center bg-[#080a12] px-4 py-8 text-[#f8fafc]">
    <div className="w-full max-w-md">
      <div className="mb-7 flex items-center justify-center gap-3"><img src="/brand/icon.svg" alt="Eduport Plus" className="h-11 w-11" /><span className="text-xl font-semibold">Eduport <span className="text-[#ffd65b]">Plus</span></span></div>
      <section className="rounded-2xl border border-white/10 bg-[#121521] p-6 sm:p-9">{children}</section>
    </div>
  </main>;
}

export const authInputClass = 'mt-2 h-12 w-full rounded-lg border border-white/20 bg-[#080a12] px-3 text-white focus:outline-none focus:ring-2 focus:ring-[#ffd65b]';
export const authButtonClass = 'flex h-12 w-full items-center justify-center gap-2 rounded-lg bg-[#ffd65b] font-semibold text-[#111827] disabled:opacity-60';

export default function LoginPage() {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const submit = async (event) => {
    event.preventDefault(); setLoading(true); setError('');
    try {
      const { data } = await api.post('/api/auth/learn/login/', { username, password });
      setPassword('');
      window.location.assign(data.must_change_password ? '/change-password' : '/dashboard');
    } catch (err) { setError(err.response?.data?.message || 'Unable to sign in. Please try again.'); }
    finally { setLoading(false); }
  };
  return <AuthScreen>
    <p className="text-xs font-semibold uppercase tracking-widest text-[#ffd65b]">Student sign in</p>
    <h1 className="mt-2 text-3xl font-semibold">Welcome back</h1>
    <p className="mt-3 text-sm leading-6 text-[#a9b1c4]">Use the username and password provided in your enrollment invitation.</p>
    <form onSubmit={submit} className="mt-6 space-y-5">
      <label className="block text-sm">Username<input className={authInputClass} name="username" autoComplete="username" autoCapitalize="none" spellCheck={false} required value={username} onChange={(event) => setUsername(event.target.value)} /></label>
      <label className="block text-sm">Password<input className={authInputClass} name="password" type="password" autoComplete="current-password" required value={password} onChange={(event) => setPassword(event.target.value)} /></label>
      {error ? <p role="alert" className="text-sm text-red-300">{error}</p> : null}
      <button className={authButtonClass} disabled={loading}>{loading ? <Loader2 className="size-4 animate-spin" /> : null}{loading ? 'Signing in…' : 'Sign in'}</button>
    </form>
  </AuthScreen>;
}
