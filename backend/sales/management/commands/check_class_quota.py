"""Report payment-managed students whose class quota does not add up.

A payment-managed student's quota is the classes the existing rules credited
from their plan payments (enrollment's, then each Autopay installment's) plus
their active additional hours (sales.additional_hours). Read-only: nothing is
written, whatever it finds.
"""
from django.core.management.base import BaseCommand, CommandError

from sales.additional_hours import reconciliation
from students.models import Student


class Command(BaseCommand):
    help = 'Report payment-managed students whose class quota differs from credited plan classes plus additional hours.'

    def add_arguments(self, parser):
        parser.add_argument('--student', help='One student code only.')
        parser.add_argument('--strict', action='store_true', help='Exit with an error when any quota does not add up.')

    def handle(self, *args, **options):
        students = Student.objects.filter(quota_source='PAYMENTS').order_by('student_code')
        if options['student']:
            students = students.filter(student_code__iexact=options['student'].strip())
        checked, mismatched = 0, []
        for student in students:
            checked += 1
            found = reconciliation(student)
            if not found['reconciles']:
                mismatched.append(student.student_code)
                self.stdout.write(f'MISMATCH {student.student_code}: quota {found["quota"]} hrs, expected '
                                  f'{found["expected_quota"]} hrs (credited plan classes {found["credited_plan_classes"]} '
                                  f'+ additional hours {found["additional_hours"]}).')
        self.stdout.write(f'{checked} payment-managed student(s) checked, {len(mismatched)} mismatch(es).')
        if mismatched and options['strict']:
            raise CommandError(f'{len(mismatched)} quota(s) do not add up.')
