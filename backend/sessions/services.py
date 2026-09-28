"""
Session domain helpers extracted from the views.

These keep the (intricate) scheduling rules in one place: title normalisation,
ISO datetime parsing, quota accounting, and conflict detection.
"""
from datetime import datetime
from django.db.models import Q
from django.utils import timezone

from core.timezones import TimezoneConversionError, zoned_wall_time_to_utc
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
    Return the first non-cancelled session that overlaps ``[start_time, end_time)``
    for the same student or the same tutor, or None if there is no conflict.
    """
    overlap_filters = Q(student=student)
    if tutor:
        overlap_filters |= Q(tutor=tutor)

    conflicts = Session.objects.filter(
        ~Q(status=SessionStatusChoices.CANCELLED),
        overlap_filters,
        start_time__lt=end_time,
        end_time__gt=start_time,
    )
    if exclude_id:
        conflicts = conflicts.exclude(id=exclude_id)
    return conflicts.first()
