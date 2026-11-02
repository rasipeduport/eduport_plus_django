"""
Submitting and editing assessment reports (design F.1): the one place report
rows are written, as bookings.booking_service is for bookings.

submit_report runs in one transaction, under the locks every booking write
takes, in the same order: the booking's slot, then the booking
(booking_service._locked_booking). A submit racing a cancel, a reschedule or a
tutor change of the same booking queues behind it, or it behind them, and
never deadlocks; whichever commits first wins and the other sees its result.
Under the locks: only the booking's assigned tutor (anyone else is told the
booking does not exist), only a booked booking whose slot has started (D2),
and only once. It saves the report as version 1 with its first revision,
completes the booking and records COMPLETED in the booking's history -- all of
it or none. The tutor's scheduling lock is not taken: nothing about the
tutor's time changes.

edit_report takes the same locks, then the report's row. It needs the version
the edit was made from, and refuses any other (REPORT_VERSION_CONFLICT), so two
edits never overwrite each other unseen. An edit that changes no field the
tutor writes saves nothing. Otherwise it saves the next version with the
system snapshots refreshed (D7), adds a revision -- earlier ones are never
touched -- and records REPORT_EDITED. Editing stays open at any time (D6).

Both log to the activity log after the transaction commits, with ids, the
version and field names only: never report text or anyone's name.

A lock wait past booking_service.LOCK_TIMEOUT, or a deadlock, answers
ReportBusy instead of holding the request.
"""
import re

from django.db import OperationalError, transaction
from django.utils import timezone

from activity.utils import log_activity
from bookings import history
# The booking locks every booking write takes, in the order they take them.
from bookings.booking_service import BUSY_SQLSTATES, _locked_booking, _set_lock_timeout, slot_label
from bookings.models import BookingEventKind, BookingStatus

from .models import (
    DEMO_FIELD_CHARS,
    ITEM_CHARS,
    MAX_ITEMS,
    MAX_SCORE_LIMIT,
    SUGGESTED_PLAN_CHARS,
    TEACHER_REMARKS_CHARS,
    PerformanceLevel,
    report_model,
)

SNAPSHOT_FIELDS = ('student_name_snapshot', 'grade_snapshot', 'tutor_name_snapshot')
# "Class 9" prints as "9", as in the report samples.
CLASS_PREFIX = re.compile(r'^\s*class\s+', re.IGNORECASE)


class ReportError(Exception):
    code = 'REPORT_FAILED'
    http_status = 400
    message = 'The report could not be saved.'

    def __init__(self):
        super().__init__(self.message)


class ReportInvalid(ReportError):
    """The fields as sent are not a report: ``fields`` maps each field to what is wrong with it."""
    code = 'VALIDATION_ERROR'
    message = 'Check the report.'

    def __init__(self, fields):
        super().__init__()
        self.fields = fields


class BookingNotAssigned(ReportError):
    """A booking the caller is not the tutor of: answered as one that does not exist."""
    code = 'NOT_FOUND'
    http_status = 404
    message = 'No such booking.'


class NoReport(ReportError):
    code = 'NO_REPORT'
    http_status = 404
    message = 'This booking has no report yet.'


class ReportExists(ReportError):
    code = 'REPORT_EXISTS'
    http_status = 409
    message = 'This booking already has a report. Edit it instead.'

    def __init__(self, version):
        super().__init__()
        self.version = version


class SlotNotStarted(ReportError):
    code = 'SLOT_NOT_STARTED'
    http_status = 409
    message = 'A report can be written once the slot has started.'


class BookingCancelled(ReportError):
    code = 'BOOKING_CANCELLED'
    http_status = 409
    message = 'This booking was cancelled, so it takes no report.'


class BookingRescheduled(ReportError):
    code = 'BOOKING_RESCHEDULED'
    http_status = 409
    message = 'This booking was moved to another slot. Write the report on the new one.'


class ReportVersionConflict(ReportError):
    code = 'REPORT_VERSION_CONFLICT'
    http_status = 409
    message = 'This report was changed after you opened it. Reload it to see the latest version.'

    def __init__(self, version):
        super().__init__()
        self.version = version


class ReportBusy(ReportError):
    code = 'REPORT_BUSY'
    http_status = 503
    message = 'Could not save the report right now. Please try again.'


def submit_report(booking, tutor, fields, now=None):
    """
    Save ``tutor``'s first report on ``booking``, from ``fields`` (the fields
    the tutor writes, see clean_fields), and complete the booking. Returns the
    report, version 1. Raises a ReportError subclass.
    """
    now = now or timezone.now()
    model = report_model(booking.booking_type)
    cleaned = clean_fields(model, fields)
    try:
        with transaction.atomic():
            _set_lock_timeout()
            booking = _locked_booking(booking)
            _check_assigned(booking, tutor)
            existing = model.objects.filter(booking=booking).first()
            if existing is not None or booking.status == BookingStatus.COMPLETED:
                raise ReportExists(existing.version if existing else None)
            if booking.status == BookingStatus.CANCELLED:
                raise BookingCancelled()
            if booking.status == BookingStatus.RESCHEDULED:
                raise BookingRescheduled()
            if booking.slot.starts_at > now:
                raise SlotNotStarted()

            saved_at = timezone.now()
            snapshots = system_snapshots(booking, tutor)
            report = model.objects.create(
                booking=booking,
                version=1,
                submitted_by=tutor,
                submitted_at=saved_at,
                updated_by=tutor,
                updated_at=saved_at,
                **snapshots,
                **cleaned,
            )
            # Version 1 changed every field the tutor writes: each had no value before.
            report.revisions.create(
                version=1, content={**cleaned, **snapshots}, changed_fields=list(model.TUTOR_FIELDS),
                edited_by=tutor, edited_at=saved_at,
            )
            booking.status = BookingStatus.COMPLETED
            booking.completed_at = saved_at
            booking.completed_by = tutor
            booking.save(update_fields=['status', 'completed_at', 'completed_by', 'updated_at'])
            history.record(
                booking, BookingEventKind.COMPLETED, actor=tutor,
                from_status=BookingStatus.BOOKED, to_status=BookingStatus.COMPLETED, report_id=report.id, version=1,
            )
    except OperationalError as exc:
        if getattr(exc.__cause__, 'sqlstate', None) in BUSY_SQLSTATES:
            raise ReportBusy() from exc
        raise
    _log_report('report.submit', booking, report, tutor)
    log_activity(
        action='booking.complete',
        entity_type='booking',
        entity_id=booking.id,
        entity_label=slot_label(booking.slot),
        # Ids only, as for every booking entry.
        context={
            'booking_type': booking.booking_type,
            'slot_starts_at': booking.slot.starts_at.isoformat(),
            'lead_id': str(booking.lead_id),
            'report_id': str(report.id),
        },
        actor=tutor,
    )
    return report


def edit_report(booking, tutor, fields, version):
    """
    Replace the fields of ``tutor``'s report on ``booking`` with ``fields``
    (all of them, see clean_fields), as an edit of ``version``. Returns
    (report, changed); an edit that changes nothing saves nothing and leaves
    the version as it was. Raises a ReportError subclass.
    """
    model = report_model(booking.booking_type)
    cleaned = clean_fields(model, fields)
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise ReportInvalid({'version': ['Give the version of the report you edited.']})
    try:
        with transaction.atomic():
            _set_lock_timeout()
            booking = _locked_booking(booking)
            _check_assigned(booking, tutor)
            # The report's row last: slot, booking, report (design B.7).
            report = model.objects.select_for_update().filter(booking=booking).first()
            if report is None:
                raise NoReport()
            if version != report.version:
                raise ReportVersionConflict(report.version)
            changed = [field for field in model.TUTOR_FIELDS if getattr(report, field) != cleaned[field]]
            if not changed:
                return report, False

            saved_at = timezone.now()
            snapshots = system_snapshots(booking, tutor)
            changed += [field for field in SNAPSHOT_FIELDS if getattr(report, field) != snapshots[field]]
            for field, value in {**cleaned, **snapshots}.items():
                setattr(report, field, value)
            report.version += 1
            report.updated_by = tutor
            report.updated_at = saved_at
            report.save()
            report.revisions.create(
                version=report.version, content={**cleaned, **snapshots}, changed_fields=changed,
                edited_by=tutor, edited_at=saved_at,
            )
            history.record(
                booking, BookingEventKind.REPORT_EDITED, actor=tutor,
                report_id=report.id, version=report.version, changed_fields=changed,
            )
    except OperationalError as exc:
        if getattr(exc.__cause__, 'sqlstate', None) in BUSY_SQLSTATES:
            raise ReportBusy() from exc
        raise
    # Field names only, never what they now say.
    _log_report('report.edit', booking, report, tutor, changed_fields=changed)
    return report, True


def preview_content(booking, tutor, fields, now=None):
    """
    What ``tutor``'s report on ``booking`` would print if ``fields`` were saved
    now, saving nothing: the fields as clean_fields leaves them and the system
    snapshots a save would take (D7) -- the content a revision holds, for
    reports.pdf to draw exactly as it draws a saved version. Offered wherever a
    save could follow: to the booking's assigned tutor, on a booked booking
    whose slot has started (a submit) or a completed one (an edit). It only
    reads, takes no lock and logs nothing. Raises a ReportError subclass, as a
    save of the same fields would.
    """
    now = now or timezone.now()
    cleaned = clean_fields(report_model(booking.booking_type), fields)
    _check_assigned(booking, tutor)
    if booking.status == BookingStatus.CANCELLED:
        raise BookingCancelled()
    if booking.status == BookingStatus.RESCHEDULED:
        raise BookingRescheduled()
    if booking.status == BookingStatus.BOOKED and booking.slot.starts_at > now:
        raise SlotNotStarted()
    return {**cleaned, **system_snapshots(booking, tutor)}


def system_snapshots(booking, tutor):
    """
    The system fields as the report prints them, from the booking's lead and
    the tutor's account (D7): the student's name, the grade without its
    "Class " ("Class 9" is "9") and the tutor's full name. Never the parent.
    """
    lead = booking.lead
    grade = (lead.grade or '').strip()
    return {
        'student_name_snapshot': lead.student_name.strip(),
        'grade_snapshot': CLASS_PREFIX.sub('', grade).strip() or grade,
        'tutor_name_snapshot': (tutor.full_name or '').strip() or tutor.username,
    }


# ---------------------------------------------------------------- the fields

def _text(cap):
    def clean(value):
        if not isinstance(value, str):
            raise ValueError('Enter text.')
        text = value.replace('\r\n', '\n').replace('\r', '\n').strip()
        if not text:
            raise ValueError('This field is required.')
        if len(text) > cap:
            raise ValueError(f'Use at most {cap} characters.')
        return text
    return clean


def _items(value):
    if not isinstance(value, list):
        raise ValueError('List the items.')
    if not 1 <= len(value) <= MAX_ITEMS:
        raise ValueError(f'List 1 to {MAX_ITEMS} items.')
    items = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError('Each item is text.')
        item = item.strip()
        if not item:
            raise ValueError('Items cannot be blank.')
        if '\n' in item or '\r' in item:
            raise ValueError('Each item is one line.')
        if len(item) > ITEM_CHARS:
            raise ValueError(f'Each item holds at most {ITEM_CHARS} characters.')
        items.append(item)
    return items


def _whole(low, high):
    def clean(value):
        # Whole numbers only (A12); a true or false is not a number here.
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError('Enter a whole number.')
        if not low <= value <= high:
            raise ValueError(f'Enter a number from {low} to {high}.')
        return value
    return clean


def _performance_level(value):
    if value not in PerformanceLevel.values:
        raise ValueError(f'Choose one of: {", ".join(PerformanceLevel.values)}.')
    return value


CLEANERS = {
    'score': _whole(0, MAX_SCORE_LIMIT),
    'max_score': _whole(1, MAX_SCORE_LIMIT),
    'performance_level': _performance_level,
    'strength_areas': _items,
    'skills_to_strengthen': _items,
    'teacher_remarks': _text(TEACHER_REMARKS_CHARS),
    'suggested_plan': _text(SUGGESTED_PLAN_CHARS),
    'assessment_review': _text(DEMO_FIELD_CHARS),
    'class_observation_review': _text(DEMO_FIELD_CHARS),
    'suggested_strategy': _text(DEMO_FIELD_CHARS),
}


def clean_fields(model, fields):
    """
    The fields the tutor writes on a ``model`` report (its TUTOR_FIELDS), each
    checked by the rules its table holds, with text trimmed and its line
    breaks made "\\n". Every one is required; any other key -- a system field
    such as a snapshot, the version or the status, or a name not known at all
    -- is refused, never dropped (ReportInvalid, naming each field).
    """
    if not isinstance(fields, dict):
        raise ReportInvalid({'non_field_errors': ['Send the report as an object of its fields.']})
    errors = {field: ['This field cannot be set.'] for field in sorted(set(fields) - set(model.TUTOR_FIELDS))}
    cleaned = {}
    for field in model.TUTOR_FIELDS:
        if field not in fields:
            errors[field] = ['This field is required.']
            continue
        try:
            cleaned[field] = CLEANERS[field](fields[field])
        except ValueError as exc:
            errors[field] = [str(exc)]
    if 'score' in cleaned and 'max_score' in cleaned and cleaned['score'] > cleaned['max_score']:
        errors['score'] = ['The score cannot be more than the maximum score.']
    if errors:
        raise ReportInvalid(errors)
    return cleaned


# ---------------------------------------------------------------- helpers

def _report_label(report, booking):
    """'Demo report · 28 Oct 2026, 19:30 IST': the activity log names a report by its slot, never its student."""
    slot = booking.slot
    return f'{report._meta.verbose_name.capitalize()} · {slot.local_date:%d %b %Y}, {slot.local_time:%H:%M} IST'


def _check_assigned(booking, tutor):
    if booking.assigned_tutor_id is None or booking.assigned_tutor_id != tutor.pk:
        raise BookingNotAssigned()


def _log_report(action, booking, report, tutor, **context):
    log_activity(
        action=action,
        entity_type='report',
        entity_id=report.id,
        entity_label=_report_label(report, booking),
        # Ids, the version and field names: never report text, a name or a phone number.
        context={
            'booking_type': booking.booking_type,
            'booking_id': str(booking.id),
            'lead_id': str(booking.lead_id),
            'version': report.version,
            **context,
        },
        actor=tutor,
    )
