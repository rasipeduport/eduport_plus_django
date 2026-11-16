"""
manage.py export_bookings, the cutover rollback's CSV (design I.5): which
bookings it holds, the Submissions sheet's columns and values, the file it
writes, and that it only reads.
"""
import csv
import io
import os
import stat
import tempfile
from datetime import datetime, timedelta
from unittest import mock

from django.core.management import CommandError, call_command
from django.db import connection
from django.test.utils import CaptureQueriesContext

from activity.models import ActivityLog

from .booking_service import cancel_booking, reschedule_booking
from .management.commands.export_bookings import BOOKING_COLUMNS, SHEET_COLUMNS
from .models import BookingEvent, BookingSlot, CancelReason, Lead, RescheduleReason
from .scheduling import BOOKING_TIMEZONE
from .tests_booking import DAY, DIAGNOSTIC, MORNING, NOW, BookingTestCase, account, book, booking_count

# The switch to Django: 27 Oct 2026, 09:00 in India (03:30 UTC).
SWITCH = datetime(2026, 10, 27, 9, 0, tzinfo=BOOKING_TIMEZONE)
PRIVATE = ('Riya', 'Asha', '501234567', 'Delhi', 'United Arab')


def booked(**kwargs):
    """A new booking, made through create_booking."""
    return book(**kwargs)[0]


def made_at(booking, when):
    """Set when ``booking`` was made, which is what the export picks bookings by."""
    type(booking).objects.filter(pk=booking.pk).update(created_at=when)
    booking.refresh_from_db()
    return booking


class ExportTestCase(BookingTestCase):
    def export(self, *args):
        """The rows the command writes to standard output for ``args``, and its summary."""
        out, err = io.StringIO(), io.StringIO()
        with mock.patch('bookings.management.commands.export_bookings.timezone.now', return_value=NOW):
            call_command('export_bookings', *args, '--output', '-', stdout=out, stderr=err)
        self.assertEqual(out.getvalue().splitlines()[0].split(','), [*SHEET_COLUMNS, *BOOKING_COLUMNS])
        return list(csv.DictReader(io.StringIO(out.getvalue()))), err.getvalue()


class WhichBookingsTests(ExportTestCase):
    def setUp(self):
        super().setUp()
        made_at(booked(student='Before'), SWITCH - timedelta(minutes=1))
        made_at(booked(student='At'), SWITCH)
        made_at(booked(student='Later', booking_type=DIAGNOSTIC, at=MORNING), SWITCH + timedelta(hours=2))

    def students(self, *args):
        return [row['Student Name'] for row in self.export(*args)[0]]

    def test_bookings_made_since_the_moment_oldest_first(self):
        self.assertEqual(self.students('--since', '2026-10-27T09:00'), ['At', 'Later'])
        # The same moment with an offset; a bare date is midnight in India.
        self.assertEqual(self.students('--since', '2026-10-27T03:30Z'), ['At', 'Later'])
        self.assertEqual(self.students('--since', '2026-10-27'), ['Before', 'At', 'Later'])

    def test_until_is_exclusive_and_type_narrows(self):
        self.assertEqual(self.students('--since', '2026-10-27T09:00', '--until', '2026-10-27T11:00'), ['At'])
        self.assertEqual(self.students('--since', '2026-10-27', '--type', 'diagnostic'), ['Later'])
        self.assertEqual(self.students('--since', '2026-10-28'), [])

    def test_bad_moments_are_refused(self):
        for args in (('--since', 'yesterday'), ('--since', '2026-10-27', '--until', '2026-10-27'),
                     ('--since', '2026-10-27T09:00', '--until', '2026-10-27T08:00'), ('--since', '2026-02-30')):
            with self.subTest(args=args), self.assertRaises(CommandError):
                self.export(*args)


class RowTests(ExportTestCase):
    def test_a_row_holds_what_the_routes_wrote_to_the_sheet(self):
        booking = made_at(booked(), datetime(2026, 10, 27, 19, 5, 9, tzinfo=BOOKING_TIMEZONE))
        # A later booking updates the lead; the row keeps what this one submitted.
        book(booking_type=DIAGNOSTIC, at=MORNING, school='New School')
        rows, _summary = self.export('--since', '2026-10-27', '--type', 'demo')
        self.assertEqual(rows, [{
            'Timestamp': '27/10/2026, 07:05:09 pm',
            'Parent Name': 'Asha Nair',
            'Phone': "'+971 0501234567",
            'Student Name': 'Riya',
            'School': 'Delhi Private School',
            'Class': 'Class 8',
            'Syllabus': 'CBSE',
            'Date': 'Wednesday, 28 Oct 2026',
            'Country': 'United Arab Emirates',
            'Time': '06:00 pm - 07:00 pm',
            'Time IST': '07:30 pm',
            'Booking Type': 'Demo',
            'Status': 'Booked',
            'Live': 'Yes',
            'Booking ID': str(booking.id),
            'Replaces Booking ID': '',
            'Slot Starts (UTC)': '2026-10-28T14:00:00+00:00',
            'Made At (UTC)': '2026-10-27T13:35:09+00:00',
        }])
        self.assertEqual(Lead.objects.get().school_name, 'New School')

    def test_moved_and_cancelled_bookings_say_what_became_of_them(self):
        first = made_at(booked(), SWITCH + timedelta(hours=1))
        moved = reschedule_booking(first, DAY + timedelta(days=2), MORNING, reason_code=RescheduleReason.OTHER,
                                   actor=account('admin_one', role='ADMIN'), now=NOW).booking
        moved = made_at(moved, SWITCH + timedelta(hours=3))
        cancelled = made_at(booked(student='Ali'), SWITCH + timedelta(hours=2))
        cancel_booking(cancelled, reason_code=CancelReason.PARENT_REQUEST)

        rows, summary = self.export('--since', '2026-10-27T09:00')
        by_id = {row['Booking ID']: row for row in rows}
        self.assertEqual([row['Booking ID'] for row in rows], [str(first.id), str(cancelled.id), str(moved.id)])
        self.assertEqual((by_id[str(first.id)]['Status'], by_id[str(first.id)]['Live']), ('Rescheduled', 'No'))
        self.assertEqual((by_id[str(cancelled.id)]['Status'], by_id[str(cancelled.id)]['Live']), ('Cancelled', 'No'))
        replacement = by_id[str(moved.id)]
        self.assertEqual(
            {key: replacement[key] for key in ('Status', 'Live', 'Replaces Booking ID', 'Date', 'Time IST', 'Time')},
            {'Status': 'Booked', 'Live': 'Yes', 'Replaces Booking ID': str(first.id), 'Date': 'Friday, 30 Oct 2026',
             'Time IST': '10:00 am', 'Time': ''},
        )
        self.assertIn('Demo: 3 (booked 1, cancelled 1, rescheduled 1); live 1', summary)

    def test_a_booking_whose_slot_has_ended_is_not_live(self):
        made_at(booked(), SWITCH)
        rows, _summary = self.export('--since', '2026-10-27')
        with mock.patch('bookings.management.commands.export_bookings.timezone.now',
                        return_value=datetime(2026, 10, 28, 20, 30, tzinfo=BOOKING_TIMEZONE)):
            out = io.StringIO()
            call_command('export_bookings', '--since', '2026-10-27', '--output', '-', stdout=out, stderr=io.StringIO())
        self.assertEqual((rows[0]['Live'], next(csv.DictReader(io.StringIO(out.getvalue())))['Live']), ('Yes', 'No'))

    def test_what_a_spreadsheet_would_run_is_neutralised(self):
        made_at(booked(parent_name='=HYPERLINK("http://example.test","x")', student='+Riya', school='@school',
                     country='-1'), SWITCH)
        row = self.export('--since', '2026-10-27')[0][0]
        self.assertEqual(
            (row['Parent Name'], row['Student Name'], row['School'], row['Country'], row['Class']),
            ('\'=HYPERLINK("http://example.test","x")', "'+Riya", "'@school", "'-1", 'Class 8'),
        )


class SafetyTests(ExportTestCase):
    def test_it_only_reads(self):
        made_at(booked(), SWITCH)
        before = (booking_count(), Lead.objects.count(), BookingSlot.objects.count(), BookingEvent.objects.count(),
                  ActivityLog.objects.count())
        with CaptureQueriesContext(connection) as queries:
            self.export('--since', '2026-10-27')
        statements = [query['sql'].lstrip().split()[0].upper() for query in queries.captured_queries]
        if connection.vendor == 'postgresql':
            self.assertIn('SET TRANSACTION READ ONLY', [query['sql'] for query in queries.captured_queries][:2])
        self.assertFalse({'INSERT', 'UPDATE', 'DELETE'} & set(statements), statements)
        self.assertEqual(before, (booking_count(), Lead.objects.count(), BookingSlot.objects.count(),
                                  BookingEvent.objects.count(), ActivityLog.objects.count()))

    def test_a_file_is_new_and_its_owners_alone(self):
        made_at(booked(), SWITCH)
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, 'bookings.csv')
            err = io.StringIO()
            call_command('export_bookings', '--since', '2026-10-27', '--output', path, stderr=err)
            self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
            with open(path, encoding='utf-8', newline='') as stream:
                written = stream.read()
            self.assertEqual(len(list(csv.DictReader(io.StringIO(written)))), 1)
            self.assertIn(f'1 booking(s) made since 2026-10-27 00:00 IST, to {path}.', err.getvalue())
            with self.assertRaisesMessage(CommandError, 'never overwrites'):
                call_command('export_bookings', '--since', '2026-10-27', '--output', path, stderr=io.StringIO())
            with open(path, encoding='utf-8', newline='') as stream:
                self.assertEqual(stream.read(), written)

    def test_the_summary_counts_and_names_no_one(self):
        made_at(booked(), SWITCH)
        made_at(booked(booking_type=DIAGNOSTIC, at=MORNING), SWITCH)
        _rows, summary = self.export('--since', '2026-10-27T09:00')
        self.assertIn('2 booking(s) made since 2026-10-27 09:00 IST, to standard output.', summary)
        self.assertIn('Demo: 1 (booked 1); live 1', summary)
        self.assertIn('Diagnostic: 1 (booked 1); live 1', summary)
        for private in PRIVATE:
            self.assertNotIn(private, summary)
