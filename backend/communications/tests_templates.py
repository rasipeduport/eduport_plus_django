"""
The message templates (communications.prd_templates): the PRD's ten messages are five
per booking type, and Message 4 of each is the BDE's call, with no text for
the parent -- so eight templates, one per booking type and message step,
version 1 the PRD 3.11 wording character for character, each template its
type's own -- Demo and Diagnostic never share one -- and every version
append-only.
"""
from django.apps import apps
from django.core.management import call_command
from django.core.management.sql import emit_post_migrate_signal
from django.db import IntegrityError, connection, transaction
from django.db.models.signals import post_migrate
from django.test import TestCase, TransactionTestCase

from bookings.models import BookingType

from .models import MESSAGE_STEPS, MessageTemplate, MessageTemplateVersion, Step, template_key
from .prd_templates import ensure_prd_templates
from .rendering import VARIABLES, placeholders

# The PRD's text, as 3.11.1 and 3.11.2 give it; [TEACHER] and [PENCIL] stand
# for its two emoji with invisible joiners, so nothing here can hide one.
TEACHER = chr(0x1F469) + chr(0x200D) + chr(0x1F3EB)
PENCIL = chr(0x270F) + chr(0xFE0F)

PRD = {
    'DEMO_ACKNOWLEDGEMENT': """Hi Sir/Ma'am,

We’ve received your request for Eduport Plus 1 on 1 Demo class on **{{demo_date}} at {{demo_time}} IST**. We will share the teacher details and class link with you shortly.

If you have any questions regarding the demo, please feel free to reach out to me.

Excited to begin your child’s learning journey with Eduport Plus!

**{{bde_name}}**

**Eduport Plus**""",
    'DEMO_CONFIRMATION_REQUEST': """Hi Sir/Ma'am,

Your child’s Eduport Plus 1 on 1 Demo class is scheduled for **{{demo_date}} at {{demo_time}} IST**, and we are awaiting your confirmation.

We kindly request you to confirm by this evening. If we do not receive your confirmation, we may need to release the slot for another student.

**{{bde_name}}**

**Eduport Plus**""",
    'DEMO_CONFIRMED': """✅ **Demo Confirmed!**

Hi Sir/Ma'am,

Thank you for confirming your child’s Eduport Plus 1 on 1 Demo class. Here are the session details:

[TEACHER] Tutor: {{tutor_name}}

📅 Date: {{demo_date}}

⏰ Time: {{demo_time}} IST

💻 Join the class: {{meeting_link}}

💡 Tip: Join from a desktop or tablet, and keep a pen and notebook handy [PENCIL]

If you need any assistance, please feel free to contact me at {{bde_phone}}.

**{{bde_name}}**

**Eduport Plus**""",
    'DEMO_AFTER_ACTIVITY': """Hi Sir/Ma'am,

Thank you for attending today’s Eduport Plus 1 on 1 demo session. We hope the class gave you a clear understanding of how our personalized 1-on-1 learning can support your child’s progress.

Our Academic Counsellor will be reaching out to you soon to collect your feedback and guide you on the next steps.

**{{bde_name}}**

**Eduport Plus**""",
    'DIAGNOSTIC_ACKNOWLEDGEMENT': """Hi Sir/Ma'am,

We’ve received your request for Eduport Plus Diagnostic Test scheduled on **{{diagnostic_date}} at {{diagnostic_time}} IST**.

We will share the test details and access link with you shortly.

If you have any questions regarding the diagnostic test, please feel free to reach out to me.

Looking forward to assessing your child’s learning level with Eduport Plus!

**{{bde_name}}**

**Eduport Plus**""",
    'DIAGNOSTIC_CONFIRMATION_REQUEST': """Hi Sir/Ma'am,

Your child’s Eduport Plus Diagnostic Test is scheduled for **{{diagnostic_date}} at {{diagnostic_time}} IST**, and we are awaiting your confirmation.

We kindly request you to confirm by this evening. If we do not receive your confirmation, we may need to release the slot for another student.

**{{bde_name}}**

**Eduport Plus**""",
    # The one change from the PRD (Phase 2 decision 2): the link is the
    # booking's tutor Meet link, {{meeting_link}}, not {{diagnostic_link}}.
    'DIAGNOSTIC_CONFIRMED': """✅ **Diagnostic Test Confirmed!**

Hi Sir/Ma’am,

Thank you for confirming your child’s Eduport Plus Diagnostic Test. Here are the test details:

📝 Test: Diagnostic Assessment

📅 Date: {{diagnostic_date}}

⏰ Time: {{diagnostic_time}} IST

💻 Access the test: {{meeting_link}}

💡 Tip: Please ensure a stable internet connection and keep a pen and notebook handy [PENCIL]

If you need any assistance, please feel free to contact me at {{bde_phone}}.

**{{bde_name}}**

**Eduport Plus**""",
    'DIAGNOSTIC_AFTER_ACTIVITY': """Hi Sir/Ma'am,

Thank you for participating in today’s Eduport Plus Diagnostic Test. We appreciate the time and effort taken to complete the assessment.

After carefully reviewing the diagnostic test results, our academic team will get back to you with detailed insights into your child’s performance along with the recommended next steps.

Our Academic Counsellor will be reaching out to you shortly to guide you further and address any questions you may have.

**{{bde_name}}**

**Eduport Plus**""",
}


def prd_text(key):
    return PRD[key].replace('[TEACHER]', TEACHER).replace('[PENCIL]', PENCIL)


def current_body(key):
    return MessageTemplate.objects.get(key=key).current_version().body


class SeedTests(TestCase):
    def test_one_template_per_booking_type_and_message_step(self):
        keys = {template_key(booking_type, step) for booking_type in BookingType.values for step in MESSAGE_STEPS}
        self.assertEqual(len(keys), 8)
        self.assertEqual(set(MessageTemplate.objects.values_list('key', flat=True)), keys)
        for template in MessageTemplate.objects.all():
            self.assertEqual(template.key, template_key(template.booking_type, template.step))
        # The 15-minute call sends no message, so it has no template.
        self.assertFalse(MessageTemplate.objects.filter(step=Step.PRE_ACTIVITY_CALL).exists())

    def test_version_one_is_the_prd_wording_character_for_character(self):
        for key in PRD:
            with self.subTest(key=key):
                version = MessageTemplate.objects.get(key=key).current_version()
                self.assertEqual(version.version, 1)
                self.assertEqual(version.body, prd_text(key))
                self.assertIsNone(version.created_by)

    def test_the_prd_typography_is_kept(self):
        self.assertIn('Hi Sir/Ma’am,', current_body('DIAGNOSTIC_CONFIRMED'))
        self.assertIn("Hi Sir/Ma'am,", current_body('DEMO_CONFIRMED'))
        self.assertIn(TEACHER + ' Tutor:', current_body('DEMO_CONFIRMED'))
        self.assertTrue(current_body('DEMO_ACKNOWLEDGEMENT').startswith("Hi Sir/Ma'am,\n\nWe’ve received"))

    def test_every_placeholder_is_one_its_booking_type_may_use(self):
        for template in MessageTemplate.objects.all():
            with self.subTest(key=template.key):
                names = placeholders(template.current_version().body)
                self.assertTrue(set(names) <= set(VARIABLES[template.booking_type]), names)

    def test_both_confirmed_messages_use_the_bookings_meet_link(self):
        for key in ('DEMO_CONFIRMED', 'DIAGNOSTIC_CONFIRMED'):
            self.assertIn('meeting_link', placeholders(current_body(key)))
        self.assertNotIn('diagnostic_link', VARIABLES[BookingType.DIAGNOSTIC])

    def test_a_new_demo_version_leaves_the_diagnostic_template_alone(self):
        demo = MessageTemplate.objects.get(key='DEMO_ACKNOWLEDGEMENT')
        MessageTemplateVersion.objects.create(template=demo, version=2, body='Edited {{bde_name}}')
        self.assertEqual(demo.current_version().version, 2)
        self.assertEqual(current_body('DIAGNOSTIC_ACKNOWLEDGEMENT'), prd_text('DIAGNOSTIC_ACKNOWLEDGEMENT'))
        self.assertEqual(demo.versions.get(version=1).body, prd_text('DEMO_ACKNOWLEDGEMENT'))


class SeederTests(TestCase):
    def test_it_runs_on_post_migrate_for_this_app(self):
        self.assertTrue(post_migrate.has_listeners(apps.get_app_config('communications')))

    def test_running_it_again_writes_nothing_and_overwrites_no_edit(self):
        demo = MessageTemplate.objects.get(key='DEMO_ACKNOWLEDGEMENT')
        MessageTemplate.objects.filter(pk=demo.pk).update(name='Demo welcome')
        MessageTemplateVersion.objects.create(template=demo, version=2, body='Edited {{bde_name}}')
        before = list(MessageTemplateVersion.objects.order_by('template', 'version').values_list('id', 'body'))
        self.assertEqual(ensure_prd_templates(), 0)
        # As every `migrate` does: post_migrate for every app, this one's seeder included.
        emit_post_migrate_signal(verbosity=0, interactive=False, db='default')
        self.assertEqual(list(MessageTemplateVersion.objects.order_by('template', 'version').values_list('id', 'body')),
                         before)
        demo.refresh_from_db()
        self.assertEqual((demo.name, demo.current_version().body), ('Demo welcome', 'Edited {{bde_name}}'))
        self.assertEqual(demo.versions.get(version=1).body, prd_text('DEMO_ACKNOWLEDGEMENT'))
        self.assertEqual((MessageTemplate.objects.count(), MessageTemplateVersion.objects.count()), (8, 9))


class SeederAfterFlushTests(TransactionTestCase):
    def test_a_flushed_database_gets_the_prd_templates_back(self):
        call_command('flush', interactive=False, verbosity=0)
        self.assertEqual(MessageTemplate.objects.count(), 8)
        for key in PRD:
            with self.subTest(key=key):
                self.assertEqual(current_body(key), prd_text(key))


class VersionRuleTests(TestCase):
    def test_versions_are_append_only(self):
        version = MessageTemplate.objects.get(key='DEMO_CONFIRMED').current_version()
        for statement in (
            'UPDATE message_template_versions SET body = %s WHERE id = %s',
            'DELETE FROM message_template_versions WHERE id = %s',
        ):
            with self.subTest(statement=statement.split()[0]), self.assertRaisesMessage(Exception, 'append-only'):
                with transaction.atomic(), connection.cursor() as cursor:
                    params = ['changed', version.id] if statement.startswith('UPDATE') else [version.id]
                    cursor.execute(statement, params)
        self.assertEqual(MessageTemplate.objects.get(key='DEMO_CONFIRMED').current_version().body, prd_text('DEMO_CONFIRMED'))

    def test_one_version_per_number(self):
        template = MessageTemplate.objects.get(key='DEMO_CONFIRMED')
        with self.assertRaises(IntegrityError), transaction.atomic():
            MessageTemplateVersion.objects.create(template=template, version=1, body='Again')
