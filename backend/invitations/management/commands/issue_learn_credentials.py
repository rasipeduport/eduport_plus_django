"""Explicit, idempotent legacy student transition; never prints credentials."""
from django.core.management.base import BaseCommand, CommandError
from invitations.credentials import issue_existing_student, credential_cipher
from students.models import Student


class Command(BaseCommand):
    help = 'Prepare Learn username/password invitations for existing students. Dry run unless --execute.'

    def add_arguments(self, parser):
        choice = parser.add_mutually_exclusive_group(required=True)
        choice.add_argument('--student-code')
        choice.add_argument('--all', action='store_true')
        parser.add_argument('--execute', action='store_true')

    def handle(self, *args, **options):
        students = Student.objects.filter(learn_invitation__isnull=True).order_by('student_code')
        if options['student_code']:
            if not Student.objects.filter(student_code=options['student_code']).exists():
                raise CommandError('Student not found.')
            students = students.filter(student_code=options['student_code'])
        if options['execute']:
            credential_cipher()
        count = 0
        for pk in students.values_list('pk', flat=True).iterator():
            if options['execute']:
                issue_existing_student(pk, actor=None)
            count += 1
        self.stdout.write(f'{count} student(s) {"issued invitations" if options["execute"] else "would receive invitations (dry run)"}. Retrieve credentials in the authorized Invitation UI.')
