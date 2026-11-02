"""
Submitting and editing reports (reports.services, design F.1): version 1
completes the booking, edits make new versions under a version check, an
unchanged edit saves nothing, the history and the activity log keep ids and
field names only -- and all of it under concurrency.
"""
import json
import threading
from datetime import timedelta
from unittest import skipUnless

from django.db import connection, transaction
from django.test import TransactionTestCase

from activity.models import ActivityLog
from bookings.booking_service import (
    BookingCompleted,
    assign_tutor,
    cancel_booking,
    create_booking,
    find_tutor_conflict,
    reschedule_booking,
    unassign_tutor,
    upcoming_assignments,
)
from bookings.models import (
    HOLDS_SEAT,
    BookingEvent,
    BookingEventKind,
    BookingSlot,
    BookingStatus,
    CancelReason,
    DemoBooking,
    Lead,
    RescheduleReason,
)
from bookings.tests_booking import (
    DAY, DEMO, DIAGNOSTIC, EVENING, MORNING, NOW, BookingTestCase, account, book, request, schedule,
)

from .models import DemoReport, DiagnosticReport, DiagnosticReportRevision, ReportShare
from .services import (
    BookingCancelled,
    BookingNotAssigned,
    BookingRescheduled,
    NoReport,
    ReportBusy,
    ReportExists,
    ReportInvalid,
    ReportVersionConflict,
    SlotNotStarted,
    edit_report,
    submit_report,
)


def diagnostic_input(**changes):
    values = {
        'score': 18, 'max_score': 25, 'performance_level': 'GOOD',
        'strength_areas': ['Fractions', 'Place value'], 'skills_to_strengthen': ['Word problems'],
        'teacher_remarks': 'Works carefully and checks each step.', 'suggested_plan': 'Two sessions a week on word problems.',
    }
    values.update(changes)
    return values


def demo_input(**changes):
    values = {
        'assessment_review': 'Quick with mental arithmetic.', 'class_observation_review': 'Asked good questions.',
        'suggested_strategy': 'Start with the Class 8 algebra track.',
    }
    values.update(changes)
    return values


def report_input(booking, **changes):
    return (demo_input if booking.booking_type == DEMO else diagnostic_input)(**changes)


def started(booking, minutes=5):
    """A moment ``minutes`` after ``booking``'s slot started."""
    return booking.slot.starts_at + timedelta(minutes=minutes)


# What the history and the activity log must never hold: the report's text, any name, the phone.
PRIVATE = (
    'Works carefully', 'Two sessions', 'Fractions', 'Word problems', 'mental arithmetic', 'good questions',
    'algebra track', 'Riya', 'Asha', '501234567', 'Tutor Anu',
)


class ReportServiceTestCase(BookingTestCase):
    def setUp(self):
        super().setUp()
        self.tutor = account('tutor_anu', role='TUTOR')
        self.other_tutor = account('tutor_binu', role='TUTOR')
        # One child, Class 8: a Diagnostic at 10:00 and a Demo at 19:30 on 28 Oct, both taught by Anu.
        self.diagnostic = assign_tutor(book(booking_type=DIAGNOSTIC, at=MORNING)[0], self.tutor, now=NOW)[0]
        self.demo = assign_tutor(book()[0], self.tutor, now=NOW)[0]

    def submit(self, booking, tutor=None, now=None, **changes):
        return submit_report(booking, tutor or self.tutor, report_input(booking, **changes), now=now or started(booking))

    def edit(self, booking, version, tutor=None, **changes):
        return edit_report(booking, tutor or self.tutor, report_input(booking, **changes), version)

    def fresh(self, booking):
        booking.refresh_from_db()
        return booking

    def events(self, booking):
        return list(booking.events.all())

    def assertNothingWritten(self, booking):
        booking = self.fresh(booking)
        self.assertEqual(booking.status, BookingStatus.BOOKED)
        self.assertFalse(DiagnosticReport.objects.filter(booking__pk=booking.pk).exists())
        self.assertFalse(DemoReport.objects.filter(booking__pk=booking.pk).exists())
        self.assertNotIn(BookingEventKind.COMPLETED, [event.kind for event in self.events(booking)])


class SubmitTests(ReportServiceTestCase):
    def test_submitting_saves_version_1_and_completes_the_booking(self):
        for booking in (self.diagnostic, self.demo):
            with self.subTest(booking_type=booking.booking_type):
                report = self.submit(booking)
                fields = report_input(booking)
                self.assertEqual(report.version, 1)
                self.assertEqual({field: getattr(report, field) for field in report.TUTOR_FIELDS}, fields)
                snapshots = {'student_name_snapshot': 'Riya', 'grade_snapshot': '8', 'tutor_name_snapshot': 'Tutor Anu'}
                self.assertEqual({field: getattr(report, field) for field in snapshots}, snapshots)
                self.assertEqual((report.submitted_by, report.updated_by), (self.tutor, self.tutor))

                booking = self.fresh(booking)
                self.assertEqual(
                    (booking.status, booking.completed_by, booking.completed_at),
                    (BookingStatus.COMPLETED, self.tutor, report.submitted_at),
                )
                revision = report.revisions.get()
                self.assertEqual((revision.version, revision.edited_by), (1, self.tutor))
                self.assertEqual(revision.content, {**fields, **snapshots})
                self.assertEqual(revision.changed_fields, list(report.TUTOR_FIELDS))
                completed = self.events(booking)[-1]
                self.assertEqual((completed.kind, completed.actor), (BookingEventKind.COMPLETED, self.tutor))
                self.assertEqual(completed.data, {
                    'from_status': 'BOOKED', 'to_status': 'COMPLETED', 'report_id': str(report.id), 'version': 1,
                })

    def test_the_activity_log_keeps_ids_and_the_version_only(self):
        report = self.submit(self.diagnostic)
        submitted = ActivityLog.objects.get(action='report.submit')
        self.assertEqual((submitted.entity_type, submitted.entity_id), ('report', str(report.id)))
        self.assertEqual(submitted.entity_label, 'Diagnostic report · 28 Oct 2026, 10:00 IST')
        self.assertEqual(submitted.context, {
            'booking_type': DIAGNOSTIC, 'booking_id': str(self.diagnostic.id), 'lead_id': str(self.diagnostic.lead_id),
            'version': 1,
        })
        completed = ActivityLog.objects.get(action='booking.complete')
        self.assertEqual((completed.entity_type, completed.entity_id), ('booking', str(self.diagnostic.id)))
        self.assertEqual(completed.entity_label, 'Diagnostic · 28 Oct 2026, 10:00 IST')
        self.assertEqual(completed.context['report_id'], str(report.id))
        recorded = json.dumps([
            [entry.entity_label, entry.changes, entry.context] for entry in ActivityLog.objects.filter(
                action__in=('report.submit', 'booking.complete'),
            )
        ] + [event.data for event in BookingEvent.objects.all()])
        for private in PRIVATE:
            self.assertNotIn(private, recorded)

    def test_only_the_assigned_tutor_submits(self):
        with self.assertRaises(BookingNotAssigned):
            self.submit(self.demo, tutor=self.other_tutor)
        unassign_tutor(self.diagnostic, now=NOW)
        with self.assertRaises(BookingNotAssigned):
            self.submit(self.diagnostic)
        for booking in (self.demo, self.diagnostic):
            self.assertNothingWritten(booking)

    def test_from_the_slot_start_and_after_it_ends(self):
        with self.assertRaises(SlotNotStarted):
            self.submit(self.demo, now=started(self.demo, minutes=-1))
        self.assertNothingWritten(self.demo)
        # At the start itself (D2), and long after the slot has ended (a report due).
        self.assertEqual(self.submit(self.demo, now=self.demo.slot.starts_at).version, 1)
        self.assertEqual(self.submit(self.diagnostic, now=started(self.diagnostic, minutes=60 * 24 * 3)).version, 1)

    def test_only_once(self):
        self.submit(self.demo)
        with self.assertRaises(ReportExists) as refused:
            self.submit(self.demo, assessment_review='A second go.')
        self.assertEqual(refused.exception.version, 1)
        self.assertEqual((DemoReport.objects.count(), DemoReport.objects.get().revisions.count()), (1, 1))

    def test_not_on_a_cancelled_or_a_moved_booking(self):
        cancel_booking(self.demo, reason_code=CancelReason.PARENT_REQUEST, now=NOW)
        with self.assertRaises(BookingCancelled):
            self.submit(self.demo)
        moved = reschedule_booking(
            self.diagnostic, DAY + timedelta(days=1), MORNING, reason_code=RescheduleReason.OTHER, now=NOW,
        ).booking
        with self.assertRaises(BookingRescheduled):
            self.submit(self.diagnostic)
        # The report goes on the booking that replaced it, whose tutor carried over.
        self.assertEqual(self.submit(moved).booking, moved)
        self.assertFalse(DemoReport.objects.exists())

    def test_the_fields_are_checked_before_anything_is_written(self):
        cases = [
            # System fields and unknown ones are refused, never dropped.
            (diagnostic_input(status='COMPLETED'), 'status'),
            (diagnostic_input(version=3), 'version'),
            (diagnostic_input(student_name_snapshot='Someone'), 'student_name_snapshot'),
            (diagnostic_input(tutor_name_snapshot='Someone'), 'tutor_name_snapshot'),
            (diagnostic_input(grade='9'), 'grade'),
            ({key: value for key, value in diagnostic_input().items() if key != 'suggested_plan'}, 'suggested_plan'),
            (diagnostic_input(score=26), 'score'),
            (diagnostic_input(score=True), 'score'),
            (diagnostic_input(score='18'), 'score'),
            (diagnostic_input(max_score=0, score=0), 'max_score'),
            (diagnostic_input(performance_level='OUTSTANDING'), 'performance_level'),
            (diagnostic_input(teacher_remarks='  \n '), 'teacher_remarks'),
            (diagnostic_input(teacher_remarks='x' * 2001), 'teacher_remarks'),
            (diagnostic_input(suggested_plan=None), 'suggested_plan'),
            (diagnostic_input(strength_areas=[]), 'strength_areas'),
            (diagnostic_input(strength_areas=['Fractions', '   ']), 'strength_areas'),
            (diagnostic_input(strength_areas=['Fractions\nDecimals']), 'strength_areas'),
            (diagnostic_input(strength_areas=['x' * 121]), 'strength_areas'),
            (diagnostic_input(strength_areas=['Topic'] * 16), 'strength_areas'),
            (diagnostic_input(strength_areas='Fractions'), 'strength_areas'),
            (diagnostic_input(skills_to_strengthen=[3]), 'skills_to_strengthen'),
        ]
        for fields, field in cases:
            with self.subTest(field=field, value=str(fields.get(field))[:20]):
                with self.assertRaises(ReportInvalid) as refused:
                    submit_report(self.diagnostic, self.tutor, fields, now=started(self.diagnostic))
                self.assertIn(field, refused.exception.fields)
                self.assertEqual(refused.exception.code, 'VALIDATION_ERROR')
        for fields, field in ((demo_input(suggested_strategy=''), 'suggested_strategy'),
                              (demo_input(assessment_review='x' * 1201), 'assessment_review'),
                              (diagnostic_input(), 'score')):
            with self.subTest(field=field), self.assertRaises(ReportInvalid) as refused:
                submit_report(self.demo, self.tutor, fields, now=started(self.demo))
            self.assertIn(field, refused.exception.fields)
        with self.assertRaises(ReportInvalid) as refused:
            submit_report(self.demo, self.tutor, ['not', 'a', 'report'], now=started(self.demo))
        self.assertIn('non_field_errors', refused.exception.fields)
        for booking in (self.diagnostic, self.demo):
            self.assertNothingWritten(booking)

    def test_text_is_trimmed_and_the_grade_prints_without_class(self):
        Lead.objects.filter(pk=self.diagnostic.lead_id).update(grade='Class 10')
        report = self.submit(
            self.diagnostic, teacher_remarks='  Line one.\r\nLine two.  ', strength_areas=['  Fractions ', 'Ratios'],
        )
        self.assertEqual((report.teacher_remarks, report.strength_areas), ('Line one.\nLine two.', ['Fractions', 'Ratios']))
        self.assertEqual(report.grade_snapshot, '10')
        Lead.objects.filter(pk=self.demo.lead_id).update(grade='Grade 4')
        self.assertEqual(self.submit(self.demo).grade_snapshot, 'Grade 4')


class EditTests(ReportServiceTestCase):
    def setUp(self):
        super().setUp()
        self.report = self.submit(self.diagnostic)

    def test_an_edit_saves_the_next_version_and_keeps_the_first(self):
        report, changed = self.edit(self.diagnostic, 1, teacher_remarks='Much more confident now.', score=20)
        self.assertTrue(changed)
        self.assertEqual((report.version, report.teacher_remarks, report.score), (2, 'Much more confident now.', 20))
        first, second = report.revisions.all()
        self.assertEqual((first.version, first.content['teacher_remarks']), (1, 'Works carefully and checks each step.'))
        self.assertEqual((second.version, second.changed_fields), (2, ['score', 'teacher_remarks']))
        edited = self.events(self.diagnostic)[-1]
        self.assertEqual((edited.kind, edited.actor), (BookingEventKind.REPORT_EDITED, self.tutor))
        self.assertEqual(edited.data, {
            'report_id': str(report.id), 'version': 2, 'changed_fields': ['score', 'teacher_remarks'],
        })
        entry = ActivityLog.objects.get(action='report.edit')
        self.assertEqual((entry.entity_id, entry.context['version'], entry.context['changed_fields']),
                         (str(report.id), 2, ['score', 'teacher_remarks']))
        self.assertNotIn('confident', json.dumps([entry.entity_label, entry.changes, entry.context, edited.data]))
        self.assertEqual(self.fresh(self.diagnostic).status, BookingStatus.COMPLETED)

    def test_an_unchanged_edit_saves_nothing(self):
        report, changed = self.edit(
            self.diagnostic, 1, teacher_remarks='  Works carefully and checks each step.\r\n', strength_areas=[' Fractions', 'Place value '],
        )
        self.assertFalse(changed)
        self.assertEqual((report.version, self.report.revisions.count()), (1, 1))
        self.assertNotIn(BookingEventKind.REPORT_EDITED, [event.kind for event in self.events(self.diagnostic)])
        self.assertFalse(ActivityLog.objects.filter(action='report.edit').exists())

    def test_a_stale_version_is_refused(self):
        self.edit(self.diagnostic, 1, score=20)
        with self.assertRaises(ReportVersionConflict) as refused:
            self.edit(self.diagnostic, 1, score=21)
        self.assertEqual(refused.exception.version, 2)
        self.assertEqual(DiagnosticReport.objects.get().score, 20)
        for version in (0, '2', True, None):
            with self.subTest(version=version), self.assertRaises(ReportInvalid) as refused:
                self.edit(self.diagnostic, version, score=21)
            self.assertIn('version', refused.exception.fields)
        self.assertEqual(DiagnosticReportRevision.objects.count(), 2)

    def test_an_edit_refreshes_the_snapshots(self):
        Lead.objects.filter(pk=self.diagnostic.lead_id).update(student_name='Riya S')
        self.tutor.full_name = 'Anu Thomas'
        self.tutor.save(update_fields=['full_name'])
        # Snapshots alone are no edit: nothing is saved for them (D7 refreshes them on a saved edit).
        report, changed = self.edit(self.diagnostic, 1)
        self.assertEqual((changed, report.student_name_snapshot), (False, 'Riya'))
        report, changed = self.edit(self.diagnostic, 1, suggested_plan='Weekly practice.')
        self.assertEqual((report.student_name_snapshot, report.tutor_name_snapshot), ('Riya S', 'Anu Thomas'))
        self.assertEqual(
            report.revisions.get(version=2).changed_fields,
            ['suggested_plan', 'student_name_snapshot', 'tutor_name_snapshot'],
        )

    def test_only_the_assigned_tutor_edits_and_only_a_report_that_exists(self):
        with self.assertRaises(BookingNotAssigned):
            self.edit(self.diagnostic, 1, tutor=self.other_tutor, score=20)
        with self.assertRaises(NoReport):
            self.edit(self.demo, 1)
        self.assertEqual(DiagnosticReport.objects.get().version, 1)

    def test_editing_stays_open_after_the_report_is_shared(self):
        ReportShare.objects.create(diagnostic_report=self.report, report_version=1, shared_by=account('bde_one'))
        report, changed = self.edit(self.diagnostic, 1, score=22)
        self.assertEqual((changed, report.version, report.shares.get().report_version), (True, 2, 1))


class CompletedBookingTests(ReportServiceTestCase):
    """What completing a booking means for the rest of the booking rules, now that it happens."""

    def setUp(self):
        super().setUp()
        self.submit(self.demo)
        self.demo = self.fresh(self.demo)

    def test_it_can_no_longer_be_cancelled_moved_or_given_another_tutor(self):
        changes = (
            lambda: cancel_booking(self.demo, reason_code=CancelReason.OTHER, now=NOW),
            lambda: reschedule_booking(self.demo, DAY + timedelta(days=1), MORNING, reason_code=RescheduleReason.OTHER, now=NOW),
            lambda: assign_tutor(self.demo, self.other_tutor, now=NOW),
            lambda: unassign_tutor(self.demo, now=NOW),
        )
        for change in changes:
            with self.subTest(change=change), self.assertRaises(BookingCompleted):
                change()
        self.assertEqual(self.fresh(self.demo).status, BookingStatus.COMPLETED)

    def test_it_keeps_its_seat_and_its_tutors_time(self):
        self.assertEqual(DemoBooking.objects.filter(slot=self.demo.slot, status__in=HOLDS_SEAT).count(), 1)
        self.assertEqual(book(student='Ali')[0].seat, 2)
        conflict = find_tutor_conflict(self.tutor, self.demo.slot.starts_at, self.demo.slot.ends_at)
        self.assertEqual(conflict.id, self.demo.id)
        # It is no longer upcoming work: the tutor's account could be deactivated.
        self.assertNotIn(self.demo, upcoming_assignments(self.tutor, now=NOW))

    def test_the_child_may_book_that_type_again(self):
        # A completed booking holds no place in Q26's one-live-booking rule.
        again, created = create_booking(request(day=DAY + timedelta(days=2)), now=NOW)
        self.assertTrue(created)
        self.assertEqual(again.lead_id, self.demo.lead_id)


# ------------------------------------------------------------- concurrency

@skipUnless(connection.vendor == 'postgresql', 'the booking locks need PostgreSQL row locking')
class ConcurrentReportTests(TransactionTestCase):
    """Real threads, each with its own database connection, starting together."""

    def setUp(self):
        schedule()
        self.tutor = account('tutor_anu', role='TUTOR')
        self.admin = account('admin_one', role='ADMIN')

    def booked(self, student='Riya', booking_type=DEMO, day=DAY):
        # Diagnostics in the morning, Demos in the evening: one tutor teaches them all.
        at = MORNING if booking_type == DIAGNOSTIC else EVENING
        made, _created = create_booking(request(student=student, booking_type=booking_type, day=day, at=at), now=NOW)
        return assign_tutor(made, self.tutor, now=NOW)[0]

    def race(self, calls):
        barrier = threading.Barrier(len(calls))
        outcomes = [None] * len(calls)

        def run(index, call):
            try:
                barrier.wait(timeout=10)
                outcomes[index] = call()
            except Exception as exc:  # the outcome, reported in the assertion
                outcomes[index] = type(exc).__name__
            finally:
                connection.close()

        threads = [threading.Thread(target=run, args=(i, call)) for i, call in enumerate(calls)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        return outcomes

    def submitter(self, booking, **changes):
        return lambda: submit_report(booking, self.tutor, report_input(booking, **changes), now=started(booking)) and 'submitted'

    def test_two_submits_at_once_make_one_report(self):
        for booking_type in (DEMO, DIAGNOSTIC):
            with self.subTest(booking_type=booking_type):
                booking = self.booked(student=f'Child {booking_type}', booking_type=booking_type)
                outcomes = self.race([self.submitter(booking), self.submitter(booking)])
                self.assertEqual(sorted(outcomes), ['ReportExists', 'submitted'], outcomes)
                events = [event.kind for event in booking.events.all()]
                self.assertEqual(events.count(BookingEventKind.COMPLETED), 1)
        self.assertEqual((DemoReport.objects.count(), DiagnosticReport.objects.count()), (1, 1))

    def test_a_submit_racing_a_cancel(self):
        for round_ in range(3):
            # A day each: a round the submit wins leaves a completed booking, which keeps its tutor's time.
            booking = self.booked(student=f'Child {round_}', day=DAY + timedelta(days=round_))

            def cancel(booking=booking):
                cancel_booking(booking, reason_code=CancelReason.NO_SHOW, actor=self.admin, now=started(booking))
                return 'cancelled'

            outcomes = self.race([self.submitter(booking), cancel])
            self.assertIn(sorted(outcomes), (['BookingCompleted', 'submitted'], ['BookingCancelled', 'cancelled']), outcomes)
            booking.refresh_from_db()
            has_report = DemoReport.objects.filter(booking=booking).exists()
            # Never both, never a mixed state: completed with its report, or cancelled without one.
            self.assertEqual((booking.status, has_report), (BookingStatus.COMPLETED, True) if has_report
                             else (BookingStatus.CANCELLED, False))

    def test_two_edits_of_one_version(self):
        booking = self.booked()
        submit_report(booking, self.tutor, demo_input(), now=started(booking))

        def editor(text):
            return lambda: edit_report(booking, self.tutor, demo_input(suggested_strategy=text), 1)[1] and 'edited'

        outcomes = self.race([editor('First idea.'), editor('Second idea.')])
        self.assertEqual(sorted(outcomes), ['ReportVersionConflict', 'edited'], outcomes)
        report = DemoReport.objects.get()
        self.assertEqual((report.version, report.revisions.count()), (2, 2))

    def test_a_booking_locked_too_long_answers_busy(self):
        booking = self.booked()
        locked, release = threading.Event(), threading.Event()

        def hold_the_slot():
            try:
                with transaction.atomic():
                    BookingSlot.objects.select_for_update().get(pk=booking.slot_id)
                    locked.set()
                    release.wait(timeout=15)
            finally:
                connection.close()

        holder = threading.Thread(target=hold_the_slot)
        holder.start()
        try:
            self.assertTrue(locked.wait(timeout=10))
            with self.assertRaises(ReportBusy):
                submit_report(booking, self.tutor, demo_input(), now=started(booking))
        finally:
            release.set()
            holder.join(timeout=15)
        booking.refresh_from_db()
        self.assertEqual((booking.status, DemoReport.objects.count()), (BookingStatus.BOOKED, 0))
