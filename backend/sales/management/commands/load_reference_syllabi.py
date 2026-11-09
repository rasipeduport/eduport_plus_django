"""
    python manage.py load_reference_syllabi --as USERNAME [--apply]

Loads the ten syllabuses of the Eduport Plus "Plan & Price" PDFs
(sales.reference_syllabi) as Draft syllabuses, written by USERNAME -- an
active account that may manage syllabuses -- through sales.services, so each
is audited like one the Admin adds in the Hub. Nothing is ever published: the
Admin reviews each draft against its PDF and publishes it from the Hub (D8).

Without --apply it only reports what it would do. A reference syllabus is
skipped when it was loaded before -- a syllabus keeps the PDF it came from as
its reference_key, whatever the Admin has since changed in its draft -- or when
a syllabus already has a revision with its title, grade, board, syllabus
version and structure, so running it again adds nothing.
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.authz import has_app_permission
from sales import services
from sales.models import Structure, Syllabus, SyllabusRevision
from sales.reference_syllabi import REFERENCE_SYLLABI
from sales.serializers import SyllabusContentSerializer


class Command(BaseCommand):
    help = 'Load the ten reference syllabuses as Draft syllabuses for the Admin to review (never published).'

    def add_arguments(self, parser):
        parser.add_argument('--as', dest='username', required=True, help='The administrator the drafts are written by.')
        parser.add_argument('--apply', action='store_true', help='Write the drafts (default: only report).')

    def handle(self, *args, username, apply, **options):
        actor = get_user_model().objects.filter(username=username.strip().lower(), is_active=True).first()
        if actor is None or not has_app_permission(actor, 'accounts.manage_sales_syllabi'):
            raise CommandError(f'{username!r} is not an active account that may manage syllabuses.')

        loaded = skipped = 0
        with transaction.atomic():
            for payload in REFERENCE_SYLLABI:
                serializer = SyllabusContentSerializer(data=payload)
                if not serializer.is_valid():
                    raise CommandError(f'{payload["title"]}: {serializer.errors}')
                content = serializer.validated_data
                source = payload['source']
                label = f'{content["title"]} ({Structure(content["structure"]).label}, {source})'
                if self._exists(source, content):
                    skipped += 1
                    self.stdout.write(f'skip   {label}: already loaded')
                    continue
                loaded += 1
                if apply:
                    syllabus = services.create_syllabus(actor, content, reference_key=source)
                    self.stdout.write(f'loaded {label} as a draft ({syllabus.pk})')
                else:
                    self.stdout.write(f'would load {label} as a draft')
        verb = 'Loaded' if apply else 'Would load'
        self.stdout.write(self.style.SUCCESS(f'{verb} {loaded} draft syllabus(es); {skipped} already there.'))
        if not apply and loaded:
            self.stdout.write('Run again with --apply to write them.')

    @staticmethod
    def _exists(source, content):
        return Syllabus.objects.filter(reference_key=source).exists() or SyllabusRevision.objects.filter(
            title=content['title'], grade=content['grade'], board=content['board'],
            syllabus_version=content['syllabus_version'], structure=content['structure'],
        ).exists()
