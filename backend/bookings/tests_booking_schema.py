"""
The Diagnostic/Demo booking split (bookings.0005): the migration from the
combined table and back, what each booking table refuses, and
``manage.py booking_split_check`` before and after.
"""
import threading
import uuid
from datetime import timedelta
from io import StringIO
from unittest import skipUnless

from django.core.management import CommandError, call_command
from django.db import IntegrityError, OperationalError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from .leads import name_key
from .models import (
    BookingChannel,
    BookingSlot,
    BookingStatus,
    BookingType,
    DemoBooking,
    DiagnosticBooking,
    Lead,
    ReferralStatus,
)
from .scheduling import slot_instants
from .tests_assignment import ist, tutor
from .tests_booking import DAY, EVENING, MORNING, account

DEMO, DIAGNOSTIC = BookingType.DEMO, BookingType.DIAGNOSTIC
BEFORE_SPLIT = '0004_booking_tutor_assignment'
SPLIT = '0005_booking_split'
NEW_TABLES = {'diagnostic_bookings', 'demo_bookings', 'booking_events'}
KEPT_TABLES = ('leads', 'booking_slots', 'booking_slot_times', 'booking_links')


def check(*args):
    """booking_split_check's output, or CommandError (with the output so far) when a check fails."""
    out = StringIO()
    try:
        call_command('booking_split_check', *args, stdout=out)
    except CommandError as exc:
        exc.output = out.getvalue()
        raise
    return out.getvalue()


class SplitMigrationTests(TransactionTestCase):
    """
    0005 from the combined table holding test bookings, back to it and on
    again. The test steps back to 0004, seeds the old table through the
    historical models and returns to the latest migration whatever happens.
    """

    def catalogue(self, query, params=None):
        with connection.cursor() as cursor:
            cursor.execute(query, params)
            return {row[0] for row in cursor.fetchall()}

    def tables(self):
        return set(connection.introspection.table_names())

    def counts(self):
        return {table: self.catalogue(f'SELECT count(*) FROM {table}') for table in KEPT_TABLES}

    def migrate(self, target):
        MigrationExecutor(connection).migrate([('bookings', target)])

    def latest(self):
        # Every app's latest: stepping bookings back also unapplies the apps
        # built on it (reports, communications), which must come back too.
        MigrationExecutor(connection).migrate(MigrationExecutor(connection).loader.graph.leaf_nodes())

    def seed(self):
        """A Demo and a Diagnostic booking in the combined table, one of them cancelled, as 0004 left them."""
        apps = MigrationExecutor(connection).loader.project_state(('bookings', BEFORE_SPLIT)).apps
        Lead, Slot, Booking = (apps.get_model('bookings', name) for name in ('Lead', 'BookingSlot', 'Booking'))
        lead = Lead.objects.create(
            parent_name='Asha Nair', phone_dial_code='+971', phone_number='501234567', phone_key='+971501234567',
            student_name='Riya', student_name_key='riya', school_name='DPS', grade='Class 8', syllabus='CBSE',
        )
        for booking_type, at, status in ((DEMO, EVENING, 'BOOKED'), (DIAGNOSTIC, MORNING, 'CANCELLED')):
            starts_at = ist(at)
            slot = Slot.objects.create(
                booking_type=booking_type, local_date=DAY, local_time=at, starts_at=starts_at,
                ends_at=starts_at + timedelta(hours=1),
            )
            Booking.objects.create(
                booking_type=booking_type, lead=lead, slot=slot, seat=1, referral_status='NO_REF', status=status,
                cancelled_at=timezone.now() if status == 'CANCELLED' else None,
            )

    def test_forward_drops_the_old_table_and_back_restores_it_empty(self):
        try:
            self.migrate(BEFORE_SPLIT)
            self.seed()
            kept = self.counts()
            before = check()
            self.assertIn('Rows in bookings that the split will discard: 2', before)
            self.assertIn('Nothing else in the database depends on bookings.', before)
            self.assertIn('All checks passed.', before)
            # Counts and dates only: never a child's or parent's details.
            for private in ('Riya', 'Asha', '501234567'):
                self.assertNotIn(private, before)
            with self.assertRaises(CommandError):
                check('--after')

            self.migrate(SPLIT)
            self.assertNotIn('bookings', self.tables())
            self.assertLessEqual(NEW_TABLES, self.tables())
            # Leads, slots, slot times and booking links are untouched.
            self.assertEqual(self.counts(), kept)
            # --after wants every bookings migration: the models declare what the later ones make too.
            with self.assertRaises(CommandError) as early:
                check('--after')
            self.assertIn('bookings migrations not applied yet: 0006_booking_reason_codes', early.exception.output)
            self.latest()
            after = check('--after')
            for trigger in ('booking_events_no_mutate', 'diagnostic_bookings_slot_type', 'demo_bookings_slot_type',
                            'booking_slots_type_fixed'):
                self.assertIn(f'{trigger} trigger present', after)
            with self.assertRaises(CommandError) as refused:
                check()
            self.assertIn('already applied', str(refused.exception.output))

            self.migrate(BEFORE_SPLIT)
            self.assertFalse(NEW_TABLES & self.tables())
            self.assertEqual(self.catalogue('SELECT count(*) FROM bookings'), {0})
            self.assertEqual(self.catalogue(
                "SELECT count(*) FROM pg_proc WHERE proname IN "
                "('booking_events_immutable', 'booking_slot_of_its_type', 'booking_slot_type_fixed', 'booking_reschedule_chain')"
            ), {0})
            self.assertEqual(self.catalogue(
                "SELECT count(*) FROM pg_trigger WHERE tgrelid = 'booking_slots'::regclass AND NOT tgisinternal"
            ), {0})
            self.assertEqual(self.counts(), kept)

            self.latest()
            check('--after')
        finally:
            self.latest()

    def test_the_check_refuses_a_drop_something_depends_on(self):
        try:
            self.migrate(BEFORE_SPLIT)
            with connection.cursor() as cursor:
                cursor.execute('CREATE VIEW booking_probe AS SELECT id FROM bookings')
            try:
                with self.assertRaises(CommandError) as refused:
                    check()
                self.assertIn('View booking_probe depends on bookings', refused.exception.output)
            finally:
                with connection.cursor() as cursor:
                    cursor.execute('DROP VIEW booking_probe')
            check()
        finally:
            self.latest()


class ReasonCodeMigrationTests(TransactionTestCase):
    """
    0006 gives a cancelled booking from before the reason codes OTHER, keeping
    its old free text where it was, and reverses to 0005 and applies again.
    """

    def columns(self, table):
        with connection.cursor() as cursor:
            cursor.execute('SELECT column_name FROM information_schema.columns WHERE table_name = %s', [table])
            return {row[0] for row in cursor.fetchall()}

    def test_existing_rows_are_coded_and_the_migration_reverses(self):
        executor = MigrationExecutor(connection)
        try:
            executor.migrate([('bookings', SPLIT)])
            apps = MigrationExecutor(connection).loader.project_state(('bookings', SPLIT)).apps
            Lead, Slot, Demo = (apps.get_model('bookings', name) for name in ('Lead', 'BookingSlot', 'DemoBooking'))
            lead = Lead.objects.create(
                parent_name='Asha Nair', phone_dial_code='+971', phone_number='501234567', phone_key='+971501234567',
                student_name='Riya', student_name_key='riya', school_name='DPS', grade='Class 8', syllabus='CBSE',
            )
            starts_at = ist(EVENING)
            slot_row = Slot.objects.create(booking_type=DEMO, local_date=DAY, local_time=EVENING, starts_at=starts_at,
                                           ends_at=starts_at + timedelta(hours=1))
            cancelled = Demo.objects.create(lead=lead, slot=slot_row, seat=1, referral_status='NO_REF', status='CANCELLED',
                                            cancelled_at=timezone.now(), cancel_reason='Parent called to cancel')
            booked = Demo.objects.create(lead=lead, slot=Slot.objects.create(
                booking_type=DEMO, local_date=DAY, local_time=MORNING, starts_at=ist(MORNING),
                ends_at=ist(MORNING) + timedelta(hours=1)), seat=1, referral_status='NO_REF')

            MigrationExecutor(connection).migrate(MigrationExecutor(connection).loader.graph.leaf_nodes())
            self.assertLessEqual({'cancel_reason_code', 'reschedule_reason_code', 'cancel_reason'}, self.columns('demo_bookings'))
            self.assertNotIn('reschedule_reason', self.columns('demo_bookings'))
            self.assertEqual(
                (DemoBooking.objects.get(pk=cancelled.pk).cancel_reason_code, DemoBooking.objects.get(pk=cancelled.pk).cancel_reason),
                ('OTHER', 'Parent called to cancel'),
            )
            self.assertEqual(DemoBooking.objects.get(pk=booked.pk).cancel_reason_code, '')

            MigrationExecutor(connection).migrate([('bookings', SPLIT)])
            self.assertIn('reschedule_reason', self.columns('demo_bookings'))
            self.assertFalse({'cancel_reason_code', 'reschedule_reason_code'} & self.columns('demo_bookings'))
            with connection.cursor() as cursor:
                cursor.execute("SELECT count(*) FROM pg_proc WHERE proname = 'booking_reschedule_chain'")
                self.assertEqual(cursor.fetchone()[0], 0)
        finally:
            MigrationExecutor(connection).migrate(MigrationExecutor(connection).loader.graph.leaf_nodes())


class SplitCheckAfterTests(TestCase):
    """--after against the migrated test database; DDL here rolls back with the test."""

    def test_the_migrated_schema_passes(self):
        out = check('--after')
        for table in NEW_TABLES:
            self.assertIn(f'{table}:', out)
        self.assertIn('All checks passed.', out)

    def test_a_missing_trigger_or_constraint_fails(self):
        with connection.cursor() as cursor:
            cursor.execute('DROP TRIGGER booking_events_no_mutate ON booking_events')
            cursor.execute('DROP TRIGGER booking_slots_type_fixed ON booking_slots')
            # A conditional unique constraint is a partial unique index in PostgreSQL.
            cursor.execute('DROP INDEX demobooking_one_holding_per_seat')
        with self.assertRaises(CommandError) as refused:
            check('--after')
        self.assertIn('the booking_events_no_mutate trigger is missing', refused.exception.output)
        self.assertIn('booking_slots: the booking_slots_type_fixed trigger is missing', refused.exception.output)
        self.assertIn('demo_bookings: demobooking_one_holding_per_seat is missing', refused.exception.output)


def slot(booking_type=DEMO, day=DAY):
    """The ``booking_type`` slot at 19:30 on ``day``, created if new."""
    starts_at, ends_at = slot_instants(day, EVENING)
    return BookingSlot.objects.get_or_create(
        booking_type=booking_type, local_date=day, local_time=EVENING,
        defaults={'starts_at': starts_at, 'ends_at': ends_at},
    )[0]


def lead(student, phone):
    return Lead.objects.create(
        parent_name='Asha', phone_dial_code='+971', phone_number=phone, phone_key=f'+971{phone}',
        student_name=student, student_name_key=name_key(student), school_name='DPS', grade='Class 8',
        syllabus='CBSE',
    )


class BookingTableConstraintTests(TestCase):
    """What the database itself refuses in each booking table, whatever the service checks."""

    def setUp(self):
        self.riya, self.ali = self.lead('Riya', '501234567'), self.lead('Ali', '509876543')
        self.tutor = tutor('tutor_one')
        self.bde = account('bde_one')

    def lead(self, student, phone):
        return lead(student, phone)

    def slot(self, booking_type=DEMO, day=DAY):
        return slot(booking_type, day)

    def booking(self, model=DemoBooking, lead=None, seat=1, **fields):
        values = dict(lead=lead or self.riya, slot=self.slot(model.BOOKING_TYPE), seat=seat,
                      referral_status=ReferralStatus.NO_REF)
        values.update(fields)
        return model.objects.create(**values)

    def completed(self):
        now = timezone.now()
        return dict(status=BookingStatus.COMPLETED, completed_at=now, assigned_tutor=self.tutor, tutor_assigned_at=now)

    def assertRefused(self, create, message=None):
        refused = self.assertRaisesMessage(IntegrityError, message) if message else self.assertRaises(IntegrityError)
        with refused, transaction.atomic():
            create()

    def test_each_type_is_its_own_table(self):
        demo = self.booking(DemoBooking)
        diagnostic = self.booking(DiagnosticBooking)
        # The same lead and seat in each type's slot: the tables never meet.
        self.assertEqual((demo.seat, diagnostic.seat, demo.lead_id), (1, 1, diagnostic.lead_id))
        self.assertEqual((demo.booking_type, diagnostic.booking_type), (DEMO, DIAGNOSTIC))
        self.assertEqual(list(self.riya.demo_bookings.all()), [demo])
        self.assertEqual(list(self.riya.diagnostic_bookings.all()), [diagnostic])

    def test_booked_and_completed_hold_the_seat_and_the_leads_place(self):
        for model in (DemoBooking, DiagnosticBooking):
            with self.subTest(model=model.__name__):
                held = self.booking(model, **self.completed())
                self.assertRefused(lambda: self.booking(model, lead=self.ali, seat=1))
                self.assertRefused(lambda: self.booking(model, seat=2))
                self.assertRefused(lambda: self.booking(model, lead=self.ali, seat=4))
                self.assertRefused(lambda: self.booking(model, lead=self.ali, seat=0))
                other = self.booking(model, lead=self.ali, seat=2)
                # Moved or cancelled, a booking frees both.
                model.objects.filter(pk=held.pk).update(
                    status=BookingStatus.RESCHEDULED, rescheduled_at=timezone.now(), completed_at=None,
                    reschedule_reason_code='OTHER',
                )
                model.objects.filter(pk=other.pk).update(
                    status=BookingStatus.CANCELLED, cancelled_at=timezone.now(), cancel_reason_code='OTHER',
                )
                self.booking(model, seat=1)
                self.booking(model, lead=self.ali, seat=2)

    def test_one_state_at_a_time_with_its_fields(self):
        now = timezone.now()
        refused = [
            dict(status='DONE'),
            dict(cancelled_at=now),
            dict(status=BookingStatus.CANCELLED),
            dict(status=BookingStatus.RESCHEDULED),
            dict(status=BookingStatus.COMPLETED, completed_at=now),
            dict(status=BookingStatus.COMPLETED, assigned_tutor=self.tutor, tutor_assigned_at=now),
            dict(self.completed(), cancelled_at=now),
            dict(status=BookingStatus.CANCELLED, cancelled_at=now, rescheduled_at=now),
            dict(status=BookingStatus.RESCHEDULED, rescheduled_at=now, completed_at=now),
            dict(assigned_tutor=self.tutor),
            # A reason code exactly when the status records one, and only a known one.
            dict(status=BookingStatus.CANCELLED, cancelled_at=now),
            dict(status=BookingStatus.CANCELLED, cancelled_at=now, cancel_reason_code='Parent asked'),
            dict(status=BookingStatus.RESCHEDULED, rescheduled_at=now),
            dict(status=BookingStatus.RESCHEDULED, rescheduled_at=now, reschedule_reason_code='NO_SHOW'),
            dict(cancel_reason_code='OTHER'),
            dict(reschedule_reason_code='OTHER'),
        ]
        for fields in refused:
            with self.subTest(fields=sorted(fields)):
                self.assertRefused(lambda: self.booking(**fields))
        for seat, fields in enumerate((
            self.completed(),
            dict(status=BookingStatus.CANCELLED, cancelled_at=now, cancel_reason_code='NO_SHOW'),
            dict(status=BookingStatus.RESCHEDULED, rescheduled_at=now, reschedule_reason_code='PARENT_REQUEST'),
        ), start=1):
            self.booking(lead=self.lead(f'Child {seat}', f'50000000{seat}'), seat=seat, **fields)

    def test_moves_form_one_chain(self):
        moved = dict(status=BookingStatus.RESCHEDULED, rescheduled_at=timezone.now(), reschedule_reason_code='OTHER')
        first = self.booking(**moved)
        later = slot(DEMO, day=DAY + timedelta(days=1))
        second = DemoBooking.objects.create(lead=self.riya, slot=later, seat=1, referral_status=ReferralStatus.NO_REF,
                                            rescheduled_from=first)
        # No booking replaces itself, and none is replaced twice.
        own = uuid.uuid4()
        self.assertRefused(lambda: self.booking(id=own, lead=self.ali, seat=2, rescheduled_from_id=own))
        elsewhere = slot(DEMO, day=DAY + timedelta(days=2))
        self.assertRefused(lambda: DemoBooking.objects.create(
            lead=self.riya, slot=elsewhere, seat=1, referral_status=ReferralStatus.NO_REF, rescheduled_from=first,
        ))
        # (Read back: building the refused one left it in first's in-memory reverse link.)
        self.assertEqual(DemoBooking.objects.get(pk=first.pk).rescheduled_to, second)

    def test_a_replacement_follows_a_moved_booking_of_its_own_lead_only(self):
        later = slot(DEMO, day=DAY + timedelta(days=1))

        def replace(previous, lead=None):
            return DemoBooking.objects.create(lead=lead or self.riya, slot=later, seat=1,
                                              referral_status=ReferralStatus.NO_REF, rescheduled_from=previous)

        booked = self.booking()
        self.assertRefused(lambda: replace(booked), 'replaces only a rescheduled booking of the same lead')
        DemoBooking.objects.filter(pk=booked.pk).update(
            status=BookingStatus.RESCHEDULED, rescheduled_at=timezone.now(), reschedule_reason_code='OTHER',
        )
        self.assertRefused(lambda: replace(booked, lead=self.ali), 'replaces only a rescheduled booking of the same lead')
        replacement = replace(booked)
        # A move is final: the moved booking stays rescheduled, so the chain it heads stays whole.
        self.assertRefused(lambda: DemoBooking.objects.filter(pk=booked.pk).update(
            status=BookingStatus.BOOKED, rescheduled_at=None, reschedule_reason_code='',
        ), 'a rescheduled booking stays rescheduled')
        self.assertRefused(lambda: DemoBooking.objects.filter(pk=booked.pk).update(
            status=BookingStatus.CANCELLED, rescheduled_at=None, reschedule_reason_code='', cancelled_at=timezone.now(),
            cancel_reason_code='OTHER',
        ), 'a rescheduled booking stays rescheduled')
        self.assertEqual(replacement.rescheduled_from, booked)

    def test_channels(self):
        handoff = dict(channel=BookingChannel.BDE_HANDOFF, referral_status=None, created_by=self.bde)
        # A Diagnostic booking is made on the public page only.
        self.assertRefused(lambda: self.booking(DiagnosticBooking, **handoff))
        self.assertRefused(lambda: self.booking(channel='WALK_IN'))
        # A handoff names who made it and carries no referral; a page booking the reverse.
        self.assertRefused(lambda: self.booking(**dict(handoff, created_by=None)))
        self.assertRefused(lambda: self.booking(**dict(handoff, referral_status=ReferralStatus.NO_REF)))
        self.assertRefused(lambda: self.booking(**dict(handoff, attributed_bde=self.bde)))
        self.assertRefused(lambda: self.booking(created_by=self.bde))
        self.assertRefused(lambda: self.booking(referral_status=None))
        made = self.booking(**handoff)
        self.assertEqual((made.channel, made.created_by), (BookingChannel.BDE_HANDOFF, self.bde))
        self.assertEqual(self.booking(DiagnosticBooking).channel, BookingChannel.PUBLIC_PAGE)


class SlotTypeTests(TestCase):
    """A booking holds a slot of its own type only, whatever writes it (bookings.0005's triggers)."""

    def setUp(self):
        self.riya, self.ali = lead('Riya', '501234567'), lead('Ali', '509876543')
        self.demo_slot, self.diagnostic_slot = slot(DEMO), slot(DIAGNOSTIC)

    def create(self, model, slot, lead=None, seat=1):
        return model.objects.create(lead=lead or self.riya, slot=slot, seat=seat, referral_status=ReferralStatus.NO_REF)

    def assertRefused(self, change, message):
        with self.assertRaisesMessage(IntegrityError, message), transaction.atomic():
            change()

    def test_each_type_on_its_own_slots(self):
        demo = self.create(DemoBooking, self.demo_slot)
        diagnostic = self.create(DiagnosticBooking, self.diagnostic_slot)
        self.assertEqual((demo.slot, diagnostic.slot), (self.demo_slot, self.diagnostic_slot))
        # Moved to another slot of its own type, or changed in any other column, it is let through.
        later = slot(DEMO, day=DAY + timedelta(days=1))
        DemoBooking.objects.filter(pk=demo.pk).update(slot=later)
        DemoBooking.objects.filter(pk=demo.pk).update(
            status=BookingStatus.CANCELLED, cancelled_at=timezone.now(), cancel_reason_code='OTHER',
        )
        demo.refresh_from_db()
        demo.save()  # a full save writes slot_id again, unchanged
        self.assertEqual(demo.slot, later)

    def test_never_on_the_other_types_slot(self):
        self.assertRefused(lambda: self.create(DemoBooking, self.diagnostic_slot), 'demo_bookings takes DEMO slots only')
        self.assertRefused(lambda: self.create(DiagnosticBooking, self.demo_slot),
                           'diagnostic_bookings takes DIAGNOSTIC slots only')
        demo = self.create(DemoBooking, self.demo_slot)
        diagnostic = self.create(DiagnosticBooking, self.diagnostic_slot)
        self.assertRefused(lambda: DemoBooking.objects.filter(pk=demo.pk).update(slot=self.diagnostic_slot),
                           'demo_bookings takes DEMO slots only')
        self.assertRefused(lambda: DiagnosticBooking.objects.filter(pk=diagnostic.pk).update(slot=self.demo_slot),
                           'diagnostic_bookings takes DIAGNOSTIC slots only')

        def raw_insert():
            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO demo_bookings (id, lead_id, slot_id, seat, status, channel, referral_status, details, "
                    "created_at, updated_at, cancel_reason, cancel_reason_code, reschedule_reason_code) "
                    "VALUES (%s, %s, %s, 2, 'BOOKED', 'PUBLIC_PAGE', 'NO_REF', '{}', now(), now(), '', '', '')",
                    [str(uuid.uuid4()), str(self.ali.pk), str(self.diagnostic_slot.pk)],
                )

        self.assertRefused(raw_insert, 'demo_bookings takes DEMO slots only')
        self.assertEqual((DemoBooking.objects.get().slot, DiagnosticBooking.objects.get().slot),
                         (self.demo_slot, self.diagnostic_slot))

    def test_a_booked_slot_keeps_its_type(self):
        demo = self.create(DemoBooking, self.demo_slot)
        diagnostic = self.create(DiagnosticBooking, self.diagnostic_slot)
        for booking, other in ((demo, DIAGNOSTIC), (diagnostic, DEMO)):
            with self.subTest(model=type(booking).__name__):

                def change(slot_id=booking.slot_id, to=other):
                    BookingSlot.objects.filter(pk=slot_id).update(booking_type=to)

                self.assertRefused(change, 'a booking slot that holds bookings keeps its type')
                # A cancelled booking still holds it: its history stays of its type.
                type(booking).objects.filter(pk=booking.pk).update(
                    status=BookingStatus.CANCELLED, cancelled_at=timezone.now(), cancel_reason_code='OTHER',
                )
                self.assertRefused(change, 'a booking slot that holds bookings keeps its type')
        # Its other columns change freely, and the same type written again is no change.
        BookingSlot.objects.filter(pk=self.demo_slot.pk).update(closed_at=timezone.now(), booking_type=DEMO)
        # A slot nobody has booked may still change type.
        empty = slot(DEMO, day=DAY + timedelta(days=1))
        BookingSlot.objects.filter(pk=empty.pk).update(booking_type=DIAGNOSTIC)
        self.create(DiagnosticBooking, BookingSlot.objects.get(pk=empty.pk), lead=self.ali)


@skipUnless(connection.vendor == 'postgresql', 'the slot type triggers need PostgreSQL row locking')
class SlotTypeRaceTests(TransactionTestCase):
    """
    A booking and a change of its slot's type, in two transactions at once:
    the second waits for the first, then sees it and is refused.
    """

    def setUp(self):
        self.riya = lead('Riya', '501234567')
        self.slot = slot(DEMO)

    def book(self):
        return DemoBooking.objects.create(lead=self.riya, slot=self.slot, seat=1, referral_status=ReferralStatus.NO_REF)

    def retype(self):
        return BookingSlot.objects.filter(pk=self.slot.pk).update(booking_type=DIAGNOSTIC)

    def holding(self, change):
        """Run ``change`` in another connection's transaction, held open until ``release`` is set; returns (release, thread)."""
        started, release = threading.Event(), threading.Event()

        def run():
            try:
                with transaction.atomic():
                    change()
                    started.set()
                    release.wait(timeout=10)
            finally:
                connection.close()

        thread = threading.Thread(target=run)
        thread.start()
        self.assertTrue(started.wait(timeout=10))
        return release, thread

    def blocked(self, change):
        with self.assertRaises(OperationalError), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SET LOCAL lock_timeout = '300ms'")
            change()

    def test_a_retype_waits_for_an_open_booking_then_is_refused(self):
        release, thread = self.holding(self.book)
        try:
            self.blocked(self.retype)
        finally:
            release.set()
            thread.join(timeout=10)
        with self.assertRaisesMessage(IntegrityError, 'keeps its type'), transaction.atomic():
            self.retype()

    def test_a_booking_waits_for_an_open_retype_then_is_refused(self):
        release, thread = self.holding(self.retype)
        try:
            self.blocked(self.book)
        finally:
            release.set()
            thread.join(timeout=10)
        with self.assertRaisesMessage(IntegrityError, 'demo_bookings takes DEMO slots only'), transaction.atomic():
            self.book()
