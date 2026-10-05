"""
Student presentation helpers shared by the list and the profile endpoints.

``serialize_student`` is the one place the Hub's student row is shaped, so the
list (`GET /api/students/`) and the profile header
(`GET /api/students/<id>/profile/`)
can never drift apart. ``build_profile_stats`` adds the cross-module counters
the profile's Overview tab reads: they are computed here rather than in the
browser so a profile is one request, and so the numbers can never exceed what
the caller is allowed to see -- every block goes through the same
``core.querysets`` scoping the list endpoints use.
"""
from django.db.models import Count, Q
from django.utils import timezone

from core.querysets import scope_exams_by_role
from sessions.models import Session, SessionStatusChoices
from sessions.services import apply_content_filter, calculate_credits_used


# A tutor's students table deliberately carries no contact details, no quota
# and no assignment history -- "enough to identify a student and join their
# class". Their profile is cut to the same shape, and server-side, because a
# tutor has no write path that could be confused by the missing keys.
#
# Mentors keep the full row the list endpoint already hands them: their
# profile view hides email and state the way their columns do, but the payload
# must stay complete because "Edit Profile" posts back every field it knows --
# a redacted mentor payload would blank the columns it could not see.
TUTOR_VISIBLE_FIELDS = (
    'id', 'student_code', 'full_name', 'status', 'status_note',
    'grade', 'syllabus', 'meet_link', 'created_at', 'timezone',
    'profile', 'mentor_profile', 'tutor_profile',
)


def _profile_brief(user):
    if not user:
        return None
    return {
        "id": str(user.id),
        "full_name": user.full_name or "",
        "email": user.email,
    }


def serialize_student(student):
    """
    The student row as both the Hub's students table and the profile header
    read it. Shape is load-bearing for the SPA -- extend, don't rename.
    """
    return {
        "id": str(student.id),
        "student_code": student.student_code,
        "full_name": student.full_name,
        "mobile_number": student.mobile_number or "",
        "country": student.country or "",
        "state": student.state or "",
        "school_name": student.school_name or "",
        "grade": student.grade or "",
        "syllabus": student.syllabus or "",
        "admission_date": student.admission_date.isoformat() if student.admission_date else None,
        "created_at": student.created_at.isoformat(),
        "meet_link": student.meet_link or "",
        "total_class_quota": student.total_class_quota,
        "remarks_for_mentor": student.remarks_for_mentor or "",
        "status": student.status.lower(),
        "status_note": student.status_note or "",
        # Raw value: the scheduling sheet tells "unset" (offer the IST
        # default, say it is unset) apart from an explicit choice.
        "timezone": student.timezone,
        "profile": {
            "email": student.profile.email if student.profile else "",
            "avatar_url": student.profile.avatar_url if student.profile else None
        } if student.profile else None,
        "mentor_profile": _profile_brief(student.mentor),
        "tutor_profile": _profile_brief(student.tutor),
    }


def redact_student_for_role(data, user):
    """
    Cut the student row down to what this caller's students table already
    shows them. Keys are removed rather than blanked so the SPA can tell "not
    visible to you" from "empty on the student".
    """
    role = getattr(user, 'role', None)
    if role == 'TUTOR' and not user.is_superuser:
        kept = {key: value for key, value in data.items() if key in TUTOR_VISIBLE_FIELDS}
        if kept.get('profile'):
            # The tutor's column set carries the avatar but no contact details.
            kept['profile'] = {"avatar_url": kept['profile'].get('avatar_url')}
        return kept
    return data


def _round1(value):
    """One decimal place, with -0.0 and 7.000000001 normalised away."""
    return round(value + 0.0, 1)


def _session_stats(student):
    counts = Session.objects.filter(student=student).aggregate(
        total=Count('id'),
        scheduled=Count('id', filter=Q(status=SessionStatusChoices.SCHEDULED)),
        attended=Count('id', filter=Q(status=SessionStatusChoices.ATTENDED)),
        cancelled=Count('id', filter=Q(status=SessionStatusChoices.CANCELLED)),
        upcoming=Count('id', filter=Q(
            status=SessionStatusChoices.SCHEDULED, start_time__gte=timezone.now()
        )),
    )
    # "Pending" is derived from the link columns, never stored -- the same
    # definition Session.display_status and the ?content= filter use.
    counts['pending'] = apply_content_filter(
        Session.objects.filter(student=student), 'missing_content'
    ).count()
    return counts


def _quota_stats(student):
    purchased = float(student.total_class_quota or 0)
    used = calculate_credits_used(student)
    return {
        "purchased": student.total_class_quota or 0,
        "used_hours": _round1(used),
        # Can go negative only if a quota was lowered after booking; the UI
        # shows the overdraft rather than clamping it away.
        "remaining_hours": _round1(purchased - used),
    }


def quota_stats(student):
    """
    The profile's quota block on its own -- what the manual "Sync from sheet"
    action returns so the cards can repaint without a second profile fetch.
    Same function, same numbers as ``build_profile_stats()['quota']``.
    """
    return _quota_stats(student)


def _exam_stats(student, user):
    """
    Chapter + additional exam counters, or ``None`` for a caller with no exam
    access at all (tutors). Scoped through the same helper the exams endpoints
    use, so the counts can never describe rows the caller cannot open.
    """
    from exams.models import (
        AdditionalExam,
        AdditionalExamStatusChoices,
        Exam,
        ExamStatusChoices,
    )

    if getattr(user, 'role', None) == 'TUTOR' and not user.is_superuser:
        # Tutors are scoped to no exams at all, and "0 exams" would read as a
        # fact about the student rather than about the caller's access.
        return None

    exams = scope_exams_by_role(Exam.objects.filter(student=student), user)
    additional = scope_exams_by_role(AdditionalExam.objects.filter(student=student), user)

    chapter = exams.aggregate(
        total=Count('id'),
        scheduled=Count('id', filter=Q(status=ExamStatusChoices.SCHEDULED)),
        attended=Count('id', filter=Q(status=ExamStatusChoices.ATTENDED)),
        cancelled=Count('id', filter=Q(status=ExamStatusChoices.CANCELLED)),
        upcoming=Count('id', filter=Q(
            status=ExamStatusChoices.SCHEDULED, start_time__gte=timezone.now()
        )),
    )
    # Unweighted mean of the per-exam percentages, matching the Learn
    # scorecard's arithmetic (each item rounded, then averaged).
    scored = exams.filter(
        status=ExamStatusChoices.ATTENDED, score__isnull=False, max_score__gt=0
    ).values_list('score', 'max_score')
    percentages = [round(score / max_score * 100) for score, max_score in scored]
    chapter['scored'] = len(percentages)
    chapter['average_pct'] = _round1(sum(percentages) / len(percentages)) if percentages else None

    extra = additional.aggregate(
        total=Count('id'),
        assigned=Count('id', filter=Q(status=AdditionalExamStatusChoices.ASSIGNED)),
        submitted=Count('id', filter=Q(status=AdditionalExamStatusChoices.SUBMITTED)),
        scored=Count('id', filter=Q(status=AdditionalExamStatusChoices.SCORED)),
    )
    return {"chapter": chapter, "additional": extra}


def _homework_stats(student):
    from homework.models import Homework, HomeworkStatusChoices

    # Homework rows only ever exist for this student's own sessions, so the
    # mentor/tutor scoping that core.querysets applies to the list endpoint is
    # already satisfied by the student filter.
    return Homework.objects.filter(student=student).aggregate(
        total=Count('id'),
        assigned=Count('id', filter=Q(status=HomeworkStatusChoices.ASSIGNED)),
        submitted=Count('id', filter=Q(status=HomeworkStatusChoices.SUBMITTED)),
        scored=Count('id', filter=Q(status=HomeworkStatusChoices.SCORED)),
    )


def build_profile_stats(student, user):
    """
    The Overview tab's numbers in one pass. ``exams`` is ``None`` when the
    caller has no exam access (tutor), which is how the SPA decides whether to
    render the Exams tab at all.
    """
    stats = {
        "quota": _quota_stats(student),
        "sessions": _session_stats(student),
        "homework": _homework_stats(student),
        "exams": _exam_stats(student, user),
    }
    if getattr(user, 'role', None) == 'TUTOR' and not user.is_superuser:
        # The tutor's students table deliberately omits quota.
        stats.pop('quota')
    return stats


def profile_highlights(student, user):
    """
    The "Next up" strip: the next scheduled class, the last attended one and
    the next scheduled exam. Serialized with the same serializers the list
    endpoints use so the SPA renders them with its existing helpers.
    """
    from sessions.serializers import SessionSerializer

    now = timezone.now()
    base = Session.objects.filter(student=student).select_related(
        'student', 'student__profile', 'tutor', 'homework'
    ).prefetch_related('files')
    next_session = base.filter(
        status=SessionStatusChoices.SCHEDULED, start_time__gte=now
    ).order_by('start_time').first()
    last_session = base.filter(
        status=SessionStatusChoices.ATTENDED
    ).order_by('-start_time').first()

    out = {
        "next_session": SessionSerializer(next_session).data if next_session else None,
        "last_session": SessionSerializer(last_session).data if last_session else None,
        "next_exam": None,
    }

    from exams.models import Exam, ExamStatusChoices
    from exams.serializers import ExamSerializer
    next_exam = scope_exams_by_role(
        Exam.objects.filter(
            student=student, status=ExamStatusChoices.SCHEDULED, start_time__gte=now
        ), user
    ).select_related('student', 'student__profile', 'mentor').prefetch_related('files').order_by('start_time').first()
    if next_exam:
        out['next_exam'] = ExamSerializer(next_exam).data
    return out
