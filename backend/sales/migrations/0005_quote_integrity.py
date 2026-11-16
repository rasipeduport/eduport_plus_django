# Written by hand, 2026-11-09.
#
# sales.0004 keeps a quote's figures and parts unchangeable, and checks at
# commit that its packages and chapters add up to its own figures. Sums alone
# would still let a part be added later that changes nothing they add -- a
# chapter or day with no classes, say. This closes that, in the database:
#
#   sales_quotes.issued_xact   the transaction that issued the quote, stamped by
#                              the database itself (pg_current_xact_id(), the
#                              top-level transaction even inside a savepoint).
#                              No code reads or writes it; sales.0004 keeps it
#                              unchanged with every other column.
#   sales_quote_lines,         a part is written only in the transaction that
#   sales_quote_chapters       issued its quote: never added to a quote issued
#                              before. A chapter must be a row of the quote's
#                              own revision, with the classes that row has for
#                              the quote's plan type; a package must be of the
#                              quote's plan type (Regular + Revision: Regular or
#                              Revision).
#   all three                  at commit (deferred): a whole-course quote covers
#                              every chapter of its revision.
#   sales_quotes               a cancelled quote says why: its reason holds more
#                              than blanks (a CHECK, as the model declares it).
from django.db import migrations, models

SQL = """
ALTER TABLE sales_quotes ADD COLUMN issued_xact xid8 NOT NULL DEFAULT pg_current_xact_id();

CREATE OR REPLACE FUNCTION sales_quote_part_checked()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  quote sales_quotes%ROWTYPE;
  chapter sales_syllabus_chapters%ROWTYPE;
  counted numeric;
BEGIN
  SELECT * INTO quote FROM sales_quotes WHERE id = NEW.quote_id;
  IF quote.issued_xact <> pg_current_xact_id() THEN
    RAISE EXCEPTION 'quote % was issued in another transaction: its packages and chapters are fixed', NEW.quote_id;
  END IF;
  IF TG_TABLE_NAME = 'sales_quote_lines' THEN
    IF NOT (NEW.plan_type = quote.plan_type
            OR (quote.plan_type = 'REGULAR_REVISION' AND NEW.plan_type IN ('REGULAR', 'REVISION'))) THEN
      RAISE EXCEPTION 'a % package is not part of quote % (%)', NEW.plan_type, quote.id, quote.plan_type;
    END IF;
    RETURN NEW;
  END IF;
  SELECT * INTO chapter FROM sales_syllabus_chapters WHERE id = NEW.chapter_id;
  IF chapter.revision_id IS DISTINCT FROM quote.revision_id THEN
    RAISE EXCEPTION 'chapter % is not of the revision quote % was made from', NEW.chapter_id, quote.id;
  END IF;
  counted := CASE quote.plan_type
    WHEN 'REGULAR' THEN coalesce(chapter.regular_classes, 0)
    WHEN 'REVISION' THEN coalesce(chapter.revision_classes, 0)
    WHEN 'REGULAR_REVISION' THEN coalesce(chapter.regular_classes, 0) + coalesce(chapter.revision_classes, 0)
    WHEN 'CHAPTER_PLAN' THEN coalesce(chapter.regular_classes, 0)
    WHEN 'BRIDGE_COURSE' THEN coalesce(chapter.bridge_classes, 0)
  END;
  IF counted IS NULL OR NEW.classes <> counted THEN
    RAISE EXCEPTION 'chapter % has % classes for quote % (%), not %', NEW.chapter_id, counted, quote.id, quote.plan_type,
      NEW.classes;
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS sales_quote_lines_checked ON sales_quote_lines;
CREATE TRIGGER sales_quote_lines_checked
  BEFORE INSERT ON sales_quote_lines
  FOR EACH ROW EXECUTE FUNCTION sales_quote_part_checked();
DROP TRIGGER IF EXISTS sales_quote_chapters_checked ON sales_quote_chapters;
CREATE TRIGGER sales_quote_chapters_checked
  BEFORE INSERT ON sales_quote_chapters
  FOR EACH ROW EXECUTE FUNCTION sales_quote_part_checked();

CREATE OR REPLACE FUNCTION sales_quote_covers_its_course()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  checked uuid;
  quote sales_quotes%ROWTYPE;
BEGIN
  -- A field is read only where it exists: a quote is its own id, a chapter names its quote.
  IF TG_TABLE_NAME = 'sales_quotes' THEN
    checked := NEW.id;
  ELSE
    checked := NEW.quote_id;
  END IF;
  SELECT * INTO quote FROM sales_quotes WHERE id = checked;
  IF quote.full_course
     AND (SELECT count(*) FROM sales_quote_chapters WHERE quote_id = quote.id)
         <> (SELECT count(*) FROM sales_syllabus_chapters WHERE revision_id = quote.revision_id) THEN
    RAISE EXCEPTION 'quote % is a whole course but does not cover every chapter of its revision', quote.id;
  END IF;
  RETURN NULL;
END;
$$;

DROP TRIGGER IF EXISTS sales_quotes_cover_their_course ON sales_quotes;
CREATE CONSTRAINT TRIGGER sales_quotes_cover_their_course
  AFTER INSERT ON sales_quotes DEFERRABLE INITIALLY DEFERRED
  FOR EACH ROW EXECUTE FUNCTION sales_quote_covers_its_course();
DROP TRIGGER IF EXISTS sales_quote_chapters_cover_their_course ON sales_quote_chapters;
CREATE CONSTRAINT TRIGGER sales_quote_chapters_cover_their_course
  AFTER INSERT ON sales_quote_chapters DEFERRABLE INITIALLY DEFERRED
  FOR EACH ROW EXECUTE FUNCTION sales_quote_covers_its_course();
"""

REVERSE_SQL = """
DROP TRIGGER IF EXISTS sales_quote_chapters_cover_their_course ON sales_quote_chapters;
DROP TRIGGER IF EXISTS sales_quotes_cover_their_course ON sales_quotes;
DROP TRIGGER IF EXISTS sales_quote_chapters_checked ON sales_quote_chapters;
DROP TRIGGER IF EXISTS sales_quote_lines_checked ON sales_quote_lines;
DROP FUNCTION IF EXISTS sales_quote_covers_its_course();
DROP FUNCTION IF EXISTS sales_quote_part_checked();
ALTER TABLE sales_quotes DROP COLUMN IF EXISTS issued_xact;
"""


class Migration(migrations.Migration):

    dependencies = [
        ('sales', '0004_quote_history'),
    ]

    operations = [
        migrations.RunSQL(SQL, REVERSE_SQL),
        migrations.AddConstraint(
            model_name='quote',
            constraint=models.CheckConstraint(
                condition=models.Q(('status', 'ISSUED'), ('cancel_reason__regex', '\\S'), _connector='OR'),
                name='sales_quotes_cancelled_with_a_reason',
            ),
        ),
    ]
