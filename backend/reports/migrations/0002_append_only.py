# Written by hand, 2026-11-01.
#
# A report's revisions and its shares are its history: once written, never
# changed or removed. A trigger on each table refuses every UPDATE and DELETE,
# the pattern booking_events and activity_log already use, so nothing --
# the ORM, the Django admin or raw SQL -- can rewrite a version or a send.
from django.db import migrations

TABLES = ('diagnostic_report_revisions', 'demo_report_revisions', 'report_shares')

APPEND_ONLY_SQL = """
CREATE OR REPLACE FUNCTION report_history_immutable()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  RAISE EXCEPTION '% is append-only', TG_TABLE_NAME;
END;
$$;
""" + ''.join(f"""
DROP TRIGGER IF EXISTS {table}_no_mutate ON {table};
CREATE TRIGGER {table}_no_mutate
  BEFORE UPDATE OR DELETE ON {table}
  FOR EACH ROW EXECUTE FUNCTION report_history_immutable();
""" for table in TABLES)

APPEND_ONLY_REVERSE_SQL = ''.join(f'DROP TRIGGER IF EXISTS {table}_no_mutate ON {table};\n' for table in TABLES) + """
DROP FUNCTION IF EXISTS report_history_immutable();
"""


class Migration(migrations.Migration):

    dependencies = [
        ('reports', '0001_reports_and_revisions'),
    ]

    operations = [
        migrations.RunSQL(APPEND_ONLY_SQL, APPEND_ONLY_REVERSE_SQL),
    ]
