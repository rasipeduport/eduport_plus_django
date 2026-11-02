"""
    python manage.py export_bookings --since WHEN [--until WHEN] [--type {demo,diagnostic}] --output PATH|-

The cutover rollback's export (design I.5): every Demo and Diagnostic booking
made in Django since a moment -- the switch -- as CSV, for operations to
re-enter in the Google Sheets funnel should the site go back to it.
Re-entering them is a separate step that needs approval at the time. This
command only reads the database, in a read-only transaction, and never
touches Google Sheets or anything else outside it.

WHEN is YYYY-MM-DD or YYYY-MM-DDTHH:MM[:SS], in Indian time unless it carries
an offset (+05:30, Z). A booking is in when it was made at or after --since
and before --until. A reschedule makes a new booking, so one moved since the
switch is in with its new slot even when the original was made before.

The first eleven columns are the Submissions sheet's (A:K), in its order and
with the values the booking routes wrote there -- the Indian timestamp, the
details as the parent submitted them, the date and Indian time as the pages
label them -- so a re-entered row counts towards its slot. The time the
parent was shown in their own zone is left empty for a moved booking: it
named the old slot. The rest say which booking a row is and what became of
it; only a live one (booked, its slot not yet ended) still needs a seat.

A cell a spreadsheet would read as a formula (=, +, -, @) starts with an
apostrophe, as the routes wrote phone numbers. The file holds parents' names
and phone numbers: it is created readable by its owner only and never
overwrites one that exists; ``--output -`` writes to standard output. The
summary, counts only, goes to standard error.
"""
import csv
import os
from datetime import datetime, timezone as dt_timezone

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.utils import timezone

from bookings.models import BOOKING_MODELS, BookingStatus, BookingType, booking_model
from bookings.scheduling import BOOKING_TIMEZONE

TYPES = {'demo': BookingType.DEMO, 'diagnostic': BookingType.DIAGNOSTIC}
SHEET_COLUMNS = (
    'Timestamp', 'Parent Name', 'Phone', 'Student Name', 'School', 'Class', 'Syllabus', 'Date', 'Country', 'Time',
    'Time IST',
)
BOOKING_COLUMNS = (
    'Booking Type', 'Status', 'Live', 'Booking ID', 'Replaces Booking ID', 'Slot Starts (UTC)', 'Made At (UTC)',
)
# Fixed English names, as the booking pages label dates (lib/booking-backend/format.ts).
WEEKDAYS = ('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday')
MONTHS = ('Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec')
FORMULA_STARTS = ('=', '+', '-', '@', '\t', '\r')


def _instant(value, option):
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        raise CommandError(f'{option} is YYYY-MM-DD or YYYY-MM-DDTHH:MM, received "{value}".')
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=BOOKING_TIMEZONE)


def date_label(day):
    """28 Oct 2026 as the pages label it: "Wednesday, 28 Oct 2026"."""
    return f'{WEEKDAYS[day.weekday()]}, {day.day:02d} {MONTHS[day.month - 1]} {day.year}'


def time_label(value):
    """19:30 as the pages label it: "07:30 pm"."""
    return f'{value.hour % 12 or 12:02d}:{value.minute:02d} {"am" if value.hour < 12 else "pm"}'


def timestamp_label(instant):
    """An instant as the routes stamped a row, in Indian time: "28/10/2026, 07:05:09 pm"."""
    local = instant.astimezone(BOOKING_TIMEZONE)
    return f'{local:%d/%m/%Y}, {local.hour % 12 or 12:02d}:{local:%M:%S} {"am" if local.hour < 12 else "pm"}'


def cell(value):
    """``value`` as a CSV cell no spreadsheet will run as a formula."""
    text = '' if value is None else str(value)
    return f"'{text}" if text.startswith(FORMULA_STARTS) else text


class Command(BaseCommand):
    help = 'Export the Demo and Diagnostic bookings made since a moment as CSV, for the cutover rollback.'

    def add_arguments(self, parser):
        parser.add_argument('--since', required=True, help='Bookings made at or after this moment (Indian time unless offset).')
        parser.add_argument('--until', help='And before this one.')
        parser.add_argument('--type', dest='booking_type', choices=sorted(TYPES), help='One booking type only; both without it.')
        parser.add_argument('--output', required=True, help='A new file to write, or - for standard output.')

    def handle(self, *args, since, until=None, booking_type=None, output, **options):
        since = _instant(since, '--since')
        until = _instant(until, '--until') if until else None
        if until is not None and until <= since:
            raise CommandError('--until must come after --since.')
        models = (booking_model(TYPES[booking_type]),) if booking_type else BOOKING_MODELS
        if output != '-' and os.path.exists(output):
            raise CommandError(f'{output} exists; the export never overwrites a file.')

        now = timezone.now()
        bookings = self._bookings(models, since, until)
        rows = [self._row(booking, now) for booking in bookings]
        if output == '-':
            self._write(self.stdout, rows)
        else:
            try:
                handle = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                raise CommandError(f'{output} exists; the export never overwrites a file.')
            with open(handle, 'w', encoding='utf-8', newline='') as stream:
                self._write(stream, rows)
        self._summary(bookings, since, until, now, output)

    @staticmethod
    def _bookings(models, since, until):
        """The bookings made in [since, until), oldest first, read in one read-only transaction."""
        found = []
        with transaction.atomic():
            if connection.vendor == 'postgresql':
                with connection.cursor() as cursor:
                    cursor.execute('SET TRANSACTION READ ONLY')
            for model in models:
                bookings = model.objects.filter(created_at__gte=since).select_related('slot')
                if until is not None:
                    bookings = bookings.filter(created_at__lt=until)
                found.extend(bookings)
        return sorted(found, key=lambda booking: (booking.created_at, booking.booking_type, str(booking.id)))

    @staticmethod
    def _row(booking, now):
        details, slot = booking.details or {}, booking.slot
        live = booking.status == BookingStatus.BOOKED and slot.ends_at > now
        sheet = (
            timestamp_label(booking.created_at),
            details.get('parent_name'),
            details.get('phone'),
            details.get('student_name'),
            details.get('school'),
            details.get('student_class'),
            details.get('syllabus'),
            date_label(slot.local_date),
            details.get('country'),
            '' if booking.rescheduled_from_id else details.get('display_time'),
            time_label(slot.local_time),
        )
        about = (
            booking.get_booking_type_display(),
            booking.get_status_display(),
            'Yes' if live else 'No',
            booking.id,
            booking.rescheduled_from_id,
            slot.starts_at.astimezone(dt_timezone.utc).isoformat(),
            booking.created_at.astimezone(dt_timezone.utc).isoformat(),
        )
        return [cell(value) for value in (*sheet, *about)]

    @staticmethod
    def _write(stream, rows):
        writer = csv.writer(stream, lineterminator='\n')
        writer.writerow((*SHEET_COLUMNS, *BOOKING_COLUMNS))
        writer.writerows(rows)

    def _summary(self, bookings, since, until, now, output):
        window = f'made since {since.astimezone(BOOKING_TIMEZONE):%Y-%m-%d %H:%M} IST'
        if until is not None:
            window += f' and before {until.astimezone(BOOKING_TIMEZONE):%Y-%m-%d %H:%M} IST'
        self.stderr.write(f'{len(bookings)} booking(s) {window}, to {"standard output" if output == "-" else output}.')
        for booking_type in (BookingType.DEMO, BookingType.DIAGNOSTIC):
            of_type = [booking for booking in bookings if booking.booking_type == booking_type]
            if not of_type:
                continue
            counts = ', '.join(
                f'{label.lower()} {count}' for value, label in BookingStatus.choices
                if (count := sum(booking.status == value for booking in of_type))
            )
            live = sum(booking.status == BookingStatus.BOOKED and booking.slot.ends_at > now for booking in of_type)
            self.stderr.write(f'  {booking_type.label}: {len(of_type)} ({counts}); live {live}')
