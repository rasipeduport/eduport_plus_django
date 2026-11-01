"""
A booking's history (bookings.history, bookings.models.BookingEvent): one
event per change, written in the change's own transaction, ids, statuses and
codes only -- never free text -- and never updated or deleted.
"""
import json
from unittest import mock

from django.db import IntegrityError, connection, transaction
from django.db.models import ProtectedError
from django.db.utils import DatabaseError

from .booking_service import InvalidReason, assign_tutor, cancel_booking, create_booking, unassign_tutor
from . import history
from .models import BookingEvent, BookingEventKind, CancelReason, DemoBooking, DiagnosticBooking, Lead
from .tests_assignment import tutor
from .tests_booking import DIAGNOSTIC, MORNING, NOW, BookingTestCase, account, book, booking_count, link, request

PRIVATE = ('Riya', 'Asha Nair', 'Delhi Private School', '501234567', 'United Arab Emirates')


class HistoryTests(BookingTestCase):
    def setUp(self):
        super().setUp()
        self.admin = account('admin_one', role='ADMIN')
        self.tutor_a, self.tutor_b = tutor('tutor_anu'), tutor('tutor_binu')

    def kinds(self, booking):
        return [event.kind for event in booking.events.all()]

    def test_each_change_is_one_event(self):
        bde = account('bde_one')
        booking, _ = book(ref=link(bde).token)
        created = booking.events.all().get()
        self.assertEqual((created.kind, created.actor, created.demo_booking, created.diagnostic_booking),
                         (BookingEventKind.CREATED, None, booking, None))
        self.assertEqual(created.data, {
            'slot_id': str(booking.slot_id), 'seat': 1, 'referral_status': 'ATTRIBUTED', 'via': 'public_booking',
        })

        assign_tutor(booking, self.tutor_a, actor=self.admin, now=NOW)
        assign_tutor(booking, self.tutor_b, actor=self.admin, now=NOW)
        unassign_tutor(booking, actor=self.admin, now=NOW)
        cancel_booking(booking, actor=self.admin, reason_code=CancelReason.PARENT_REQUEST)
        booking.refresh_from_db()
        self.assertEqual(self.kinds(booking), [
            BookingEventKind.CREATED, BookingEventKind.TUTOR_ASSIGNED, BookingEventKind.TUTOR_ASSIGNED,
            BookingEventKind.TUTOR_UNASSIGNED, BookingEventKind.CANCELLED,
        ])
        _created, first, second, unassigned, cancelled = booking.events.all()
        self.assertEqual(first.data, {'old_tutor_id': None, 'new_tutor_id': str(self.tutor_a.id)})
        self.assertEqual(second.data, {'old_tutor_id': str(self.tutor_a.id), 'new_tutor_id': str(self.tutor_b.id)})
        self.assertEqual(unassigned.data, {'old_tutor_id': str(self.tutor_b.id)})
        # A reason code, never free text: on the booking and in its history alike.
        self.assertEqual(cancelled.data, {'from_status': 'BOOKED', 'to_status': 'CANCELLED', 'reason_code': 'PARENT_REQUEST'})
        self.assertEqual((booking.cancel_reason_code, booking.cancel_reason), ('PARENT_REQUEST', ''))
        self.assertEqual({event.actor for event in (first, second, unassigned, cancelled)}, {self.admin})

    def test_nothing_changed_is_no_event(self):
        booking, _ = book()
        book(phone='501234567')  # the same submission again
        assign_tutor(booking, self.tutor_a, actor=self.admin, now=NOW)
        assign_tutor(booking, self.tutor_a, actor=self.admin, now=NOW)
        cancel_booking(booking, actor=self.admin, reason_code=CancelReason.OTHER)
        cancel_booking(booking, actor=self.admin, reason_code=CancelReason.OTHER)
        other, _ = book(student='Ali', at=MORNING)
        unassign_tutor(other, actor=self.admin, now=NOW)
        self.assertEqual(self.kinds(booking), [
            BookingEventKind.CREATED, BookingEventKind.TUTOR_ASSIGNED, BookingEventKind.CANCELLED,
        ])
        self.assertEqual(self.kinds(other), [BookingEventKind.CREATED])

    def test_each_type_keeps_its_own_history(self):
        demo, _ = book()
        diagnostic, _ = book(booking_type=DIAGNOSTIC)
        self.assertEqual((demo.events.all().get().demo_booking, demo.events.all().get().diagnostic_booking), (demo, None))
        self.assertEqual(diagnostic.events.all().get().diagnostic_booking, diagnostic)
        self.assertEqual(diagnostic.events.all().get().booking, diagnostic)

    def test_ids_statuses_and_codes_only(self):
        booking, _ = book()
        assign_tutor(booking, self.tutor_a, actor=self.admin, now=NOW)
        # Free text is no reason at all (Q9, M1): refused before anything is written.
        with self.assertRaises(InvalidReason):
            cancel_booking(booking, actor=self.admin, reason_code='Asha Nair called from 501234567 to cancel')
        cancel_booking(booking, actor=self.admin, reason_code=CancelReason.PARENT_REQUEST)
        recorded = json.dumps([event.data for event in BookingEvent.objects.all()])
        for private in (*PRIVATE, 'called', self.tutor_a.full_name, self.tutor_a.email):
            self.assertNotIn(private, recorded)
        booking.refresh_from_db()
        self.assertEqual((booking.cancel_reason_code, booking.cancel_reason), ('PARENT_REQUEST', ''))

    def test_free_text_is_refused_before_anything_is_written(self):
        booking, _ = book()
        for data in ({'reason': 'Parent asked'}, {'note': 'x'}, {'student_name': 'Riya'}):
            with self.subTest(keys=sorted(data)), self.assertRaises(ValueError):
                history.record(booking, BookingEventKind.CANCELLED, actor=self.admin, **data)
        self.assertEqual(self.kinds(booking), [BookingEventKind.CREATED])
        # Every key the service writes is one the history knows.
        self.assertLessEqual({'slot_id', 'seat', 'referral_status', 'via', 'old_tutor_id', 'new_tutor_id',
                              'from_status', 'to_status'}, history.DATA_KEYS)

    def test_a_change_and_its_event_commit_or_roll_back_together(self):
        with mock.patch('bookings.booking_service.history.record', side_effect=RuntimeError('history down')):
            with self.assertRaises(RuntimeError):
                create_booking(request(), now=NOW)
        self.assertEqual((booking_count(), Lead.objects.count(), BookingEvent.objects.count()), (0, 0, 0))

        booking, _ = book()
        for change in (lambda: assign_tutor(booking, self.tutor_a, actor=self.admin, now=NOW),
                       lambda: cancel_booking(booking, actor=self.admin, reason_code=CancelReason.OTHER)):
            with mock.patch('bookings.booking_service.history.record', side_effect=RuntimeError('history down')):
                with self.assertRaises(RuntimeError):
                    change()
            booking.refresh_from_db()
            self.assertEqual((booking.status, booking.assigned_tutor), ('BOOKED', None))
        self.assertEqual(self.kinds(booking), [BookingEventKind.CREATED])


class AppendOnlyTests(BookingTestCase):
    def setUp(self):
        super().setUp()
        self.booking, _ = book()
        self.event = self.booking.events.all().get()

    def assertRefused(self, change):
        with self.assertRaisesMessage(DatabaseError, 'booking_events is append-only'), transaction.atomic():
            change()

    def test_never_updated_or_deleted(self):
        def save():
            self.event.kind = BookingEventKind.CANCELLED
            self.event.save()

        def raw_update():
            with connection.cursor() as cursor:
                cursor.execute("UPDATE booking_events SET kind = 'CANCELLED' WHERE id = %s", [str(self.event.pk)])

        def raw_delete():
            with connection.cursor() as cursor:
                cursor.execute('DELETE FROM booking_events')

        for change in (save, lambda: BookingEvent.objects.update(data={}), lambda: self.event.delete(),
                       lambda: BookingEvent.objects.all().delete(), raw_update, raw_delete):
            self.assertRefused(change)
        self.assertEqual(self.booking.events.all().get().kind, BookingEventKind.CREATED)

    def test_one_booking_and_a_known_kind(self):
        for fields in ({}, {'demo_booking': self.booking, 'diagnostic_booking': self.diagnostic()},
                       {'demo_booking': self.booking, 'kind': 'EMAILED'}):
            with self.subTest(fields=sorted(fields)), self.assertRaises(IntegrityError), transaction.atomic():
                BookingEvent.objects.create(**{'kind': BookingEventKind.CREATED, **fields})

    def diagnostic(self):
        booking, _ = book(booking_type=DIAGNOSTIC)
        return booking

    def test_a_booking_with_history_is_never_deleted(self):
        for booking in (self.booking, self.diagnostic()):
            with self.subTest(model=type(booking).__name__), self.assertRaises(ProtectedError), transaction.atomic():
                booking.delete()
        self.assertTrue(DemoBooking.objects.filter(pk=self.booking.pk).exists())
        self.assertEqual(DiagnosticBooking.objects.count(), 1)
