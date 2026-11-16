from django.db import migrations


SQL = """
CREATE FUNCTION sales_purchase_checked() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE quoted sales_quotes%ROWTYPE;
BEGIN
  IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'purchase history cannot be deleted'; END IF;
  IF TG_OP = 'UPDATE' THEN
    IF OLD.student_id IS NOT NULL OR (to_jsonb(NEW) - 'student_id') IS DISTINCT FROM (to_jsonb(OLD) - 'student_id') THEN
      RAISE EXCEPTION 'purchase snapshot is immutable';
    END IF;
    RETURN NEW;
  END IF;
  SELECT * INTO quoted FROM sales_quotes WHERE id = NEW.quote_id;
  IF quoted.lead_id IS DISTINCT FROM (SELECT enquiry_id FROM sales_sale WHERE id = NEW.sale_id)
     OR quoted.currency <> 'AED' OR quoted.status <> 'ISSUED'
     OR NEW.amount <> round(quoted.payable_amount) OR NEW.classes <> quoted.classes
     OR (NEW.collection_mode = 'PARTIAL' AND quoted.single_payment_saving > 0) THEN
    RAISE EXCEPTION 'purchase must match its own enquiry quote and collection policy';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER sales_purchase_checked BEFORE INSERT OR UPDATE OR DELETE ON sales_purchase
  FOR EACH ROW EXECUTE FUNCTION sales_purchase_checked();

CREATE FUNCTION sales_payment_fixed() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'payment history cannot be deleted'; END IF;
  IF TG_OP = 'UPDATE' AND (OLD.status = 'SUCCEEDED' OR
      (to_jsonb(NEW) - ARRAY['status','verified_at','stripe_payment_intent','payment_date'])
      IS DISTINCT FROM (to_jsonb(OLD) - ARRAY['status','verified_at','stripe_payment_intent','payment_date'])) THEN
    RAISE EXCEPTION 'payment allocation and receipt are immutable';
  END IF;
  IF NEW.purchase_id IS NOT NULL AND NEW.sale_id IS DISTINCT FROM (SELECT sale_id FROM sales_purchase WHERE id=NEW.purchase_id) THEN
    RAISE EXCEPTION 'payment must belong to its own purchase';
  END IF;
  IF NEW.purpose = 'TOKEN' AND (SELECT kind FROM sales_sale WHERE id=NEW.sale_id) <> 'TOKEN' THEN
    RAISE EXCEPTION 'only a token sale can receive a token';
  END IF;
  IF NEW.status = 'SUCCEEDED' AND (NEW.verified_at IS NULL OR
     (NEW.method = 'STRIPE' AND NEW.stripe_payment_intent IS NULL) OR
     (NEW.method <> 'STRIPE' AND (NOT NEW.received_confirmed OR NEW.proof = ''))) THEN
    RAISE EXCEPTION 'successful payment requires verified provider evidence or a confirmed receipt';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER sales_payment_fixed BEFORE INSERT OR UPDATE OR DELETE ON sales_payment
  FOR EACH ROW EXECUTE FUNCTION sales_payment_fixed();

CREATE FUNCTION sales_payment_balances() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE bought sales_purchase%ROWTYPE; paid_classes numeric; paid_amount numeric;
BEGIN
  SELECT * INTO bought FROM sales_purchase WHERE id=NEW.purchase_id OR (NEW.purchase_id IS NULL AND sale_id=NEW.sale_id AND is_initial);
  IF bought.id IS NULL THEN RETURN NULL; END IF;
  SELECT coalesce(sum(classes),0) INTO paid_classes FROM sales_payment WHERE purchase_id=bought.id AND status='SUCCEEDED';
  SELECT coalesce(sum(amount),0) INTO paid_amount FROM sales_payment
    WHERE status='SUCCEEDED' AND (purchase_id=bought.id OR (bought.is_initial AND sale_id=NEW.sale_id AND purpose='TOKEN'));
  IF paid_classes > bought.classes OR paid_amount > bought.amount OR
     (paid_classes > 0 AND paid_amount <> round(bought.amount * paid_classes / bought.classes)) THEN
    RAISE EXCEPTION 'payment allocation exceeds or disagrees with the agreed purchase';
  END IF;
  RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER sales_payment_balances AFTER INSERT OR UPDATE ON sales_payment
  DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION sales_payment_balances();

CREATE FUNCTION sales_initial_sale_fixed() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'initial sale history cannot be deleted'; END IF;
  IF OLD.student_id IS NOT NULL OR (to_jsonb(NEW) - ARRAY['parent_email','student_id','enrolled_at'])
      IS DISTINCT FROM (to_jsonb(OLD) - ARRAY['parent_email','student_id','enrolled_at']) THEN
    RAISE EXCEPTION 'initial sale attribution is immutable';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER sales_initial_sale_fixed BEFORE UPDATE OR DELETE ON sales_sale
  FOR EACH ROW EXECUTE FUNCTION sales_initial_sale_fixed();
"""

REVERSE = """
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM sales_payment) OR EXISTS (SELECT 1 FROM sales_purchase) THEN
    RAISE EXCEPTION 'cannot remove the initial sales ledger while financial history exists';
  END IF;
END $$;
DROP TRIGGER sales_payment_balances ON sales_payment;
DROP FUNCTION sales_payment_balances();
DROP TRIGGER sales_payment_fixed ON sales_payment;
DROP FUNCTION sales_payment_fixed();
DROP TRIGGER sales_purchase_checked ON sales_purchase;
DROP FUNCTION sales_purchase_checked();
DROP TRIGGER sales_initial_sale_fixed ON sales_sale;
DROP FUNCTION sales_initial_sale_fixed();
"""


class Migration(migrations.Migration):
    dependencies = [('sales', '0008_salessequence_stripecustomer_stripeevent_and_more'), ('accounts', '0023_alter_hubpermission_options')]
    operations = [migrations.RunSQL(SQL, REVERSE)]
