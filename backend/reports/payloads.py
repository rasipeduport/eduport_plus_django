"""
Reports as the Hub's APIs answer them, written out field by field, so nothing
reaches a caller by being added to a model: a report carries the fields its
tutor writes, the system fields as the report prints them, its version and
when it was saved -- never the parent, the lead, the booking's submission or
the BDE.
"""
from bookings.enquiries import booking_brief


def report_body(report):
    """One report as last saved. ``fields`` is what an edit sends back, with the ``version`` it was made from."""
    return {
        'id': str(report.id),
        'booking_id': str(report.booking_id),
        'booking_type': report.booking_type,
        'version': report.version,
        'fields': {field: getattr(report, field) for field in report.TUTOR_FIELDS},
        # The system fields as the report prints them (D7).
        'student_name': report.student_name_snapshot,
        'grade': report.grade_snapshot,
        'tutor_name': report.tutor_name_snapshot,
        'submitted_at': _when(report.submitted_at),
        'updated_at': _when(report.updated_at),
    }


def revision_rows(report):
    """
    Every saved version of ``report``, oldest first: what it said, which fields
    that save changed, who saved it and when. Revisions are append-only, so
    this is the report's whole history.
    """
    rows = []
    for revision in report.revisions.select_related('edited_by').order_by('version'):
        content = revision.content
        rows.append({
            'version': revision.version,
            'changed_fields': list(revision.changed_fields),
            'edited_at': _when(revision.edited_at),
            'edited_by': {'id': str(revision.edited_by_id), 'name': revision.edited_by.full_name},
            'fields': {field: content.get(field) for field in report.TUTOR_FIELDS},
            'student_name': content.get('student_name_snapshot'),
            'grade': content.get('grade_snapshot'),
            'tutor_name': content.get('tutor_name_snapshot'),
        })
    return rows


def booking_completion(booking):
    """The booking a submit or edit was made on: its status, and when it was completed."""
    return {
        'id': str(booking.id),
        'booking_type': booking.booking_type,
        'status': booking.status,
        'completed_at': _when(booking.completed_at),
    }


def lead_report_row(booking):
    """
    One report on a lead's list, as the lead's owner BDE reads it (P9): the
    booking it was written on -- when it was, and that it is completed -- and
    the report as last saved. Nothing about sending it: no send is recorded.
    """
    return {
        'booking': {**booking_brief(booking), 'status': booking.status, 'completed_at': _when(booking.completed_at)},
        'report': report_body(booking.report),
    }


def _when(value):
    return value.isoformat() if value else None
