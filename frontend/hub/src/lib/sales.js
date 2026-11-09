// Sales Management: the /api/sales/ contract (backend sales/views.py) as the
// Hub uses it -- for administrators, the syllabuses on offer, each a
// published revision and at most one draft, and the global pricing, one
// version after another; for BDEs, the catalogue on sale they quote parents
// from. The API enforces every rule; this only decides what the Hub offers
// and how it reads.
import { SYLLABI } from '@/lib/enquiries';

export const SYLLABI_URL = '/api/sales/syllabi/';
export const PDF_PREVIEW_URL = `${SYLLABI_URL}pdf-preview/`;
export const PRICING_URL = '/api/sales/pricing/';
export const syllabusUrl = (id) => `${SYLLABI_URL}${id}/`;
// POST starts the next draft of a published syllabus, PUT saves the draft, DELETE discards it.
export const draftUrl = (id) => `${syllabusUrl(id)}draft/`;
export const publishUrl = (id) => `${syllabusUrl(id)}publish/`;
export const deactivateUrl = (id) => `${syllabusUrl(id)}deactivate/`;
export const reactivateUrl = (id) => `${syllabusUrl(id)}reactivate/`;
export const duplicateUrl = (id) => `${syllabusUrl(id)}duplicate/`;
export const revisionUrl = (id, number) => `${syllabusUrl(id)}revisions/${number}/`;
// What a syllabus offers (its published revision, else its draft), or one revision, as the customer PDF.
export const syllabusPdfUrl = (id) => `${syllabusUrl(id)}pdf/`;
export const revisionPdfUrl = (id, number) => `${revisionUrl(id, number)}pdf/`;

// The catalogue on sale (accounts.view_sales_catalogue): each syllabus as its published revision sells it,
// its PDF, and -- a Bridge Course -- the PDF of the days chosen ({ revision, chapter_ids }).
export const CATALOGUE_URL = '/api/sales/catalogue/';
export const catalogueUrl = (id) => `${CATALOGUE_URL}${id}/`;
export const cataloguePdfUrl = (id) => `${catalogueUrl(id)}pdf/`;
export const catalogueSelectionPdfUrl = (id) => `${catalogueUrl(id)}selection/pdf/`;

// Quotes (accounts.create_sales_quotes, manage_sales_quotes): what a parent was quoted, kept as it was issued.
// The API answers each caller with their own -- every one for a manager -- and only a manager cancels.
export const QUOTES_URL = '/api/sales/quotes/';
export const quoteUrl = (id) => `${QUOTES_URL}${id}/`;
export const quotePdfUrl = (id) => `${quoteUrl(id)}pdf/`;
export const quoteCancelUrl = (id) => `${quoteUrl(id)}cancel/`;
export const enquiryPlanUrl = (id) => `/api/sales/enquiries/${id}/plan/`;

// Catalogue PDFs require a staff session. Never put their URLs (or blob URLs)
// in parent messages: the file must be shared or attached by the BDE.
export function syllabusWhatsAppMessage(title, parentName) {
  return `${parentName ? `Hello ${parentName}` : 'Hello'}, here is ${title} from Eduport Plus. I will attach the syllabus PDF for your review.`;
}
export const QUOTE_STATUSES = [
  { value: 'ISSUED', label: 'Issued' },
  { value: 'CANCELLED', label: 'Cancelled' },
];
// The plan types that sell a whole course: every chapter, none chosen (backend sales.quotes.WHOLE_COURSE_PLANS).
export const WHOLE_COURSE_PLANS = ['REGULAR', 'REVISION', 'REGULAR_REVISION'];

export const SYLLABUS_STATUSES = [
  { value: 'DRAFT', label: 'Draft' },
  { value: 'PUBLISHED', label: 'Published' },
  { value: 'INACTIVE', label: 'Inactive' },
];

export const STRUCTURES = [
  {
    value: 'CHAPTER_WISE',
    label: 'Chapter-wise',
    description: 'Chapters with their Regular and Revision classes.',
  },
  {
    value: 'BRIDGE_COURSE',
    label: 'Bridge Course',
    description: 'A topic a day, each with its number of classes.',
  },
];

export const PLAN_TYPES = [
  { value: 'REGULAR', label: 'Regular', description: 'The full course: every chapter’s Regular classes.' },
  { value: 'REVISION', label: 'Revision', description: 'The exam-oriented course: every chapter’s Revision classes.' },
  {
    value: 'REGULAR_REVISION',
    label: 'Regular + Revision',
    description: 'Both courses together. The PDF shows the two packages.',
  },
  {
    value: 'CHAPTER_PLAN',
    label: 'Chapter Plan',
    description: 'Chosen chapters of this syllabus, priced per class. BDEs will pick the chapters when selling.',
  },
  {
    value: 'BRIDGE_COURSE',
    label: 'Bridge Course',
    description: 'Sold as the whole course, or by the day: BDEs choose the days when quoting.',
  },
];
// The plan types each structure offers: a Bridge Course is sold only as itself -- whole, or by the day
// (backend STRUCTURE_PLAN_TYPES).
export const STRUCTURE_PLAN_TYPES = {
  CHAPTER_WISE: ['REGULAR', 'REVISION', 'REGULAR_REVISION', 'CHAPTER_PLAN'],
  BRIDGE_COURSE: ['BRIDGE_COURSE'],
};
// The order the API stores them in (backend PlanType).
const PLAN_TYPE_ORDER = ['REGULAR', 'REVISION', 'CHAPTER_PLAN', 'BRIDGE_COURSE', 'REGULAR_REVISION'];
// The packages a card is printed for, and so the only ones a single-payment privilege can apply to
// (backend PRIVILEGE_PLAN_TYPES): Regular + Revision prints the Regular and Revision cards.
export const PRIVILEGE_PLAN_TYPES = ['REGULAR', 'REVISION', 'BRIDGE_COURSE'];

// The curricula, as the lead forms and the Hub name them.
export const BOARDS = SYLLABI.map((board) => ({ value: board, label: board }));
export const GRADES = Array.from({ length: 12 }, (_, index) => ({ value: String(index + 1), label: `Grade ${index + 1}` }));
export const SYLLABUS_VERSIONS = ['New Syllabus', 'Old Syllabus'];

// The reference PDFs' wording, which the API fills in when a line is left empty.
export const SUBTITLES = {
  CHAPTER_WISE: 'Detailed Chapter-Wise 1:1 Learning Plan',
  BRIDGE_COURSE: 'Detailed Bridge Course Curriculum',
};
export const packageTitleFor = (title) => `${title || 'Grade 6 CBSE'} – 1:1 Tuition Packages & Fee Details`;
export const defaultInclusions = (board) => [
  'Personalized 1:1 live sessions',
  `Structured ${board || 'CBSE'} aligned learning`,
  'Dedicated mentor support',
];
export const MAX_INCLUSIONS = 6;
export const MAX_CHAPTERS = 60;

export const labelOf = (options, value) => options.find((option) => option.value === value)?.label ?? value ?? '';
export const planTypeLabel = (value) => labelOf(PLAN_TYPES, value);
export const structureLabel = (value) => labelOf(STRUCTURES, value);
export const orderedPlanTypes = (planTypes) => PLAN_TYPE_ORDER.filter((value) => planTypes.includes(value));

/** A refusal from the API as `{ status, code, message, fields, problems }` (fields: the API's per-field errors). */
export function salesError(err, fallback) {
  const response = err?.response;
  const data = response?.data ?? {};
  return {
    status: response?.status ?? null,
    code: typeof data.error === 'string' ? data.error : null,
    message: response
      ? data.message || data.detail || fallback
      : 'Could not reach the server. Check your connection and try again.',
    fields: data.fields && typeof data.fields === 'object' && !Array.isArray(data.fields) ? data.fields : {},
    problems: Array.isArray(data.problems) ? data.problems : [],
  };
}

/** The first message of an API field error (a list of strings, or one). */
export function firstMessage(value) {
  if (Array.isArray(value)) return typeof value[0] === 'string' ? value[0] : '';
  return typeof value === 'string' ? value : '';
}

/** A failed PDF request's JSON body: a PDF is fetched as a blob, so a refusal's body arrives as one too. */
export async function pdfErrorBody(err) {
  let data = err?.response?.data;
  if (data && typeof data === 'object' && typeof data.text === 'function') {
    try {
      data = JSON.parse(await data.text());
    } catch {
      data = {};
    }
  }
  return data && typeof data === 'object' ? data : {};
}

/** Whether a PDF request was refused only for a stale CSRF token (lib/api retries JSON requests itself, not blobs). */
export async function isCsrfFailure(err) {
  if (err?.response?.status !== 403) return false;
  const data = await pdfErrorBody(err);
  return data.error === 'CSRF_FAILED' || String(data.detail ?? '').startsWith('CSRF Failed');
}

/** What to tell someone whose syllabus PDF failed. */
export async function salesPdfError(err) {
  const response = err?.response;
  if (!response) return 'Could not reach the server. Check your connection and try again.';
  const data = await pdfErrorBody(err);
  const detail = typeof data.detail === 'string' ? data.detail : '';
  switch (response.status) {
    case 400:
      // Days of a Bridge Course the API will not draw say why; anything else is the editor's content.
      if (data.error === 'INVALID_SELECTION' && data.message) return data.message;
      return 'Check the syllabus details: the PDF cannot be drawn until they are complete.';
    case 401:
      return 'Your session has ended. Sign in again to see the PDF.';
    case 403:
      if (detail.startsWith('CSRF Failed') || data.error === 'CSRF_FAILED') {
        return 'The request could not be verified. Refresh the page and try again.';
      }
      return /credentials/i.test(detail) ? 'Your session has ended. Sign in again to see the PDF.' : 'You do not have access to syllabuses.';
    case 404:
      return 'This syllabus or revision no longer exists.';
    case 409:
      return data.message || 'Set up the global pricing first: the PDF prices every package.';
    case 429: {
      const seconds = /(\d+)\s*second/.exec(detail)?.[1];
      return seconds ? `Too many PDFs in a short time. Try again in ${seconds} seconds.` : 'Too many PDFs in a short time. Try again in a minute.';
    }
    default:
      return 'Could not draw the PDF. Try again.';
  }
}

/** Save `blob` as `name`: a link to an object URL, clicked once, then freed. */
export function saveBlob(blob, name) {
  const href = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = href;
  anchor.download = name;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(href), 1000);
}

// ---------------------------------------------------------------- numbers
// Class counts are whole or half classes; amounts are exact decimals. The
// arithmetic below is done in whole half-classes and cents (BigInt), so the
// editor's prices agree with the API's to the last fil (backend sales.pricing).

const CLASSES_RE = /^\s*(\d{1,2})(?:\.([05]))?\s*$/;
const MONEY_RE = /^\s*(\d{1,8})(?:\.(\d{1,2}))?\s*$/;

/** A class count ("1.5") in half classes (3n), or null when it is not a whole or half number up to 99.5. */
export function toHalves(text) {
  const match = CLASSES_RE.exec(String(text ?? ''));
  if (!match) return null;
  return BigInt(match[1]) * 2n + (match[2] === '5' ? 1n : 0n);
}

/** Half classes (3n) as a class count ("1.5"). */
export function fromHalves(halves) {
  const whole = halves / 2n;
  return halves % 2n ? `${whole}.5` : `${whole}`;
}

/** An amount ("35.25") in cents (3525n), or null. */
export function toCents(text) {
  const match = MONEY_RE.exec(String(text ?? ''));
  if (!match) return null;
  return BigInt(match[1]) * 100n + BigInt((match[2] ?? '').padEnd(2, '0'));
}

/** n / 200 as plain digits: a whole number of cents times half classes, exactly ("687.375"). */
function fromTwoHundredths(n) {
  const thousandths = n * 5n;
  const whole = thousandths / 1000n;
  const fraction = (thousandths % 1000n).toString().padStart(3, '0').replace(/0+$/, '');
  return fraction ? `${whole}.${fraction}` : `${whole}`;
}

/** Plain digits grouped in thousands: "1330.5" is "1,330.5". */
export function groupDigits(text) {
  const [whole, fraction] = String(text).split('.');
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  return fraction ? `${grouped}.${fraction}` : grouped;
}

/** "AED 1,330", "AED 122.50", "AED 687.375" -- an amount as the PDF prints it: whole cents, every fil kept. */
export function formatAmount(value, currency) {
  if (value === null || value === undefined) return '—';
  const [whole, fraction] = String(value).split('.');
  return `${currency} ${groupDigits(whole)}${fraction ? `.${fraction.padEnd(2, '0')}` : ''}`;
}

/** "38 Classes", "1 Class". */
export const classesLabel = (value) => `${value} ${value === '1' ? 'Class' : 'Classes'}`;

/** The total of each column over `chapters` (form rows or API rows), in half classes; an unreadable count adds nothing. */
export function chapterTotals(chapters) {
  const totals = { regular: 0n, revision: 0n, bridge: 0n };
  for (const chapter of chapters) {
    for (const column of Object.keys(totals)) {
      totals[column] += toHalves(chapter[`${column}_classes`]) ?? 0n;
    }
  }
  return totals;
}

/** The packages the PDF shows for `planTypes`: Regular and Revision for either alone or together, and a Bridge Course. */
export function cardPlanTypes(planTypes) {
  const cards = [];
  if (planTypes.includes('REGULAR') || planTypes.includes('REGULAR_REVISION')) cards.push('REGULAR');
  if (planTypes.includes('REVISION') || planTypes.includes('REGULAR_REVISION')) cards.push('REVISION');
  if (planTypes.includes('BRIDGE_COURSE')) cards.push('BRIDGE_COURSE');
  return cards;
}

export const PACKAGE_TITLES = {
  REGULAR: 'Regular Course Package',
  REVISION: 'Revision Course (Exam Oriented) Package',
  BRIDGE_COURSE: 'Bridge Course Package',
};
// A Bridge Course's card when it is bought by the day (backend sales.pricing.SELECTED_DAYS_TITLE).
export const SELECTED_DAYS_TITLE = 'Bridge Course – Selected Days Package';
// A Chapter Plan's card: the chapters chosen (backend sales.quotes.CHAPTER_PLAN_TITLE).
export const CHAPTER_PLAN_TITLE = 'Chapter Plan Package';

/**
 * One package card -- `halves` classes of `planType` at `pricing`'s offer fee
 * (`fee`, in cents) -- as the API prices it: the total exactly, and the
 * single-payment price `percent` (in hundredths of a percent) off it, worked
 * out exactly, then rounded to the nearest whole currency unit (a half rounds
 * up), when the pricing gives `planType` the privilege.
 */
function pricedCard(planType, title, halves, fee, percent, pricing) {
  const total = fee * halves; // over 200
  let singlePayment = null;
  if (percent > 0n && (pricing.single_payment_plan_types ?? []).includes(planType)) {
    // In 1/2,000,000ths of a unit; adding half a unit before dividing rounds a half up.
    const price = (total * (10000n - percent) + 1000000n) / 2000000n;
    singlePayment = { price: price.toString(), saving: fromTwoHundredths(total - price * 200n) };
  }
  return {
    plan_type: planType,
    title,
    classes: fromHalves(halves),
    fee_per_class: fromTwoHundredths(fee * 2n),
    total: fromTwoHundredths(total),
    single_payment: singlePayment,
  };
}

/**
 * The packages `planTypes` over `chapters` cost at `pricing` (the API's
 * pricing version), as the API prices them: the offer fee per class, exactly,
 * and the single-payment price -- `single_payment_percent` off, worked out
 * exactly, then rounded to the nearest whole currency unit (a half rounds up)
 * -- for the plan types it lists.
 */
export function packagePrices(planTypes, chapters, pricing) {
  const fee = toCents(pricing?.offer_fee);
  if (fee === null) return [];
  const percent = toCents(pricing.single_payment_percent) ?? 0n; // in hundredths of a percent
  const totals = chapterTotals(chapters);
  const columns = { REGULAR: 'regular', REVISION: 'revision', BRIDGE_COURSE: 'bridge' };
  return cardPlanTypes(planTypes).map((planType) =>
    pricedCard(planType, PACKAGE_TITLES[planType], totals[columns[planType]], fee, percent, pricing)
  );
}

/**
 * A Bridge Course bought by the day, priced as the API prices it (backend
 * services.selection_data): the `days` (the revision's chapters, in the
 * course's order) whose ids are in `selectedIds` -- in the course's order,
 * whatever the order chosen -- their classes, and their package at `pricing`
 * (null without one). Every day chosen is the whole course: its own package,
 * exactly as before.
 */
export function bridgeSelection(days, selectedIds, pricing) {
  const chosen = new Set(selectedIds);
  const picked = days.filter((day) => chosen.has(day.id));
  const fullCourse = days.length > 0 && picked.length === days.length;
  const halves = picked.reduce((sum, day) => sum + (toHalves(day.bridge_classes) ?? 0n), 0n);
  const fee = toCents(pricing?.offer_fee);
  const pricedPackage =
    fee === null
      ? null
      : pricedCard(
          'BRIDGE_COURSE',
          fullCourse ? PACKAGE_TITLES.BRIDGE_COURSE : SELECTED_DAYS_TITLE,
          halves,
          fee,
          toCents(pricing.single_payment_percent) ?? 0n,
          pricing
        );
  return { days: picked, fullCourse, classes: fromHalves(halves), package: pricedPackage };
}

/**
 * A Chapter Plan, priced as the API prices a quote of one (backend
 * sales.quotes): the `chapters` whose ids are in `selectedIds`, in the
 * course's order, their Regular classes at `pricing`'s offer fee (null without
 * one). No single-payment privilege names a Chapter Plan.
 */
export function chapterPlanSelection(chapters, selectedIds, pricing) {
  const chosen = new Set(selectedIds);
  const picked = chapters.filter((chapter) => chosen.has(chapter.id));
  const halves = picked.reduce((sum, chapter) => sum + (toHalves(chapter.regular_classes) ?? 0n), 0n);
  const fee = toCents(pricing?.offer_fee);
  const pricedPackage =
    fee === null ? null : pricedCard('CHAPTER_PLAN', CHAPTER_PLAN_TITLE, halves, fee, toCents(pricing.single_payment_percent) ?? 0n, pricing);
  return { days: picked, fullCourse: chapters.length > 0 && picked.length === chapters.length, classes: fromHalves(halves), package: pricedPackage };
}

/** An exact amount ("122.5") in thousandths (122500n): a fee with cents times half classes has at most three places. */
function toThousandths(text) {
  const [whole, fraction = ''] = String(text).split('.');
  return BigInt(whole) * 1000n + BigInt(fraction.padEnd(3, '0').slice(0, 3));
}

function fromThousandths(n) {
  const fraction = (n % 1000n).toString().padStart(3, '0').replace(/0+$/, '');
  return fraction ? `${n / 1000n}.${fraction}` : `${n / 1000n}`;
}

/**
 * What a quote of `planType` would say, as the API's quote_snapshot works it
 * out: its packages (Regular + Revision two, each rounded on its own), their
 * classes and total, the single-payment saving and what is payable at once.
 * `selectedIds` are a Chapter Plan's chapters or a Bridge Course's days (none,
 * or every day: the whole course). Null without pricing.
 */
export function quotePreview(planType, chapters, selectedIds, pricing) {
  if (toCents(pricing?.offer_fee) === null) return null;
  let lines;
  let fullCourse = true;
  if (planType === 'CHAPTER_PLAN') {
    lines = [chapterPlanSelection(chapters, selectedIds, pricing).package];
    fullCourse = chapters.length > 0 && selectedIds.length === chapters.length;
  } else if (planType === 'BRIDGE_COURSE') {
    const picked = bridgeSelection(chapters, selectedIds.length ? selectedIds : chapters.map((chapter) => chapter.id), pricing);
    lines = [picked.package];
    fullCourse = picked.fullCourse;
  } else {
    lines = packagePrices([planType], chapters, pricing);
  }
  const total = lines.reduce((sum, line) => sum + toThousandths(line.total), 0n);
  const saving = lines.reduce((sum, line) => sum + (line.single_payment ? toThousandths(line.single_payment.saving) : 0n), 0n);
  // A package's classes may pass 99.5 (a whole course): read them whole, not as a chapter's count.
  const halves = lines.reduce((sum, line) => {
    const [whole, fraction] = line.classes.split('.');
    return sum + BigInt(whole) * 2n + (fraction === '5' ? 1n : 0n);
  }, 0n);
  return {
    lines,
    fullCourse,
    classes: fromHalves(halves),
    total_fee: fromThousandths(total),
    single_payment_saving: fromThousandths(saving),
    payable_amount: fromThousandths(total - saving),
  };
}

/** A quote's plan as one line: "Bridge Course · selected days", "Chapter Plan", "Regular + Revision". */
export function quotePlanLabel(quote) {
  const label = planTypeLabel(quote.plan_type);
  if (quote.plan_type === 'BRIDGE_COURSE') return quote.full_course ? 'Full Bridge Course' : 'Bridge Course · Selected Chapters';
  return label;
}

/** "Riya Nair (parent of Arjun)": the enquiry a quote answers ('' for none). */
export function enquiryLabel(lead) {
  if (!lead) return '';
  return lead.student_name ? `${lead.parent_name} (parent of ${lead.student_name})` : lead.parent_name;
}

// ---------------------------------------------------------------- the editor's form

let rowKey = 0;
/** A chapter row of the editor: its `key` names it while it moves; `id` is the draft's row, if saved. */
export function chapterRow(chapter = {}) {
  rowKey += 1;
  const count = (value) => (value === null || value === undefined ? '' : String(value));
  return {
    key: `row-${rowKey}`,
    id: chapter.id ?? null,
    name: chapter.name ?? '',
    regular_classes: count(chapter.regular_classes),
    revision_classes: count(chapter.revision_classes),
    bridge_classes: count(chapter.bridge_classes),
  };
}

/** A new syllabus's form. */
export function emptyForm() {
  return {
    title: '',
    subtitle: '',
    package_title: '',
    grade: '',
    board: 'CBSE',
    syllabus_version: '',
    structure: 'CHAPTER_WISE',
    plan_types: ['REGULAR', 'REVISION', 'REGULAR_REVISION'],
    inclusions: defaultInclusions('CBSE'),
    chapters: [chapterRow()],
  };
}

/** A revision from the API as the editor's form. */
export function formFrom(revision) {
  return {
    title: revision.title,
    subtitle: revision.subtitle,
    package_title: revision.package_title,
    grade: String(revision.grade),
    board: revision.board,
    syllabus_version: revision.syllabus_version ?? '',
    structure: revision.structure,
    plan_types: [...revision.plan_types],
    inclusions: [...revision.inclusions],
    chapters: revision.chapters.map(chapterRow),
  };
}

/** The editor's form as the API takes it (SyllabusContentSerializer): counts of the form's structure only. */
export function payloadOf(form) {
  const bridge = form.structure === 'BRIDGE_COURSE';
  const count = (value) => (String(value ?? '').trim() === '' ? null : String(value).trim());
  return {
    title: form.title.trim(),
    subtitle: form.subtitle.trim(),
    package_title: form.package_title.trim(),
    grade: form.grade === '' ? null : Number(form.grade),
    board: form.board,
    syllabus_version: form.syllabus_version.trim(),
    structure: form.structure,
    plan_types: bridge ? ['BRIDGE_COURSE'] : orderedPlanTypes(form.plan_types),
    inclusions: form.inclusions.map((line) => line.trim()).filter(Boolean),
    chapters: form.chapters.map((chapter) => ({
      ...(chapter.id ? { id: chapter.id } : {}),
      name: chapter.name.trim(),
      ...(bridge
        ? { bridge_classes: count(chapter.bridge_classes) }
        : { regular_classes: count(chapter.regular_classes), revision_classes: count(chapter.revision_classes) }),
    })),
  };
}

/** Whether two forms would save the same content. */
export function sameContent(a, b) {
  return JSON.stringify(payloadOf(a)) === JSON.stringify(payloadOf(b));
}

/**
 * What the form needs before it is sent -- the API checks it all again:
 * `{ field: message }`, a chapter's under `chapters.<index>.<field>`.
 */
export function formErrors(form) {
  const errors = {};
  if (!form.title.trim()) errors.title = 'Enter the title the PDF shows.';
  if (!form.grade) errors.grade = 'Choose the grade.';
  if (!form.board) errors.board = 'Choose the board.';
  if (form.structure === 'CHAPTER_WISE' && !form.plan_types.length) errors.plan_types = 'Choose at least one plan type.';
  if (!form.chapters.length) errors.chapters = 'Add at least one chapter.';
  const columns = form.structure === 'BRIDGE_COURSE' ? ['bridge_classes'] : ['regular_classes', 'revision_classes'];
  form.chapters.forEach((chapter, index) => {
    if (!chapter.name.trim()) errors[`chapters.${index}.name`] = 'Enter the chapter name.';
    for (const column of columns) {
      const value = String(chapter[column] ?? '').trim();
      if (value === '') errors[`chapters.${index}.${column}`] = 'Enter the number of classes.';
      else if (toHalves(value) === null) errors[`chapters.${index}.${column}`] = 'Use whole or half classes, such as 2 or 1.5.';
    }
  });
  return errors;
}

/** The API's field errors (`fields`) flattened as formErrors gives them. */
export function apiFieldErrors(fields) {
  const errors = {};
  for (const [field, value] of Object.entries(fields ?? {})) {
    if (field === 'chapters' && value && typeof value === 'object' && !Array.isArray(value)) {
      for (const [index, rowErrors] of Object.entries(value)) {
        if (rowErrors && typeof rowErrors === 'object' && !Array.isArray(rowErrors)) {
          for (const [column, messages] of Object.entries(rowErrors)) errors[`chapters.${index}.${column}`] = firstMessage(messages);
        } else {
          errors.chapters = firstMessage(rowErrors);
        }
      }
    } else {
      errors[field] = firstMessage(value) || 'Check this field.';
    }
  }
  return errors;
}
