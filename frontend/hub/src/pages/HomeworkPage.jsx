import { useEffect, useState } from 'react';
import { ArrowDownUp, BookOpen, ChevronDown, Loader2, X } from 'lucide-react';

import api from '../lib/api';
import { mentorZoneFormatter } from '../lib/timezone';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '../components/ui/dropdown-menu';
import { HomeworkGradeSheet } from '../components/homework/homework-grade-sheet';
import { ResultCell } from '../components/exams/result-cell';
import { HOMEWORK_STATUS_VARIANT, homeworkStatusLabel } from '../lib/homework-status';

// Staff read class and submission times in IST (MENTOR_TIMEZONE), not the device's zone.
const DATE_FORMAT = mentorZoneFormatter({ month: 'short', day: 'numeric', year: 'numeric' });
const DATETIME_FORMAT = mentorZoneFormatter({ month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });

// Status tabs as the Hub's homework page names them.
const TABS = [
  { key: 'all', label: 'All' },
  { key: 'submitted', label: 'Needs review' },
  { key: 'assigned', label: 'Awaiting' },
  { key: 'scored', label: 'Scored' },
];

/**
 * /homework -- the management and review page (Hub parity). Admins see every
 * homework, mentors and tutors their students'. Grading (the score form in
 * the sheet) is the tutor's job; the mentor only reviews.
 */
export default function HomeworkPage() {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [userRole, setUserRole] = useState('ADMIN');
  const [tab, setTab] = useState('all');
  const [search, setSearch] = useState('');
  const [tutorFilter, setTutorFilter] = useState('');
  const [sortDesc, setSortDesc] = useState(true);
  const [gradeId, setGradeId] = useState(null);

  const canScore = userRole === 'ADMIN' || userRole === 'TUTOR';

  const fetchRows = async () => {
    setLoading(true);
    setError('');
    try {
      const res = await api.get('/api/homework/');
      setRows(res.data.homework || []);
    } catch (err) {
      setError(err.response?.data?.error || err.response?.data?.message || 'Failed to load homework.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    api
      .get('/api/auth/me/')
      .then((res) => {
        const role = res.data.user?.role || 'ADMIN';
        setUserRole(role);
        // Tutors land on the review queue, everyone else on the full list.
        if (role === 'TUTOR') setTab('submitted');
      })
      .catch(() => {});
    fetchRows();
  }, []);

  const term = search.trim().toLowerCase();
  const filtered = rows
    .filter((r) => tab === 'all' || (r.status || '').toLowerCase() === tab)
    .filter((r) => !tutorFilter || r.tutor_profile?.id === tutorFilter)
    .filter((r) => {
      if (!term) return true;
      const name = (r.students?.full_name || '').toLowerCase();
      const code = (r.students?.student_code || '').toLowerCase();
      const title = (r.session?.title || '').toLowerCase();
      return name.includes(term) || code.includes(term) || title.includes(term);
    })
    .sort((a, b) => {
      const ta = a.submitted_at ? new Date(a.submitted_at).getTime() : 0;
      const tb = b.submitted_at ? new Date(b.submitted_at).getTime() : 0;
      return sortDesc ? tb - ta : ta - tb;
    });

  const counts = TABS.reduce((acc, t) => {
    acc[t.key] = t.key === 'all' ? rows.length : rows.filter((r) => (r.status || '').toLowerCase() === t.key).length;
    return acc;
  }, {});

  const tutorOptions =
    userRole === 'ADMIN'
      ? Array.from(
          new Map(rows.filter((r) => r.tutor_profile).map((r) => [r.tutor_profile.id, { id: r.tutor_profile.id, name: r.tutor_profile.full_name || r.tutor_profile.email }])).values()
        ).sort((a, b) => a.name.localeCompare(b.name))
      : [];

  const hasFilters = Boolean(search) || Boolean(tutorFilter);

  return (
    <div className="flex flex-col gap-6 w-full max-w-full box-border">
      <div className="flex flex-col gap-1">
        <h1 className="text-lg font-semibold text-zinc-900 dark:text-white">Homework</h1>
        <p className="text-sm text-zinc-500">
          {userRole === 'MENTOR' ? "Track your students' homework. Submissions are reviewed by the tutor." : 'Review submitted homework and grade it.'}
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Input placeholder="Filter by student or session..." value={search} onChange={(e) => setSearch(e.target.value)} className="max-w-xs" />

        {tutorOptions.length > 0 && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" size="sm">
                Tutor
                {tutorFilter ? <span className="text-muted-foreground ml-1">(1)</span> : null}
                <ChevronDown className="ml-1 size-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" className="max-h-72 overflow-y-auto">
              <DropdownMenuLabel>Tutor</DropdownMenuLabel>
              <DropdownMenuSeparator />
              <DropdownMenuRadioGroup value={tutorFilter} onValueChange={setTutorFilter}>
                <DropdownMenuRadioItem value="">All tutors</DropdownMenuRadioItem>
                {tutorOptions.map((opt) => (
                  <DropdownMenuRadioItem key={opt.id} value={opt.id}>
                    {opt.name}
                  </DropdownMenuRadioItem>
                ))}
              </DropdownMenuRadioGroup>
            </DropdownMenuContent>
          </DropdownMenu>
        )}

        <Button variant="outline" size="sm" onClick={() => setSortDesc((v) => !v)}>
          <ArrowDownUp className="size-4" />
          {sortDesc ? 'Newest submissions' : 'Oldest submissions'}
        </Button>

        {hasFilters && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              setSearch('');
              setTutorFilter('');
            }}
            className="text-muted-foreground"
          >
            <X className="size-4" />
            Clear
          </Button>
        )}
      </div>

      {error && <div className="bg-red-950/40 text-red-400 text-xs p-3 rounded-lg border border-red-900/50">{error}</div>}

      <div className="flex gap-4 overflow-x-auto border-b border-zinc-200 dark:border-[rgba(255,255,255,0.08)] sm:gap-6">
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`shrink-0 whitespace-nowrap pb-3 text-sm font-medium transition-colors relative cursor-pointer ${
              tab === t.key ? 'text-zinc-900 dark:text-white border-b-2 border-zinc-900 dark:border-white' : 'text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-300'
            }`}
          >
            {t.label}
            <span className="ml-1.5 text-xs text-zinc-500">{counts[t.key] ?? 0}</span>
          </button>
        ))}
      </div>

      <div className="border border-[rgba(255,255,255,0.08)] bg-[#0a0a0a] rounded-xl shadow-xl overflow-x-auto w-full">
        {loading ? (
          <div className="flex items-center justify-center py-20">
            <Loader2 className="w-8 h-8 animate-spin text-white" />
          </div>
        ) : filtered.length === 0 ? (
          <div className="py-16 text-center">
            <BookOpen className="w-8 h-8 mx-auto text-zinc-600 mb-3" />
            <p className="text-zinc-500 text-sm">{tab === 'submitted' ? 'Nothing waiting for review.' : 'No homework found.'}</p>
          </div>
        ) : (
          <table className="w-full text-left border-collapse text-sm">
            <thead>
              <tr className="border-b border-[rgba(255,255,255,0.08)] bg-[#0f0f0f]">
                {['Student', 'Session', 'Tutor', 'Status', 'Submitted', 'Score'].map((h) => (
                  <th key={h} className="h-12 px-4 font-semibold text-xs text-zinc-400 align-middle">{h}</th>
                ))}
                <th className="h-12 px-4 w-32"></th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((r) => {
                const status = (r.status || '').toLowerCase();
                const grade = canScore && status === 'submitted';
                return (
                  <tr key={r.id} className="hover:bg-[rgba(255,255,255,0.02)] border-b border-[rgba(255,255,255,0.08)] h-[54px] transition-colors">
                    <td className="py-2 px-4 align-middle">
                      <div className="flex flex-col gap-0.5">
                        <span className="font-medium text-white text-sm">{r.students?.full_name || '—'}</span>
                        <span className="text-xs text-[#a1a1aa] font-mono">{r.students?.student_code || ''}</span>
                      </div>
                    </td>
                    <td className="py-2 px-4 align-middle">
                      <div className="flex flex-col gap-0.5">
                        <span className="font-semibold text-white text-sm">{r.session?.title || '—'}</span>
                        <span className="text-xs text-zinc-500">{r.session?.start_time ? DATE_FORMAT.format(new Date(r.session.start_time)) : ''}</span>
                      </div>
                    </td>
                    <td className="py-2 px-4 align-middle text-sm text-[#e4e4e7]">{r.tutor_profile?.full_name || r.tutor_profile?.email || '—'}</td>
                    <td className="py-2 px-4 align-middle">
                      <Badge variant={HOMEWORK_STATUS_VARIANT[status] || 'secondary'}>{homeworkStatusLabel(r)}</Badge>
                    </td>
                    <td className="py-2 px-4 align-middle text-sm text-zinc-300 whitespace-nowrap">
                      {r.submitted_at ? DATETIME_FORMAT.format(new Date(r.submitted_at)) : <span className="text-zinc-500">—</span>}
                    </td>
                    <td className="py-2 px-4 align-middle text-sm whitespace-nowrap tabular-nums">
                      {status === 'scored' ? <ResultCell score={r.score} maxScore={r.max_score} /> : <span className="text-zinc-500">—</span>}
                    </td>
                    <td className="py-2 px-4 align-middle text-right">
                      <button
                        type="button"
                        onClick={() => setGradeId(r.id)}
                        className={`inline-flex items-center h-7 px-2.5 rounded-md border text-xs font-medium whitespace-nowrap transition-colors ${
                          grade ? 'border-white/20 bg-white text-zinc-950 hover:bg-zinc-200' : 'border-white/10 bg-zinc-800 text-zinc-200 hover:bg-zinc-700 hover:text-white'
                        }`}
                      >
                        {grade ? 'Grade' : 'View'}
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      <HomeworkGradeSheet homeworkId={gradeId} open={Boolean(gradeId)} onOpenChange={(v) => !v && setGradeId(null)} onSaved={fetchRows} canScore={canScore} />
    </div>
  );
}
