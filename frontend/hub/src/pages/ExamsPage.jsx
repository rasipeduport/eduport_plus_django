import { useState, useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Loader2, Calendar, ClipboardList, Video, ExternalLink, ChevronDown, X, Plus, FileText } from 'lucide-react';
import { format } from 'date-fns';

import api from '../lib/api';
import StaffActionsDropdown from '../components/StaffActionsDropdown';
import { Badge } from '../components/ui/badge';
import { Tooltip, TooltipContent, TooltipTrigger } from '../components/ui/tooltip';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Calendar as CalendarPicker } from '../components/ui/calendar';
import { Popover, PopoverContent, PopoverTrigger } from '../components/ui/popover';
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '../components/ui/dropdown-menu';
import { StudentSectionTabs } from '../components/students/section-tabs';
import { NewExamSheet } from '../components/exams/new-exam-sheet';
import { NewAdditionalExamSheet } from '../components/exams/new-additional-exam-sheet';
import { MarkResultDialog } from '../components/exams/mark-result-dialog';
import { RescheduleExamDialog } from '../components/exams/reschedule-exam-dialog';
import { CancelExamDialog } from '../components/exams/cancel-exam-dialog';
import { AdditionalExamGradeSheet } from '../components/exams/additional-exam-grade-sheet';
import { AdditionalExamsTable } from '../components/exams/additional-exams-table';
import { EXAM_STATUS_VARIANT, examStatusLabel, isHttpsUrl } from '../lib/exam-status';

// Same browser-local formats as the sessions table.
const DATE_FORMAT = new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
const TIME_FORMAT = new Intl.DateTimeFormat('en-US', { hour: 'numeric', minute: '2-digit', hour12: true });

const STATUS_OPTIONS = ['scheduled', 'attended', 'cancelled'];

function StatusBadge({ exam }) {
  const key = (exam.status || '').toLowerCase();
  const badge = <Badge variant={EXAM_STATUS_VARIANT[key] || 'secondary'}>{examStatusLabel(exam)}</Badge>;
  if (key === 'cancelled' && exam.cancellation_reason) {
    return (
      <Tooltip>
        <TooltipTrigger asChild>
          <span className="cursor-help">{badge}</span>
        </TooltipTrigger>
        <TooltipContent>
          <p className="max-w-xs">{exam.cancellation_reason}</p>
        </TooltipContent>
      </Tooltip>
    );
  }
  return badge;
}

function RecordingLink({ href }) {
  const url = (href || '').trim();
  if (!url) return <span className="text-zinc-500">—</span>;
  if (!isHttpsUrl(url)) return <span className="block max-w-40 truncate text-xs text-zinc-400" title={url}>{url}</span>;
  return (
    <a
      href={url}
      target="_blank"
      rel="noopener noreferrer"
      title={url}
      className="inline-flex items-center gap-1.5 h-7 px-2.5 rounded-md border border-white/10 bg-zinc-800 hover:bg-zinc-700 text-xs font-medium text-zinc-200 hover:text-white whitespace-nowrap transition-colors"
    >
      <Video className="w-3.5 h-3.5 shrink-0" />
      Open
      <ExternalLink className="w-3 h-3 text-zinc-400 shrink-0" />
    </a>
  );
}

/**
 * Exams page (Hub parity). Without `?student_id=` it is the read-only global
 * list (admin: all, mentor: own students); with it, the student's exams page
 * with the New menu and row actions, reached from "Manage Exams".
 */
export default function ExamsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const studentIdQuery = searchParams.get('student_id');

  const [exams, setExams] = useState([]);
  const [additionalExams, setAdditionalExams] = useState([]);
  const [students, setStudents] = useState([]);
  const [chapterNames, setChapterNames] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [userRole, setUserRole] = useState('ADMIN');

  const [searchTerm, setSearchTerm] = useState('');
  const [dateRange, setDateRange] = useState(undefined);
  const [statusFilter, setStatusFilter] = useState([]);
  const [mentorFilter, setMentorFilter] = useState([]);
  const [columnVisibility, setColumnVisibility] = useState({});
  const [selectedStudentId, setSelectedStudentId] = useState(studentIdQuery || '');

  // Dialogs / drawers
  const [resultExam, setResultExam] = useState(null);
  const [rescheduleExam, setRescheduleExam] = useState(null);
  const [cancelExam, setCancelExam] = useState(null);
  const [gradeExamId, setGradeExamId] = useState(null);
  const [createExamOpen, setCreateExamOpen] = useState(false);
  const [createAdditionalOpen, setCreateAdditionalOpen] = useState(false);

  useEffect(() => {
    fetchUserInfo();
    fetchStudents();
    fetchExams();
  }, []);

  useEffect(() => {
    setSelectedStudentId(studentIdQuery || '');
  }, [studentIdQuery]);

  useEffect(() => {
    if (!selectedStudentId) {
      setChapterNames([]);
      return;
    }
    api
      .get('/api/exams/chapter-names/', { params: { student_id: selectedStudentId } })
      .then((res) => setChapterNames(res.data.chapter_names || []))
      .catch(() => setChapterNames([]));
  }, [selectedStudentId]);

  const fetchUserInfo = async () => {
    try {
      const res = await api.get('/api/auth/me/');
      setUserRole(res.data.user?.role || 'ADMIN');
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

  const fetchExams = async () => {
    setLoading(true);
    setError('');
    try {
      const [ex, add] = await Promise.all([api.get('/api/exams/'), api.get('/api/additional-exams/')]);
      setExams(ex.data.exams || []);
      setAdditionalExams(add.data.additional_exams || []);
    } catch (err) {
      setError(err.response?.data?.error || err.response?.data?.message || 'Failed to load exams.');
    } finally {
      setLoading(false);
    }
  };

  const refresh = () => {
    fetchExams();
    if (selectedStudentId) {
      api
        .get('/api/exams/chapter-names/', { params: { student_id: selectedStudentId } })
        .then((res) => setChapterNames(res.data.chapter_names || []))
        .catch(() => {});
    }
  };

  const clearStudentFilter = () => {
    setSelectedStudentId('');
    setSearchParams({});
  };

  const isGlobal = !selectedStudentId;
  const isAdmin = userRole === 'ADMIN';

  const term = searchTerm.trim().toLowerCase();
  const filteredExams = exams.filter((e) => {
    const studentMatch = selectedStudentId ? e.student_id === selectedStudentId : true;
    const studentName = e.students?.full_name || '';
    const termMatch = !term || (e.chapter_name || '').toLowerCase().includes(term) || studentName.toLowerCase().includes(term);
    const startMs = new Date(e.start_time).getTime();
    const dateMatch =
      !dateRange ||
      ((!dateRange.from || startMs >= dateRange.from.getTime()) && (!dateRange.to || startMs <= dateRange.to.getTime()));
    const statusMatch = statusFilter.length === 0 || statusFilter.includes((e.status || '').toLowerCase());
    const mentorId = e.mentor_profile?.id ?? e.mentor ?? null;
    const mentorMatch = mentorFilter.length === 0 || (mentorId != null && mentorFilter.includes(mentorId));
    return studentMatch && termMatch && dateMatch && statusMatch && mentorMatch;
  });

  const filteredAdditional = additionalExams.filter((a) => {
    const studentMatch = selectedStudentId ? a.student_id === selectedStudentId : true;
    const studentName = a.students?.full_name || '';
    const termMatch = !term || (a.title || '').toLowerCase().includes(term) || studentName.toLowerCase().includes(term);
    return studentMatch && termMatch;
  });

  const mentorOptions = isAdmin
    ? Array.from(
        new Map(
          exams
            .filter((e) => e.mentor_profile)
            .map((e) => [e.mentor_profile.id, { id: e.mentor_profile.id, name: e.mentor_profile.full_name || e.mentor_profile.email }])
        ).values()
      ).sort((a, b) => a.name.localeCompare(b.name))
    : [];

  const hasActiveFilters = Boolean(searchTerm) || Boolean(dateRange?.from || dateRange?.to) || statusFilter.length > 0 || mentorFilter.length > 0;
  const clearFilters = () => {
    setSearchTerm('');
    setDateRange(undefined);
    setStatusFilter([]);
    setMentorFilter([]);
  };

  const dateLabel = (() => {
    if (!dateRange?.from && !dateRange?.to) return 'Date range';
    if (dateRange?.from && dateRange?.to) return `${format(dateRange.from, 'MMM d')} - ${format(dateRange.to, 'MMM d, yyyy')}`;
    if (dateRange?.from) return `From ${format(dateRange.from, 'MMM d, yyyy')}`;
    return `Until ${format(dateRange.to, 'MMM d, yyyy')}`;
  })();

  const applyDateRange = (range) => {
    if (!range || (!range.from && !range.to)) {
      setDateRange(undefined);
      return;
    }
    const to = range.to ? new Date(range.to.getFullYear(), range.to.getMonth(), range.to.getDate(), 23, 59, 59, 999) : undefined;
    setDateRange({ from: range.from, to });
  };

  const toggleIn = (setter) => (value, checked) =>
    setter((prev) => (checked ? Array.from(new Set([...prev, value])) : prev.filter((v) => v !== value)));

  const columns = [
    { id: 'chapter', label: 'Chapter', cell: (e) => <span className="font-semibold text-white text-sm block max-w-60 truncate" title={e.chapter_name}>{e.chapter_name}</span> },
    { id: 'date', label: 'Date', cellClass: 'text-sm text-zinc-300 whitespace-nowrap', cell: (e) => DATE_FORMAT.format(new Date(e.start_time)) },
    {
      id: 'time',
      label: 'Time',
      cellClass: 'text-sm text-zinc-300 whitespace-nowrap',
      cell: (e) => `${TIME_FORMAT.format(new Date(e.start_time))} - ${TIME_FORMAT.format(new Date(e.end_time))}`,
    },
    { id: 'status', label: 'Status', cell: (e) => <StatusBadge exam={e} /> },
    ...(isGlobal
      ? [
          {
            id: 'student',
            label: 'Student',
            cell: (e) => (
              <div className="flex flex-col gap-0.5">
                <span className="font-medium text-white text-sm">{e.students?.full_name || '—'}</span>
                <span className="text-xs text-[#a1a1aa] font-mono">{e.students?.student_code || ''}</span>
              </div>
            ),
          },
          { id: 'mentor', label: 'Mentor', cellClass: 'text-sm text-[#e4e4e7]', cell: (e) => e.mentor_profile?.full_name || e.mentor_profile?.email || '—' },
        ]
      : []),
    {
      id: 'score',
      label: 'Score',
      cellClass: 'text-sm whitespace-nowrap tabular-nums',
      cell: (e) =>
        (e.status || '').toLowerCase() === 'attended' && e.score != null && e.max_score != null ? (
          <span className="text-zinc-300">{e.score}/{e.max_score}</span>
        ) : (
          <span className="text-zinc-500">—</span>
        ),
    },
    {
      id: 'question_paper',
      label: 'Question Paper',
      cellClass: 'text-sm whitespace-nowrap',
      cell: (e) =>
        e.file_count > 0 ? (
          <span className="inline-flex items-center gap-1 text-zinc-300">
            <FileText className="w-3.5 h-3.5 text-zinc-400" />
            {e.file_count} {e.file_count === 1 ? 'file' : 'files'}
          </span>
        ) : (
          <span className="text-zinc-500">—</span>
        ),
    },
    { id: 'recording', label: 'Recording', cell: (e) => <RecordingLink href={e.recording_link} /> },
  ];
  const visibleColumns = columns.filter((c) => columnVisibility[c.id] !== false);

  const getStudentName = (id) => students.find((x) => x.id === id)?.full_name || 'Unknown Student';
  const selectedStudent = students.find((s) => s.id === selectedStudentId) || null;

  const rowActions = (exam) => {
    const status = (exam.status || '').toLowerCase();
    const isScheduled = status === 'scheduled';
    const isAttended = status === 'attended';
    return [
      { label: isAttended ? 'Edit Result' : 'Record Result', disabled: !isScheduled && !isAttended, onClick: () => setResultExam(exam) },
      { label: 'Reschedule', disabled: !isScheduled, onClick: () => setRescheduleExam(exam) },
      { label: 'Cancel Exam', disabled: !isScheduled, danger: true, onClick: () => setCancelExam(exam) },
    ];
  };

  return (
    <div className="flex flex-col gap-6 w-full max-w-full box-border">
      {selectedStudentId && (
        <>
          <StudentSectionTabs studentId={selectedStudentId} active="exams" />
          <div className="bg-zinc-100 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-xl px-4 py-3 flex items-center justify-between">
            <div className="flex items-center gap-2 text-sm text-zinc-700 dark:text-zinc-300">
              <span className="font-semibold text-zinc-900 dark:text-white">Filtering:</span>
              <span>Exams for {getStudentName(selectedStudentId)}</span>
            </div>
            <button onClick={clearStudentFilter} className="text-xs text-zinc-400 hover:text-zinc-600 dark:hover:text-white underline cursor-pointer">
              Clear Filter
            </button>
          </div>
        </>
      )}

      {/* Filter bar (Hub parity): chapter/student search, date range, status, mentor, columns. */}
      <div className="flex flex-wrap items-center gap-2">
        <Input placeholder="Filter by chapter or student..." value={searchTerm} onChange={(e) => setSearchTerm(e.target.value)} className="max-w-xs" />

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

        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="outline" size="sm">
              Status
              {statusFilter.length > 0 ? <span className="text-muted-foreground ml-1">({statusFilter.length})</span> : null}
              <ChevronDown className="ml-1 size-4" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start">
            <DropdownMenuLabel>Status</DropdownMenuLabel>
            <DropdownMenuSeparator />
            {STATUS_OPTIONS.map((opt) => (
              <DropdownMenuCheckboxItem
                key={opt}
                className="capitalize"
                checked={statusFilter.includes(opt)}
                onCheckedChange={(checked) => toggleIn(setStatusFilter)(opt, Boolean(checked))}
                onSelect={(e) => e.preventDefault()}
              >
                {opt}
              </DropdownMenuCheckboxItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>

        {mentorOptions.length > 0 && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" size="sm">
                Mentor
                {mentorFilter.length > 0 ? <span className="text-muted-foreground ml-1">({mentorFilter.length})</span> : null}
                <ChevronDown className="ml-1 size-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" className="max-h-72 overflow-y-auto">
              <DropdownMenuLabel>Mentor</DropdownMenuLabel>
              <DropdownMenuSeparator />
              {mentorOptions.map((opt) => (
                <DropdownMenuCheckboxItem
                  key={opt.id}
                  checked={mentorFilter.includes(opt.id)}
                  onCheckedChange={(checked) => toggleIn(setMentorFilter)(opt.id, Boolean(checked))}
                  onSelect={(e) => e.preventDefault()}
                >
                  {opt.name}
                </DropdownMenuCheckboxItem>
              ))}
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
            {columns.map((c) => (
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

        {selectedStudentId && (
          <div className="ml-auto">
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button className="h-10 px-4 bg-white hover:bg-zinc-200 text-zinc-950 rounded-xl text-sm font-semibold shadow-sm transition-all flex items-center gap-2 shrink-0 justify-center cursor-pointer">
                  <Plus className="w-4 h-4" />
                  New
                  <ChevronDown className="w-4 h-4" />
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onSelect={() => setCreateExamOpen(true)}>Chapter Exam</DropdownMenuItem>
                <DropdownMenuItem onSelect={() => setCreateAdditionalOpen(true)}>Additional Exam</DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        )}
      </div>

      {error && <div className="bg-red-950/40 text-red-400 text-xs p-3 rounded-lg border border-red-900/50">{error}</div>}

      {/* Chapter exams */}
      <div className="border border-[rgba(255,255,255,0.08)] bg-[#0a0a0a] rounded-xl shadow-xl overflow-x-auto w-full">
        {loading ? (
          <div className="flex items-center justify-center py-20">
            <Loader2 className="w-8 h-8 animate-spin text-white" />
          </div>
        ) : filteredExams.length === 0 ? (
          <div className="py-16 text-center">
            <ClipboardList className="w-8 h-8 mx-auto text-zinc-600 mb-3" />
            <p className="text-zinc-500 text-sm">{selectedStudentId ? 'No exams found for this student.' : 'No exams found.'}</p>
          </div>
        ) : (
          <table className="w-full text-left border-collapse text-sm">
            <thead>
              <tr className="border-b border-[rgba(255,255,255,0.08)] bg-[#0f0f0f]">
                {visibleColumns.map((c) => (
                  <th key={c.id} className="h-12 px-4 font-semibold text-xs text-zinc-400 align-middle">{c.label}</th>
                ))}
                {!isGlobal && <th className="h-12 px-4 w-10"></th>}
              </tr>
            </thead>
            <tbody>
              {filteredExams.map((exam) => (
                <tr key={exam.id} className="hover:bg-[rgba(255,255,255,0.02)] border-b border-[rgba(255,255,255,0.08)] h-[54px] transition-colors">
                  {visibleColumns.map((c) => (
                    <td key={c.id} className={`py-2 px-4 align-middle ${c.cellClass || ''}`}>{c.cell(exam)}</td>
                  ))}
                  {!isGlobal && (
                    <td className="py-2 px-4 align-middle text-right sticky right-0 bg-[#0a0a0a] border-l border-[rgba(255,255,255,0.08)] transition-colors z-10">
                      <StaffActionsDropdown items={rowActions(exam)} />
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Additional exams */}
      <section className="flex flex-col gap-3">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-zinc-900 dark:text-white">Additional Exams</h2>
          <span className="text-xs text-zinc-500">Question paper from the mentor, answer sheet from the student, scored X/Y.</span>
        </div>
        {loading ? null : <AdditionalExamsTable rows={filteredAdditional} showStudent={isGlobal} onOpen={(r) => setGradeExamId(r.id)} />}
      </section>

      {/* Drawers and dialogs */}
      <NewExamSheet student={selectedStudent} chapterNames={chapterNames} open={createExamOpen} onOpenChange={setCreateExamOpen} onCreated={() => { refresh(); fetchStudents(); }} />
      <NewAdditionalExamSheet student={selectedStudent} open={createAdditionalOpen} onOpenChange={setCreateAdditionalOpen} onCreated={refresh} />
      <MarkResultDialog exam={resultExam} open={Boolean(resultExam)} onOpenChange={(v) => !v && setResultExam(null)} onSaved={refresh} />
      <RescheduleExamDialog
        exam={rescheduleExam}
        studentTimezone={students.find((s) => s.id === rescheduleExam?.student_id)?.timezone}
        open={Boolean(rescheduleExam)}
        onOpenChange={(v) => !v && setRescheduleExam(null)}
        onSaved={refresh}
      />
      <CancelExamDialog exam={cancelExam} open={Boolean(cancelExam)} onOpenChange={(v) => !v && setCancelExam(null)} onSaved={refresh} />
      <AdditionalExamGradeSheet examId={gradeExamId} open={Boolean(gradeExamId)} onOpenChange={(v) => !v && setGradeExamId(null)} onSaved={refresh} />
    </div>
  );
}
