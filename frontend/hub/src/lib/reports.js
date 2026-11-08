// Demo and Diagnostic assessment reports (backend reports app): the tutor's
// /api/tutor/bookings/<type>/<id>/report/ contract, the Admin's read-only
// /api/bookings/<type>/<id>/report/, the owner BDE's reports on their own
// leads (P9), and the report PDFs (P7). The API enforces every rule -- who may
// write or read a report, when, how often, and what each field may hold -- so
// this only mirrors those rules for the form, builds requests and labels what
// comes back. The API's answer always wins.
import { bdeBookingUrl, bookingState, bookingUrl, tutorBookingUrl } from '@/lib/bookings';
import { enquiryUrl } from '@/lib/enquiries';

// Each report field by the name the report prints it under: the fields the
// tutor writes (reports.models TUTOR_FIELDS) and the system fields printed
// with them. An edit's history names the fields it changed by these.
export const REPORT_FIELD_LABELS = {
  score: 'Score',
  max_score: 'Maximum score',
  performance_level: 'Performance level',
  strength_areas: 'Strength areas',
  skills_to_strengthen: 'Skills to strengthen',
  teacher_remarks: "Teacher's remarks",
  suggested_plan: 'Suggested plan',
  assessment_review: 'Assessment review',
  class_observation_review: 'Class observation review',
  suggested_strategy: 'Suggested strategy',
  student_name_snapshot: 'Student name',
  grade_snapshot: 'Grade',
  tutor_name_snapshot: 'Tutor name',
};

/** "Score, Teacher's remarks": the fields an edit changed, in the order the API gives them. */
export function reportFieldsText(names) {
  return (names ?? []).map((name) => REPORT_FIELD_LABELS[name] ?? name).join(', ');
}

// ------------------------------------------------------------------ the form

// The fields the tutor writes for each type, in the order the report prints
// them (reports.models DiagnosticReport / DemoReport TUTOR_FIELDS).
export const REPORT_FIELDS = {
  DIAGNOSTIC: [
    'score',
    'max_score',
    'performance_level',
    'strength_areas',
    'skills_to_strengthen',
    'teacher_remarks',
    'suggested_plan',
  ],
  DEMO: ['assessment_review', 'class_observation_review', 'suggested_strategy'],
};

// The limits the API holds them to (reports.models, reports.services CLEANERS).
export const MAX_ITEMS = 15;
export const ITEM_CHARS = 120;
export const MAX_SCORE = 1000;
const TEXT_CHARS = {
  teacher_remarks: 2000,
  suggested_plan: 1000,
  assessment_review: 1200,
  class_observation_review: 1200,
  suggested_strategy: 1200,
};
const LIST_FIELDS = new Set(['strength_areas', 'skills_to_strengthen']);
const NUMBER_FIELDS = new Set(['score', 'max_score']);

/** The id of ``field``'s control on the report form ("report-teacher-remarks"). */
export const reportFieldId = (field) => `report-${field.replace(/_/g, '-')}`;

/** The most characters ``field`` (a free-text field) may hold. */
export const textLimit = (field) => TEXT_CHARS[field];
export const isListField = (field) => LIST_FIELDS.has(field);

export const PERFORMANCE_LEVELS = [
  { value: 'EXCELLENT', label: 'Excellent' },
  { value: 'GOOD', label: 'Good' },
  { value: 'AVERAGE', label: 'Average' },
  { value: 'BELOW_AVERAGE', label: 'Below Average' },
];
export const performanceLevelLabel = (value) =>
  PERFORMANCE_LEVELS.find((level) => level.value === value)?.label ?? value ?? '';

// Printed on every report but never typed: template constants (design A6).
export const REPORT_SUBJECT = 'Mathematics';
export const DIAGNOSTIC_ASSESSMENT_TYPE = 'Diagnostic Test';

/** A count in characters as the API counts them: line breaks as one, an emoji as one. */
export function charCount(text) {
  return [...normalizedText(text)].length;
}

function normalizedText(text) {
  return String(text ?? '')
    .replace(/\r\n/g, '\n')
    .replace(/\r/g, '\n');
}

/** A blank form for a report of ``type`` (DIAGNOSTIC or DEMO): one empty row in each list. */
export function emptyReportForm(type) {
  return Object.fromEntries(
    fieldsOf(type).map((field) => [field, isListField(field) ? [''] : ''])
  );
}

/** The form for a saved report: ``fields`` is the API's report.fields. */
export function reportForm(type, fields) {
  return Object.fromEntries(
    fieldsOf(type).map((field) => {
      const value = fields?.[field];
      if (isListField(field)) return [field, Array.isArray(value) && value.length ? [...value] : ['']];
      if (NUMBER_FIELDS.has(field)) return [field, value === null || value === undefined ? '' : String(value)];
      return [field, value ?? ''];
    })
  );
}

/**
 * The request body for ``values``: exactly the fields the tutor writes, text
 * trimmed with its line breaks as "\n", blank list rows left out, and the
 * scores as numbers where they are whole numbers (else as typed, for the API
 * to refuse). Never a system field: the API prints those itself (D7).
 */
export function reportPayload(type, values) {
  return Object.fromEntries(
    fieldsOf(type).map((field) => {
      const value = values?.[field];
      if (isListField(field)) {
        return [field, (Array.isArray(value) ? value : []).map((item) => normalizedText(item).trim()).filter(Boolean)];
      }
      if (NUMBER_FIELDS.has(field)) return [field, wholeNumber(value) ?? normalizedText(value).trim()];
      return [field, normalizedText(value).trim()];
    })
  );
}

/** Whether ``a`` and ``b`` would send different reports. */
export function reportChanged(type, a, b) {
  return JSON.stringify(reportPayload(type, a)) !== JSON.stringify(reportPayload(type, b));
}

/**
 * The problems the API would find in ``values``, as { field: message } --
 * empty when it would accept them. The rules and words are the API's
 * (reports.services clean_fields), checked here only to say so sooner.
 */
export function validateReport(type, values) {
  const errors = {};
  const payload = reportPayload(type, values);
  for (const field of fieldsOf(type)) {
    const message = NUMBER_FIELDS.has(field)
      ? numberProblem(field, payload[field])
      : isListField(field)
        ? listProblem(values?.[field])
        : field === 'performance_level'
          ? levelProblem(payload[field])
          : textProblem(payload[field], textLimit(field));
    if (message) errors[field] = message;
  }
  if (!errors.score && !errors.max_score && 'score' in payload && payload.score > payload.max_score) {
    errors.score = 'The score cannot be more than the maximum score.';
  }
  return errors;
}

/**
 * The problem with each row of a list, or null: more than one line, or longer
 * than ITEM_CHARS. A blank row is no problem -- it is simply not sent.
 */
export function itemProblems(items) {
  return (Array.isArray(items) ? items : []).map((item) => {
    const text = normalizedText(item).trim();
    if (!text) return null;
    if (text.includes('\n')) return 'Each item is one line.';
    if (charCount(text) > ITEM_CHARS) return `Each item holds at most ${ITEM_CHARS} characters.`;
    return null;
  });
}

function numberProblem(field, value) {
  if (value === '' || value === null || value === undefined) return 'This field is required.';
  if (typeof value !== 'number') return 'Enter a whole number.';
  const low = field === 'max_score' ? 1 : 0;
  if (value < low || value > MAX_SCORE) return `Enter a number from ${low} to ${MAX_SCORE}.`;
  return null;
}

function listProblem(items) {
  const rows = (Array.isArray(items) ? items : []).map((item) => normalizedText(item).trim()).filter(Boolean);
  if (!rows.length || rows.length > MAX_ITEMS) return `List 1 to ${MAX_ITEMS} items.`;
  return itemProblems(rows).find(Boolean) ?? null;
}

function levelProblem(value) {
  if (!value) return 'This field is required.';
  return PERFORMANCE_LEVELS.some((level) => level.value === value) ? null : 'Choose a performance level.';
}

function textProblem(value, limit) {
  if (!value) return 'This field is required.';
  return charCount(value) > limit ? `Use at most ${limit} characters.` : null;
}

function wholeNumber(value) {
  const text = String(value ?? '').trim();
  return /^\d+$/.test(text) ? Number(text) : null;
}

function fieldsOf(type) {
  const fields = REPORT_FIELDS[type];
  if (!fields) throw new Error(`Unknown report type: ${type}`);
  return fields;
}

/**
 * ``{ status, code, message, fields, version }`` from an axios error. The
 * report API answers ``{ error: CODE, message, fields?, version? }``: each of
 * ``fields`` names its problem (the first of the API's messages for it, under
 * the field's own name, or non_field_errors), and ``version`` is the report's
 * current version on REPORT_EXISTS and REPORT_VERSION_CONFLICT.
 */
export function reportError(err, fallback) {
  const response = err?.response;
  const data = response?.data ?? {};
  const fields = {};
  if (data.fields && typeof data.fields === 'object' && !Array.isArray(data.fields)) {
    for (const [field, messages] of Object.entries(data.fields)) {
      const message = Array.isArray(messages) ? messages[0] : messages;
      if (typeof message === 'string' && message) fields[field] = message;
    }
  }
  return {
    status: response?.status ?? null,
    code: typeof data.error === 'string' ? data.error : null,
    message: response
      ? data.message || data.detail || fallback
      : 'Could not reach the server. Check your connection and try again.',
    fields,
    version: Number.isInteger(data.version) ? data.version : null,
  };
}

// ---------------------------------------------------------- where it stands

/**
 * Where a booking stands with its report, for the tutor: cancelled or moved
 * (no report can follow), completed (its report is in), report due (started,
 * the slot over and no report yet -- the API's own report_due, design B.1), or
 * where it stands as a class (the API's activity_state): in progress (started
 * by the tutor, so the report may be written now), ready to start, not
 * started yet, not started (the slot ended with no start), or upcoming. A
 * label only: the API decides what may be done.
 */
export function reportState(booking) {
  if (booking.status === 'CANCELLED' || booking.status === 'RESCHEDULED') {
    return { key: booking.status.toLowerCase(), ...bookingState(booking) };
  }
  if (booking.status === 'COMPLETED' || booking.has_report) {
    return { key: 'completed', label: 'Completed', variant: 'secondary' };
  }
  if (booking.report_due) return { key: 'report_due', label: 'Report due', variant: 'warning' };
  const state = booking.activity_state in STATE_KEYS ? booking.activity_state : 'UPCOMING';
  return { key: STATE_KEYS[state], ...bookingState({ activity_state: state }) };
}

// The key each state of a booked booking goes by on the tutor's screens.
const STATE_KEYS = {
  UPCOMING: 'upcoming',
  READY: 'ready',
  LATE: 'late',
  IN_PROGRESS: 'in_progress',
  NOT_STARTED: 'not_started',
};

/**
 * What the tutor is offered on a booking: write its report once they have
 * started it (never because its scheduled time has come), edit or download
 * it once in.
 */
export function reportActions(booking) {
  const hasReport = Boolean(booking.has_report);
  return {
    write: booking.status === 'BOOKED' && Boolean(booking.started_at) && !hasReport,
    edit: hasReport,
    pdf: hasReport,
  };
}

// What the tutor's screens call a booking's report: a Demo's is the tutor's
// feedback, a Diagnostic's the test's results. The report and its PDF keep
// their own titles (Demo Report, Academic Report).
export const REPORT_WORDS = {
  DEMO: {
    tab: 'Feedback',
    noun: 'feedback',
    page: 'Demo feedback',
    write: 'Submit Feedback',
    edit: 'Edit feedback',
    submit: 'Submit feedback',
  },
  DIAGNOSTIC: {
    tab: 'Results',
    noun: 'results',
    page: 'Diagnostic results',
    write: 'Enter Results',
    edit: 'Edit results',
    submit: 'Submit results',
  },
};

/** The tutor's words for `type`'s report (REPORT_WORDS), Demo's for an unknown type. */
export const reportWords = (type) => REPORT_WORDS[type] ?? REPORT_WORDS.DEMO;

/**
 * Where a booking's feedback (a Demo's) or results (a Diagnostic's) stand,
 * for its tutor: Submitted, at the report's version; Pending once the tutor
 * has started the class and no report is in -- `due` once the slot is over
 * (the API's report_due); After the class while a booked class has not been
 * started; and none (null) for a booking no report can follow: cancelled,
 * moved, or a slot that ended unstarted. Nothing is kept in between: the
 * report is saved whole, on submit, so there are no drafts.
 */
export function feedbackState(booking) {
  if (booking.has_report) return { key: 'submitted', label: 'Submitted', variant: 'success', version: booking.report_version };
  if (booking.report_due || reportActions(booking).write) {
    return { key: 'pending', label: 'Pending', variant: 'warning', due: Boolean(booking.report_due) };
  }
  if (booking.status === 'BOOKED' && booking.activity_state !== 'NOT_STARTED') {
    return { key: 'later', label: 'After the class', variant: 'outline' };
  }
  return null;
}

/** The Admin list's report column: the report's version, Report due, or nothing. */
export function reportBadge(booking) {
  if (booking.has_report) return { label: `Report v${booking.report_version}`, variant: 'success' };
  if (booking.report_due) return { label: 'Report due', variant: 'warning' };
  return null;
}

// --------------------------------------------------------------------- URLs

export const tutorReportUrl = (type, id) => `${tutorBookingUrl(type, id)}report/`;
export const tutorReportPreviewUrl = (type, id) => `${tutorReportUrl(type, id)}preview/`;
export const bookingReportUrl = (type, id) => `${bookingUrl(type, id)}report/`;

/** A report's PDF under ``reportUrl`` (the tutor's or the Admin's): as last saved, or as saved at ``version``. */
export function reportPdfUrl(reportUrl, version = null) {
  return version === null || version === undefined ? `${reportUrl}pdf/` : `${reportUrl}revisions/${version}/pdf/`;
}

// The lead's owner BDE (P9): the reports on one of their enquiries as they
// print, and each one's PDF as last saved -- the current version only.
export const bdeReportsUrl = (enquiryId) => `${enquiryUrl(enquiryId)}reports/`;
export const bdeReportPdfUrl = (type, id) => `${bdeBookingUrl(type, id)}report/pdf/`;
// The enquiry page telling the API it just sent the report to the parent (POST): ends the BDE's reminder to share it.
export const bdeReportShareUrl = (type, id) => `${bdeBookingUrl(type, id)}report/share/`;

const PAGE_SEGMENTS = { DEMO: 'demo', DIAGNOSTIC: 'diagnostic' };

/** The tutor's page for writing or editing a booking's report: /my-bookings/<demo|diagnostic>/<id>/report. */
export function tutorReportPagePath(type, id) {
  const segment = PAGE_SEGMENTS[type];
  if (!segment) throw new Error(`Unknown booking type: ${type}`);
  return `/my-bookings/${segment}/${id}/report`;
}

/** The booking type a report page's path names (``segment`` is demo or diagnostic), or null. */
export function reportTypeFromPath(segment) {
  return Object.keys(PAGE_SEGMENTS).find((type) => PAGE_SEGMENTS[type] === segment) ?? null;
}

/** The name a PDF is saved under when the server's own cannot be read: "Diagnostic-Report.pdf", "...-v2.pdf". */
export function reportPdfFallbackName(type, version = null) {
  const kind = type === 'DIAGNOSTIC' ? 'Diagnostic' : 'Demo';
  return version === null || version === undefined ? `${kind}-Report.pdf` : `${kind}-Report-v${version}.pdf`;
}

// ------------------------------------------------------------------- the PDF

/** The file name a Content-Disposition header gives, or null. */
export function filenameFromDisposition(header) {
  if (typeof header !== 'string') return null;
  const encoded = /filename\*\s*=\s*(?:UTF-8|utf-8)''([^;]+)/.exec(header);
  if (encoded) {
    try {
      return decodeURIComponent(encoded[1].trim());
    } catch {
      /* fall through to the plain name */
    }
  }
  const plain = /filename\s*=\s*"([^"]*)"|filename\s*=\s*([^;]+)/.exec(header);
  const name = plain ? (plain[1] ?? plain[2] ?? '').trim() : '';
  return name || null;
}

/**
 * What to tell someone whose PDF download failed. A PDF is fetched as a
 * blob, so a refusal's JSON body arrives as one too and is read here first.
 */
export async function reportPdfError(err) {
  const response = err?.response;
  if (!response) return 'Could not reach the server. Check your connection and try again.';
  const data = await jsonBody(response.data);
  const detail = typeof data.detail === 'string' ? data.detail : '';
  switch (response.status) {
    case 401:
      return 'Your session has ended. Sign in again to download the PDF.';
    case 403:
      return /credentials/i.test(detail)
        ? 'Your session has ended. Sign in again to download the PDF.'
        : 'You do not have access to this report.';
    case 404:
      if (data.error === 'NO_REPORT') return 'This booking has no report yet.';
      if (data.error === 'NO_VERSION') return 'That version of the report does not exist.';
      return 'This booking is not available to you any more.';
    case 429: {
      const seconds = /(\d+)\s*second/.exec(detail)?.[1];
      return seconds
        ? `Too many downloads in a short time. Try again in ${seconds} seconds.`
        : 'Too many downloads in a short time. Try again in a minute.';
    }
    default:
      return data.message || 'The PDF could not be made. Try again.';
  }
}

/**
 * ``err`` with its body read as the JSON it holds. A PDF is asked for as a
 * blob, so a refusal's JSON arrives as one too; read first, it gives
 * reportError its fields (a preview's VALIDATION_ERROR).
 */
export async function withJsonBody(err) {
  if (!err?.response) return err;
  return { ...err, response: { ...err.response, data: await jsonBody(err.response.data) } };
}

async function jsonBody(data) {
  if (data && typeof data === 'object' && typeof data.text === 'function') {
    try {
      return JSON.parse(await data.text());
    } catch {
      return {};
    }
  }
  return data && typeof data === 'object' ? data : {};
}

// ------------------------------------------------- sending it, by the BDE (P9)

const MESSAGE_KINDS = { DIAGNOSTIC: DIAGNOSTIC_ASSESSMENT_TYPE, DEMO: 'Demo Class' };

/**
 * The message Send via WhatsApp fills in (design A11): "Hello Asha Nair,
 * please find Riya's Diagnostic Test report from Eduport Plus attached." It
 * says the PDF is attached because the BDE attaches it, by hand, before
 * sending: a WhatsApp link carries no file.
 */
export function reportWhatsAppMessage(type, parentName, studentName) {
  const greeting = parentName ? `Hello ${parentName}` : 'Hello';
  return `${greeting}, please find ${studentName}'s ${MESSAGE_KINDS[type] ?? 'assessment'} report from Eduport Plus attached.`;
}

/**
 * Whether this browser can hand a PDF file to the device's share sheet (the
 * Web Share API with files): most phones can, some desktop browsers too, and
 * only on a secure page (HTTPS, or localhost). Where it cannot, Share PDF is
 * not offered.
 */
export function canSharePdf() {
  try {
    return (
      typeof navigator !== 'undefined' &&
      typeof navigator.share === 'function' &&
      typeof navigator.canShare === 'function' &&
      navigator.canShare({ files: [new File(['%PDF-'], 'report.pdf', { type: 'application/pdf' })] })
    );
  } catch {
    return false;
  }
}
