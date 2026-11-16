"""Token Sale chosen with its tuition plan (sales.token_sales). Prepared, not applied.

A Token Sale quote (collection mode TOKEN) is collected in full, on its own
Token Sale only. Before enrollment, every Token Sale's tuition payment covers
every class of its purchase: the AED 100 token alone never enrolls, and the
first tuition payment -- the one that enrolls (sales.payments.succeed) --
settles the whole remaining balance. Existing reservations have no balance
deadline and keep their expected start date as their reminder's date. The
migration refuses to run while a Token Sale still has an unpaid tuition link
for part of its classes (PRECHECK).
"""
from importlib import import_module

from django.db import migrations, models


def prior_function(module, name):
    source = import_module(f'sales.migrations.{module}').SQL
    start = source.index(f'FUNCTION {name}()')
    end = source.index('END $$;', start) + len('END $$;')
    return 'CREATE OR REPLACE ' + source[start:end]


# Before this migration a Token Sale could send a tuition link for part of its classes. One still unpaid
# (PENDING, or FAILED and retryable) would enroll on part of the balance once paid: expire it first.
PRECHECK = """
DO $$ BEGIN
  IF EXISTS(
    SELECT 1 FROM sales_payment p JOIN sales_sale s ON s.id=p.sale_id JOIN sales_purchase b ON b.id=p.purchase_id
    WHERE s.kind='TOKEN' AND s.student_id IS NULL AND p.purpose='TUITION' AND p.status IN ('PENDING','FAILED')
      AND p.classes<>b.classes
  ) THEN
    RAISE EXCEPTION 'a Token Sale has an unpaid tuition link for part of its classes: expire it before applying sales.0021 (a pending link from the Hub; a failed one by setting its status to EXPIRED)';
  END IF;
END $$;
"""

SQL = PRECHECK + """
CREATE OR REPLACE FUNCTION sales_confirmed_purchase_mode() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE quoted sales_quotes%ROWTYPE;
BEGIN
  SELECT * INTO quoted FROM sales_quotes WHERE id=NEW.quote_id;
  IF quoted.collection_mode='TOKEN' THEN
    IF NEW.collection_mode<>'FULL' OR (SELECT kind FROM sales_sale WHERE id=NEW.sale_id) IS DISTINCT FROM 'TOKEN' THEN
      RAISE EXCEPTION 'a Token Sale quote is collected in full, on its own Token Sale only';
    END IF;
  ELSIF quoted.collection_intention_confirmed AND NOT (
      (quoted.collection_mode IN ('FULL','PARTIAL') AND NEW.collection_mode=quoted.collection_mode)
      OR (quoted.collection_mode='AUTOPAY' AND NEW.collection_mode='PARTIAL')) THEN
    RAISE EXCEPTION 'purchase collection mode must follow the confirmed immutable quote';
  END IF;
  RETURN NEW;
END $$;

CREATE FUNCTION sales_token_tuition_in_full() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE v_kind text; v_enrolled boolean; v_classes numeric;
BEGIN
  IF NEW.purpose<>'TUITION' THEN RETURN NEW; END IF;
  SELECT kind, student_id IS NOT NULL INTO v_kind, v_enrolled FROM sales_sale WHERE id=NEW.sale_id;
  IF v_kind IS DISTINCT FROM 'TOKEN' OR v_enrolled THEN RETURN NEW; END IF;
  SELECT classes INTO v_classes FROM sales_purchase WHERE id=NEW.purchase_id;
  IF NEW.classes IS DISTINCT FROM v_classes THEN
    RAISE EXCEPTION 'a Token Sale''s tuition before enrollment is one payment for every class of its purchase';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER sales_token_tuition_in_full BEFORE INSERT ON sales_payment
  FOR EACH ROW EXECUTE FUNCTION sales_token_tuition_in_full();
"""

REVERSE = """
DO $$ BEGIN
  IF EXISTS(SELECT 1 FROM sales_quotes WHERE collection_mode='TOKEN')
     OR EXISTS(SELECT 1 FROM sales_sale WHERE balance_due_date IS NOT NULL) THEN
    RAISE EXCEPTION 'Token Sale quotes or balance deadlines exist; their rules cannot be removed';
  END IF;
END $$;
DROP TRIGGER sales_token_tuition_in_full ON sales_payment;
DROP FUNCTION sales_token_tuition_in_full();
""" + prior_function('0013_quote_collection_integrity', 'sales_confirmed_purchase_mode')


class Migration(migrations.Migration):

    dependencies = [
        ('sales', '0020_stripe_event_backfill'),
    ]

    operations = [
        migrations.AddField(
            model_name='sale',
            name='balance_due_date',
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='quote',
            name='collection_mode',
            field=models.CharField(choices=[('FULL', 'Single / Complete Payment'), ('PARTIAL', 'Partial Payment'), ('AUTOPAY', 'Autopay'), ('TOKEN', 'Token Sale')], max_length=7),
        ),
        migrations.AddConstraint(
            model_name='sale',
            constraint=models.CheckConstraint(condition=models.Q(('balance_due_date__isnull', True), ('kind', 'TOKEN'), _connector='OR'), name='sales_balance_due_date_token_only'),
        ),
        migrations.RunSQL(SQL, REVERSE),
    ]
