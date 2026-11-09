from django.db import migrations, models


# Historical rows stay untouched: NULL on an old Chapter Plan means Regular.
# The existing immutable-row trigger also protects this new column automatically.
PART_CHECK = """
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
    WHEN 'CHAPTER_PLAN' THEN CASE quote.class_mode
      WHEN 'REVISION' THEN chapter.revision_classes
      ELSE chapter.regular_classes END
    WHEN 'BRIDGE_COURSE' THEN coalesce(chapter.bridge_classes, 0)
  END;
  IF counted IS NULL OR NEW.classes <> counted THEN
    RAISE EXCEPTION 'chapter % has % classes for quote % (%), not %', NEW.chapter_id, counted, quote.id, quote.plan_type,
      NEW.classes;
  END IF;
  RETURN NEW;
END;
$$;
"""
OLD_PART_CHECK = PART_CHECK.replace(
    "WHEN 'CHAPTER_PLAN' THEN CASE quote.class_mode\n      WHEN 'REVISION' THEN chapter.revision_classes\n      ELSE chapter.regular_classes END",
    "WHEN 'CHAPTER_PLAN' THEN coalesce(chapter.regular_classes, 0)",
)
MODE_CHECK = """
CREATE FUNCTION sales_quote_class_mode_checked() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.plan_type = 'CHAPTER_PLAN' THEN
    IF NEW.class_mode IS NULL OR NEW.class_mode NOT IN ('REGULAR', 'REVISION') THEN
      RAISE EXCEPTION 'a new Chapter Plan must name its Regular or Revision class mode';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM sales_syllabus_revisions
                   WHERE id = NEW.revision_id AND published_at IS NOT NULL
                     AND structure = 'CHAPTER_WISE' AND 'CHAPTER_PLAN' = ANY(plan_types)) THEN
      RAISE EXCEPTION 'a Chapter Plan must use a published revision that offers it';
    END IF;
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER sales_quote_class_mode_checked
  BEFORE INSERT ON sales_quotes FOR EACH ROW EXECUTE FUNCTION sales_quote_class_mode_checked();
"""
REVERSE_GUARD = """
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM sales_quotes WHERE plan_type = 'CHAPTER_PLAN' AND class_mode = 'REVISION') THEN
    RAISE EXCEPTION 'cannot remove class mode while Revision Chapter Plan quotes exist: their history must be preserved';
  END IF;
END $$;
"""


class Migration(migrations.Migration):
    dependencies = [('sales', '0006_quote_replacements')]

    operations = [
        migrations.AddField(
            model_name='quote', name='class_mode',
            field=models.CharField(blank=True, null=True, max_length=8, choices=[('REGULAR', 'Regular'), ('REVISION', 'Revision')]),
        ),
        migrations.AddConstraint(
            model_name='quote',
            constraint=models.CheckConstraint(
                condition=models.Q(class_mode__isnull=True) | models.Q(plan_type='CHAPTER_PLAN', class_mode__in=['REGULAR', 'REVISION']),
                name='sales_quotes_chapter_class_mode',
            ),
        ),
        migrations.RunSQL(
            PART_CHECK + MODE_CHECK,
            REVERSE_GUARD + 'DROP TRIGGER sales_quote_class_mode_checked ON sales_quotes; DROP FUNCTION sales_quote_class_mode_checked();' + OLD_PART_CHECK,
        ),
    ]
