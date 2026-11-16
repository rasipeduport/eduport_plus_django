# Lead notes (bookings.notes): one new table, lead_notes -- the notes staff
# keep on a lead, shared by its owner BDE, the tutors assigned to its bookings
# and the administrators. No existing row is written.

import django.db.models.deletion
import django.utils.timezone
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('bookings', '0012_redemos'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='LeadNote',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('body', models.TextField()),
                ('author_name', models.CharField(max_length=255)),
                ('author_role', models.CharField(
                    choices=[('BDE', 'BDE'), ('TUTOR', 'Tutor'), ('ADMIN', 'Admin')], max_length=10)),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now, editable=False)),
                ('author', models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='lead_notes',
                    to=settings.AUTH_USER_MODEL)),
                ('lead', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT, related_name='notes', to='bookings.lead')),
            ],
            options={
                'verbose_name': 'Lead note',
                'verbose_name_plural': 'Lead notes',
                'db_table': 'lead_notes',
                'ordering': ['created_at', 'id'],
                'indexes': [models.Index(fields=['lead', 'created_at'], name='lead_notes_lead_idx')],
                'constraints': [
                    models.CheckConstraint(condition=models.Q(('body', ''), _negated=True), name='lead_notes_body_given'),
                    models.CheckConstraint(
                        condition=models.Q(('author_role__in', ['BDE', 'TUTOR', 'ADMIN'])), name='lead_notes_known_role'),
                ],
            },
        ),
    ]
