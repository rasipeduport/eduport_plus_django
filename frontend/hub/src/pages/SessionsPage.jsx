import { useState, useEffect } from 'react';
import { useSearchParams, Link } from 'react-router-dom';
import { 
  Loader2, Calendar, Video, FileText, 
  BookOpen, Plus, Link2, AlertTriangle, RefreshCw, Check, ExternalLink, ChevronDown, X
} from 'lucide-react';
import api from '../lib/api';
import { EXAM_VIEW, PERMISSIONS, can, canAny } from '../lib/access';
import { describeApiError } from '../lib/api-errors';
import { mentorZoneFormatter } from '../lib/timezone';
import StaffActionsDropdown from '../components/StaffActionsDropdown';
import { NewSessionSheet } from '../components/sessions/new-session-sheet';
import { RescheduleSessionDialog } from '../components/sessions/reschedule-session-dialog';
import { StartSessionButton } from '../components/sessions/start-session-button';
import { CorrectOutcomeDialog, RecordOutcomeDialog } from '../components/sessions/session-outcome-dialogs';
import {
  bookedLength,
  classState,
  hasEnded,
  isAssignedTutor,
  mayCancel,
  mayRecordOutcome,
  notesMode,
  outcomeReasonLabel,
  startOpensAt,
  startState,
} from '../lib/session-lifecycle';
import { CLASS_STATE_VARIANT, classStateLabel } from '../lib/session-status';
import { classMeetLink, classMeetMissing } from '../lib/meet-rooms';
import { SchedulingError } from '../components/sessions/scheduling-error';
import { StudentSectionTabs } from '../components/students/section-tabs';
import { HomeworkGradeSheet } from '../components/homework/homework-grade-sheet';
import { HOMEWORK_STATUS_VARIANT, homeworkBadgeLabel } from '../lib/homework-status';
import { ContentInput, contentStateFor, contentError, contentPayload, formatBytes } from '../components/sessions/content-input';
import { Badge } from '../components/ui/badge';
import { Tooltip, TooltipContent, TooltipTrigger } from '../components/ui/tooltip';
import { format } from 'date-fns';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Calendar as CalendarPicker } from '../components/ui/calendar';
import { Popover, PopoverContent, PopoverTrigger } from '../components/ui/popover';
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '../components/ui/dropdown-menu';

const ALLOWED_DURATIONS = [
  { label: '30 mins', value: 0.5 },
  { label: '1 hour', value: 1.0 },
  { label: '1.5 hours', value: 1.5 },
  { label: '2 hours', value: 2.0 }
];

const MEET_PREFIX = 'https://meet.google.com/';

// Hub-style table formats. Times stay browser-local, as this table always was.
// Staff read every session in IST (MENTOR_TIMEZONE), not the device's zone.
const DATE_FORMAT = mentorZoneFormatter({ month: 'short', day: 'numeric', year: 'numeric' });
const TIME_FORMAT = mentorZoneFormatter({ hour: 'numeric', minute: '2-digit', hour12: true });
// When a tutor started or completed a class (it may be days after the class).
const STAMP_FORMAT = mentorZoneFormatter({ month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', hour12: true });
const stamp = (iso) => STAMP_FORMAT.format(new Date(iso));
const personName = (profile) => profile?.full_name || profile?.email || 'the tutor';

// The status tabs: each lists the classes in those states (lib/session-lifecycle
// classState, the backend's class_state). Needs Action holds what an ended class
// still waits for -- its tutor's notes, or its outcome.
const TABS = [
  { id: 'upcoming', label: 'Upcoming', states: ['upcoming', 'in_progress'] },
  { id: 'needs_action', label: 'Needs Action', states: ['notes_due', 'not_started'] },
  { id: 'completed', label: 'Completed', states: ['completed'] },
  { id: 'not_conducted', label: 'No-show / Not Conducted', states: ['not_conducted'] },
  { id: 'cancelled', label: 'Cancelled', states: ['cancelled'] },
];
const TAB_IDS = TABS.map((tab) => tab.id);
const inTab = (tabId, state) => (TABS.find((tab) => tab.id === tabId)?.states || []).includes(state);

const CONTENT_LABEL = { notes: 'Notes', recording: 'Recording', homework: 'Homework' };

// Post-session content filter (attended rows only; `?content=` on the API).
const CONTENT_FILTERS = [
  { value: 'all', label: 'All' },
  { value: 'complete', label: 'Complete' },
  { value: 'missing_notes', label: 'Missing Notes' },
  { value: 'missing_recording', label: 'Missing Recording' },
  { value: 'missing_homework', label: 'Missing Homework' },
  { value: 'missing_content', label: 'Missing Content' },
];

// Whether a required post-session item is absent on an attended class. The
// API's `missing_content` is the source of truth; a payload without it falls
// back to the link itself. Never true for scheduled/cancelled rows.
const isContentMissing = (s, key) => {
  if ((s.status || '').toLowerCase() !== 'attended') return false;
  if (Array.isArray(s.missing_content)) return s.missing_content.includes(key);
  return !(s[`${key}_link`] || '').trim();
};

// The row's badge: where the class stands. A cancelled class shows its reason
// on hover, one not conducted its note; an attended class whose material is
// incomplete also gets a Content missing chip listing what it lacks.
function StatusBadge({ session, now }) {
  const state = classState(session, now);
  const badge = <Badge variant={CLASS_STATE_VARIANT[state] || 'secondary'}>{classStateLabel(state, session)}</Badge>;
  let hint = null;
  if (state === 'cancelled' && session.cancellation_reason) hint = session.cancellation_reason;
  else if (state === 'not_conducted' && session.outcome_note) hint = session.outcome_note;
  const missing = session.display_status === 'pending' ? (session.missing_content || []).map((k) => CONTENT_LABEL[k] || k) : [];
  return (
    <span className="flex flex-wrap items-center gap-1">
      {hint ? (
        <Tooltip>
          <TooltipTrigger asChild>
            <span className="cursor-help">{badge}</span>
          </TooltipTrigger>
          <TooltipContent>
            <p className="max-w-xs">{hint}</p>
          </TooltipContent>
        </Tooltip>
      ) : (
        badge
      )}
      {missing.length > 0 && (
        <Tooltip>
          <TooltipTrigger asChild>
            <span className="cursor-help">
              <Badge variant="outline">Content missing</Badge>
            </span>
          </TooltipTrigger>
          <TooltipContent>
            <p className="max-w-xs">Missing: {missing.join(', ')}</p>
          </TooltipContent>
        </Tooltip>
      )}
    </span>
  );
}

// Under the badge: who started the class (its tutor, the student's mentor or an
// administrator), that its tutor's notes are due (whenever they come in, they
// complete it), that nobody started it, who recorded its outcome, or the
// completion the tutor's own notes made (backend sessions.lifecycle).
// Staff attendance is noted too -- it records attendance, never the tutor's
// completion.
function ClassProgress({ session, now }) {
  const state = classState(session, now);
  const started = session.started_at ? `${stamp(session.started_at)} by ${personName(session.started_by_profile)}` : null;
  const staffAttended = (session.status || '').toLowerCase() === 'attended' && !session.completed_at;
  const parts = [];
  let hint = null;
  if (state === 'upcoming') {
    if (now.getTime() >= new Date(session.start_time).getTime()) parts.push('Not started yet');
  } else if (state === 'in_progress') {
    parts.push(`Started ${started}`);
  } else if (state === 'notes_due') {
    parts.push("Awaiting the tutor's notes");
    if (staffAttended) parts.push('Marked attended by staff');
    hint = `Started ${started}`;
  } else if (state === 'not_started') {
    parts.push('Nobody started this class');
    if (staffAttended) parts.push('Marked attended by staff');
    hint = "Its tutor's notes cannot complete it; its outcome can be recorded.";
  } else if (state === 'completed') {
    parts.push(`Completed by tutor · ${stamp(session.completed_at)}`);
    hint = [
      started ? `Started ${started}` : 'Not started in the Hub',
      `completed by ${personName(session.completed_by_profile)}'s notes`,
      `${bookedLength(session)} as booked`,
    ].filter(Boolean).join(' · ');
  } else if (state === 'not_conducted') {
    if (session.outcome_reason) parts.push(outcomeReasonLabel(session.outcome_reason));
    if (session.outcome_recorded_at) parts.push(`recorded ${stamp(session.outcome_recorded_at)}`);
    hint = [
      session.outcome_recorded_by_profile ? `Recorded by ${personName(session.outcome_recorded_by_profile)}` : null,
      session.outcome_corrected_at
        ? `corrected by ${personName(session.outcome_corrected_by_profile)} ${stamp(session.outcome_corrected_at)}`
        : null,
    ].filter(Boolean).join(' · ') || null;
  }
  if (parts.length === 0) return null;
  return (
    <span className="text-[11px] text-zinc-500 whitespace-nowrap" title={hint || undefined}>
      {parts.join(' · ')}
    </span>
  );
}

// Required content that an attended class still lacks. Deliberately louder
// than the "—" used for a field that simply does not apply.
function MissingBadge() {
  return (
    <Badge variant="outline" className="border-destructive/40 bg-destructive/10 text-destructive">
      <AlertTriangle />
      Missing
    </Badge>
  );
}

// A session resource (recording / notes / homework link). The Hub prints the
// URL truncated; a compact open-in-new-tab action keeps this wider table
// usable. "—" when unset (or a Missing badge when the class is attended and
// the item is required); a value that is not a web URL is shown as text.
function ResourceLink({ href, icon: Icon, label, missing = false, file = null }) {
  const url = (href || '').trim();
  if (!url) return missing ? <MissingBadge /> : <span className="text-zinc-500">—</span>;
  if (!/^https?:\/\/\S+$/i.test(url)) {
    return <span className="block max-w-40 truncate text-xs text-zinc-400" title={url}>{url}</span>;
  }
  // An uploaded file opens through the same link; the hover text names it.
  const title = file ? `${file.file_name} (${file.content_type}, ${formatBytes(file.size_bytes)})` : url;
  return (
    <a
      href={url}
      target="_blank"
      rel="noopener noreferrer"
      title={title}
      aria-label={label}
      className="inline-flex items-center gap-1.5 h-7 px-2.5 rounded-md border border-white/10 bg-zinc-800 hover:bg-zinc-700 text-xs font-medium text-zinc-200 hover:text-white whitespace-nowrap transition-colors"
    >
      <Icon className="w-3.5 h-3.5 shrink-0" />
      Open
      <ExternalLink className="w-3 h-3 text-zinc-400 shrink-0" />
    </a>
  );
}

export default function SessionsPage({ user }) {
  const [searchParams, setSearchParams] = useSearchParams();
  const studentIdQuery = searchParams.get('student_id');

  const [sessions, setSessions] = useState([]);
  const [students, setStudents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  
  // Filtering & Search states (Hub filter bar: title, date range, tutor, columns)
  const [searchTerm, setSearchTerm] = useState('');
  const [dateRange, setDateRange] = useState(undefined); // { from, to } with `to` at end of day
  const [tutorFilter, setTutorFilter] = useState([]); // tutor profile ids
  const [columnVisibility, setColumnVisibility] = useState({}); // { [columnId]: false } hides
  // One of TAB_IDS; ?tab= opens another (the dashboards link to Needs Action).
  const [activeTab, setActiveTab] = useState(() => (TAB_IDS.includes(searchParams.get('tab')) ? searchParams.get('tab') : 'upcoming'));
  // Post-session content filter (Completed tab only). The API does the
  // filtering; `contentSessions` holds its result while a filter is active.
  const [contentFilter, setContentFilter] = useState('all');
  const [contentSessions, setContentSessions] = useState(null);
  const [selectedStudentId, setSelectedStudentId] = useState(studentIdQuery || '');

  // What the caller may do follows their permissions (App.jsx, from /me);
  // the API checks the same ones.
  const canCreate = can(user, PERMISSIONS.createSession);
  const canManage = can(user, PERMISSIONS.manageSession);
  const canCancel = can(user, PERMISSIONS.cancelSession);
  const canEditNotes = can(user, PERMISSIONS.editSessionNotes);
  // Correcting or removing a recorded outcome: administrators only.
  const canCorrectOutcome = can(user, PERMISSIONS.correctSessionOutcome);
  // Whoever oversees every session (admins) can complete every post-session
  // item themselves; mentors and tutors keep their split (recording +
  // homework vs. notes).
  const isAdmin = can(user, PERMISSIONS.viewAllSessions);

  // Modals active state
  // 'attend' | 'notes' | 'reschedule' | 'links' | 'cancel' | 'outcome' | 'correct'
  const [modalType, setModalType] = useState(null);
  const [activeSession, setActiveSession] = useState(null);

  const [saving, setSaving] = useState(false);
  const [modalError, setModalError] = useState('');

  // "New Session" drawer (Hub parity): its form state lives in the sheet.
  const [createOpen, setCreateOpen] = useState(false);
  // Homework review drawer, opened from the HW Status badge on attended rows.
  const [gradeHomeworkId, setGradeHomeworkId] = useState(null);

  // Content dialog state per field: { mode: 'url' | 'file', url, file, existing }
  // (see components/sessions/content-input.jsx). Set when a dialog opens.
  const [content, setContent] = useState({ recording: null, notes: null, homework: null });
  const setFieldContent = (field) => (next) => setContent((prev) => ({ ...prev, [field]: next }));

  // Form states for cancelling
  const [cancelReason, setCancelReason] = useState('');
  const [needMakeup, setNeedMakeup] = useState(false);
  const [makeupTime, setMakeupTime] = useState('');
  const [makeupDuration, setMakeupDuration] = useState(1.0);

  // The clock the tutor's actions follow, so they open on their own: Start
  // Session 5 minutes before a class, completing notes once it ends. The
  // server checks both again by its own clock.
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), 15000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    fetchStudents();
    fetchSessions();
  }, []);

  useEffect(() => {
    if (studentIdQuery) {
      setSelectedStudentId(studentIdQuery);
    }
  }, [studentIdQuery]);

  const fetchStudents = async () => {
    try {
      const res = await api.get('/api/students/');
      setStudents(res.data);
    } catch (err) {
      console.error('Failed to load students', err);
    }
  };

  // `sessions` is always the unfiltered list: it feeds the tutor options and
  // the New Session drawer's credit maths. While a Content filter is active
  // the table instead shows the API's filtered result, refreshed together.
  const fetchSessions = async (content = contentFilter) => {
    setLoading(true);
    setError('');
    try {
      const [all, filtered] = await Promise.all([
        api.get('/api/sessions/'),
        content && content !== 'all' ? api.get('/api/sessions/', { params: { content } }) : Promise.resolve(null),
      ]);
      setSessions(all.data.sessions || []);
      setContentSessions(filtered ? filtered.data.sessions || [] : null);
    } catch (err) {
      setError(err.response?.data?.error || 'Failed to load sessions.');
    } finally {
      setLoading(false);
    }
  };

  const applyContentFilter = async (value) => {
    setContentFilter(value);
    if (value === 'all') {
      setContentSessions(null);
      return;
    }
    setLoading(true);
    setError('');
    try {
      const res = await api.get('/api/sessions/', { params: { content: value } });
      setContentSessions(res.data.sessions || []);
    } catch (err) {
      setError(err.response?.data?.error || 'Failed to load sessions.');
    } finally {
      setLoading(false);
    }
  };

  // The Content filter only means something on the Completed tab; leaving the
  // tab drops it so the other tabs always show their full lists.
  const switchTab = (tab) => {
    setActiveTab(tab);
    if (tab !== 'completed' && contentFilter !== 'all') {
      setContentFilter('all');
      setContentSessions(null);
    }
  };

  const openModal = (type, session = null) => {
    setModalType(type);
    setActiveSession(session);
    setModalError('');
    setSaving(false);

    if ((type === 'attend' || type === 'links' || type === 'notes') && session) {
      setContent({
        recording: contentStateFor(session, 'recording'),
        notes: contentStateFor(session, 'notes'),
        homework: contentStateFor(session, 'homework'),
      });
    } else if (type === 'cancel' && session) {
      setCancelReason('');
      setNeedMakeup(false);
      setMakeupTime('');
      setMakeupDuration(1.0);
    }
  };

  // What the notes dialog open now does (lib/session-lifecycle notesMode): complete the class, or save an edit.
  const dialogNotesMode = modalType === 'notes' && activeSession ? notesMode(activeSession, now) : null;
  const completingNotes = dialogNotesMode === 'complete';

  const closeModal = () => {
    setModalType(null);
    setActiveSession(null);
    setModalError('');
  };

  const errorMessage = (err, fallback) =>
    err.response?.data?.error || err.response?.data?.message || err.message || fallback;

  // Validate the given content fields, upload every chosen file (each upload
  // writes its own link server-side), and return the URL-mode fields to send
  // in one PUT. Throws an Error with a user-facing message on bad input.
  const submitContent = async (fields, { required = [] } = {}) => {
    for (const field of fields) {
      const err = contentError(content[field], { required: required.includes(field), label: CONTENT_LABEL[field] });
      if (err) throw new Error(err);
    }
    const body = {};
    for (const field of fields) {
      const payload = contentPayload(content[field]);
      if (payload.kind === 'file') {
        const form = new FormData();
        form.append('file', payload.file);
        await api.post(`/api/sessions/${activeSession.id}/files/${field}/`, form);
      } else if (payload.kind === 'url') {
        body[`${field}_link`] = payload.value;
      }
    }
    return body;
  };

  const handleSaveLinks = async (e) => {
    e.preventDefault();
    setSaving(true);
    setModalError('');

    try {
      const body = await submitContent(['recording', 'notes', 'homework']);
      if (Object.keys(body).length > 0) {
        await api.put('/api/sessions/', { id: activeSession.id, ...body });
      }
      fetchSessions();
      closeModal();
    } catch (err) {
      setModalError(errorMessage(err, 'Failed to save resource links.'));
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
        setModalError(describeApiError(err, 'Failed to cancel and shift series.'));
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

    // Attendance is recorded on its own. Each item may come now or later, as
    // a URL or an upload; the API reports the class as Pending until all
    // three exist. A mentor supplies the recording and homework and the
    // tutor the notes; an admin can supply all three here.
    setSaving(true);
    setModalError('');

    try {
      const body = await submitContent(isAdmin ? ['recording', 'notes', 'homework'] : ['recording', 'homework']);
      await api.put('/api/sessions/', { id: activeSession.id, status: 'ATTENDED', ...body });
      fetchSessions();
      closeModal();
    } catch (err) {
      setModalError(errorMessage(err, 'Failed to mark session attended.'));
    } finally {
      setSaving(false);
    }
  };

  // Tutor's post-session responsibility: the notes link, and only that. The
  // API refuses anything else from a tutor. For a class someone started that
  // has ended, submitting the notes completes it, however long after the class
  // -- a new upload does so itself; notes kept as they were are sent again so
  // the submission still counts.
  const handleSaveNotes = async (e) => {
    e.preventDefault();
    setSaving(true);
    setModalError('');

    try {
      const kept = contentPayload(content.notes).kind === 'keep';
      const body = await submitContent(['notes'], { required: ['notes'] });
      if ('notes_link' in body) {
        await api.put('/api/sessions/', { id: activeSession.id, notes_link: body.notes_link });
      } else if (kept && notesMode(activeSession, new Date()) === 'complete') {
        await api.put('/api/sessions/', { id: activeSession.id, notes_link: activeSession.notes_link });
      }
      fetchSessions();
      closeModal();
    } catch (err) {
      setModalError(errorMessage(err, 'Failed to save the notes.'));
    } finally {
      setSaving(false);
    }
  };

  // The tutor's one row action. Their notes complete the class, so they wait
  // for someone's Start and its scheduled end -- then they complete it whenever
  // they come in; once completed, they are edits. None on a class cancelled or
  // recorded as not conducted.
  const tutorNotesItem = (session) => {
    const mode = notesMode(session, now);
    const open = () => openModal('notes', session);
    if (mode === 'complete') return { label: 'Submit Notes', onClick: open };
    if (mode === 'save') return { label: 'Update Notes', onClick: open };
    if (mode === 'wait') {
      return {
        label: 'Submit Notes',
        disabled: true,
        title: `Opens when the class ends at ${TIME_FORMAT.format(new Date(session.end_time))}`,
        onClick: () => {},
      };
    }
    if (mode === 'not_started') {
      return {
        label: 'Submit Notes',
        disabled: true,
        title: hasEnded(session, now)
          ? 'Nobody started this class, so it takes no notes'
          : 'Opens once the class has been started and has ended',
        onClick: () => {},
      };
    }
    return null;
  };

  // What an administrator or the student's mentor may do with a row. Mark
  // Attended (operational only) once the class has ended; Reschedule while
  // nobody started it; Record Outcome once it ended without its tutor's
  // completion; Correct Outcome (administrators) once one is recorded; Cancel
  // until the scheduled end. The API checks every one again.
  const staffItems = (session) => {
    const status = (session.status || '').toLowerCase();
    const state = classState(session, now);
    return [
      ...(status === 'scheduled' ? [
        {
          label: 'Mark Attended',
          onClick: () => openModal('attend', session),
          disabled: !hasEnded(session, now),
          title: hasEnded(session, now) ? undefined : 'Available once the class has ended',
        },
        ...(session.started_at ? [] : [{ label: 'Reschedule', onClick: () => openModal('reschedule', session) }]),
      ] : []),
      ...(mayRecordOutcome(session, now)
        ? [{ label: 'Record Outcome', onClick: () => openModal('outcome', session) }]
        : []),
      ...(state === 'not_conducted' && canCorrectOutcome
        ? [{ label: 'Correct Outcome', onClick: () => openModal('correct', session) }]
        : []),
      ...(state !== 'not_conducted' ? [{ label: 'Edit Resource Links', onClick: () => openModal('links', session) }] : []),
      ...(canCancel && mayCancel(session, now)
        ? [{ label: 'Cancel Session', onClick: () => openModal('cancel', session), danger: true }]
        : []),
    ];
  };

  const clearStudentFilter = () => {
    setSelectedStudentId('');
    setSearchParams({});
  };

  // Filter sessions. With a Content filter active the rows come from the API's
  // filtered result (attended only); the title/date/tutor filters still apply.
  const tableSource = contentFilter !== 'all' && contentSessions ? contentSessions : sessions;
  const studentRow = (session) =>
    selectedStudentId ? (session.student_id === selectedStudentId || session.student?.id === selectedStudentId) : true;
  const filteredSessions = tableSource.filter(session => {
    const studentMatch = studentRow(session);
    const tabMatch = inTab(activeTab, classState(session, now));
    // The search box matches the session title or the student's name.
    const term = searchTerm.trim().toLowerCase();
    const studentName = session.students?.full_name || session.student_profile?.full_name || session.student?.full_name || '';
    const titleMatch =
      !term ||
      (session.title || '').toLowerCase().includes(term) ||
      studentName.toLowerCase().includes(term);
    const startMs = new Date(session.start_time).getTime();
    const dateMatch =
      !dateRange ||
      ((!dateRange.from || startMs >= dateRange.from.getTime()) && (!dateRange.to || startMs <= dateRange.to.getTime()));
    const tutorId = session.tutor_profile?.id ?? session.tutor ?? null;
    const tutorMatch = tutorFilter.length === 0 || (tutorId != null && tutorFilter.includes(tutorId));
    return studentMatch && tabMatch && titleMatch && dateMatch && tutorMatch;
  });

  // Tutor filter choices come from the rows on screen, like the Hub. A tutor
  // only ever sees their own students' sessions, so the control is hidden
  // unless the caller may view all sessions or their mentored students'.
  const tutorOptions = !canAny(user, [PERMISSIONS.viewAllSessions, PERMISSIONS.viewMentoredSessions])
    ? []
    : Array.from(
        new Map(
          sessions
            .filter((s) => s.tutor_profile)
            .map((s) => [s.tutor_profile.id, { id: s.tutor_profile.id, name: s.tutor_profile.full_name || s.tutor_profile.email }])
        ).values()
      ).sort((a, b) => a.name.localeCompare(b.name));

  const hasActiveFilters =
    Boolean(searchTerm) || Boolean(dateRange?.from || dateRange?.to) || tutorFilter.length > 0 || contentFilter !== 'all';

  const clearFilters = () => {
    setSearchTerm('');
    setDateRange(undefined);
    setTutorFilter([]);
    setContentFilter('all');
    setContentSessions(null);
  };

  const contentFilterLabel = CONTENT_FILTERS.find((o) => o.value === contentFilter)?.label;

  const dateLabel = (() => {
    if (!dateRange?.from && !dateRange?.to) return 'Date range';
    if (dateRange?.from && dateRange?.to) return `${format(dateRange.from, 'MMM d')} - ${format(dateRange.to, 'MMM d, yyyy')}`;
    if (dateRange?.from) return `From ${format(dateRange.from, 'MMM d, yyyy')}`;
    return `Until ${format(dateRange.to, 'MMM d, yyyy')}`;
  })();

  // The picker returns midnight for `to`; extend it to the end of that day so a
  // session that afternoon still falls inside the range.
  const applyDateRange = (range) => {
    if (!range || (!range.from && !range.to)) {
      setDateRange(undefined);
      return;
    }
    const to = range.to
      ? new Date(range.to.getFullYear(), range.to.getMonth(), range.to.getDate(), 23, 59, 59, 999)
      : undefined;
    setDateRange({ from: range.from, to });
  };

  const toggleTutor = (id, checked) => {
    setTutorFilter((prev) => (checked ? Array.from(new Set([...prev, id])) : prev.filter((v) => v !== id)));
  };

  // Table columns in Hub order. Every one but Actions can be hidden from the
  // Columns menu, where `id` doubles as the label (underscores become spaces).
  // `tabs` limits a column to those tabs: recording, notes and homework only
  // exist once a class has ended (Needs Action shows what is in so far), the
  // homework status and rating once it is completed, and the Meet room is
  // only worth joining for a class that has not happened yet.
  const columns = [
    {
      id: 'title',
      label: 'Session Title',
      cell: (s) => (
        <div className="flex flex-col gap-0.5">
          <span className="font-semibold text-white text-sm">{s.title}</span>
          {s.series_id && (
            <span className="text-[10px] text-zinc-500 font-mono">
              Series Class #{s.class_number}
            </span>
          )}
        </div>
      ),
    },
    { id: 'date', label: 'Date', cellClass: 'text-sm text-zinc-300 whitespace-nowrap', cell: (s) => DATE_FORMAT.format(new Date(s.start_time)) },
    {
      id: 'time',
      label: 'Time',
      cellClass: 'text-sm text-zinc-300 whitespace-nowrap',
      cell: (s) => `${TIME_FORMAT.format(new Date(s.start_time))} - ${TIME_FORMAT.format(new Date(s.end_time))}`,
    },
    {
      id: 'status',
      label: 'Status',
      cell: (s) => (
        <div className="flex flex-col items-start gap-1">
          <StatusBadge session={s} now={now} />
          <ClassProgress session={s} now={now} />
        </div>
      ),
    },
    {
      id: 'student',
      label: 'Student',
      cell: (s) => (
        <div className="flex flex-col gap-0.5">
          <span className="font-medium text-white text-sm">
            {s.students?.full_name || s.student_profile?.full_name || s.student?.full_name || '—'}
          </span>
          <span className="text-xs text-[#a1a1aa] font-mono">
            {s.students?.student_code || s.student_profile?.student_code || s.student?.student_code || ''}
          </span>
        </div>
      ),
    },
    { id: 'tutor', label: 'Tutor', cellClass: 'text-sm text-[#e4e4e7]', cell: (s) => s.tutor_profile?.full_name || s.tutor_profile?.email || '—' },
    {
      id: 'student_mentor',
      label: "Student's Mentor",
      cellClass: 'text-sm text-[#e4e4e7]',
      cell: (s) => s.students?.mentor_profile?.full_name || s.students?.mentor_profile?.email || '—',
    },
    {
      id: 'meeting',
      label: 'Meeting',
      tabs: ['upcoming', 'cancelled'],
      // The class's room: the Meet link of the tutor it is assigned to
      // (`tutor_meet_link`), never the student's; without one the cell says
      // why. Only a real https URL gets a Join button. From 5
      // minutes before a class until it ends, whoever may start it -- its
      // tutor, the student's mentor or an administrator -- gets Start Session
      // instead (backend sessions.lifecycle); once started, Join Meet. The
      // tutor also sees when Start opens; staff keep Join Meet otherwise.
      cell: (s) => {
        const ownClass = isAssignedTutor(s, user);
        const start = ownClass || canManage ? startState(s, now) : null;
        if (start === 'ready') {
          return (
            <StartSessionButton session={s} asTutor={ownClass} onStarted={() => fetchSessions()} onRefresh={() => fetchSessions()} />
          );
        }
        if (ownClass && start === 'upcoming') {
          return (
            <span className="text-xs text-zinc-500 whitespace-nowrap">
              Start opens {TIME_FORMAT.format(startOpensAt(s))}
            </span>
          );
        }
        if (ownClass && start === 'closed') {
          return <span className="text-xs text-zinc-500 italic whitespace-nowrap">Class ended</span>;
        }
        const meetLink = classMeetLink(s);
        return meetLink ? (
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
          <span className="text-xs text-zinc-500 italic whitespace-nowrap">{classMeetMissing(s)}</span>
        );
      },
    },
    // Attended-only columns. Each required item that is still absent gets the
    // Missing badge; rating is optional and stays "—" when unset.
    { id: 'recording', label: 'Recording', tabs: ['needs_action', 'completed'], cell: (s) => <ResourceLink href={s.recording_link} icon={Video} label="Open recording" missing={isContentMissing(s, 'recording')} file={s.content_files?.recording} /> },
    { id: 'notes', label: 'Notes', tabs: ['needs_action', 'completed'], cell: (s) => <ResourceLink href={s.notes_link} icon={FileText} label="Open notes" missing={isContentMissing(s, 'notes')} file={s.content_files?.notes} /> },
    { id: 'homework', label: 'Homework', tabs: ['needs_action', 'completed'], cell: (s) => <ResourceLink href={s.homework_link} icon={BookOpen} label="Open homework" missing={isContentMissing(s, 'homework')} file={s.content_files?.homework} /> },
    // The homework lifecycle behind the link (assigned -> submitted -> scored);
    // the badge opens the same review sheet as the /homework page.
    {
      id: 'homework_status',
      label: 'HW Status',
      tabs: ['completed'],
      cell: (s) =>
        s.homework ? (
          <button type="button" onClick={() => setGradeHomeworkId(s.homework.id)} className="cursor-pointer" title="Open homework review">
            <Badge variant={HOMEWORK_STATUS_VARIANT[(s.homework.status || '').toLowerCase()] || 'secondary'}>{homeworkBadgeLabel(s.homework)}</Badge>
          </button>
        ) : (
          <span className="text-zinc-500">—</span>
        ),
    },
    {
      id: 'rating',
      label: 'Rating',
      tabs: ['completed'],
      cellClass: 'text-sm whitespace-nowrap',
      cell: (s) => (s.rating != null ? <span className="text-zinc-300">{s.rating}/5</span> : <span className="text-zinc-500">—</span>),
    },
  ];
  const tabColumns = columns.filter((c) => !c.tabs || c.tabs.includes(activeTab));
  const visibleColumns = tabColumns.filter((c) => columnVisibility[c.id] !== false);

  const getStudentName = (id) => {
    const s = students.find(x => x.id === id);
    return s ? s.full_name : 'Unknown Student';
  };

  // Drawer inputs: the student behind the filter and their live quota usage.
  // Credits used mirrors the API's calculate_credits_used over the same list
  // the table renders: each class's `consumes_credit` -- every class but a
  // cancelled one, or one not conducted for a reason other than the student's
  // no-show.
  const selectedStudent = students.find(s => s.id === selectedStudentId) || null;
  const usesCredit = (s) => (typeof s.consumes_credit === 'boolean' ? s.consumes_credit : s.status?.toLowerCase() !== 'cancelled');
  const creditsUsed = selectedStudent
    ? sessions
        .filter(s => s.student_id === selectedStudent.id && usesCredit(s))
        .reduce((sum, s) => sum + Math.max(0, (new Date(s.end_time) - new Date(s.start_time)) / 3600000), 0)
    : 0;

  return (
    <div className="flex flex-col gap-6 w-full max-w-full box-border">
      
      {/* Sessions | Exams switcher + banner when filtering by student */}
      {selectedStudentId && (
        <StudentSectionTabs studentId={selectedStudentId} active="sessions" canViewExams={canAny(user, EXAM_VIEW)} />
      )}
      {selectedStudentId && (
        <div className="bg-zinc-100 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-xl px-4 py-3 flex flex-wrap items-center justify-between gap-2">
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

      {/* Filter bar (Hub parity): title, date range, tutor, columns. Student
          scoping comes only from ?student_id, shown in the banner above. */}
      <div className="flex flex-wrap items-center gap-2">
        <Input
          placeholder="Filter by session title or student..."
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
          className="max-w-xs"
        />

        <Popover>
          <PopoverTrigger asChild>
            <Button variant="outline" size="sm">
              <Calendar className="size-4" />
              {dateLabel}
            </Button>
          </PopoverTrigger>
          <PopoverContent className="w-auto p-0" align="start">
            <CalendarPicker
              mode="range"
              selected={dateRange?.from || dateRange?.to ? { from: dateRange?.from, to: dateRange?.to } : undefined}
              onSelect={applyDateRange}
              numberOfMonths={2}
            />
          </PopoverContent>
        </Popover>

        {tutorOptions.length > 0 && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" size="sm">
                Tutor
                {tutorFilter.length > 0 ? <span className="text-muted-foreground ml-1">({tutorFilter.length})</span> : null}
                <ChevronDown className="ml-1 size-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" className="max-h-72 overflow-y-auto">
              <DropdownMenuLabel>Tutor</DropdownMenuLabel>
              <DropdownMenuSeparator />
              {tutorOptions.map((opt) => (
                <DropdownMenuCheckboxItem
                  key={opt.id}
                  checked={tutorFilter.includes(opt.id)}
                  onCheckedChange={(checked) => toggleTutor(opt.id, Boolean(checked))}
                  onSelect={(e) => e.preventDefault()}
                >
                  {opt.name}
                </DropdownMenuCheckboxItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
        )}

        {activeTab === 'completed' && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" size="sm">
                Content
                {contentFilter !== 'all' ? <span className="text-muted-foreground ml-1">({contentFilterLabel})</span> : null}
                <ChevronDown className="ml-1 size-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start">
              <DropdownMenuLabel>Content</DropdownMenuLabel>
              <DropdownMenuSeparator />
              <DropdownMenuRadioGroup value={contentFilter} onValueChange={applyContentFilter}>
                {CONTENT_FILTERS.map((opt) => (
                  <DropdownMenuRadioItem key={opt.value} value={opt.value}>
                    {opt.label}
                  </DropdownMenuRadioItem>
                ))}
              </DropdownMenuRadioGroup>
            </DropdownMenuContent>
          </DropdownMenu>
        )}

        {hasActiveFilters && (
          <Button variant="ghost" size="sm" onClick={clearFilters} className="text-muted-foreground">
            <X className="size-4" />
            Clear
          </Button>
        )}

        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="outline" size="sm">
              Columns
              <ChevronDown className="ml-1 size-4" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            {tabColumns.map((c) => (
              <DropdownMenuCheckboxItem
                key={c.id}
                className="capitalize"
                checked={columnVisibility[c.id] !== false}
                onCheckedChange={(value) => setColumnVisibility((prev) => ({ ...prev, [c.id]: Boolean(value) }))}
              >
                {c.id.replace(/_/g, ' ')}
              </DropdownMenuCheckboxItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>

        {selectedStudentId && canCreate && (
          <div className="ml-auto">
            <button 
              onClick={() => setCreateOpen(true)}
              className="h-10 px-4 bg-white hover:bg-zinc-200 text-zinc-950 rounded-xl text-sm font-semibold shadow-sm transition-all flex items-center gap-2 self-stretch sm:self-auto shrink-0 justify-center cursor-pointer"
            >
              <Plus className="w-4 h-4" />
              New Session
            </button>
          </div>
        )}
      </div>

      {error && (
        <div className="bg-red-950/40 text-red-400 text-xs p-3 rounded-lg border border-red-900/50">
          {error}
        </div>
      )}

      {/* Tabs, by where each class stands. Needs Action counts what waits there. */}
      <div className="flex gap-4 overflow-x-auto border-b border-zinc-200 dark:border-[rgba(255,255,255,0.08)] sm:gap-6">
        {TABS.map((tab) => {
          const waiting = tab.id === 'needs_action'
            ? sessions.filter((session) => studentRow(session) && inTab(tab.id, classState(session, now))).length
            : 0;
          // The count sits beside the tab, so the tab keeps its name whatever it counts.
          return (
            <div key={tab.id} className="flex shrink-0 items-start gap-1.5">
              <button
                onClick={() => switchTab(tab.id)}
                className={`shrink-0 whitespace-nowrap pb-3 text-sm font-medium transition-colors relative cursor-pointer ${
                  activeTab === tab.id
                    ? 'text-zinc-900 dark:text-white border-b-2 border-zinc-900 dark:border-white'
                    : 'text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-300'
                }`}
              >
                {tab.label}
              </button>
              {waiting > 0 ? (
                <span className="rounded-full bg-warning/15 px-1.5 text-xs text-warning" aria-label={`${waiting} need action`}>
                  {waiting}
                </span>
              ) : null}
            </div>
          );
        })}
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
                  {visibleColumns.map((c) => (
                    <th key={c.id} className="h-12 px-4 font-semibold text-xs text-zinc-400 align-middle">{c.label}</th>
                  ))}
                  <th className="h-12 px-4 w-10"></th>
                </tr>
              </thead>
              <tbody>
                {filteredSessions.map((session) => (
                  <tr 
                    key={session.id} 
                    className="hover:bg-[rgba(255,255,255,0.02)] border-b border-[rgba(255,255,255,0.08)] h-[54px] transition-colors"
                  >
                    {visibleColumns.map((c) => (
                      <td key={c.id} className={`py-2 px-4 align-middle ${c.cellClass || ''}`}>{c.cell(session)}</td>
                    ))}

                    <td className="py-2 px-4 align-middle text-right sticky right-0 bg-[#0a0a0a] group-hover:bg-[#111] border-l border-[rgba(255,255,255,0.08)] transition-colors z-10">
                      {!canManage ? (
                        // With only edit_session_notes (tutors), the notes
                        // link of their own classes is all there is; a
                        // class cancelled or not conducted takes none.
                        canEditNotes && isAssignedTutor(session, user) && tutorNotesItem(session) && (
                          <StaffActionsDropdown items={[tutorNotesItem(session)]} />
                        )
                      ) : (
                        <StaffActionsDropdown items={staffItems(session)} />
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
      </div>

      {/* Modals & Sheets Overlay. Reschedule and the outcome dialogs are
          design-system dialogs below, so they are left out of this legacy overlay. */}
      {['attend', 'notes', 'links', 'cancel'].includes(modalType) && (
        <div className="fixed inset-0 bg-black/45 flex items-center justify-center z-50 p-4">
          
          {/* Mark Attended Modal — captures required resource links */}
          {modalType === 'attend' && (
            <div className="w-full max-w-md bg-[#1c1c1c] border border-white/10 rounded-2xl p-5 shadow-2xl relative max-h-[calc(100dvh-2rem)] overflow-y-auto sm:p-6">
              <h3 className="text-base font-semibold text-white m-0">Mark Session Attended</h3>
              <p className="text-xs text-zinc-400 mt-1 mb-6">{activeSession?.title}</p>

              <form onSubmit={handleMarkAttended} className="space-y-4">
                <SchedulingError error={modalError} legacy />

                <p className="text-[11px] text-zinc-500 m-0">
                  {isAdmin
                    ? 'Recording, notes and homework can each be added now or later. '
                    : 'Recording and homework can be added now or later; the tutor adds the notes. '}
                  The class shows <span className="text-amber-400">Content missing</span> until all three are available.
                </p>

                <p className="text-[11px] text-zinc-500 m-0">
                  {activeSession?.started_at
                    ? `Started ${stamp(activeSession.started_at)} by ${personName(activeSession.started_by_profile)}. Marking it attended records attendance only; the tutor's own notes complete it, whenever they come in.`
                    : "Nobody started this class, so its tutor's notes cannot complete it. Marking it attended records attendance only and never counts toward Tutor Earnings."}
                </p>

                <ContentInput
                  label="Class Recording"
                  optional
                  placeholder="https://drive.google.com/..."
                  value={content.recording}
                  onChange={setFieldContent('recording')}
                  disabled={saving}
                />

                {isAdmin && (
                  <ContentInput
                    label="Class Notes"
                    optional
                    placeholder="https://docs.google.com/..."
                    value={content.notes}
                    onChange={setFieldContent('notes')}
                    disabled={saving}
                  />
                )}

                <ContentInput
                  label="Homework Assignment"
                  optional
                  placeholder="https://classroom.google.com/..."
                  value={content.homework}
                  onChange={setFieldContent('homework')}
                  disabled={saving}
                />

                {!isAdmin && (
                  <div className="flex items-center justify-between gap-3 rounded-lg border border-white/10 bg-white/[0.02] px-3 py-2">
                    <span className="text-xs font-bold text-zinc-400 uppercase tracking-widest">Class Notes <span className="text-zinc-600 normal-case tracking-normal font-medium">(added by the tutor)</span></span>
                    {activeSession?.notes_link
                      ? <Badge variant="success"><Check />Available</Badge>
                      : <Badge variant="warning"><AlertTriangle />Not added yet</Badge>}
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

          {/* Tutor: Add / Update Notes Link */}
          {modalType === 'notes' && (
            <div className="w-full max-w-md bg-[#1c1c1c] border border-white/10 rounded-2xl p-5 shadow-2xl relative max-h-[calc(100dvh-2rem)] overflow-y-auto sm:p-6">
              <h3 className="text-base font-semibold text-white m-0">
                {completingNotes ? 'Submit Notes' : 'Update Notes'}
              </h3>
              <p className="text-xs text-zinc-400 mt-1 mb-6">{activeSession?.title}</p>

              <form onSubmit={handleSaveNotes} className="space-y-4">
                <SchedulingError error={modalError} legacy />

                <p className="text-[11px] text-zinc-500 m-0">
                  {completingNotes
                    ? `Paste a link to your notes or upload the file (PDF, image, or video). Submitting them completes this class: ${bookedLength(activeSession)} as booked.`
                    : 'Paste a link to your notes or upload the file (PDF, image, or video). This updates the notes of a completed class.'}
                </p>

                <ContentInput
                  label="Class Notes"
                  placeholder="https://docs.google.com/..."
                  value={content.notes}
                  onChange={setFieldContent('notes')}
                  disabled={saving}
                />

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
                    {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <FileText className="w-3.5 h-3.5" />}
                    {completingNotes ? 'Submit & Complete' : 'Save Notes'}
                  </button>
                </div>
              </form>
            </div>
          )}

          {/* 3. Resource Links Modal */}
          {modalType === 'links' && (
            <div className="w-full max-w-md bg-[#1c1c1c] border border-white/10 rounded-2xl p-5 shadow-2xl relative max-h-[calc(100dvh-2rem)] overflow-y-auto sm:p-6">
              <h3 className="text-base font-semibold text-white m-0">Edit Resource Links</h3>
              <p className="text-xs text-zinc-400 mt-1 mb-6">{activeSession?.title}</p>

              <form onSubmit={handleSaveLinks} className="space-y-4">
                <SchedulingError error={modalError} legacy />

                <p className="text-[11px] text-zinc-500 m-0">
                  Each item can be a link or an uploaded file (PDF, image, or video).
                </p>

                <ContentInput
                  label="Class Recording"
                  placeholder="https://drive.google.com/..."
                  value={content.recording}
                  onChange={setFieldContent('recording')}
                  disabled={saving}
                />

                <ContentInput
                  label="Class Notes"
                  placeholder="https://docs.google.com/..."
                  value={content.notes}
                  onChange={setFieldContent('notes')}
                  disabled={saving}
                />

                <ContentInput
                  label="Homework Assignment"
                  placeholder="https://classroom.google.com/..."
                  value={content.homework}
                  onChange={setFieldContent('homework')}
                  disabled={saving}
                />

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
            <div className="w-full max-w-md bg-[#1c1c1c] border border-white/10 rounded-2xl p-5 shadow-2xl relative max-h-[calc(100dvh-2rem)] overflow-y-auto sm:p-6">
              <h3 className="text-base font-semibold text-white m-0">Cancel Session</h3>
              <p className="text-xs text-zinc-400 mt-1 mb-6">{activeSession?.title}</p>

              <form onSubmit={handleCancelSession} className="space-y-4">
                <SchedulingError error={modalError} legacy />

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

      {/* No-show / Not Conducted and an administrator's correction. */}
      <RecordOutcomeDialog
        session={modalType === 'outcome' ? activeSession : null}
        open={modalType === 'outcome'}
        onOpenChange={(v) => !v && closeModal()}
        onSaved={() => fetchSessions()}
      />
      <CorrectOutcomeDialog
        session={modalType === 'correct' ? activeSession : null}
        open={modalType === 'correct'}
        onOpenChange={(v) => !v && closeModal()}
        onSaved={() => fetchSessions()}
      />

      <HomeworkGradeSheet
        homeworkId={gradeHomeworkId}
        open={Boolean(gradeHomeworkId)}
        onOpenChange={(v) => !v && setGradeHomeworkId(null)}
        onSaved={() => fetchSessions()}
        canScore={can(user, PERMISSIONS.scoreHomework)}
      />

      {/* Reschedule: the student's stored zone governs the time entered; the
          dialog never writes the student, so only sessions need refetching. */}
      <RescheduleSessionDialog
        session={activeSession}
        studentTimezone={students.find((s) => s.id === activeSession?.student_id)?.timezone}
        open={modalType === 'reschedule'}
        onOpenChange={(v) => !v && closeModal()}
        onSaved={() => fetchSessions()}
      />

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
