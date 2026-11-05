"""
The parent message templates as the PRD gives them: version 1 of each, the
wording of the Eduport Plus Demo & Diagnostic Management PRD, section 3.11.1
(Demo) and 3.11.2 (Diagnostic), character for character -- its curly and
straight apostrophes, emoji, blank lines and **bold** included. The one
change, by the Phase 2 decisions: the Diagnostic confirmed message's link is
{{meeting_link}}, the booking's tutor Meet link, as Diagnostic tests are
taught over Google Meet too (the PRD wrote {{diagnostic_link}}). Message 4 of
each type has no template: it is a call for the BDE, with no text for the
parent -- so the PRD's ten messages are eight templates.

ensure_prd_templates() writes a template and its version 1 only where they
are missing, and never touches a later version: the database is where the
templates live and are edited (as new versions). It runs after every
``migrate`` (communications.apps), so a new database -- or one a test flushed
-- always has them.
"""
from django.db import connections

TEACHER = '\U0001F469\u200D\U0001F3EB'  # woman teacher (a joined emoji sequence)
PENCIL = '\u270F\uFE0F'  # pencil, emoji presentation

SIGNATURE = '**{{bde_name}}**\n\n**Eduport Plus**'

TEMPLATES = [
    ('DEMO_ACKNOWLEDGEMENT', 'DEMO', 'ACKNOWLEDGEMENT', 'Demo – Initial acknowledgement', (
        "Hi Sir/Ma'am,\n\n"
        "We’ve received your request for Eduport Plus 1 on 1 Demo class on **{{demo_date}} at {{demo_time}} IST**. "
        "We will share the teacher details and class link with you shortly.\n\n"
        "If you have any questions regarding the demo, please feel free to reach out to me.\n\n"
        "Excited to begin your child’s learning journey with Eduport Plus!\n\n"
        + SIGNATURE
    )),
    ('DEMO_CONFIRMATION_REQUEST', 'DEMO', 'CONFIRMATION_REQUEST', 'Demo – Confirmation request', (
        "Hi Sir/Ma'am,\n\n"
        "Your child’s Eduport Plus 1 on 1 Demo class is scheduled for **{{demo_date}} at {{demo_time}} IST**, "
        "and we are awaiting your confirmation.\n\n"
        "We kindly request you to confirm by this evening. If we do not receive your confirmation, "
        "we may need to release the slot for another student.\n\n"
        + SIGNATURE
    )),
    ('DEMO_CONFIRMED', 'DEMO', 'PARENT_CONFIRMATION', 'Demo – Demo confirmed', (
        "✅ **Demo Confirmed!**\n\n"
        "Hi Sir/Ma'am,\n\n"
        "Thank you for confirming your child’s Eduport Plus 1 on 1 Demo class. Here are the session details:\n\n"
        + TEACHER + " Tutor: {{tutor_name}}\n\n"
        "📅 Date: {{demo_date}}\n\n"
        "⏰ Time: {{demo_time}} IST\n\n"
        "💻 Join the class: {{meeting_link}}\n\n"
        "💡 Tip: Join from a desktop or tablet, and keep a pen and notebook handy " + PENCIL + "\n\n"
        "If you need any assistance, please feel free to contact me at {{bde_phone}}.\n\n"
        + SIGNATURE
    )),
    ('DEMO_AFTER_ACTIVITY', 'DEMO', 'AFTER_ACTIVITY', 'Demo – After-demo message', (
        "Hi Sir/Ma'am,\n\n"
        "Thank you for attending today’s Eduport Plus 1 on 1 demo session. We hope the class gave you a clear "
        "understanding of how our personalized 1-on-1 learning can support your child’s progress.\n\n"
        "Our Academic Counsellor will be reaching out to you soon to collect your feedback and guide you on the "
        "next steps.\n\n"
        + SIGNATURE
    )),
    ('DIAGNOSTIC_ACKNOWLEDGEMENT', 'DIAGNOSTIC', 'ACKNOWLEDGEMENT', 'Diagnostic – Initial acknowledgement', (
        "Hi Sir/Ma'am,\n\n"
        "We’ve received your request for Eduport Plus Diagnostic Test scheduled on "
        "**{{diagnostic_date}} at {{diagnostic_time}} IST**.\n\n"
        "We will share the test details and access link with you shortly.\n\n"
        "If you have any questions regarding the diagnostic test, please feel free to reach out to me.\n\n"
        "Looking forward to assessing your child’s learning level with Eduport Plus!\n\n"
        + SIGNATURE
    )),
    ('DIAGNOSTIC_CONFIRMATION_REQUEST', 'DIAGNOSTIC', 'CONFIRMATION_REQUEST', 'Diagnostic – Confirmation request', (
        "Hi Sir/Ma'am,\n\n"
        "Your child’s Eduport Plus Diagnostic Test is scheduled for **{{diagnostic_date}} at {{diagnostic_time}} IST**, "
        "and we are awaiting your confirmation.\n\n"
        "We kindly request you to confirm by this evening. If we do not receive your confirmation, "
        "we may need to release the slot for another student.\n\n"
        + SIGNATURE
    )),
    ('DIAGNOSTIC_CONFIRMED', 'DIAGNOSTIC', 'PARENT_CONFIRMATION', 'Diagnostic – Diagnostic confirmed', (
        "✅ **Diagnostic Test Confirmed!**\n\n"
        "Hi Sir/Ma’am,\n\n"
        "Thank you for confirming your child’s Eduport Plus Diagnostic Test. Here are the test details:\n\n"
        "📝 Test: Diagnostic Assessment\n\n"
        "📅 Date: {{diagnostic_date}}\n\n"
        "⏰ Time: {{diagnostic_time}} IST\n\n"
        "💻 Access the test: {{meeting_link}}\n\n"
        "💡 Tip: Please ensure a stable internet connection and keep a pen and notebook handy " + PENCIL + "\n\n"
        "If you need any assistance, please feel free to contact me at {{bde_phone}}.\n\n"
        + SIGNATURE
    )),
    ('DIAGNOSTIC_AFTER_ACTIVITY', 'DIAGNOSTIC', 'AFTER_ACTIVITY', 'Diagnostic – After-diagnostic message', (
        "Hi Sir/Ma'am,\n\n"
        "Thank you for participating in today’s Eduport Plus Diagnostic Test. We appreciate the time and effort "
        "taken to complete the assessment.\n\n"
        "After carefully reviewing the diagnostic test results, our academic team will get back to you with "
        "detailed insights into your child’s performance along with the recommended next steps.\n\n"
        "Our Academic Counsellor will be reaching out to you shortly to guide you further and address any "
        "questions you may have.\n\n"
        + SIGNATURE
    )),
]


def ensure_prd_templates(using='default'):
    """Write each missing template, and each template's missing version 1. Returns how many rows it wrote."""
    from .models import MessageTemplate, MessageTemplateVersion

    tables = set(connections[using].introspection.table_names())
    if not {MessageTemplate._meta.db_table, MessageTemplateVersion._meta.db_table} <= tables:
        return 0  # communications is not migrated (yet) on this database
    written = 0
    for key, booking_type, step, name, body in TEMPLATES:
        template, created = MessageTemplate.objects.using(using).get_or_create(
            key=key, defaults={'booking_type': booking_type, 'step': step, 'name': name},
        )
        written += created
        if not MessageTemplateVersion.objects.using(using).filter(template=template, version=1).exists():
            MessageTemplateVersion.objects.using(using).create(
                template=template, version=1, body=body, note='PRD 3.11 wording',
            )
            written += 1
    return written
