from django.db import migrations


SQL = """
CREATE FUNCTION sales_autopay_agreement_fixed() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'autopay agreement history cannot be deleted'; END IF;
  IF TG_OP = 'UPDATE' AND (
    (to_jsonb(NEW) - ARRAY['status','setup_status','setup_message','stripe_customer_id','stripe_payment_method_id','card_brand','card_last4','initial_paid_at','consent_verified_at','ready_at'])
      IS DISTINCT FROM
    (to_jsonb(OLD) - ARRAY['status','setup_status','setup_message','stripe_customer_id','stripe_payment_method_id','card_brand','card_last4','initial_paid_at','consent_verified_at','ready_at'])
    OR (OLD.stripe_customer_id <> '' AND NEW.stripe_customer_id IS DISTINCT FROM OLD.stripe_customer_id)
    OR (OLD.initial_paid_at IS NOT NULL AND NEW.initial_paid_at IS DISTINCT FROM OLD.initial_paid_at)
    OR (OLD.consent_verified_at IS NOT NULL AND NEW.consent_verified_at IS DISTINCT FROM OLD.consent_verified_at)
  ) THEN RAISE EXCEPTION 'agreed autopay terms are immutable'; END IF;
  IF NEW.stripe_customer_id <> '' AND NOT EXISTS (
    SELECT 1 FROM sales_stripecustomer c JOIN sales_sale s ON s.enquiry_id=c.enquiry_id
      JOIN sales_purchase p ON p.sale_id=s.id WHERE p.id=NEW.purchase_id
      AND c.customer_id=NEW.stripe_customer_id AND c.livemode=NEW.livemode
  ) THEN RAISE EXCEPTION 'autopay customer and environment must match its purchase'; END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER sales_autopay_agreement_fixed BEFORE INSERT OR UPDATE OR DELETE ON sales_autopayagreement
  FOR EACH ROW EXECUTE FUNCTION sales_autopay_agreement_fixed();

CREATE FUNCTION sales_autopay_installment_fixed() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'autopay installment history cannot be deleted'; END IF;
  IF TG_OP = 'UPDATE' AND (
    (to_jsonb(NEW) - ARRAY['payment_id','status','paid_at']) IS DISTINCT FROM (to_jsonb(OLD) - ARRAY['payment_id','status','paid_at'])
    OR (OLD.payment_id IS NOT NULL AND NEW.payment_id IS DISTINCT FROM OLD.payment_id)
    OR (OLD.status='PAID' AND NEW IS DISTINCT FROM OLD)
  ) THEN RAISE EXCEPTION 'agreed installment allocation is immutable'; END IF;
  IF NEW.payment_id IS NOT NULL AND NOT EXISTS (
    SELECT 1 FROM sales_payment p JOIN sales_autopayagreement a ON a.purchase_id=p.purchase_id
      WHERE a.id=NEW.agreement_id AND p.id=NEW.payment_id AND p.amount=NEW.amount AND p.classes=NEW.classes
      AND p.currency='AED' AND p.method='STRIPE' AND p.purpose='TUITION'
  ) THEN RAISE EXCEPTION 'installment payment must match its frozen allocation'; END IF;
  IF NEW.status='PAID' AND NOT EXISTS (SELECT 1 FROM sales_payment p WHERE p.id=NEW.payment_id AND p.status='SUCCEEDED')
    THEN RAISE EXCEPTION 'only a verified received payment can settle an installment'; END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER sales_autopay_installment_fixed BEFORE INSERT OR UPDATE OR DELETE ON sales_autopayinstallment
  FOR EACH ROW EXECUTE FUNCTION sales_autopay_installment_fixed();

CREATE FUNCTION sales_autopay_schedule_balanced() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE bought sales_purchase%ROWTYPE; allocated_classes numeric; allocated_amount numeric; row_count integer; last_position integer;
BEGIN
  SELECT p.* INTO bought FROM sales_purchase p JOIN sales_autopayagreement a ON a.purchase_id=p.id WHERE a.id=NEW.agreement_id;
  SELECT sum(classes),sum(amount),count(*),max(position) INTO allocated_classes,allocated_amount,row_count,last_position
    FROM sales_autopayinstallment WHERE agreement_id=NEW.agreement_id;
  IF bought.collection_mode<>'PARTIAL' OR allocated_classes<>bought.classes OR allocated_amount<>bought.amount
     OR last_position<>row_count-1 OR row_count<2 OR NOT EXISTS(SELECT 1 FROM sales_autopayinstallment WHERE agreement_id=NEW.agreement_id AND position=0)
    THEN RAISE EXCEPTION 'autopay schedule must exactly reconcile its whole AED purchase'; END IF;
  IF EXISTS (
    SELECT 1 FROM (
      SELECT i.*,sum(classes) OVER(ORDER BY position) cumulative,lag(due_at) OVER(ORDER BY position) previous_due
      FROM sales_autopayinstallment i WHERE agreement_id=NEW.agreement_id
    ) terms JOIN sales_autopayagreement a ON a.id=terms.agreement_id
    WHERE mod(terms.classes,0.5)<>0 OR terms.amount<>round(bought.amount*terms.cumulative/bought.classes)-round(bought.amount*(terms.cumulative-terms.classes)/bought.classes)
      OR (terms.position>0 AND (terms.due_at<=a.created_at OR terms.due_at<=terms.previous_due))
  ) THEN RAISE EXCEPTION 'autopay schedule dates and proportional allocations must match the agreed snapshot'; END IF;
  RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER sales_autopay_schedule_balanced AFTER INSERT OR UPDATE ON sales_autopayinstallment
  DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION sales_autopay_schedule_balanced();

CREATE FUNCTION sales_autopay_attempt_fixed() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'autopay collection attempt history cannot be deleted'; END IF;
  IF TG_OP = 'UPDATE' AND (
    (to_jsonb(NEW) - ARRAY['status','stripe_payment_intent_id','stripe_checkout_id','checkout_url','error_code','updated_at'])
      IS DISTINCT FROM
    (to_jsonb(OLD) - ARRAY['status','stripe_payment_intent_id','stripe_checkout_id','checkout_url','error_code','updated_at'])
    OR (OLD.stripe_payment_intent_id<>'' AND NEW.stripe_payment_intent_id IS DISTINCT FROM OLD.stripe_payment_intent_id)
    OR (OLD.stripe_checkout_id IS NOT NULL AND NEW.stripe_checkout_id IS DISTINCT FROM OLD.stripe_checkout_id)
    OR (OLD.checkout_url<>'' AND NEW.checkout_url IS DISTINCT FROM OLD.checkout_url)
    OR OLD.status='SUCCEEDED'
  ) THEN RAISE EXCEPTION 'collection attempt origin and provider references are immutable'; END IF;
  IF NEW.number<1 THEN RAISE EXCEPTION 'attempt numbers start at one'; END IF;
  IF NEW.stripe_payment_intent_id<>'' AND EXISTS (
    SELECT 1 FROM sales_autopayattempt a WHERE a.stripe_payment_intent_id=NEW.stripe_payment_intent_id AND a.installment_id<>NEW.installment_id
  ) THEN RAISE EXCEPTION 'a payment intent cannot belong to different installments'; END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER sales_autopay_attempt_fixed BEFORE INSERT OR UPDATE OR DELETE ON sales_autopayattempt
  FOR EACH ROW EXECUTE FUNCTION sales_autopay_attempt_fixed();
"""

REVERSE = """
DO $$ BEGIN
  IF EXISTS(SELECT 1 FROM sales_autopayagreement) THEN RAISE EXCEPTION 'cannot remove autopay safeguards while agreements exist'; END IF;
END $$;
DROP TRIGGER sales_autopay_attempt_fixed ON sales_autopayattempt;
DROP FUNCTION sales_autopay_attempt_fixed();
DROP TRIGGER sales_autopay_schedule_balanced ON sales_autopayinstallment;
DROP FUNCTION sales_autopay_schedule_balanced();
DROP TRIGGER sales_autopay_installment_fixed ON sales_autopayinstallment;
DROP FUNCTION sales_autopay_installment_fixed();
DROP TRIGGER sales_autopay_agreement_fixed ON sales_autopayagreement;
DROP FUNCTION sales_autopay_agreement_fixed();
"""


class Migration(migrations.Migration):
    dependencies = [('sales', '0010_autopay_agreements')]
    operations = [migrations.RunSQL(SQL, REVERSE)]
