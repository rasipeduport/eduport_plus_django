"""
The reference syllabuses (D8): transcribed from the ten "Plan & Price" PDFs,
each totalling what its PDF's table states, and loaded only as drafts.
"""
from io import StringIO

from django.core.management import CommandError, call_command
from django.test import SimpleTestCase, TestCase

from activity.models import ActivityLog

from . import services
from .models import Syllabus, SyllabusRevision
from .pricing import chapter_totals, plain
from .reference_syllabi import REFERENCE_SYLLABI, REFERENCE_TOTALS
from .serializers import SyllabusContentSerializer
from .tests_api import REFERENCE_PRICING
from .tests_lifecycle import account


class TranscriptionTests(SimpleTestCase):
    def test_each_reference_totals_what_its_pdf_states(self):
        self.assertEqual(len(REFERENCE_SYLLABI), 10)
        for payload, expected in zip(REFERENCE_SYLLABI, REFERENCE_TOTALS):
            with self.subTest(title=payload['title'], structure=payload['structure']):
                serializer = SyllabusContentSerializer(data=payload)
                self.assertTrue(serializer.is_valid(), serializer.errors)
                totals = chapter_totals(serializer.validated_data['chapters'])
                self.assertEqual({column: plain(total) for column, total in totals.items()}, expected)


class LoadCommandTests(TestCase):
    def setUp(self):
        self.admin = account('reference_admin')

    def load(self, *args):
        out = StringIO()
        call_command('load_reference_syllabi', '--as', 'reference_admin', *args, stdout=out)
        return out.getvalue()

    def test_it_reports_first_then_loads_drafts_once(self):
        self.assertIn('Would load 10 draft syllabus(es)', self.load())
        self.assertFalse(Syllabus.objects.exists())

        self.assertIn('Loaded 10 draft syllabus(es); 0 already there.', self.load('--apply'))
        self.assertEqual(Syllabus.objects.count(), 10)
        # Drafts only: nothing is published until the Admin reviews it.
        self.assertFalse(SyllabusRevision.objects.filter(published_at__isnull=False).exists())
        self.assertEqual(ActivityLog.objects.filter(action='syllabus.create', actor=self.admin).count(), 10)

        self.assertIn('Loaded 0 draft syllabus(es); 10 already there.', self.load('--apply'))
        self.assertEqual(Syllabus.objects.count(), 10)

    def test_a_reference_is_loaded_once_even_after_the_admin_edits_its_draft(self):
        self.load('--apply')
        syllabus = Syllabus.objects.get(reference_key='9th Plan & Price.pdf')
        draft = syllabus.revisions.get()
        content = {**services._content_of(draft), 'title': 'Grade 9 CBSE (2026)', 'syllabus_version': 'New Syllabus'}
        services.save_draft(self.admin, syllabus.pk, content, draft.updated_at)
        self.assertIn('Loaded 0 draft syllabus(es); 10 already there.', self.load('--apply'))
        self.assertEqual(Syllabus.objects.count(), 10)
        self.assertEqual(services.syllabus_detail(syllabus.pk)['reference'], '9th Plan & Price.pdf')
        self.assertEqual(sorted(Syllabus.objects.values_list('reference_key', flat=True)),
                         sorted(payload['source'] for payload in REFERENCE_SYLLABI))

    def test_grade_6_loads_as_its_pdf_prices_it(self):
        self.load('--apply')
        self.client.force_login(self.admin)
        self.client.post('/api/sales/pricing/', REFERENCE_PRICING, content_type='application/json')
        revision = SyllabusRevision.objects.get(title='Grade 6 CBSE', structure='CHAPTER_WISE')
        draft = services.syllabus_detail(revision.syllabus_id)['draft']
        self.assertEqual([(p['title'], p['total'], p['single_payment']) for p in draft['packages']], [
            ('Regular Course Package', '1330', {'price': '1264', 'saving': '66'}),
            ('Revision Course (Exam Oriented) Package', '665', None),
        ])

    def test_only_an_account_that_manages_syllabuses(self):
        account('reference_tutor', role='TUTOR')
        with self.assertRaises(CommandError):
            call_command('load_reference_syllabi', '--as', 'reference_tutor', '--apply', stdout=StringIO())
        with self.assertRaises(CommandError):
            call_command('load_reference_syllabi', '--as', 'nobody', stdout=StringIO())
        self.assertFalse(Syllabus.objects.exists())
