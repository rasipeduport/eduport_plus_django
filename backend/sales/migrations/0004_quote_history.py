# Written by hand, 2026-11-09.
#
# A quote is what a parent was told: once issued, its figures never change,
# whatever revision is published or pricing version saved later. Triggers
# hold it, as sales.0002 holds the published syllabuses and the pricing:
#
#   sales_quotes           never deleted; an UPDATE may change only the
#                          status and the cancellation it records (every other
#                          column, and any added later, is compared whole), and
#                          a cancelled quote changes no more.
#   sales_quote_lines,     written with their quote, then never changed or
#   sales_quote_chapters   removed.
#   all three              at commit (deferred), a quote's packages and
#                          chapters add up to its own classes, total and
#                          saving: a quote is never left without them, nor
#                          given another package or chapter afterwards.
from django.db import migrations

SQL = """
CREATE OR REPLACE FUNCTION sales_quotes_immutable()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'quote % is history and cannot be deleted', OLD.id;
  END IF;
  IF (to_jsonb(NEW) - ARRAY['status', 'cancelled_at', 'cancelled_by_id', 'cancel_reason'])
     IS DISTINCT FROM (to_jsonb(OLD) - ARRAY['status', 'cancelled_at', 'cancelled_by_id', 'cancel_reason']) THEN
    RAISE EXCEPTION 'quote % keeps its figures: only its status may change', OLD.id;
  END IF;
  IF OLD.status = 'CANCELLED' THEN
    RAISE EXCEPTION 'quote % is cancelled and cannot change', OLD.id;
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS sales_quotes_figures_fixed ON sales_quotes;
CREATE TRIGGER sales_quotes_figures_fixed
  BEFORE UPDATE OR DELETE ON sales_quotes
  FOR EACH ROW EXECUTE FUNCTION sales_quotes_immutable();

CREATE OR REPLACE FUNCTION sales_quote_parts_immutable()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION '% of quote % cannot change', TG_TABLE_NAME, OLD.quote_id;
END;
$$;

DROP TRIGGER IF EXISTS sales_quote_lines_fixed ON sales_quote_lines;
CREATE TRIGGER sales_quote_lines_fixed
  BEFORE UPDATE OR DELETE ON sales_quote_lines
  FOR EACH ROW EXECUTE FUNCTION sales_quote_parts_immutable();
DROP TRIGGER IF EXISTS sales_quote_chapters_fixed ON sales_quote_chapters;
CREATE TRIGGER sales_quote_chapters_fixed
  BEFORE UPDATE OR DELETE ON sales_quote_chapters
  FOR EACH ROW EXECUTE FUNCTION sales_quote_parts_immutable();

CREATE OR REPLACE FUNCTION sales_quote_adds_up()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  checked uuid;
  quote sales_quotes%ROWTYPE;
BEGIN
  -- A field is read only where it exists: a quote is its own id, a package or chapter names its quote.
  IF TG_TABLE_NAME = 'sales_quotes' THEN
    checked := NEW.id;
  ELSE
    checked := NEW.quote_id;
  END IF;
  SELECT * INTO quote FROM sales_quotes WHERE id = checked;
  IF (SELECT coalesce(sum(classes), 0) FROM sales_quote_lines WHERE quote_id = quote.id) <> quote.classes
     OR (SELECT coalesce(sum(total), 0) FROM sales_quote_lines WHERE quote_id = quote.id) <> quote.total_fee
     OR (SELECT coalesce(sum(single_payment_saving), 0) FROM sales_quote_lines WHERE quote_id = quote.id)
        <> quote.single_payment_saving
     OR (SELECT coalesce(sum(classes), 0) FROM sales_quote_chapters WHERE quote_id = quote.id) <> quote.classes THEN
    RAISE EXCEPTION 'quote % does not add up to its packages and chapters', quote.id;
  END IF;
  RETURN NULL;
END;
$$;

DROP TRIGGER IF EXISTS sales_quotes_add_up ON sales_quotes;
CREATE CONSTRAINT TRIGGER sales_quotes_add_up
  AFTER INSERT ON sales_quotes DEFERRABLE INITIALLY DEFERRED
  FOR EACH ROW EXECUTE FUNCTION sales_quote_adds_up();
DROP TRIGGER IF EXISTS sales_quote_lines_add_up ON sales_quote_lines;
CREATE CONSTRAINT TRIGGER sales_quote_lines_add_up
  AFTER INSERT ON sales_quote_lines DEFERRABLE INITIALLY DEFERRED
  FOR EACH ROW EXECUTE FUNCTION sales_quote_adds_up();
DROP TRIGGER IF EXISTS sales_quote_chapters_add_up ON sales_quote_chapters;
CREATE CONSTRAINT TRIGGER sales_quote_chapters_add_up
  AFTER INSERT ON sales_quote_chapters DEFERRABLE INITIALLY DEFERRED
  FOR EACH ROW EXECUTE FUNCTION sales_quote_adds_up();
"""

REVERSE_SQL = """
DROP TRIGGER IF EXISTS sales_quote_chapters_add_up ON sales_quote_chapters;
DROP TRIGGER IF EXISTS sales_quote_lines_add_up ON sales_quote_lines;
DROP TRIGGER IF EXISTS sales_quotes_add_up ON sales_quotes;
DROP TRIGGER IF EXISTS sales_quote_chapters_fixed ON sales_quote_chapters;
DROP TRIGGER IF EXISTS sales_quote_lines_fixed ON sales_quote_lines;
DROP TRIGGER IF EXISTS sales_quotes_figures_fixed ON sales_quotes;
DROP FUNCTION IF EXISTS sales_quote_adds_up();
DROP FUNCTION IF EXISTS sales_quote_parts_immutable();
DROP FUNCTION IF EXISTS sales_quotes_immutable();
"""


class Migration(migrations.Migration):

    dependencies = [
        ('sales', '0003_quotes'),
    ]

    operations = [
        migrations.RunSQL(SQL, REVERSE_SQL),
    ]
