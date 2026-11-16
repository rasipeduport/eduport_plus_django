"""
Notes on a lead (bookings.models.LeadNote): the plain running discussion staff
keep on one enquiry, read and added from three places, each of which finds the
lead the way its own workspace already does:

    GET/POST /api/bde/enquiries/<lead_id>/notes/       its owner BDE (bookings.views)
    GET/POST /api/tutor/bookings/<type>/<id>/notes/    a tutor assigned to one of its bookings now --
                                                       that booking's lead's notes (bookings.tutor_views)
    GET/POST /api/leads/<lead_id>/notes/               the administrators (bookings.lead_views)

So whoever may read the lead there may read its notes and add one, and anyone
else is answered as that workspace answers a lead or booking that does not
exist. A note belongs to the lead, never to a booking: the lead's Diagnostic
and Demo bookings share one discussion. Notes are staff's words only -- no
parent or student page, booking history, activity log or notification carries
them -- and are kept as written, never edited or deleted.
"""
from .models import LeadNote
from .scheduling import BOOKING_TIMEZONE_NAME

NOTE_MAX_LENGTH = 2000
INVALID_NOTE = f'Write the note, in {NOTE_MAX_LENGTH} characters at most.'


def note_row(note):
    """One note as the API gives it: what it says, who wrote it, in which role, and when."""
    return {
        'id': str(note.id),
        'body': note.body,
        'author': {'full_name': note.author_name},
        'author_role': note.author_role,
        'author_role_label': note.get_author_role_display(),
        'created_at': note.created_at.isoformat(),
    }


def notes_of(lead):
    """Every note on ``lead``, oldest first: {"results", "count", "timezone"}."""
    rows = [note_row(note) for note in LeadNote.objects.filter(lead=lead).order_by('created_at', 'id')]
    return {'results': rows, 'count': len(rows), 'timezone': BOOKING_TIMEZONE_NAME}


def add_note(lead, author, role, body):
    """Add ``body`` to ``lead``'s notes, written by ``author`` in ``role`` (a LeadNoteRole)."""
    return LeadNote.objects.create(
        lead=lead, body=body, author=author, author_name=author.full_name or author.email, author_role=role,
    )
