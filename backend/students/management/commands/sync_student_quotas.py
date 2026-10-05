"""
    python manage.py sync_student_quotas [--dry-run]

The manual handle on the same sync Celery beat runs on a schedule: for a first
rollout, for an operator who cannot wait for the next tick, and for checking
what a sheet change would do before it lands (``--dry-run``).
"""
from django.core.management.base import BaseCommand

from students.quota_sync import format_code_list, sync_student_quotas_from_sheet


class Command(BaseCommand):
    help = (
        "Sync every student's class quota from the enrolment sheet's "
        '"No of classes paid for" column.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help="Report what would change without writing to the database.",
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        report = sync_student_quotas_from_sheet(dry_run=dry_run)

        if report.failed:
            # Non-zero exit without a traceback: the cause is already logged,
            # and a cron wrapper only needs to know the run did not happen.
            self.stderr.write(self.style.ERROR(
                f"Quota sync failed, no quota changed: {report.error}"
            ))
            return

        verb = "would change" if dry_run else "changed"
        self.stdout.write(
            f"Rows read: {report.rows_processed} | "
            f"codes in sheet: {report.codes_in_sheet} | "
            f"{verb}: {report.students_updated} | "
            f"already correct: {report.students_unchanged} | "
            f"not in sheet (untouched): {report.students_not_in_sheet}"
        )

        for code, old, new in report.changes:
            self.stdout.write(f"  {code}: {old} -> {new}")

        for label, values in (
            ("row(s) with no student code", report.rows_without_code),
            ("sheet code(s) not enrolled", report.codes_not_in_db),
            ("code(s) with no numeric value (left unchanged)", report.codes_without_numeric_value),
            ("code(s) appearing on several rows (summed)", report.duplicate_codes),
        ):
            if not values:
                continue
            if isinstance(values, int):
                self.stdout.write(self.style.WARNING(f"  {values} {label}"))
            else:
                self.stdout.write(self.style.WARNING(
                    f"  {len(values)} {label}: {format_code_list(values)}"
                ))

        if report.non_numeric_values:
            self.stdout.write(self.style.WARNING(
                f"  {len(report.non_numeric_values)} non-numeric value(s) skipped: "
                + format_code_list([f"{code}={raw!r}" for code, raw in report.non_numeric_values])
            ))

        if dry_run:
            self.stdout.write(self.style.NOTICE("Dry run: nothing was written."))
        else:
            self.stdout.write(self.style.SUCCESS("Quota sync complete."))
