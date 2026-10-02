"""
Exam domain rules, ported from the Supabase Hub routes, RLS helpers and
Postgres triggers. Everything a trigger or policy enforced there is a function
here, called by the views inside ``transaction.atomic()``.
"""
import math
import re
from datetime import timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from core.timezones import DEFAULT_TIMEZONE, is_valid_timezone
from sessions.models import Session, SessionStatusChoices
from sessions.services import ALLOWED_DURATIONS, normalize_link, resolve_start_time, _signature_matches
from .models import (
    Exam,
    ExamStatusChoices,
    ExamFile,
    AdditionalExam,
    AdditionalExamStatusChoices,
    AdditionalExamFile,
    ExamFileKind,
)


class ExamStateError(Exception):
    """A status transition the state machine refuses. The view answers 409."""


# ------------------------------------------------------------ chapter names

# Same suffix the series routes strip: "Real Numbers - Class 3" -> "Real Numbers".
SERIES_SUFFIX_RE = re.compile(r'\s*-\s*[Cc]lass\s+\d+$')


def derive_chapter_names(student):
    """
    The deduped, sorted list of chapter names a student can be examined on
    (Hub ``deriveChapterNames``): individual session titles as-is, plus series
    base titles -- but a series is only offered once ALL of its classes are
    ATTENDED. Cancelled single classes still count (as in the Hub).
    """
    names = set()
    tally = {}
    for s in Session.objects.filter(student=student).only('title', 'series_id', 'status'):
        if s.series_id:
            name = SERIES_SUFFIX_RE.sub('', s.title or '').strip()
            if not name:
                continue
            entry = tally.setdefault(s.series_id, {'name': name, 'total': 0, 'attended': 0})
            entry['total'] += 1
            if s.status == SessionStatusChoices.ATTENDED:
                entry['attended'] += 1
        else:
            name = (s.title or '').strip()
            if name:
                names.add(name)
    for entry in tally.values():
        if entry['total'] > 0 and entry['attended'] == entry['total']:
            names.add(entry['name'])
    return sorted(names, key=lambda n: n.lower())


# ------------------------------------------------------------ scheduling

def resolve_exam_slot(data, timezone_name, label='This exam'):
    """
    The (start, end, duration) an exam request names. Accepts the sessions
    shape -- ``local_date`` + ``local_time`` with ``timezone`` (preferred) or a
    UTC ISO ``start_time`` -- and a ``duration_hours`` from ALLOWED_DURATIONS.
    Raises ValueError (incl. TimezoneConversionError) with a user message.
    """
    duration = data.get('duration_hours')
    if isinstance(duration, bool) or not isinstance(duration, (int, float)) or duration not in ALLOWED_DURATIONS:
        raise ValueError('duration_hours must be 0.5, 1, 1.5, or 2')
    if timezone_name is not None and not is_valid_timezone(timezone_name):
        raise ValueError(f'Unknown time zone "{timezone_name}"')
    start = resolve_start_time(data, timezone_name, label)
    end = start + timedelta(hours=duration)
    return start, end, duration


def find_exam_conflict(student, mentor, start_time, end_time, exclude_exam_id=None):
    """
    Overlap check across the student's sessions and exams and the mentor's
    exams (the Hub's ``findConflict``). Returns a human label of the first
    conflict, or None if the slot is free.

    Only SCHEDULED rows block a slot: the Django sessions API deliberately lets
    attended/cancelled classes be booked over, and exams follow that rule.
    """
    session = Session.objects.filter(
        student=student,
        status=SessionStatusChoices.SCHEDULED,
        start_time__lt=end_time,
        end_time__gt=start_time,
    ).first()
    if session:
        return f'the session "{session.title}"'

    student_exams = Exam.objects.filter(
        student=student,
        status=ExamStatusChoices.SCHEDULED,
        start_time__lt=end_time,
        end_time__gt=start_time,
    )
    if exclude_exam_id:
        student_exams = student_exams.exclude(id=exclude_exam_id)
    exam = student_exams.first()
    if exam:
        return f'the exam "{exam.chapter_name}"'

    if mentor:
        mentor_exams = Exam.objects.filter(
            mentor=mentor,
            status=ExamStatusChoices.SCHEDULED,
            start_time__lt=end_time,
            end_time__gt=start_time,
        )
        if exclude_exam_id:
            mentor_exams = mentor_exams.exclude(id=exclude_exam_id)
        exam = mentor_exams.first()
        if exam:
            return f'another exam ("{exam.chapter_name}") at this time'
    return None


def find_exam_conflict_for_session(student, start_time, end_time):
    """The reverse check the sessions views run: a SCHEDULED exam of the
    student overlapping a proposed class, or None."""
    return Exam.objects.filter(
        student=student,
        status=ExamStatusChoices.SCHEDULED,
        start_time__lt=end_time,
        end_time__gt=start_time,
    ).first()


# ------------------------------------------------------------ scores / links

def _as_int(value, label):
    if isinstance(value, bool):
        raise ValueError(f'{label} must be a whole number')
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if re.fullmatch(r'-?\d+', text):
            return int(text)
        if re.fullmatch(r'-?\d+\.0+', text):
            return int(float(text))
    raise ValueError(f'{label} must be a whole number')


def validate_score(score, max_score):
    """The Hub's score rule: integers, max > 0, 0 <= score <= max."""
    if score is None or max_score is None:
        raise ValueError('A score and a maximum are required')
    score_val = _as_int(score, 'Score')
    max_val = _as_int(max_score, 'Maximum')
    if score_val < 0:
        raise ValueError('Score cannot be negative')
    if max_val <= 0:
        raise ValueError('Maximum must be greater than 0')
    if score_val > max_val:
        raise ValueError('Score cannot exceed the maximum')
    return score_val, max_val


def normalize_recording_link(value):
    """Stripped, blank -> None; a non-empty value must be an https URL."""
    link = normalize_link(value)
    if link is None:
        return None
    if not re.match(r'^https://\S+$', link):
        raise ValueError('Recording link must be an https URL')
    return link


# ------------------------------------------------------------ files

# Declared MIME type -> canonical extension. PDF or image only (the Hub's exam
# buckets); no video, no gif.
EXAM_CONTENT_TYPES = {
    'application/pdf': '.pdf',
    'image/png': '.png',
    'image/jpeg': '.jpg',
    'image/webp': '.webp',
    'image/heic': '.heic',
    'image/heif': '.heif',
}

_SNIFF_BYTES = 16


def validate_exam_upload(upload):
    """Allow-list + size ceiling + magic number. Returns (content_type, ext)."""
    content_type = (upload.content_type or '').split(';')[0].strip().lower()
    if content_type not in EXAM_CONTENT_TYPES:
        raise ValueError(
            f'Unsupported file type{": " + content_type if content_type else ""}. '
            f'Allowed: {", ".join(EXAM_CONTENT_TYPES)}'
        )
    limit = settings.EXAM_FILE_MAX_BYTES
    if upload.size == 0:
        raise ValueError(f'"{upload.name}" is empty')
    if upload.size > limit:
        raise ValueError(f'"{upload.name}" exceeds the {limit // (1024 * 1024)} MB limit')
    upload.seek(0)
    head = upload.read(_SNIFF_BYTES)
    upload.seek(0)
    if not _signature_matches(content_type, head):
        raise ValueError(f'"{upload.name}" does not look like a {content_type} file')
    return content_type, EXAM_CONTENT_TYPES[content_type]


def validate_upload_batch(uploads, required=False, required_message='At least one file is required'):
    """Count limit + per-file validation. Returns [(upload, content_type, ext)]."""
    if required and len(uploads) == 0:
        raise ValueError(required_message)
    if len(uploads) > settings.EXAM_MAX_FILES_PER_UPLOAD:
        raise ValueError(f'At most {settings.EXAM_MAX_FILES_PER_UPLOAD} files may be uploaded')
    out = []
    for upload in uploads:
        content_type, ext = validate_exam_upload(upload)
        out.append((upload, content_type, ext))
    return out


def _basename(name, fallback):
    import os
    return os.path.basename(name or '')[:255] or fallback


def store_exam_files(exam, validated, user):
    """Persist question-paper rows + bytes for a chapter exam."""
    rows = []
    for upload, content_type, ext in validated:
        row = ExamFile(
            exam=exam,
            kind=ExamFileKind.QUESTION_PAPER,
            file_name=_basename(upload.name, f'question_paper{ext}'),
            content_type=content_type,
            size_bytes=upload.size,
            extension=ext,
            uploaded_by=user,
        )
        row.file.save(f'{row.id}{ext}', upload, save=False)
        row.save()
        rows.append(row)
    return rows


def store_additional_exam_files(exam, kind, validated, user):
    rows = []
    for upload, content_type, ext in validated:
        row = AdditionalExamFile(
            additional_exam=exam,
            kind=kind,
            file_name=_basename(upload.name, f'{kind}{ext}'),
            content_type=content_type,
            size_bytes=upload.size,
            extension=ext,
            uploaded_by=user,
        )
        row.file.save(f'{row.id}{ext}', upload, save=False)
        row.save()
        rows.append(row)
    return rows


def discard_file_bytes(rows):
    """After a rolled-back transaction the rows are gone; drop their bytes."""
    for row in rows:
        try:
            if row.file:
                row.file.delete(save=False)
        except Exception:  # best effort cleanup
            pass


# ------------------------------------------------------------ state machines

def assert_exam_transition(exam, new_status):
    """
    ``enforce_exam_transition``: same-status updates (reschedule while
    scheduled, result edits while attended) pass; otherwise only
    scheduled -> attended | cancelled.
    """
    if new_status == exam.status:
        return
    if exam.status == ExamStatusChoices.SCHEDULED and new_status in (
        ExamStatusChoices.ATTENDED, ExamStatusChoices.CANCELLED
    ):
        return
    raise ExamStateError(f'Illegal exam status transition: {exam.status.lower()} -> {new_status.lower()}')


def assert_additional_exam_transition(exam, new_status):
    """``enforce_additional_exam_transition``: assigned -> submitted -> scored, forward only."""
    allowed = {
        (AdditionalExamStatusChoices.ASSIGNED, AdditionalExamStatusChoices.SUBMITTED),
        (AdditionalExamStatusChoices.SUBMITTED, AdditionalExamStatusChoices.SCORED),
    }
    if (exam.status, new_status) in allowed:
        return
    raise ExamStateError(
        f'Illegal additional exam status transition: {exam.status.lower()} -> {new_status.lower()}'
    )


# ------------------------------------------------------------ handover / purge

def handover_open_exams(student_filter, new_mentor):
    """
    Hand a mentor's OPEN exam work to ``new_mentor`` (the exam parts of the
    Hub's reassign RPCs): scheduled chapter exams and assigned/submitted
    additional exams. Completed work keeps the mentor who handled it.
    ``student_filter`` is a Q() selecting the students concerned.
    Returns (exams_repointed, additional_exams_repointed).
    """
    exams = Exam.objects.filter(student_filter, status=ExamStatusChoices.SCHEDULED).update(mentor=new_mentor)
    add = AdditionalExam.objects.filter(
        student_filter,
        status__in=[AdditionalExamStatusChoices.ASSIGNED, AdditionalExamStatusChoices.SUBMITTED],
    ).update(mentor=new_mentor)
    return exams, add


def exam_history_exists(student):
    return (
        Exam.objects.filter(student=student).exists()
        or AdditionalExam.objects.filter(student=student).exists()
    )


# ------------------------------------------------------------ scorecard

SCORECARD_RANGES = ('week', 'month', 'all')

CATEGORY_LABELS = {'homework': 'Homework', 'exam': 'Chapter Exams'}


def student_zone(student):
    zone = getattr(student, 'timezone', None)
    return zone if zone and is_valid_timezone(zone) else DEFAULT_TIMEZONE


def _js_round(value):
    """Math.round semantics (halves toward +infinity), unlike Python's banker's rounding."""
    return int(math.floor(value + 0.5))


def _mean(values):
    values = [v for v in values if v is not None]
    if not values:
        return None
    return sum(values) / len(values)


def _round_or_none(value):
    return None if value is None else _js_round(value)


def score_entry(category, label, score, max_score, scored_at):
    """Normalise one score row (Learn ``toEntry``); None when unusable."""
    if score is None or max_score is None or max_score <= 0 or not scored_at:
        return None
    return {
        'category': category,
        'label': label,
        'score': score,
        'max_score': max_score,
        'pct': _js_round(score / max_score * 100),
        'scored_at': scored_at,
    }


def collect_score_entries(student):
    """
    The student's final scores: attended chapter exams, timestamped by the
    exam's end time (Learn ``getScorecard``). Additional exams never count.
    Homework is not ported yet; its rows would be appended here.
    """
    entries = []
    rows = Exam.objects.filter(
        student=student, status=ExamStatusChoices.ATTENDED, type='CHAPTER'
    ).only('score', 'max_score', 'end_time', 'created_at', 'chapter_name')
    for row in rows:
        entry = score_entry('exam', row.chapter_name or 'Chapter Exam', row.score, row.max_score,
                            row.end_time or row.created_at)
        if entry:
            entries.append(entry)
    return entries


def _day_start(moment, tz):
    local = moment.astimezone(tz)
    return local.replace(hour=0, minute=0, second=0, microsecond=0)


def _buckets(range_key, now, tz, earliest):
    today = _day_start(now, tz)
    if range_key == 'week':
        out = []
        for i in range(6, -1, -1):
            start = today - timedelta(days=i)
            out.append({'key': start.date().isoformat(), 'label': start.strftime('%a'),
                        'start': start, 'end': start + timedelta(days=1)})
        return out
    if range_key == 'month':
        end_of_today = today + timedelta(days=1)
        out = []
        for k in range(5):
            end = end_of_today - timedelta(days=7 * (4 - k))
            start = end - timedelta(days=7)
            out.append({'key': start.date().isoformat(), 'label': f'{start.day} {start.strftime("%b")}',
                        'start': start, 'end': end})
        return out
    # all: one bucket per calendar month from the earliest score to this month
    if earliest is None:
        return []
    first = _day_start(earliest, tz).replace(day=1)
    cursor = first
    this_month = today.replace(day=1)
    out = []
    while cursor <= this_month:
        if cursor.month == 12:
            nxt = cursor.replace(year=cursor.year + 1, month=1)
        else:
            nxt = cursor.replace(month=cursor.month + 1)
        out.append({'key': cursor.date().isoformat(), 'label': cursor.strftime('%b %y'),
                    'start': cursor, 'end': nxt})
        cursor = nxt
    return out


def _avg_in_range(entries, start, end):
    return _mean([e['pct'] for e in entries if start <= e['scored_at'] < end])


def build_scorecard(entries, range_key, now=None, zone=DEFAULT_TIMEZONE):
    """
    Learn ``buildScorecard``: percentages per entry, an unweighted mean over
    the window, the delta against the previous equal-length window, per-
    category averages, chart buckets and the 8 most recent scores. Bucket
    edges are computed in the student's zone.
    """
    if range_key not in SCORECARD_RANGES:
        range_key = 'month'
    now = now or timezone.now()
    tz = ZoneInfo(zone)
    entries = sorted(entries, key=lambda e: e['scored_at'])
    earliest = entries[0]['scored_at'] if entries else None
    buckets = _buckets(range_key, now, tz, earliest)

    if range_key == 'all':
        window_start = None
    elif buckets:
        window_start = buckets[0]['start']
    else:
        window_start = _day_start(now, tz) - timedelta(days=6 if range_key == 'week' else 34)

    in_window = [e for e in entries if window_start is None or e['scored_at'] >= window_start]
    overall = _round_or_none(_mean([e['pct'] for e in in_window]))

    delta = None
    if range_key != 'all' and in_window and window_start is not None:
        window_len = now - window_start
        prev_avg = _avg_in_range(entries, window_start - window_len, window_start)
        if prev_avg is not None and overall is not None:
            delta = _js_round(overall - prev_avg)

    categories = []
    for category in ('homework', 'exam'):
        items = [e for e in in_window if e['category'] == category]
        categories.append({
            'category': category,
            'label': CATEGORY_LABELS[category],
            'avg': _round_or_none(_mean([e['pct'] for e in items])),
            'count': len(items),
        })

    chart = []
    for b in buckets:
        chart.append({
            'key': b['key'],
            'label': b['label'],
            'homework': _round_or_none(_avg_in_range([e for e in in_window if e['category'] == 'homework'], b['start'], b['end'])),
            'exam': _round_or_none(_avg_in_range([e for e in in_window if e['category'] == 'exam'], b['start'], b['end'])),
        })

    recent = sorted(in_window, key=lambda e: e['scored_at'], reverse=True)[:8]
    return {
        'range': range_key,
        'overall': overall,
        'delta': delta,
        'lifetime_count': len(entries),
        'total_count': len(in_window),
        'categories': categories,
        'buckets': chart,
        'recent': [
            {
                'category': e['category'],
                'label': e['label'],
                'score': e['score'],
                'max_score': e['max_score'],
                'pct': e['pct'],
                'scored_at': e['scored_at'].isoformat(),
            }
            for e in recent
        ],
    }
