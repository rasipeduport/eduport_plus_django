"""Tie newly confirmed quote intentions to the existing payment ledger.

Historical purchases/agreements are unchanged. Their Quote confirmation marker
is false, so their already-frozen FULL/PARTIAL ledger terms remain valid.
"""
from django.db import migrations

SQL = """
CREATE FUNCTION sales_confirmed_purchase_mode() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE quoted sales_quotes%ROWTYPE;
BEGIN
  SELECT * INTO quoted FROM sales_quotes WHERE id=NEW.quote_id;
  IF quoted.collection_intention_confirmed AND NOT (
      (quoted.collection_mode IN ('FULL','PARTIAL') AND NEW.collection_mode=quoted.collection_mode)
      OR (quoted.collection_mode='AUTOPAY' AND NEW.collection_mode='PARTIAL')) THEN
    RAISE EXCEPTION 'purchase collection mode must follow the confirmed immutable quote';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER sales_confirmed_purchase_mode BEFORE INSERT ON sales_purchase
  FOR EACH ROW EXECUTE FUNCTION sales_confirmed_purchase_mode();

CREATE FUNCTION sales_confirmed_autopay_mode() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE v_purchase_id uuid; quoted sales_quotes%ROWTYPE; has_agreement boolean;
BEGIN
  IF TG_TABLE_NAME='sales_purchase' THEN v_purchase_id := NEW.id;
  ELSE v_purchase_id := NEW.purchase_id; END IF;
  SELECT q.* INTO quoted FROM sales_quotes q JOIN sales_purchase p ON p.quote_id=q.id WHERE p.id=v_purchase_id;
  IF quoted.collection_intention_confirmed THEN
    SELECT EXISTS(SELECT 1 FROM sales_autopayagreement a WHERE a.purchase_id=v_purchase_id) INTO has_agreement;
    IF (quoted.collection_mode='AUTOPAY') IS DISTINCT FROM has_agreement THEN
      RAISE EXCEPTION 'autopay agreement must match the confirmed quote intention';
    END IF;
  END IF;
  RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER sales_confirmed_autopay_purchase AFTER INSERT ON sales_purchase
  DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION sales_confirmed_autopay_mode();
CREATE CONSTRAINT TRIGGER sales_confirmed_autopay_agreement AFTER INSERT ON sales_autopayagreement
  DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION sales_confirmed_autopay_mode();
"""

REVERSE = """
DROP TRIGGER sales_confirmed_autopay_agreement ON sales_autopayagreement;
DROP TRIGGER sales_confirmed_autopay_purchase ON sales_purchase;
DROP FUNCTION sales_confirmed_autopay_mode();
DROP TRIGGER sales_confirmed_purchase_mode ON sales_purchase;
DROP FUNCTION sales_confirmed_purchase_mode();
"""

class Migration(migrations.Migration):
    dependencies = [('sales', '0012_quote_collection_intention')]
    operations = [migrations.RunSQL(SQL, REVERSE)]
