/**
 * The student profile's Documents tab.
 *
 * There is no documents table in the API: every file in the product is
 * already attached to the thing it belongs to — a class's notes / recording /
 * homework upload, an exam's question paper, an additional exam's question
 * paper and answer sheet, a homework submission. This collects those into one
 * ledger from the payloads the other tabs already fetched, which also means
 * the ledger inherits their access rules for free: a tutor is served no
 * exams, and a mentor is served a homework submission only once it is scored,
 * so neither can appear here.
 *
 * Pasted links are deliberately not documents. A link has no name, type or
 * size, and it is shown where it belongs: on the class itself.
 */

export const DOCUMENT_SOURCES = [
  { key: 'session', label: 'Class content' },
  { key: 'exam', label: 'Exams' },
  { key: 'additional_exam', label: 'Additional exams' },
  { key: 'homework', label: 'Homework' },
];

const SESSION_FIELD_LABEL = { notes: 'Notes', recording: 'Recording', homework: 'Homework' };
const EXAM_KIND_LABEL = { question_paper: 'Question paper', answer_sheet: 'Answer sheet' };

function toDocument(file, { source, kind, context, url }) {
  if (!file) return null;
  const href = (url ?? file.url ?? '').trim();
  if (!href) return null;
  return {
    id: `${source}:${file.id}`,
    name: file.file_name || 'Untitled file',
    contentType: file.content_type || '',
    sizeBytes: file.size_bytes ?? null,
    createdAt: file.created_at || null,
    url: href,
    source,
    kind,
    context,
  };
}

/**
 * Build the ledger, newest first.
 *
 * `sessions`, `exams`, `additionalExams` and `homework` are the raw API rows
 * the matching tabs render; any of them may be missing (its tab has not been
 * opened, or the role cannot see it), in which case that source contributes
 * nothing rather than erroring.
 */
export function collectDocuments({ sessions = [], exams = [], additionalExams = [], homework = [] } = {}) {
  const documents = [];

  for (const session of sessions) {
    const files = session.content_files || {};
    for (const [field, file] of Object.entries(files)) {
      // `url` on a content file is the session's link column, which an upload
      // wrote with the path of its authenticated download view.
      documents.push(
        toDocument(file, {
          source: 'session',
          kind: SESSION_FIELD_LABEL[field] || field,
          context: session.title,
        })
      );
    }
  }

  for (const exam of exams) {
    for (const file of exam.files || []) {
      documents.push(
        toDocument(file, {
          source: 'exam',
          kind: EXAM_KIND_LABEL[file.kind] || 'Question paper',
          context: exam.chapter_name,
        })
      );
    }
  }

  for (const exam of additionalExams) {
    for (const file of [...(exam.question_paper || []), ...(exam.answer_sheet || [])]) {
      documents.push(
        toDocument(file, {
          source: 'additional_exam',
          kind: EXAM_KIND_LABEL[file.kind] || 'File',
          context: exam.title,
        })
      );
    }
  }

  for (const row of homework) {
    for (const file of row.submission || []) {
      documents.push(
        toDocument(file, {
          source: 'homework',
          kind: 'Submission',
          context: row.session?.title,
        })
      );
    }
  }

  return documents
    .filter(Boolean)
    .sort((a, b) => new Date(b.createdAt || 0) - new Date(a.createdAt || 0));
}

/** A short, human file type from a MIME type ("application/pdf" -> "PDF"). */
export function documentTypeLabel(contentType) {
  const mime = (contentType || '').toLowerCase();
  if (!mime) return '—';
  if (mime === 'application/pdf') return 'PDF';
  const [group, subtype = ''] = mime.split('/');
  if (group === 'image') return subtype.toUpperCase() || 'Image';
  if (group === 'video') return subtype.toUpperCase() || 'Video';
  if (group === 'audio') return subtype.toUpperCase() || 'Audio';
  return subtype.split(/[.+]/).pop().toUpperCase() || group.toUpperCase();
}
