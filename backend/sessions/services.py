"""
Session domain helpers extracted from the views.

These keep the (intricate) scheduling rules in one place: title normalisation,
ISO datetime parsing, quota accounting, and conflict detection.
"""
from datetime import datetime
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import connection
from django.db.models import Q
from django.utils import timezone

from core.timezones import DEFAULT_TIMEZONE, TimezoneConversionError, is_valid_timezone, zoned_wall_time_to_utc
from .models import Session, SessionStatusChoices

ALLOWED_DURATIONS = [0.5, 1, 1.5, 2]
MAX_SERIES_ITEMS = 20


def normalize_title(title):
    """
    Collapse whitespace and Title-Case every word -- the Hub's ``normalizeTitle``,
    so "  real   numbers " is stored as "Real Numbers" in both apps.
    """
    if not title:
        return ""
    return " ".join(w[:1].upper() + w[1:].lower() for w in title.split())


def parse_iso_datetime(dt_str):
    """Parse an ISO 8601 string into a timezone-aware datetime, or None if invalid."""
    try:
        # standard ISO format: 2026-06-17T12:00:00Z -> timezone-aware datetime
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        if timezone.is_naive(dt):
            dt = timezone.make_aware(dt, timezone.utc)
        return dt
    except Exception:
        return None


def resolve_start_time(item, timezone_name, label):
    """
    The instant one scheduling input names.

    Accepts either a wall clock plus a zone (preferred: ``local_date`` +
    ``local_time`` with the request's top-level ``timezone``) or a UTC ISO
    ``start_time`` (legacy). The preferred shape moves the wall-clock -> UTC
    conversion server-side, so the stored instant no longer depends on the
    machine the mentor is using. Raises ``TimezoneConversionError`` with a
    message meant for the mentor -- non-existent local times inside a DST gap
    are rejected here rather than silently shifted by an hour.
    """
    local_date = item.get("local_date")
    local_time = item.get("local_time")
    if local_date or local_time:
        if not local_date or not local_time:
            raise TimezoneConversionError(f"{label}: local_date and local_time must be supplied together")
        if not timezone_name:
            raise TimezoneConversionError(f"{label}: timezone is required when scheduling with a local time")
        try:
            return zoned_wall_time_to_utc(local_date, local_time, timezone_name)
        except TimezoneConversionError as exc:
            raise TimezoneConversionError(f"{label}: {exc}") from exc

    start_time_str = item.get("start_time")
    if not start_time_str:
        raise TimezoneConversionError(f"{label}: either local_date + local_time, or start_time, is required")
    start_time = parse_iso_datetime(start_time_str) if isinstance(start_time_str, str) else None
    if not start_time:
        raise TimezoneConversionError(f"{label}: start_time is not a valid date")
    return start_time


def normalize_link(value):
    """
    A resource link as stored: stripped, with blank strings collapsed to None
    so "no link" has exactly one representation for the completion checks and
    the content filter. Non-string, non-null input raises ValueError.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("must be a string or null")
    return value.strip() or None


def _link_missing(field):
    return Q(**{f"{field}__isnull": True}) | Q(**{field: ""})


# ?content= values on the sessions list. Every option is scoped to ATTENDED
# rows: a scheduled class has no material yet and a cancelled one never will,
# so neither counts as "missing" anything.
CONTENT_FILTERS = ('complete', 'missing_notes', 'missing_recording', 'missing_homework', 'missing_content')


def apply_content_filter(queryset, value):
    """
    Restrict a Session queryset by post-session content state. Raises
    ValueError for an unknown value so the view can answer 400.
    """
    if value not in CONTENT_FILTERS:
        raise ValueError(f"content must be one of {', '.join(CONTENT_FILTERS)}")

    queryset = queryset.filter(status=SessionStatusChoices.ATTENDED)
    fields = dict(Session.REQUIRED_CONTENT)
    if value == 'complete':
        for field in fields.values():
            queryset = queryset.exclude(_link_missing(field))
        return queryset
    if value == 'missing_content':
        any_missing = Q()
        for field in fields.values():
            any_missing |= _link_missing(field)
        return queryset.filter(any_missing)
    # missing_notes / missing_recording / missing_homework
    return queryset.filter(_link_missing(fields[value.removeprefix('missing_')]))


def calculate_credits_used(student):
    """Total hours consumed by the student's non-cancelled sessions."""
    existing_sessions = Session.objects.filter(student=student).exclude(
        status=SessionStatusChoices.CANCELLED
    )
    credits_used = 0.0
    for s in existing_sessions:
        credits_used += (s.end_time - s.start_time).total_seconds() / 3600.0
    return credits_used


def find_conflict(student, tutor, start_time, end_time, exclude_id=None):
    """
    Return the first SCHEDULED session that overlaps ``[start_time, end_time)``
    for the same student or the same tutor, or None if there is no conflict.

    Only active (SCHEDULED) sessions block a slot: an ATTENDED session has
    already happened and a CANCELLED one never will, so neither should stop
    a new booking from being placed over its time.
    """
    overlap_filters = Q(student=student)
    if tutor:
        overlap_filters |= Q(tutor=tutor)

    conflicts = Session.objects.filter(
        overlap_filters,
        status=SessionStatusChoices.SCHEDULED,
        start_time__lt=end_time,
        end_time__gt=start_time,
    )
    if exclude_id:
        conflicts = conflicts.exclude(id=exclude_id)
    return conflicts.first()


def find_internal_overlap(windows):
    """
    First pair of windows in one booking request that overlap each other,
    as ``(earlier_index, later_index)``, or None. ``windows`` is a list of
    ``(start_time, end_time)`` in request order. Same half-open rule as
    ``find_conflict``: touching windows (3:00 end, 3:00 start) do not overlap.
    """
    ordered = sorted(range(len(windows)), key=lambda i: windows[i][0])
    for pos in range(1, len(ordered)):
        prev, cur = ordered[pos - 1], ordered[pos]
        if windows[cur][0] < windows[prev][1]:
            return (min(prev, cur), max(prev, cur))
    return None


# Advisory-lock key classes: the (int, int) form of pg_advisory_xact_lock
# takes a class and a key, so a student's and a tutor's queues never collide.
_LOCK_CLASS_STUDENT = 1
_LOCK_CLASS_TUTOR = 2


def lock_scheduling(student_id, tutor_id):
    """
    Serialise bookings for one student and one tutor for the rest of the
    current transaction.

    ``find_conflict`` is a check-then-insert, so two requests racing each
    other can both see an empty slot and both write into it. Taking a
    transaction-scoped PostgreSQL advisory lock on the student and on the
    tutor before the check makes the second request wait until the first has
    committed; its conflict query then sees the new row. Advisory locks need
    no extension, no schema change and no clean-up of historical rows, which
    is why they are used instead of an exclusion constraint. Keys are taken
    in a fixed order so two requests sharing both parties cannot deadlock.
    Must be called inside ``transaction.atomic()``; a no-op off PostgreSQL.
    """
    if connection.vendor != 'postgresql':
        return
    keys = [(_LOCK_CLASS_STUDENT, str(student_id))]
    if tutor_id:
        keys.append((_LOCK_CLASS_TUTOR, str(tutor_id)))
    with connection.cursor() as cursor:
        for lock_class, key in sorted(keys):
            cursor.execute("SELECT pg_advisory_xact_lock(%s, hashtext(%s))", [lock_class, key])


# ------------------------------------------------------------ conflict replies

TUTOR_SESSION_CONFLICT = 'TUTOR_SESSION_CONFLICT'
SERIES_ITEMS_OVERLAP = 'SERIES_ITEMS_OVERLAP'
STUDENT_SESSION_CONFLICT = 'STUDENT_SESSION_CONFLICT'


def _staff_name(user):
    if not user:
        return None
    return user.full_name or user.email


def _format_window(start_time, end_time, zone_name):
    """"2:00 PM to 3:00 PM IST on Mon 12 Oct 2026" in the zone the mentor schedules in."""
    tz = ZoneInfo(zone_name)
    start = start_time.astimezone(tz)
    end = end_time.astimezone(tz)

    def clock(dt):
        return f"{(dt.hour % 12) or 12}:{dt.minute:02d} {'AM' if dt.hour < 12 else 'PM'}"

    label = start.strftime('%Z') or zone_name
    day = f"{start:%a} {start.day} {start:%b} {start.year}"
    return f"{clock(start)} to {clock(end)} {label} on {day}"


def conflict_response_data(conflict, student, zone_name=None, label=None):
    """
    Body of the 409 answered when ``conflict`` (a SCHEDULED session returned
    by ``find_conflict``) blocks a booking for ``student``.

    The sessions API has always answered errors as ``{"error": <text>}``, and
    the SPAs print that text, so the human-readable message stays in
    ``error``; ``code`` and ``conflict`` are added beside it for clients that
    want to tell a tutor clash from a student clash without parsing text.
    Times are rendered in ``zone_name`` (the zone the mentor is scheduling
    in, falling back to the student's zone, then IST).
    """
    if not zone_name or not is_valid_timezone(zone_name):
        zone_name = student.timezone if is_valid_timezone(getattr(student, 'timezone', None)) else DEFAULT_TIMEZONE
    window = _format_window(conflict.start_time, conflict.end_time, zone_name)
    prefix = f"{label} conflicts" if label else "This conflicts"

    if conflict.student_id == student.id:
        code = STUDENT_SESSION_CONFLICT
        message = (
            f'{prefix} with "{conflict.title}": this student already has a session scheduled '
            f'from {window}. Choose a different time.'
        )
    else:
        code = TUTOR_SESSION_CONFLICT
        tutor_name = _staff_name(conflict.tutor) or 'The tutor'
        message = (
            f'{prefix} with "{conflict.title}": tutor {tutor_name} is already scheduled with '
            f'{conflict.student.full_name} from {window}. Choose a different time or tutor.'
        )

    return {
        "error": message,
        "code": code,
        "conflict": {
            "type": 'student' if code == STUDENT_SESSION_CONFLICT else 'tutor',
            "session_id": str(conflict.id),
            "title": conflict.title,
            "start_time": conflict.start_time.isoformat(),
            "end_time": conflict.end_time.isoformat(),
            "student_name": conflict.student.full_name,
            "tutor_name": _staff_name(conflict.tutor),
            "timezone": zone_name,
        },
    }


# ------------------------------------------------------------ file uploads

# Declared MIME type -> (kind, canonical extension). Only these may be
# uploaded as session content; `kind` selects the size ceiling.
CONTENT_TYPES = {
    'application/pdf': ('document', '.pdf'),
    'image/png': ('image', '.png'),
    'image/jpeg': ('image', '.jpg'),
    'image/webp': ('image', '.webp'),
    'image/gif': ('image', '.gif'),
    'image/heic': ('image', '.heic'),
    'image/heif': ('image', '.heif'),
    'video/mp4': ('video', '.mp4'),
    'video/webm': ('video', '.webm'),
    'video/quicktime': ('video', '.mov'),
    'video/x-matroska': ('video', '.mkv'),
}

_SNIFF_BYTES = 16


def _signature_matches(content_type, head):
    """
    Cheap magic-number check so a renamed .html cannot be stored and served
    back as an image or a PDF. Container formats that all start with an ISO
    'ftyp' box (mp4/mov/heic/heif) share one rule.
    """
    if content_type == 'application/pdf':
        return head.startswith(b'%PDF')
    if content_type == 'image/png':
        return head.startswith(b'\x89PNG\r\n\x1a\n')
    if content_type == 'image/jpeg':
        return head.startswith(b'\xff\xd8\xff')
    if content_type == 'image/gif':
        return head.startswith((b'GIF87a', b'GIF89a'))
    if content_type == 'image/webp':
        return head.startswith(b'RIFF') and head[8:12] == b'WEBP'
    if content_type in ('video/mp4', 'video/quicktime', 'image/heic', 'image/heif'):
        return head[4:8] == b'ftyp'
    if content_type in ('video/webm', 'video/x-matroska'):
        return head.startswith(b'\x1a\x45\xdf\xa3')
    return False


def validate_content_upload(upload):
    """
    Check an uploaded file against the allowlist, the per-kind size ceiling
    and its magic number. Returns ``(kind, content_type, extension)`` or
    raises ValueError with a message meant for the user.
    """
    content_type = (upload.content_type or '').split(';')[0].strip().lower()
    if content_type not in CONTENT_TYPES:
        raise ValueError('Unsupported file type. Upload a PDF, an image, or a video.')
    kind, extension = CONTENT_TYPES[content_type]

    limit = settings.SESSION_CONTENT_MAX_BYTES[kind]
    if upload.size == 0:
        raise ValueError(f'"{upload.name}" is empty.')
    if upload.size > limit:
        raise ValueError(f'"{upload.name}" is larger than the {limit // (1024 * 1024)} MB limit for {kind}s.')

    upload.seek(0)
    head = upload.read(_SNIFF_BYTES)
    upload.seek(0)
    if not _signature_matches(content_type, head):
        raise ValueError(f'"{upload.name}" does not look like a {content_type} file.')
    return kind, content_type, extension
