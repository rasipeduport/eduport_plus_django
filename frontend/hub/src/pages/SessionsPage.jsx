import { useState, useEffect } from 'react';
import { useSearchParams, Link } from 'react-router-dom';
import { 
  Loader2, Search, Calendar, Video, FileText, 
  BookOpen, Plus, Link2, AlertTriangle, RefreshCw, Check, ExternalLink
} from 'lucide-react';
import api from '../lib/api';
import StaffActionsDropdown from '../components/StaffActionsDropdown';
import { NewSessionSheet } from '../components/sessions/new-session-sheet';
import { Badge } from '../components/ui/badge';
import { Tooltip, TooltipContent, TooltipTrigger } from '../components/ui/tooltip';

const ALLOWED_DURATIONS = [
  { label: '30 mins', value: 0.5 },
  { label: '1 hour', value: 1.0 },
  { label: '1.5 hours', value: 1.5 },
  { label: '2 hours', value: 2.0 }
];

const MEET_PREFIX = 'https://meet.google.com/';

const isHttpsUrl = (value) => /^https:\/\/\S+$/i.test((value || '').trim());

// Hub-style table formats. Times stay browser-local, as this table always was.
const DATE_FORMAT = new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
const TIME_FORMAT = new Intl.DateTimeFormat('en-US', { hour: 'numeric', minute: '2-digit', hour12: true });

const STATUS_LABEL = { scheduled: 'Scheduled', attended: 'Attended', cancelled: 'Cancelled' };
const STATUS_VARIANT = { scheduled: 'secondary', attended: 'success', cancelled: 'destructive' };

// Status badge as the Hub renders it; a cancelled session shows its reason on hover.
function StatusBadge({ status, reason }) {
  const key = (status || '').toLowerCase();
  const badge = <Badge variant={STATUS_VARIANT[key] || 'secondary'}>{STATUS_LABEL[key] || 'Scheduled'}</Badge>;
  if (key === 'cancelled' && reason) {
    return (
      <Tooltip>
        <TooltipTrigger asChild>
          <span className="cursor-help">{badge}</span>
        </TooltipTrigger>
        <TooltipContent>
          <p className="max-w-xs">{reason}</p>
        </TooltipContent>
      </Tooltip>
    );
  }
  return badge;
}

// A session resource (recording / notes / homework link). The Hub prints the
// URL truncated; a compact open-in-new-tab action keeps this wider table
// usable. "—" when unset; a value that is not a web URL is shown as text.
function ResourceLink({ href, icon: Icon, label }) {
  const url = (href || '').trim();
  if (!url) return <span className="text-zinc-500">—</span>;
  if (!/^https?:\/\/\S+$/i.test(url)) {
    return <span className="block max-w-40 truncate text-xs text-zinc-400" title={url}>{url}</span>;
  }
  return (
    <a
      href={url}
      target="_blank"
      rel="noopener noreferrer"
      title={url}
      aria-label={label}
      className="inline-flex items-center gap-1.5 h-7 px-2.5 rounded-md border border-white/10 bg-zinc-800 hover:bg-zinc-700 text-xs font-medium text-zinc-200 hover:text-white whitespace-nowrap transition-colors"
    >
      <Icon className="w-3.5 h-3.5 shrink-0" />
      Open
      <ExternalLink className="w-3 h-3 text-zinc-400 shrink-0" />
    </a>
  );
}

export default function SessionsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const studentIdQuery = searchParams.get('student_id');

  const [sessions, setSessions] = useState([]);
  const [students, setStudents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  
  // Filtering & Search states
  const [searchTerm, setSearchTerm] = useState('');
  const [activeTab, setActiveTab] = useState('scheduled'); // 'scheduled' | 'attended' | 'cancelled'
  const [selectedStudentId, setSelectedStudentId] = useState(studentIdQuery || '');

  // User role context
  const [userRole, setUserRole] = useState('ADMIN');
  const [currentUser, setCurrentUser] = useState(null);

  // Modals active state
  const [modalType, setModalType] = useState(null); // 'attend' | 'reschedule' | 'links' | 'cancel'
  const [activeSession, setActiveSession] = useState(null);

  const [saving, setSaving] = useState(false);
  const [modalError, setModalError] = useState('');

  // "New Session" drawer (Hub parity): its form state lives in the sheet.
  const [createOpen, setCreateOpen] = useState(false);

  // Form states for rescheduling
  const [rescheduleTime, setRescheduleTime] = useState('');
  const [rescheduleDuration, setRescheduleDuration] = useState(1.0);

  // Form states for updating resources
  const [recLink, setRecLink] = useState('');
  const [notesLink, setNotesLink] = useState('');
  const [hwLink, setHwLink] = useState('');

  // Form states for cancelling
  const [cancelReason, setCancelReason] = useState('');
  const [needMakeup, setNeedMakeup] = useState(false);
  const [makeupTime, setMakeupTime] = useState('');
  const [makeupDuration, setMakeupDuration] = useState(1.0);

  useEffect(() => {
    fetchUserInfo();
    fetchStudents();
    fetchSessions();
  }, []);

  useEffect(() => {
    if (studentIdQuery) {
      setSelectedStudentId(studentIdQuery);
    }
  }, [studentIdQuery]);

  const fetchUserInfo = async () => {
    try {
      const res = await api.get('/api/auth/me/');
      setUserRole(res.data.user?.role || 'ADMIN');
      setCurrentUser(res.data.user);
    } catch (err) {
      console.error('Failed to load user info', err);
    }
  };

  const fetchStudents = async () => {
    try {
      const res = await api.get('/api/students/');
      setStudents(res.data);
    } catch (err) {
      console.error('Failed to load students', err);
    }
  };

  const fetchSessions = async () => {
    setLoading(true);
    setError('');
    try {
      const res = await api.get('/api/sessions/');
      setSessions(res.data.sessions || []);
    } catch (err) {
      setError(err.response?.data?.error || 'Failed to load sessions.');
    } finally {
      setLoading(false);
    }
  };

  const openModal = (type, session = null) => {
    setModalType(type);
    setActiveSession(session);
    setModalError('');
    setSaving(false);

    if (type === 'attend' && session) {
      setRecLink(session.recording_link || '');
      setNotesLink(session.notes_link || '');
      setHwLink(session.homework_link || '');
    } else if (type === 'reschedule' && session) {
      // Local time formatting for datetime-local input
      const localTime = new Date(session.start_time);
      const tzOffset = localTime.getTimezoneOffset() * 60000; // offset in milliseconds
      const localISOTime = new Date(localTime.getTime() - tzOffset).toISOString().slice(0, 16);
      
      setRescheduleTime(localISOTime);
      
      const durationHours = (new Date(session.end_time) - new Date(session.start_time)) / 3600000;
      setRescheduleDuration(durationHours);
    } else if (type === 'links' && session) {
      setRecLink(session.recording_link || '');
      setNotesLink(session.notes_link || '');
      setHwLink(session.homework_link || '');
    } else if (type === 'cancel' && session) {
      setCancelReason('');
      setNeedMakeup(false);
      setMakeupTime('');
      setMakeupDuration(1.0);
    }
  };

  const closeModal = () => {
    setModalType(null);
    setActiveSession(null);
    setModalError('');
  };

  const handleReschedule = async (e) => {
    e.preventDefault();
    setSaving(true);
    setModalError('');

    const startUtc = new Date(rescheduleTime).toISOString();
    try {
      await api.put('/api/sessions/', {
        id: activeSession.id,
        start_time: startUtc,
        duration_hours: Number(rescheduleDuration)
      });
      fetchSessions();
      closeModal();
    } catch (err) {
      setModalError(err.response?.data?.error || 'Failed to reschedule session.');
    } finally {
      setSaving(false);
    }
  };

  const handleSaveLinks = async (e) => {
    e.preventDefault();
    setSaving(true);
    setModalError('');

    try {
      await api.put('/api/sessions/', {
        id: activeSession.id,
        recording_link: recLink.trim() || null,
        notes_link: notesLink.trim() || null,
        homework_link: hwLink.trim() || null
      });
      fetchSessions();
      closeModal();
    } catch (err) {
      setModalError(err.response?.data?.error || 'Failed to save resource links.');
    } finally {
      setSaving(false);
    }
  };

  const handleCancelSession = async (e) => {
    e.preventDefault();
    setSaving(true);
    setModalError('');

    const isPartOfSeries = activeSession.series_id && activeSession.class_number !== null;
    
    // Scenario A: Series cancellation (has Shift/makeup)
    if (isPartOfSeries && needMakeup) {
      if (!makeupTime) {
        setModalError('Please select a make-up class start time.');
        setSaving(false);
        return;
      }
      try {
        await api.post('/api/sessions/cancel/', {
          session_id: activeSession.id,
          cancellation_reason: cancelReason.trim(),
          new_last_start_time: new Date(makeupTime).toISOString(),
          new_last_duration_hours: Number(makeupDuration)
        });
        fetchSessions();
        closeModal();
      } catch (err) {
        setModalError(err.response?.data?.error || 'Failed to cancel and shift series.');
      } finally {
        setSaving(false);
      }
    } else {
      // Scenario B: Simple cancellation
      try {
        await api.put('/api/sessions/', {
          id: activeSession.id,
          status: 'CANCELLED',
          cancellation_reason: cancelReason.trim()
        });
        fetchSessions();
        closeModal();
      } catch (err) {
        setModalError(err.response?.data?.error || 'Failed to cancel session.');
      } finally {
        setSaving(false);
      }
    }
  };

  const handleMarkAttended = async (e) => {
    e.preventDefault();

    // Match the staff flow: recording, notes, and homework are captured and
    // required at the moment a class is marked attended.
    const links = [recLink, notesLink, hwLink].map(l => l.trim());
    if (links.some(l => !isHttpsUrl(l))) {
      setModalError('All three links are required and must be valid https:// URLs.');
      return;
    }

    setSaving(true);
    setModalError('');

    try {
      await api.put('/api/sessions/', {
        id: activeSession.id,
        status: 'ATTENDED',
        recording_link: links[0],
        notes_link: links[1],
        homework_link: links[2]
      });
      fetchSessions();
      closeModal();
    } catch (err) {
      setModalError(err.response?.data?.error || 'Failed to mark session attended.');
    } finally {
      setSaving(false);
    }
  };

  const clearStudentFilter = () => {
    setSelectedStudentId('');
    setSearchParams({});
  };

  // Filter sessions
  const filteredSessions = sessions.filter(session => {
    const studentMatch = selectedStudentId ? (session.student_id === selectedStudentId || session.student?.id === selectedStudentId) : true;
    const tabMatch = session.status?.toLowerCase() === activeTab;
    
    const studentName = session.students?.full_name || session.student_profile?.full_name || session.student?.full_name || '';
    const studentCode = session.students?.student_code || session.student_profile?.student_code || session.student?.student_code || '';
    const textMatch = searchTerm.trim() === '' || 
      session.title.toLowerCase().includes(searchTerm.toLowerCase()) ||
      studentName.toLowerCase().includes(searchTerm.toLowerCase()) ||
      studentCode.toLowerCase().includes(searchTerm.toLowerCase());
      
    return studentMatch && tabMatch && textMatch;
  });

  const getStudentName = (id) => {
    const s = students.find(x => x.id === id);
    return s ? s.full_name : 'Unknown Student';
  };

  // Drawer inputs: the student behind the filter and their live quota usage.
  // Credits used mirrors the API's calculate_credits_used (hours of every
  // non-cancelled session) over the same list the table renders.
  const selectedStudent = students.find(s => s.id === selectedStudentId) || null;
  const creditsUsed = selectedStudent
    ? sessions
        .filter(s => s.student_id === selectedStudent.id && s.status?.toLowerCase() !== 'cancelled')
        .reduce((sum, s) => sum + Math.max(0, (new Date(s.end_time) - new Date(s.start_time)) / 3600000), 0)
    : 0;

  return (
    <div className="flex flex-col gap-6 w-full max-w-full box-border">
      
      {/* Banner when filtering by student */}
      {selectedStudentId && (
        <div className="bg-zinc-100 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-xl px-4 py-3 flex items-center justify-between">
          <div className="flex items-center gap-2 text-sm text-zinc-700 dark:text-zinc-300">
            <span className="font-semibold text-zinc-900 dark:text-white">Filtering:</span>
            <span>Sessions for {getStudentName(selectedStudentId)}</span>
          </div>
          <button 
            onClick={clearStudentFilter}
            className="text-xs text-zinc-400 hover:text-zinc-600 dark:hover:text-white underline cursor-pointer"
          >
            Clear Filter
          </button>
        </div>
      )}

      {/* Header and filters */}
      <div className="flex flex-col sm:flex-row gap-4 items-start sm:items-center justify-between">
        <div className="flex flex-col sm:flex-row gap-3 w-full sm:w-auto">
          {/* Search bar */}
          <div className="relative flex-1 sm:w-80">
            <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-zinc-500" />
            <input
              type="text"
              placeholder="Search title, student or ID..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="w-full pl-10 pr-4 h-10 bg-[#111] border border-[rgba(255,255,255,0.08)] rounded-xl text-sm text-white placeholder-zinc-500 focus:outline-none focus:ring-1 focus:ring-zinc-600 transition-all"
            />
          </div>

          {/* Student Filter dropdown */}
          <select
            value={selectedStudentId}
            onChange={(e) => {
              setSelectedStudentId(e.target.value);
              if (e.target.value) {
                setSearchParams({ student_id: e.target.value });
              } else {
                setSearchParams({});
              }
            }}
            className="h-10 px-3 bg-white dark:bg-[#111] border border-zinc-200 dark:border-[rgba(255,255,255,0.08)] rounded-xl text-sm text-zinc-900 dark:text-zinc-300 focus:outline-none focus:ring-1 focus:ring-zinc-400 dark:focus:ring-zinc-600"
          >
            <option value="">All Students</option>
            {students.map(s => (
              <option key={s.id} value={s.id}>
                {s.full_name} ({s.student_code})
              </option>
            ))}
          </select>
        </div>

        {selectedStudentId && userRole !== 'TUTOR' && (
          <button 
            onClick={() => setCreateOpen(true)}
            className="h-10 px-4 bg-white hover:bg-zinc-200 text-zinc-950 rounded-xl text-sm font-semibold shadow-sm transition-all flex items-center gap-2 self-stretch sm:self-auto shrink-0 justify-center cursor-pointer"
          >
            <Plus className="w-4 h-4" />
            New Session
          </button>
        )}
      </div>

      {error && (
        <div className="bg-red-950/40 text-red-400 text-xs p-3 rounded-lg border border-red-900/50">
          {error}
        </div>
      )}

      {/* Tabs */}
      <div className="flex border-b border-zinc-200 dark:border-[rgba(255,255,255,0.08)] gap-6">
        {['scheduled', 'attended', 'cancelled'].map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`pb-3 text-sm font-medium transition-colors relative capitalize cursor-pointer ${
              activeTab === tab 
                ? 'text-zinc-900 dark:text-white border-b-2 border-zinc-900 dark:border-white' 
                : 'text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-300'
            }`}
          >
            {tab}
          </button>
        ))}
      </div>

      {/* Sessions Table */}
      <div className="border border-[rgba(255,255,255,0.08)] bg-[#0a0a0a] rounded-xl shadow-xl overflow-x-auto w-full">
          {loading ? (
            <div className="flex items-center justify-center py-20">
              <Loader2 className="w-8 h-8 animate-spin text-white" />
            </div>
          ) : filteredSessions.length === 0 ? (
            <div className="py-16 text-center">
              <Calendar className="w-8 h-8 mx-auto text-zinc-600 mb-3" />
              <p className="text-zinc-500 text-sm">No sessions found in this tab.</p>
            </div>
          ) : (
            <table className="w-full text-left border-collapse text-sm">
              <thead>
                <tr className="border-b border-[rgba(255,255,255,0.08)] bg-[#0f0f0f]">
                  <th className="h-12 px-4 font-semibold text-xs text-zinc-400 align-middle">Session Title</th>
                  <th className="h-12 px-4 font-semibold text-xs text-zinc-400 align-middle">Date</th>
                  <th className="h-12 px-4 font-semibold text-xs text-zinc-400 align-middle">Time</th>
                  <th className="h-12 px-4 font-semibold text-xs text-zinc-400 align-middle">Status</th>
                  <th className="h-12 px-4 font-semibold text-xs text-zinc-400 align-middle">Student</th>
                  <th className="h-12 px-4 font-semibold text-xs text-zinc-400 align-middle">Tutor</th>
                  <th className="h-12 px-4 font-semibold text-xs text-zinc-400 align-middle">Student's Mentor</th>
                  <th className="h-12 px-4 font-semibold text-xs text-zinc-400 align-middle">Meeting</th>
                  <th className="h-12 px-4 font-semibold text-xs text-zinc-400 align-middle">Recording</th>
                  <th className="h-12 px-4 font-semibold text-xs text-zinc-400 align-middle">Notes</th>
                  <th className="h-12 px-4 font-semibold text-xs text-zinc-400 align-middle">Homework</th>
                  <th className="h-12 px-4 font-semibold text-xs text-zinc-400 align-middle">Rating</th>
                  <th className="h-12 px-4 w-10"></th>
                </tr>
              </thead>
              <tbody>
                {filteredSessions.map((session) => {
                  const sName = session.students?.full_name || session.student_profile?.full_name || session.student?.full_name || '—';
                  const sCode = session.students?.student_code || session.student_profile?.student_code || session.student?.student_code || '';
                  const tName = session.tutor_profile?.full_name || session.tutor_profile?.email || '—';
                  const mName = session.students?.mentor_profile?.full_name || session.students?.mentor_profile?.email || '—';
                  // The student's own Meet room (students.meet_link), nested by the
                  // Sessions API. Only a real https URL gets a Join button.
                  const meetLink = (session.students?.meet_link || '').trim();
                  
                  const start = new Date(session.start_time);
                  const end = new Date(session.end_time);
                  const dateStr = DATE_FORMAT.format(start);
                  const timeStr = `${TIME_FORMAT.format(start)} - ${TIME_FORMAT.format(end)}`;

                  return (
                    <tr 
                      key={session.id} 
                      className="hover:bg-[rgba(255,255,255,0.02)] border-b border-[rgba(255,255,255,0.08)] h-[54px] transition-colors"
                    >
                      <td className="py-2 px-4 align-middle">
                        <div className="flex flex-col gap-0.5">
                          <span className="font-semibold text-white text-sm">{session.title}</span>
                          {session.series_id && (
                            <span className="text-[10px] text-zinc-500 font-mono">
                              Series Class #{session.class_number}
                            </span>
                          )}
                        </div>
                      </td>
                      <td className="py-2 px-4 text-sm text-zinc-300 align-middle whitespace-nowrap">{dateStr}</td>
                      <td className="py-2 px-4 text-sm text-zinc-300 align-middle whitespace-nowrap">{timeStr}</td>
                      <td className="py-2 px-4 align-middle">
                        <StatusBadge status={session.status} reason={session.cancellation_reason} />
                      </td>
                      <td className="py-2 px-4 align-middle">
                        <div className="flex flex-col gap-0.5">
                          <span className="font-medium text-white text-sm">{sName}</span>
                          <span className="text-xs text-[#a1a1aa] font-mono">{sCode}</span>
                        </div>
                      </td>
                      <td className="py-2 px-4 text-sm text-[#e4e4e7] align-middle">{tName}</td>
                      <td className="py-2 px-4 text-sm text-[#e4e4e7] align-middle">{mName}</td>
                      <td className="py-2 px-4 align-middle">
                        {isHttpsUrl(meetLink) ? (
                          <a
                            href={meetLink}
                            target="_blank"
                            rel="noopener noreferrer"
                            title={meetLink}
                            className="inline-flex items-center gap-1.5 h-7 px-2.5 rounded-md border border-white/10 bg-zinc-800 hover:bg-zinc-700 text-xs font-medium text-zinc-200 hover:text-white whitespace-nowrap transition-colors"
                          >
                            <Video className="w-3.5 h-3.5 shrink-0" />
                            Join Meet
                            <ExternalLink className="w-3 h-3 text-zinc-400 shrink-0" />
                          </a>
                        ) : (
                          <span className="text-xs text-zinc-500 italic whitespace-nowrap">No meet link</span>
                        )}
                      </td>
                      <td className="py-2 px-4 align-middle">
                        <ResourceLink href={session.recording_link} icon={Video} label="Open recording" />
                      </td>
                      <td className="py-2 px-4 align-middle">
                        <ResourceLink href={session.notes_link} icon={FileText} label="Open notes" />
                      </td>
                      <td className="py-2 px-4 align-middle">
                        <ResourceLink href={session.homework_link} icon={BookOpen} label="Open homework" />
                      </td>
                      <td className="py-2 px-4 text-sm align-middle whitespace-nowrap">
                        {session.rating != null ? (
                          <span className="text-zinc-300">{session.rating}/5</span>
                        ) : (
                          <span className="text-zinc-500">—</span>
                        )}
                      </td>

                      <td className="py-2 px-4 align-middle text-right sticky right-0 bg-[#0a0a0a] group-hover:bg-[#111] border-l border-[rgba(255,255,255,0.08)] transition-colors z-10">
                        {userRole !== 'TUTOR' && (
                          <StaffActionsDropdown
                            items={[
                              ...(activeTab === 'scheduled' ? [
                                { label: 'Mark Attended', onClick: () => openModal('attend', session) },
                                { label: 'Reschedule', onClick: () => openModal('reschedule', session) },
                              ] : []),
                              { label: 'Edit Resource Links', onClick: () => openModal('links', session) },
                              ...(activeTab === 'scheduled' ? [
                                { label: 'Cancel Session', onClick: () => openModal('cancel', session), danger: true },
                              ] : []),
                            ]}
                          />
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
      </div>

      {/* Modals & Sheets Overlay */}
      {modalType && (
        <div className="fixed inset-0 bg-black/45 flex items-center justify-center z-50 p-4">
          
          {/* Mark Attended Modal — captures required resource links */}
          {modalType === 'attend' && (
            <div className="w-full max-w-md bg-[#1c1c1c] border border-white/10 rounded-2xl p-6 shadow-2xl relative">
              <h3 className="text-base font-semibold text-white m-0">Mark Session Attended</h3>
              <p className="text-xs text-zinc-400 mt-1 mb-6">{activeSession?.title}</p>

              <form onSubmit={handleMarkAttended} className="space-y-4">
                {modalError && <p className="text-xs text-red-400 bg-red-950/40 p-2 rounded border border-red-900/50 m-0">{modalError}</p>}

                <p className="text-[11px] text-zinc-500 m-0">All three links are required to mark this class attended.</p>

                <div className="space-y-1.5">
                  <label className="block text-xs font-bold text-zinc-400 uppercase tracking-widest">Class Recording Link</label>
                  <input
                    type="url"
                    placeholder="https://drive.google.com/..."
                    value={recLink}
                    onChange={(e) => setRecLink(e.target.value)}
                    className="w-full px-3 py-2 bg-white/[0.04] border border-white/10 rounded-lg text-sm text-white placeholder-zinc-600 focus:outline-none focus:ring-2 focus:ring-white/20"
                    required
                  />
                </div>

                <div className="space-y-1.5">
                  <label className="block text-xs font-bold text-zinc-400 uppercase tracking-widest">Class Notes Link</label>
                  <input
                    type="url"
                    placeholder="https://docs.google.com/..."
                    value={notesLink}
                    onChange={(e) => setNotesLink(e.target.value)}
                    className="w-full px-3 py-2 bg-white/[0.04] border border-white/10 rounded-lg text-sm text-white placeholder-zinc-600 focus:outline-none focus:ring-2 focus:ring-white/20"
                    required
                  />
                </div>

                <div className="space-y-1.5">
                  <label className="block text-xs font-bold text-zinc-400 uppercase tracking-widest">Homework Assignment Link</label>
                  <input
                    type="url"
                    placeholder="https://classroom.google.com/..."
                    value={hwLink}
                    onChange={(e) => setHwLink(e.target.value)}
                    className="w-full px-3 py-2 bg-white/[0.04] border border-white/10 rounded-lg text-sm text-white placeholder-zinc-600 focus:outline-none focus:ring-2 focus:ring-white/20"
                    required
                  />
                </div>

                <div className="flex justify-end gap-3 pt-2">
                  <button
                    type="button"
                    onClick={closeModal}
                    className="px-4 py-2 text-xs font-semibold text-zinc-400 hover:text-white border border-white/10 rounded-lg hover:bg-white/10 transition-all"
                    disabled={saving}
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    className="px-4 py-2 bg-white hover:bg-zinc-200 text-black text-xs font-semibold rounded-lg shadow-md transition-all flex items-center gap-1.5"
                    disabled={saving}
                  >
                    {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Check className="w-3.5 h-3.5" />}
                    Mark Attended
                  </button>
                </div>
              </form>
            </div>
          )}

          {/* 2. Reschedule Modal */}
          {modalType === 'reschedule' && (
            <div className="w-full max-w-sm bg-[#1c1c1c] border border-white/10 rounded-2xl p-6 shadow-2xl relative">
              <h3 className="text-base font-semibold text-white m-0">Reschedule Session</h3>
              <p className="text-xs text-zinc-400 mt-1 mb-6">{activeSession?.title}</p>

              <form onSubmit={handleReschedule} className="space-y-4">
                {modalError && <p className="text-xs text-red-400 bg-red-950/40 p-2 rounded border border-red-900/50 m-0">{modalError}</p>}

                <div className="space-y-1.5">
                  <label className="block text-xs font-bold text-zinc-400 uppercase tracking-widest">New Date & Time</label>
                  <input
                    type="datetime-local"
                    value={rescheduleTime}
                    onChange={(e) => setRescheduleTime(e.target.value)}
                    className="w-full px-3 py-2 bg-white/[0.04] border border-white/10 rounded-lg text-sm text-white focus:outline-none focus:ring-2 focus:ring-white/20"
                    required
                  />
                </div>

                <div className="space-y-1.5">
                  <label className="block text-xs font-bold text-zinc-400 uppercase tracking-widest">Duration</label>
                  <select
                    value={rescheduleDuration}
                    onChange={(e) => setRescheduleDuration(Number(e.target.value))}
                    className="w-full px-3 py-2 bg-white/[0.04] border border-white/10 rounded-lg text-sm text-white focus:outline-none focus:ring-2 focus:ring-white/20"
                  >
                    {ALLOWED_DURATIONS.map(d => (
                      <option key={d.value} value={d.value}>{d.label}</option>
                    ))}
                  </select>
                </div>

                <div className="flex justify-end gap-3 pt-2">
                  <button
                    type="button"
                    onClick={closeModal}
                    className="px-4 py-2 text-xs font-semibold text-zinc-400 hover:text-white border border-white/10 rounded-lg hover:bg-white/10 transition-all"
                    disabled={saving}
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    className="px-4 py-2 bg-white hover:bg-zinc-200 text-black text-xs font-semibold rounded-lg shadow-md transition-all flex items-center gap-1.5"
                    disabled={saving}
                  >
                    {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : null}
                    Reschedule
                  </button>
                </div>
              </form>
            </div>
          )}

          {/* 3. Resource Links Modal */}
          {modalType === 'links' && (
            <div className="w-full max-w-md bg-[#1c1c1c] border border-white/10 rounded-2xl p-6 shadow-2xl relative">
              <h3 className="text-base font-semibold text-white m-0">Edit Resource Links</h3>
              <p className="text-xs text-zinc-400 mt-1 mb-6">{activeSession?.title}</p>

              <form onSubmit={handleSaveLinks} className="space-y-4">
                {modalError && <p className="text-xs text-red-400 bg-red-950/40 p-2 rounded border border-red-900/50 m-0">{modalError}</p>}

                <div className="space-y-1.5">
                  <label className="block text-xs font-bold text-zinc-400 uppercase tracking-widest">Class Recording Link</label>
                  <input
                    type="url"
                    placeholder="https://drive.google.com/..."
                    value={recLink}
                    onChange={(e) => setRecLink(e.target.value)}
                    className="w-full px-3 py-2 bg-white/[0.04] border border-white/10 rounded-lg text-sm text-white placeholder-zinc-600 focus:outline-none focus:ring-2 focus:ring-white/20"
                  />
                </div>

                <div className="space-y-1.5">
                  <label className="block text-xs font-bold text-zinc-400 uppercase tracking-widest">Class Notes Link</label>
                  <input
                    type="url"
                    placeholder="https://docs.google.com/..."
                    value={notesLink}
                    onChange={(e) => setNotesLink(e.target.value)}
                    className="w-full px-3 py-2 bg-white/[0.04] border border-white/10 rounded-lg text-sm text-white placeholder-zinc-600 focus:outline-none focus:ring-2 focus:ring-white/20"
                  />
                </div>

                <div className="space-y-1.5">
                  <label className="block text-xs font-bold text-zinc-400 uppercase tracking-widest">Homework Assignment Link</label>
                  <input
                    type="url"
                    placeholder="https://classroom.google.com/..."
                    value={hwLink}
                    onChange={(e) => setHwLink(e.target.value)}
                    className="w-full px-3 py-2 bg-white/[0.04] border border-white/10 rounded-lg text-sm text-white placeholder-zinc-600 focus:outline-none focus:ring-2 focus:ring-white/20"
                  />
                </div>

                <div className="flex justify-end gap-3 pt-2">
                  <button
                    type="button"
                    onClick={closeModal}
                    className="px-4 py-2 text-xs font-semibold text-zinc-400 hover:text-white border border-white/10 rounded-lg hover:bg-white/10 transition-all"
                    disabled={saving}
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    className="px-4 py-2 bg-white hover:bg-zinc-200 text-black text-xs font-semibold rounded-lg shadow-md transition-all flex items-center gap-1.5"
                    disabled={saving}
                  >
                    {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : null}
                    Save Links
                  </button>
                </div>
              </form>
            </div>
          )}

          {/* 4. Cancel Session Modal */}
          {modalType === 'cancel' && (
            <div className="w-full max-w-md bg-[#1c1c1c] border border-white/10 rounded-2xl p-6 shadow-2xl relative">
              <h3 className="text-base font-semibold text-white m-0">Cancel Session</h3>
              <p className="text-xs text-zinc-400 mt-1 mb-6">{activeSession?.title}</p>

              <form onSubmit={handleCancelSession} className="space-y-4">
                {modalError && <p className="text-xs text-red-400 bg-red-950/40 p-2 rounded border border-red-900/50 m-0">{modalError}</p>}

                <div className="space-y-1.5">
                  <label className="block text-xs font-bold text-zinc-400 uppercase tracking-widest">Reason for Cancellation</label>
                  <textarea
                    placeholder="e.g. Tutor unavailable, public holiday..."
                    value={cancelReason}
                    onChange={(e) => setCancelReason(e.target.value)}
                    rows={3}
                    className="w-full px-3 py-2 bg-white/[0.04] border border-white/10 rounded-lg text-sm text-white placeholder-zinc-600 focus:outline-none focus:ring-2 focus:ring-white/20 resize-none"
                    required
                  />
                </div>

                {/* Series Shift controls */}
                {activeSession.series_id && activeSession.class_number !== null && (
                  <div className="space-y-3 pt-2 border-t border-white/10">
                    <div className="flex items-center gap-2.5">
                      <input
                        id="need-makeup"
                        type="checkbox"
                        checked={needMakeup}
                        onChange={(e) => setNeedMakeup(e.target.checked)}
                        className="rounded border-zinc-700 bg-zinc-950 text-white focus:ring-white/20"
                      />
                      <label htmlFor="need-makeup" className="text-xs font-semibold text-zinc-300 cursor-pointer flex items-center gap-1.5 select-none">
                        Shift series and schedule Make-up Class
                        <AlertTriangle className="w-3.5 h-3.5 text-amber-500 shrink-0" />
                      </label>
                    </div>

                    {needMakeup && (
                      <div className="space-y-3 bg-amber-950/20 border border-amber-900/30 rounded-lg p-3">
                        <p className="text-[10px] text-amber-300 m-0">
                          This class is part of a series. Activating this option will cancel this class, automatically shift subsequent classes back by one index (renumbering their titles), and add a make-up class to the end of the series.
                        </p>
                        
                        <div className="space-y-1.5">
                          <label className="block text-[10px] font-bold text-zinc-400 uppercase tracking-widest">Make-up Class Start Time</label>
                          <input
                            type="datetime-local"
                            value={makeupTime}
                            onChange={(e) => setMakeupTime(e.target.value)}
                            className="w-full px-3 py-2 bg-white/[0.04] border border-white/10 rounded-lg text-sm text-white focus:outline-none focus:ring-2 focus:ring-white/20"
                            required={needMakeup}
                          />
                        </div>

                        <div className="space-y-1.5">
                          <label className="block text-[10px] font-bold text-zinc-400 uppercase tracking-widest">Make-up Class Duration</label>
                          <select
                            value={makeupDuration}
                            onChange={(e) => setMakeupDuration(Number(e.target.value))}
                            className="w-full px-3 py-2 bg-white/[0.04] border border-white/10 rounded-lg text-sm text-white focus:outline-none focus:ring-2 focus:ring-white/20"
                          >
                            {ALLOWED_DURATIONS.map(d => (
                              <option key={d.value} value={d.value}>{d.label}</option>
                            ))}
                          </select>
                        </div>
                      </div>
                    )}
                  </div>
                )}

                <div className="flex justify-end gap-3 pt-2">
                  <button
                    type="button"
                    onClick={closeModal}
                    className="px-4 py-2 text-xs font-semibold text-zinc-400 hover:text-white border border-white/10 rounded-lg hover:bg-white/10 transition-all"
                    disabled={saving}
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    className="px-4 py-2 bg-red-600 hover:bg-red-500 text-white text-xs font-semibold rounded-lg shadow-md transition-all flex items-center gap-1.5"
                    disabled={saving}
                  >
                    {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : null}
                    Confirm Cancel
                  </button>
                </div>
              </form>
            </div>
          )}

        </div>
      )}

      {/* New Session drawer (Hub parity). Refetch students too: saving may
          have written the student's timezone. */}
      <NewSessionSheet
        student={selectedStudent}
        creditsUsed={creditsUsed}
        open={createOpen}
        onOpenChange={setCreateOpen}
        onCreated={() => {
          fetchSessions();
          fetchStudents();
        }}
      />

    </div>
  );
}
