# Written by hand, 2026-11-09.
#
# What was published or charged is history: a published syllabus revision,
# its chapters and every pricing version can never change once written.
# Triggers refuse it, the pattern activity_log, booking_events and the report
# revisions (reports.0002) already use, so nothing -- the ORM, the Django
# admin or raw SQL -- can rewrite them.
#
#   sales_pricing_versions     append-only: every UPDATE and DELETE is refused.
#   sales_syllabus_revisions   a published revision refuses every UPDATE and
#                              DELETE. A draft stays editable and deletable;
#                              publishing it is the UPDATE that stamps it.
#   sales_syllabus_chapters    no row of a published revision may be added,
#                              changed or removed. The trigger reads the
#                              revision FOR SHARE, so a chapter write and the
#                              publication of its revision never interleave: the
#                              write lands before the publication, or is refused
#                              after it.
from django.db import migrations

SQL = """
CREATE OR REPLACE FUNCTION sales_pricing_versions_immutable()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  RAISE EXCEPTION '% is append-only', TG_TABLE_NAME;
END;
$$;

DROP TRIGGER IF EXISTS sales_pricing_versions_no_mutate ON sales_pricing_versions;
CREATE TRIGGER sales_pricing_versions_no_mutate
  BEFORE UPDATE OR DELETE ON sales_pricing_versions
  FOR EACH ROW EXECUTE FUNCTION sales_pricing_versions_immutable();

CREATE OR REPLACE FUNCTION sales_published_revision_immutable()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  IF OLD.published_at IS NOT NULL THEN
    RAISE EXCEPTION 'syllabus revision % is published and cannot change', OLD.id;
  END IF;
  IF TG_OP = 'DELETE' THEN
    RETURN OLD;
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS sales_syllabus_revisions_published_no_mutate ON sales_syllabus_revisions;
CREATE TRIGGER sales_syllabus_revisions_published_no_mutate
  BEFORE UPDATE OR DELETE ON sales_syllabus_revisions
  FOR EACH ROW EXECUTE FUNCTION sales_published_revision_immutable();

CREATE OR REPLACE FUNCTION sales_published_chapters_immutable()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
  published timestamptz;
BEGIN
  IF TG_OP IN ('UPDATE', 'DELETE') THEN
    SELECT published_at INTO published FROM sales_syllabus_revisions WHERE id = OLD.revision_id FOR SHARE;
    IF published IS NOT NULL THEN
      RAISE EXCEPTION 'the chapters of published syllabus revision % cannot change', OLD.revision_id;
    END IF;
  END IF;
  IF TG_OP IN ('INSERT', 'UPDATE') THEN
    SELECT published_at INTO published FROM sales_syllabus_revisions WHERE id = NEW.revision_id FOR SHARE;
    IF published IS NOT NULL THEN
      RAISE EXCEPTION 'the chapters of published syllabus revision % cannot change', NEW.revision_id;
    END IF;
  END IF;
  IF TG_OP = 'DELETE' THEN
    RETURN OLD;
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS sales_syllabus_chapters_published_no_mutate ON sales_syllabus_chapters;
CREATE TRIGGER sales_syllabus_chapters_published_no_mutate
  BEFORE INSERT OR UPDATE OR DELETE ON sales_syllabus_chapters
  FOR EACH ROW EXECUTE FUNCTION sales_published_chapters_immutable();
"""

REVERSE_SQL = """
DROP TRIGGER IF EXISTS sales_syllabus_chapters_published_no_mutate ON sales_syllabus_chapters;
DROP TRIGGER IF EXISTS sales_syllabus_revisions_published_no_mutate ON sales_syllabus_revisions;
DROP TRIGGER IF EXISTS sales_pricing_versions_no_mutate ON sales_pricing_versions;
DROP FUNCTION IF EXISTS sales_published_chapters_immutable();
DROP FUNCTION IF EXISTS sales_published_revision_immutable();
DROP FUNCTION IF EXISTS sales_pricing_versions_immutable();
"""


class Migration(migrations.Migration):

    dependencies = [
        ('sales', '0001_initial'),
    ]

    operations = [
        migrations.RunSQL(SQL, REVERSE_SQL),
    ]
