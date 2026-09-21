# Append-only hardening for activity_log — a direct port of the original Hub's
# 20260617160134_activity_log.sql trigger and 20260617160223 FK drop:
#   1. actor/student FKs lose their DB constraint and delete action so no
#      deletion elsewhere can ever mutate (SET NULL) or block on a log row.
#   2. A BEFORE UPDATE OR DELETE trigger rejects every mutation, for every
#      role — the log accepts inserts only.
# Row-level triggers do not fire on TRUNCATE, so Django's test-database flush
# is unaffected.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

APPEND_ONLY_SQL = """
CREATE OR REPLACE FUNCTION activity_log_immutable()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  RAISE EXCEPTION 'activity_log is append-only';
END;
$$;

DROP TRIGGER IF EXISTS activity_log_no_mutate ON activity_log;
CREATE TRIGGER activity_log_no_mutate
  BEFORE UPDATE OR DELETE ON activity_log
  FOR EACH ROW EXECUTE FUNCTION activity_log_immutable();
"""

APPEND_ONLY_REVERSE_SQL = """
DROP TRIGGER IF EXISTS activity_log_no_mutate ON activity_log;
DROP FUNCTION IF EXISTS activity_log_immutable();
"""


class Migration(migrations.Migration):

    dependencies = [
        ('activity', '0001_initial'),
        ('students', '0002_alter_student_profile'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(
            model_name='activitylog',
            name='actor',
            field=models.ForeignKey(
                blank=True,
                db_constraint=False,
                null=True,
                on_delete=django.db.models.deletion.DO_NOTHING,
                related_name='activity_logs',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name='activitylog',
            name='student',
            field=models.ForeignKey(
                blank=True,
                db_constraint=False,
                null=True,
                on_delete=django.db.models.deletion.DO_NOTHING,
                related_name='activity_logs',
                to='students.student',
            ),
        ),
        migrations.RunSQL(APPEND_ONLY_SQL, APPEND_ONLY_REVERSE_SQL),
    ]
