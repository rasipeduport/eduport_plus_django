import { useState, useEffect, useRef, Fragment } from 'react';
import { Loader2, Search, ChevronDown, ChevronUp, Calendar } from 'lucide-react';
import api from '../lib/api';

const PAGE_SIZE = 25;

// action code -> short badge label
const ACTION_LABELS = {
  'student.create': 'Student added',
  'student.update_status': 'Status changed',
  'student.update_quota': 'Quota changed',
  'student.update_meet_link': 'Meet link updated',
  'session.create': 'Session created',
  'session.create_series': 'Series created',
  'session.cancel': 'Session cancelled',
  'session.cancel_series': 'Session cancelled',
  'session.reschedule': 'Session rescheduled',
  'session.mark_attended': 'Session attended',
  'session.rate': 'Session rated',
  'session.update_links': 'Resources updated',
  'session.update': 'Session updated',
  'invitation.create': 'Invitation sent',
  'invitation.update_email': 'Invitation email changed',
  'invitation.withdraw': 'Invitation withdrawn',
  'USER_UPDATE': 'User updated',
  'USER_DELETE': 'User deleted',
  'user.deactivate': 'User deactivated',
  'user.reactivate': 'User reactivated',
  'staff.reassign_all': 'Workload reassigned',
  'ONBOARDED': 'Onboarded',
  'LOGIN': 'Logged in',
  'LOGOUT': 'Logged out',
};

// Options for the "All actions" filter dropdown
const ACTION_OPTIONS = Object.entries(ACTION_LABELS).map(([value, label]) => ({ value, label }));

// Options for the "All types" filter dropdown (must match stored entity_type)
const TYPE_OPTIONS = [
  { value: 'session', label: 'Sessions' },
  { value: 'student', label: 'Students' },
  { value: 'invitation', label: 'Invitations' },
  { value: 'USER', label: 'Users' },
];

function actionLabel(action) {
  return ACTION_LABELS[action] || action;
}

// "17 Jun 2026, 10:03 PM"
function formatWhen(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  const day = d.getDate();
  const month = d.toLocaleString('en-US', { month: 'short' });
  const year = d.getFullYear();
  let h = d.getHours();
  const m = String(d.getMinutes()).padStart(2, '0');
  const ampm = h >= 12 ? 'PM' : 'AM';
  h = h % 12 || 12;
  return `${day} ${month} ${year}, ${h}:${m} ${ampm}`;
}

// Human-friendly primary description of the action
function describe(log) {
  const c = log.changes || {};
  const ctx = log.context || {};
  switch (log.action) {
    case 'student.create':
      return 'Added the student';
    case 'student.update_status': {
      const oldS = c.status?.old || 'none';
      const newS = c.status?.new || 'none';
      const note = c.status_note?.new;
      return `Changed status from "${oldS}" to "${newS}"${note ? ` — ${note}` : ''}`;
    }
    case 'student.update_quota':
      return `Changed class quota from ${c.total_class_quota?.old ?? 0} to ${c.total_class_quota?.new ?? 0}`;
    case 'student.update_meet_link':
      return 'Updated the meet link';
    case 'session.create':
      return 'Created a session';
    case 'session.create_series':
      return `Created a series of ${ctx.count ?? ''} classes`.replace(/\s+/g, ' ').trim();
    case 'session.cancel':
    case 'session.cancel_series':
      return `Cancelled the session${ctx.reason ? ` — ${ctx.reason}` : ''}`;
    case 'session.reschedule': {
      const o = c.start_time?.old;
      const n = c.start_time?.new;
      return o && n ? `Rescheduled from ${formatWhen(o)} to ${formatWhen(n)}` : 'Rescheduled the session';
    }
    case 'session.mark_attended':
      return 'Marked the session as attended';
    case 'session.rate':
      return `Rated the session ${c.rating?.new ?? ''} stars`.replace(/\s+/g, ' ').trim();
    case 'session.update_links':
      return 'Updated class resources';
    case 'session.update':
      return 'Updated the session';
    case 'invitation.create':
      return 'Sent an invitation';
    case 'invitation.update_email':
      return `Changed invitation email to ${c.email?.new ?? ''}`.trim();
    case 'invitation.withdraw':
      return 'Withdrew the invitation';
    case 'USER_UPDATE':
      return 'Updated user details';
    case 'USER_DELETE':
      return 'Deleted the user';
    case 'user.deactivate':
      return `Deactivated ${log.entity_label || 'the user'}${ctx.reason ? ` — ${ctx.reason}` : ''}`;
    case 'user.reactivate':
      return `Reactivated ${log.entity_label || 'the user'}`;
    case 'staff.reassign_all':
      return "Reassigned this staff member's students before deactivation";
    case 'ONBOARDED':
      return 'Onboarded to the platform';
    case 'LOGIN':
      return 'Logged in';
    case 'LOGOUT':
      return 'Logged out';
    default:
      return log.action;
  }
}

// Secondary "Student: X" / "Session: Y" line, entity-aware
function entityLine(log) {
  if (log.action === 'LOGIN' || log.action === 'LOGOUT' || log.action === 'ONBOARDED') {
    return log.student_name ? `Student: ${log.student_name}` : null;
  }
  const t = (log.entity_type || '').toLowerCase();
  if (t === 'student') return `Student: ${log.student_name || log.entity_label || '—'}`;
  if (t === 'session') return log.entity_label ? `Session: ${log.entity_label}` : null;
  if (t === 'invitation') return log.entity_label ? `Invitation: ${log.entity_label}` : null;
  if (t === 'user') return log.entity_label ? `User: ${log.entity_label}` : null;
  return null;
}

const selectClass =
  'h-10 pl-4 pr-9 bg-[#111] border border-[rgba(255,255,255,0.08)] rounded-xl text-sm font-medium text-zinc-300 hover:text-white hover:bg-zinc-900 focus:outline-none focus:ring-1 focus:ring-zinc-600 transition-colors appearance-none cursor-pointer';

export default function ActivityPage() {
  const [logs, setLogs] = useState([]);
  const [count, setCount] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [expandedId, setExpandedId] = useState(null);

  // Filters
  const [searchInput, setSearchInput] = useState('');
  const [search, setSearch] = useState('');
  const [actionFilter, setActionFilter] = useState('');
  const [typeFilter, setTypeFilter] = useState('');
  const [actorFilter, setActorFilter] = useState('');
  const [fromDate, setFromDate] = useState('');
  const [toDate, setToDate] = useState('');
  const [actorOptions, setActorOptions] = useState([]);

  const [showDateRange, setShowDateRange] = useState(false);
  const dateRef = useRef(null);

  // Debounce the search box into the committed `search` filter
  useEffect(() => {
    const t = setTimeout(() => {
      setSearch(searchInput);
      setPage(1);
    }, 400);
    return () => clearTimeout(t);
  }, [searchInput]);

  // Close the date-range popover on outside click
  useEffect(() => {
    function handleClickOutside(e) {
      if (dateRef.current && !dateRef.current.contains(e.target)) {
        setShowDateRange(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  useEffect(() => {
    const fetchLogs = async () => {
      setLoading(true);
      setError('');
      try {
        const params = new URLSearchParams();
        if (search) params.set('q', search);
        if (actionFilter) params.set('action', actionFilter);
        if (typeFilter) params.set('entity', typeFilter);
        if (actorFilter) params.set('actor', actorFilter);
        if (fromDate) params.set('from', fromDate);
        if (toDate) params.set('to', toDate);
        params.set('page', page);
        params.set('page_size', PAGE_SIZE);

        const res = await api.get(`/api/activity/?${params.toString()}`);
        setLogs(res.data.results || []);
        setCount(res.data.count || 0);
        if (res.data.actor_options) setActorOptions(res.data.actor_options);
      } catch (err) {
        setError(err.response?.data?.message || 'Failed to load activity log.');
      } finally {
        setLoading(false);
      }
    };
    fetchLogs();
  }, [search, actionFilter, typeFilter, actorFilter, fromDate, toDate, page]);

  const totalPages = Math.max(1, Math.ceil(count / PAGE_SIZE));
  const rangeStart = count === 0 ? 0 : (page - 1) * PAGE_SIZE + 1;
  const rangeEnd = Math.min(page * PAGE_SIZE, count);
  const dateActive = fromDate || toDate;

  const onFilterChange = (setter) => (e) => {
    setter(e.target.value);
    setPage(1);
  };

  return (
    <div className="flex flex-col gap-6 w-full max-w-full box-border">
      {/* Heading */}
      <div>
        <h1 className="text-2xl font-bold text-zinc-900 dark:text-white m-0 tracking-tight">Activity log</h1>
        <p className="text-sm text-zinc-500 dark:text-[#a1a1aa] mt-1.5 m-0">
          A record of who changed what across students, sessions, invitations, and users.
        </p>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="relative flex-1 min-w-[220px] sm:max-w-xs">
          <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-zinc-500" />
          <input
            type="text"
            placeholder="Search actor or target..."
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            className="w-full pl-10 pr-4 h-10 bg-[#111] border border-[rgba(255,255,255,0.08)] rounded-xl text-sm text-white placeholder-zinc-500 focus:outline-none focus:ring-1 focus:ring-zinc-600 transition-all"
          />
        </div>

        <div className="relative">
          <select value={actionFilter} onChange={onFilterChange(setActionFilter)} className={selectClass}>
            <option value="">All actions</option>
            {ACTION_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
          <ChevronDown className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-zinc-500" />
        </div>

        <div className="relative">
          <select value={typeFilter} onChange={onFilterChange(setTypeFilter)} className={selectClass}>
            <option value="">All types</option>
            {TYPE_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
          <ChevronDown className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-zinc-500" />
        </div>

        {actorOptions.length > 0 && (
          <div className="relative">
            <select value={actorFilter} onChange={onFilterChange(setActorFilter)} className={selectClass}>
              <option value="">All actors</option>
              {actorOptions.map((a) => (
                <option key={a.id} value={a.id}>{a.name}</option>
              ))}
            </select>
            <ChevronDown className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-zinc-500" />
          </div>
        )}

        <div className="relative" ref={dateRef}>
          <button
            type="button"
            onClick={() => setShowDateRange((v) => !v)}
            className={`h-10 px-4 bg-[#111] border rounded-xl text-sm font-medium transition-colors flex items-center gap-2 ${
              dateActive
                ? 'border-zinc-500 text-white'
                : 'border-[rgba(255,255,255,0.08)] text-zinc-300 hover:text-white hover:bg-zinc-900'
            }`}
          >
            <Calendar className="w-4 h-4" />
            {dateActive ? `${fromDate || '…'} → ${toDate || '…'}` : 'Date range'}
          </button>

          {showDateRange && (
            <div className="absolute right-0 mt-1.5 w-64 bg-[#121214] border border-[#1e1e24] rounded-xl shadow-xl p-3 z-50 space-y-3">
              <div className="space-y-1">
                <label className="block text-[10px] font-bold text-zinc-500 uppercase tracking-widest">From</label>
                <input
                  type="date"
                  value={fromDate}
                  onChange={(e) => { setFromDate(e.target.value); setPage(1); }}
                  className="w-full px-3 h-9 bg-[#1a1a1e] border border-[#27272a] rounded-lg text-sm text-white focus:outline-none focus:ring-1 focus:ring-zinc-600"
                />
              </div>
              <div className="space-y-1">
                <label className="block text-[10px] font-bold text-zinc-500 uppercase tracking-widest">To</label>
                <input
                  type="date"
                  value={toDate}
                  onChange={(e) => { setToDate(e.target.value); setPage(1); }}
                  className="w-full px-3 h-9 bg-[#1a1a1e] border border-[#27272a] rounded-lg text-sm text-white focus:outline-none focus:ring-1 focus:ring-zinc-600"
                />
              </div>
              {dateActive && (
                <button
                  type="button"
                  onClick={() => { setFromDate(''); setToDate(''); setPage(1); }}
                  className="text-[11px] font-semibold text-zinc-400 hover:text-white"
                >
                  Clear dates
                </button>
              )}
            </div>
          )}
        </div>
      </div>

      {error && (
        <div className="bg-red-950/40 text-red-400 text-xs p-3 rounded-lg border border-red-900/50">{error}</div>
      )}

      {/* Table */}
      <div className="border border-[rgba(255,255,255,0.08)] bg-[#0a0a0a] rounded-xl shadow-xl overflow-x-auto w-full">
        <table className="w-full text-left border-collapse text-sm">
          <thead>
            <tr className="border-b border-[rgba(255,255,255,0.08)] bg-[#0f0f0f]">
              <th className="h-12 px-6 font-semibold text-xs text-zinc-400 align-middle">When</th>
              <th className="h-12 px-6 font-semibold text-xs text-zinc-400 align-middle">Who</th>
              <th className="h-12 px-6 font-semibold text-xs text-zinc-400 align-middle">Action</th>
              <th className="h-12 px-6 font-semibold text-xs text-zinc-400 align-middle">Details</th>
              <th className="h-12 px-2 w-10"></th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan="5" className="py-16 text-center">
                  <Loader2 className="w-6 h-6 animate-spin text-white mx-auto" />
                </td>
              </tr>
            ) : logs.length === 0 ? (
              <tr>
                <td colSpan="5" className="py-12 text-center text-zinc-500 text-sm">
                  No activity found matching these filters.
                </td>
              </tr>
            ) : (
              logs.map((log) => {
                const hasChanges = Object.keys(log.changes || {}).length > 0;
                const isExpanded = expandedId === log.id;
                const secondary = entityLine(log);
                return (
                  <Fragment key={log.id}>
                    <tr
                      className={`group hover:bg-[rgba(255,255,255,0.02)] border-b border-[rgba(255,255,255,0.08)] transition-colors ${hasChanges ? 'cursor-pointer' : ''}`}
                      onClick={() => hasChanges && setExpandedId(isExpanded ? null : log.id)}
                    >
                      <td className="py-3 px-6 align-top text-zinc-400 text-sm whitespace-nowrap">
                        {formatWhen(log.created_at)}
                      </td>
                      <td className="py-3 px-6 align-top whitespace-nowrap">
                        <div className="font-semibold text-white text-sm">{log.actor_name || log.actor_email || 'System'}</div>
                        {log.actor_role && (
                          <div className="text-xs text-zinc-500 capitalize">{log.actor_role.toLowerCase()}</div>
                        )}
                      </td>
                      <td className="py-3 px-6 align-top whitespace-nowrap">
                        <span className="inline-flex items-center px-2.5 py-1 rounded-md text-xs font-medium bg-[rgba(255,255,255,0.06)] text-zinc-200 border border-[rgba(255,255,255,0.08)]">
                          {actionLabel(log.action)}
                        </span>
                      </td>
                      <td className="py-3 px-6 align-top">
                        <div className="text-white text-sm leading-snug">{describe(log)}</div>
                        {secondary && <div className="text-xs text-zinc-500 mt-0.5">{secondary}</div>}
                      </td>
                      <td className="py-3 px-2 align-top text-right">
                        {hasChanges && (
                          isExpanded
                            ? <ChevronUp className="w-4 h-4 text-zinc-400 inline-block" />
                            : <ChevronDown className="w-4 h-4 text-zinc-500 inline-block" />
                        )}
                      </td>
                    </tr>
                    {isExpanded && hasChanges && (
                      <tr className="bg-[rgba(255,255,255,0.015)] border-b border-[rgba(255,255,255,0.08)]">
                        <td colSpan="5" className="px-6 pb-4 pt-0">
                          <div className="bg-white/[0.03] border border-white/10 rounded-lg p-3 space-y-1.5 divide-y divide-white/5 text-[11px] max-w-xl">
                            {Object.entries(log.changes).map(([field, delta]) => (
                              <div key={field} className="grid grid-cols-[120px_1fr] gap-2 pt-1.5 first:pt-0">
                                <span className="text-zinc-500 font-medium capitalize">{field.replace(/_/g, ' ')}</span>
                                <span className="text-zinc-300 flex items-center gap-1.5 flex-wrap">
                                  <span className="line-through text-zinc-500">{String(delta?.old ?? '—')}</span>
                                  <span>→</span>
                                  <span className="text-white font-medium">{String(delta?.new ?? '—')}</span>
                                </span>
                              </div>
                            ))}
                          </div>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      {/* Footer / pagination */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <p className="text-xs text-zinc-500 m-0">
          Showing {rangeStart}–{rangeEnd} of {count}
        </p>
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page <= 1}
            className="h-9 px-4 bg-[#111] border border-[rgba(255,255,255,0.08)] rounded-lg text-xs font-semibold text-zinc-300 hover:text-white hover:bg-zinc-900 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          >
            Previous
          </button>
          <span className="text-xs text-zinc-400">Page {page} of {totalPages}</span>
          <button
            type="button"
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page >= totalPages}
            className="h-9 px-4 bg-[#111] border border-[rgba(255,255,255,0.08)] rounded-lg text-xs font-semibold text-zinc-300 hover:text-white hover:bg-zinc-900 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          >
            Next
          </button>
        </div>
      </div>
    </div>
  );
}
