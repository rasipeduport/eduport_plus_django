"""
Class-quota sync: the enrolment sheet is the source of truth for what a
student has paid for.

``Student.total_class_quota`` used to be typed in by hand, through the Hub's
"Top-up Class Quota" dialog. It is now derived from one column of the
enrolment sheet the sales team already maintains:

    O  "No of classes paid for"          -> Student.total_class_quota
    N  "Actual No of classes purchased"  -> deliberately NOT read

N records what was *ordered*, which can exceed what has been *paid for*, and
only the paid figure may be spent. Reading N would let a student book classes
nobody has paid for, so it stays out of this module entirely.

Nothing downstream of the column changes. Quota is still one integer on the
student, still consumed in HOURS by ``sessions.services.calculate_credits_used``
(a 1.5-hour class still costs 1.5), and still read from Postgres on every
request -- no API path talks to Google.

Written to fail safe, in this order:

    fetch the whole sheet once
        -> group rows by student code, summing the numeric paid figures
        -> resolve the students in one query
        -> compute every update in memory
        -> apply them in a single transaction

So a Sheets outage, a renamed tab or a bad credential leaves every stored
quota exactly as it was: the run aborts before the first write. Anything the
sheet does not clearly state -- a blank cell, the word "Token", a code with no
row -- is skipped and reported, never turned into a silent zero.
"""
import logging
from dataclasses import asdict, dataclass, field

from django.db import transaction
from django.utils import timezone

from invitations.sheets import (
    COL_CLASSES_PAID_FOR,
    COL_STUDENT_CODE,
    GoogleSheetsService,
)

from .models import Student

logger = logging.getLogger(__name__)


@dataclass
class QuotaSyncReport:
    """
    What one run did. Every list here is a *skip* -- a row or a student the
    sync chose not to act on -- so a short report means a clean sheet.
    """
    rows_processed: int = 0
    codes_in_sheet: int = 0
    students_updated: int = 0
    students_unchanged: int = 0
    students_not_in_sheet: int = 0

    # Diagnostics, all of them skips.
    rows_without_code: int = 0
    codes_not_in_db: list = field(default_factory=list)
    codes_without_numeric_value: list = field(default_factory=list)
    non_numeric_values: list = field(default_factory=list)
    duplicate_codes: list = field(default_factory=list)

    # (student_code, old quota, new quota) for every student actually changed.
    changes: list = field(default_factory=list)

    dry_run: bool = False
    failed: bool = False
    error: str = None

    def as_dict(self):
        """JSON-safe form, for the Celery task's return value."""
        return asdict(self)


def _cell(row, index):
    """One cell as a stripped string; '' when the row is short or empty."""
    if len(row) > index:
        return str(row[index]).strip()
    return ""


def parse_paid_classes(raw):
    """
    One "No of classes paid for" cell as a number of classes, or ``None`` when
    the cell does not hold a number at all.

    ``"0"`` returns 0.0, not None: a recorded zero is a real figure (paid for
    nothing yet) and must be allowed to drive the quota to zero. A blank cell
    is the caller's business -- it checks for that before asking here, so a
    ``None`` from this function always means "there was text, and it was not a
    number" (``Token``, a note, a stray word) and is always worth reporting.
    """
    text = (raw or '').strip()
    if not text:
        return None
    try:
        return float(text.replace(',', ''))
    except ValueError:
        return None


def _total_to_quota(code, total):
    """
    A summed paid-classes figure as the integer the column stores.

    Both adjustments are logged rather than applied quietly: the sheet is typed
    in by hand, and a fractional or negative class count is a data-entry
    problem somebody should see, not something to absorb in silence.
    """
    quota = int(round(total))
    if quota != total:
        logger.warning(
            "Quota sync: %s has a fractional classes-paid-for total (%s); storing %s.",
            code, total, quota,
        )
    if quota < 0:
        logger.warning(
            "Quota sync: %s has a negative classes-paid-for total (%s); storing 0.",
            code, quota,
        )
        quota = 0
    return quota


def _reduce_values(code, values):
    """
    A student's collected column-O figures -> the integer quota they imply, or
    ``None`` when the sheet states no number for them at all.

    THE one place the business rule lives. Both callers go through it:
    ``sync_student_quotas_from_sheet`` (periodically) and ``quota_for_code``
    (at enrolment), so the duplicate-row sum, the rounding and the clamp can
    never diverge between the two.

    ``None`` means "the sheet does not say", which the two callers are right to
    read differently: the sync leaves a stored quota untouched, while enrolment
    has nothing to preserve and starts the student at 0.
    """
    if not values:
        return None
    return _total_to_quota(code, sum(values))


def quota_for_code(rows, student_code):
    """
    The quota one student code is owed by these sheet rows, or ``None`` when no
    row states a number for it.

    Used by the enrolment flow to initialise ``Student.total_class_quota`` the
    moment a student is invited, so a new student is not stuck at 0 until the
    next scheduled sync. ``rows`` is passed in rather than fetched so the
    caller's single ``fetch_enrollment_rows()`` serves both the profile lookup
    and this.
    """
    key = (student_code or '').strip().upper()
    if not key:
        return None
    return _reduce_values(key, group_paid_classes_by_code(rows).get(key, []))


def _students_by_code():
    """
    Every student keyed by their normalised code, in ONE query.

    Codes are matched case- and whitespace-insensitively because both sides are
    typed in by hand. ``student_code`` is unique in the database, but only
    exactly -- two rows differing in case would collide here, so that is
    reported and the first kept rather than letting the later one win silently.
    """
    by_code = {}
    for student in Student.objects.all():
        key = (student.student_code or '').strip().upper()
        if not key:
            continue
        if key in by_code:
            logger.warning(
                "Quota sync: students %s and %s both normalise to the code %r; "
                "syncing the first only.",
                by_code[key].id, student.id, key,
            )
            continue
        by_code[key] = student
    return by_code


def group_paid_classes_by_code(rows, report=None):
    """
    Sheet rows -> ``{student_code: [numeric paid figures]}``, codes normalised.

    A code is registered the moment it appears, even when its paid figure is
    unusable, so "this student has rows but none of them say a number" stays
    distinguishable from "this student is not in the sheet at all" -- the two
    cases are both skips, but only the first is a data-entry problem.

    ``report`` is optional: the periodic sync passes its own to collect the
    diagnostics, while the enrolment lookup wants only the numbers. Either way
    a non-numeric cell is logged as it is read, so "Token" is never silently
    swallowed by either caller.
    """
    report = report if report is not None else QuotaSyncReport()
    grouped = {}
    row_counts = {}

    for row in rows:
        code = _cell(row, COL_STUDENT_CODE).upper()
        if not code:
            report.rows_without_code += 1
            continue

        row_counts[code] = row_counts.get(code, 0) + 1
        grouped.setdefault(code, [])

        raw = _cell(row, COL_CLASSES_PAID_FOR)
        if not raw:
            # Nothing recorded on this row. Normal for a row that is not a
            # payment, and not a statement that zero was paid.
            continue

        value = parse_paid_classes(raw)
        if value is None:
            report.non_numeric_values.append([code, raw])
            logger.warning(
                "Quota sync: %s has a non-numeric classes-paid-for value %r; "
                "it does not count towards the quota.",
                code, raw,
            )
            continue

        grouped[code].append(value)

    report.codes_in_sheet = len(grouped)
    # One code per row is the norm; several rows mean several paid entries,
    # which the business rule says to add up rather than treat as a conflict.
    report.duplicate_codes = sorted(code for code, n in row_counts.items() if n > 1)
    return grouped


# A sheet row exists for every enquiry, not just every enrolled student, so
# the "not enrolled" list is long and mostly uninteresting. Logged hourly, it
# would bury the lines that matter.
_MAX_CODES_LOGGED = 15


def format_code_list(codes):
    """A code list for one log line or one command line: the first few, then a count."""
    shown = ", ".join(codes[:_MAX_CODES_LOGGED])
    extra = len(codes) - _MAX_CODES_LOGGED
    return f"{shown} and {extra} more" if extra > 0 else shown


def _log_summary(report):
    if report.failed:
        return

    verb = "would update" if report.dry_run else "updated"
    logger.info(
        "Quota sync: %d sheet rows, %d student codes, %s %d student(s), %d unchanged, "
        "%d student(s) absent from the sheet (left as they were).",
        report.rows_processed, report.codes_in_sheet, verb,
        report.students_updated, report.students_unchanged,
        report.students_not_in_sheet,
    )
    for code, old, new in report.changes:
        logger.info("Quota sync: %s total_class_quota %s -> %s.", code, old, new)
    if report.duplicate_codes:
        logger.info(
            "Quota sync: %d code(s) appeared on more than one row and were summed: %s.",
            len(report.duplicate_codes), format_code_list(report.duplicate_codes),
        )
    if report.rows_without_code:
        logger.warning(
            "Quota sync: %d row(s) had no student code and were skipped.",
            report.rows_without_code,
        )
    if report.codes_not_in_db:
        # Expected and harmless: a sheet row is written at enquiry time, long
        # before (or without) the student ever enrolling. INFO, not WARNING.
        logger.info(
            "Quota sync: %d sheet code(s) match no enrolled student and were skipped: %s.",
            len(report.codes_not_in_db), format_code_list(report.codes_not_in_db),
        )
    if report.codes_without_numeric_value:
        logger.warning(
            "Quota sync: %d code(s) had no numeric classes-paid-for value on any row; "
            "their stored quota was left unchanged: %s.",
            len(report.codes_without_numeric_value),
            format_code_list(report.codes_without_numeric_value),
        )
    if report.non_numeric_values:
        # Each one was named as it was read; this is only the tally.
        logger.warning(
            "Quota sync: %d non-numeric classes-paid-for cell(s) were not counted.",
            len(report.non_numeric_values),
        )


def sync_student_quotas_from_sheet(dry_run=False):
    """
    Sync every enrolled student's ``total_class_quota`` from the enrolment
    sheet's "No of classes paid for" column. Returns a ``QuotaSyncReport``.

    Never raises: a failure to read the sheet is reported on the returned
    object (``failed``/``error``) with no database write attempted, because the
    caller is a scheduled job whose correct response to an outage is to change
    nothing and try again on the next tick.

    ``dry_run`` computes the whole result and logs it without writing, which is
    how the management command's ``--dry-run`` previews a first sync.
    """
    report = QuotaSyncReport(dry_run=dry_run)

    try:
        rows = GoogleSheetsService.fetch_enrollment_rows()
    except Exception as exc:
        report.failed = True
        report.error = f"{type(exc).__name__}: {exc}"
        logger.exception(
            "Quota sync ABORTED: the enrolment sheet could not be read. "
            "No student quota was changed."
        )
        return report

    report.rows_processed = len(rows)
    grouped = group_paid_classes_by_code(rows, report)
    students = _students_by_code()
    report.students_not_in_sheet = len(set(students) - set(grouped))

    now = timezone.now()
    updates = []
    for code in sorted(grouped):
        values = grouped[code]
        student = students.get(code)
        if student is None:
            # In the sheet, not enrolled: an enquiry or a future student.
            report.codes_not_in_db.append(code)
            continue
        quota = _reduce_values(code, values)
        if quota is None:
            # Every row for this student was blank or unparseable. Leaving the
            # stored quota alone is the only safe answer -- an empty cell is
            # not a statement that nothing was paid for. (Enrolment reads the
            # same None differently: a brand-new student starts at 0.)
            report.codes_without_numeric_value.append(code)
            continue

        if quota == student.total_class_quota:
            report.students_unchanged += 1
            continue

        report.changes.append([code, student.total_class_quota, quota])
        student.total_class_quota = quota
        # bulk_update does not fire `auto_now`, so the column is set by hand to
        # keep "when did this row last change" honest.
        student.updated_at = now
        updates.append(student)

    report.students_updated = len(updates)

    # Every decision is made by here, so the write is one short transaction:
    # a run either lands completely or not at all.
    if updates and not dry_run:
        with transaction.atomic():
            Student.objects.bulk_update(updates, ['total_class_quota', 'updated_at'])

    _log_summary(report)
    return report
