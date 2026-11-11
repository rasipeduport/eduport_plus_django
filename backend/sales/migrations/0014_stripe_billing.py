"""Native Billing mappings and frozen allocation guards. Prepared, not applied.

Existing agreements retain LEGACY_PI; switching engines is an explicit operation.
No provider calls, data rewrite, or automatic agreement migration occurs here.
"""
from importlib import import_module

from django.db import migrations, models


SQL = """
CREATE OR REPLACE FUNCTION sales_autopay_agreement_fixed() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'autopay agreement history cannot be deleted'; END IF;
  IF TG_OP = 'UPDATE' AND (
    (to_jsonb(NEW) - ARRAY['status','setup_status','setup_message','stripe_customer_id','stripe_payment_method_id','card_brand','card_last4','initial_paid_at','consent_verified_at','ready_at',
      'collection_engine','stripe_subscription_id','stripe_schedule_id','stripe_product_id','stripe_subscription_status','stripe_schedule_status','billing_status','billing_message','billing_request','provisioning_started_at'])
    IS DISTINCT FROM
    (to_jsonb(OLD) - ARRAY['status','setup_status','setup_message','stripe_customer_id','stripe_payment_method_id','card_brand','card_last4','initial_paid_at','consent_verified_at','ready_at',
      'collection_engine','stripe_subscription_id','stripe_schedule_id','stripe_product_id','stripe_subscription_status','stripe_schedule_status','billing_status','billing_message','billing_request','provisioning_started_at'])
    OR (OLD.stripe_customer_id<>'' AND NEW.stripe_customer_id IS DISTINCT FROM OLD.stripe_customer_id)
    OR (OLD.initial_paid_at IS NOT NULL AND NEW.initial_paid_at IS DISTINCT FROM OLD.initial_paid_at)
    OR (OLD.consent_verified_at IS NOT NULL AND NEW.consent_verified_at IS DISTINCT FROM OLD.consent_verified_at)
    OR (OLD.stripe_subscription_id IS NOT NULL AND NEW.stripe_subscription_id IS DISTINCT FROM OLD.stripe_subscription_id)
    OR (OLD.stripe_schedule_id IS NOT NULL AND NEW.stripe_schedule_id IS DISTINCT FROM OLD.stripe_schedule_id)
    OR (OLD.stripe_product_id<>'' AND NEW.stripe_product_id IS DISTINCT FROM OLD.stripe_product_id)
    OR (OLD.billing_request<>'{}'::jsonb AND NEW.billing_request IS DISTINCT FROM OLD.billing_request)
    OR (OLD.provisioning_started_at IS NOT NULL AND NEW.provisioning_started_at IS DISTINCT FROM OLD.provisioning_started_at)
  ) THEN RAISE EXCEPTION 'agreed autopay terms and provider origin are immutable'; END IF;
  IF TG_OP='UPDATE' AND NEW.collection_engine IS DISTINCT FROM OLD.collection_engine AND (
    OLD.collection_engine<>'LEGACY_PI' OR NEW.collection_engine<>'STRIPE_BILLING'
    OR OLD.initial_paid_at IS NULL OR OLD.setup_status<>'READY'
    OR EXISTS(SELECT 1 FROM sales_autopayinstallment i WHERE i.agreement_id=NEW.id AND i.position>0 AND i.status<>'PAID'
      AND (i.payment_id IS NOT NULL OR EXISTS(SELECT 1 FROM sales_autopayattempt t WHERE t.installment_id=i.id)))
  ) THEN RAISE EXCEPTION 'only a verified legacy agreement without in-flight collections can move to Billing'; END IF;
  IF NEW.collection_engine NOT IN ('LEGACY_PI','STRIPE_BILLING') THEN RAISE EXCEPTION 'unknown collection engine'; END IF;
  IF NEW.stripe_customer_id<>'' AND NOT EXISTS (
    SELECT 1 FROM sales_stripecustomer c JOIN sales_sale s ON s.enquiry_id=c.enquiry_id
      JOIN sales_purchase p ON p.sale_id=s.id WHERE p.id=NEW.purchase_id
      AND c.customer_id=NEW.stripe_customer_id AND c.livemode=NEW.livemode
  ) THEN RAISE EXCEPTION 'autopay customer and environment must match its purchase'; END IF;
  RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION sales_autopay_installment_fixed() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP='DELETE' THEN RAISE EXCEPTION 'autopay installment history cannot be deleted'; END IF;
  IF TG_OP='UPDATE' AND (
    (to_jsonb(NEW) - ARRAY['payment_id','status','paid_at','stripe_invoice_id','stripe_invoice_status','stripe_invoice_number','stripe_invoice_url','stripe_next_payment_attempt'])
      IS DISTINCT FROM
    (to_jsonb(OLD) - ARRAY['payment_id','status','paid_at','stripe_invoice_id','stripe_invoice_status','stripe_invoice_number','stripe_invoice_url','stripe_next_payment_attempt'])
    OR (OLD.payment_id IS NOT NULL AND NEW.payment_id IS DISTINCT FROM OLD.payment_id)
    OR (OLD.stripe_invoice_id IS NOT NULL AND NEW.stripe_invoice_id IS DISTINCT FROM OLD.stripe_invoice_id)
    OR (OLD.status='PAID' AND NEW IS DISTINCT FROM OLD)
  ) THEN RAISE EXCEPTION 'agreed installment allocation and settled history are immutable'; END IF;
  IF NEW.payment_id IS NOT NULL AND NOT EXISTS (
    SELECT 1 FROM sales_payment p JOIN sales_autopayagreement a ON a.purchase_id=p.purchase_id
      WHERE a.id=NEW.agreement_id AND p.id=NEW.payment_id AND p.amount=NEW.amount AND p.classes=NEW.classes
      AND p.currency='AED' AND p.method='STRIPE' AND p.purpose='TUITION'
  ) THEN RAISE EXCEPTION 'installment payment must match its frozen allocation'; END IF;
  IF NEW.stripe_invoice_id IS NOT NULL AND (NEW.position=0 OR NOT EXISTS(
    SELECT 1 FROM sales_autopayagreement a WHERE a.id=NEW.agreement_id AND a.collection_engine='STRIPE_BILLING'
  )) THEN RAISE EXCEPTION 'recurring invoices belong only to native Billing installments'; END IF;
  IF NEW.status='PAID' AND NOT EXISTS(SELECT 1 FROM sales_payment p WHERE p.id=NEW.payment_id AND p.status='SUCCEEDED')
    THEN RAISE EXCEPTION 'only a verified received payment can settle an installment'; END IF;
  RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION sales_autopay_attempt_fixed() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP='DELETE' THEN RAISE EXCEPTION 'autopay collection attempt history cannot be deleted'; END IF;
  IF TG_OP='UPDATE' AND (
    (to_jsonb(NEW) - ARRAY['status','stripe_payment_intent_id','stripe_checkout_id','checkout_url','error_code','updated_at','provider_attempt_key','stripe_invoice_payment_id','stripe_charge_id'])
      IS DISTINCT FROM
    (to_jsonb(OLD) - ARRAY['status','stripe_payment_intent_id','stripe_checkout_id','checkout_url','error_code','updated_at','provider_attempt_key','stripe_invoice_payment_id','stripe_charge_id'])
    OR (OLD.stripe_payment_intent_id<>'' AND NEW.stripe_payment_intent_id IS DISTINCT FROM OLD.stripe_payment_intent_id)
    OR (OLD.stripe_checkout_id IS NOT NULL AND NEW.stripe_checkout_id IS DISTINCT FROM OLD.stripe_checkout_id)
    OR (OLD.checkout_url<>'' AND NEW.checkout_url IS DISTINCT FROM OLD.checkout_url)
    OR (OLD.provider_attempt_key IS NOT NULL AND NEW.provider_attempt_key IS DISTINCT FROM OLD.provider_attempt_key)
    OR (OLD.stripe_invoice_payment_id<>'' AND NEW.stripe_invoice_payment_id IS DISTINCT FROM OLD.stripe_invoice_payment_id)
    OR (OLD.stripe_charge_id<>'' AND NEW.stripe_charge_id IS DISTINCT FROM OLD.stripe_charge_id)
    OR OLD.status='SUCCEEDED'
  ) THEN RAISE EXCEPTION 'collection attempt origin and provider references are immutable'; END IF;
  IF NEW.number<1 THEN RAISE EXCEPTION 'attempt numbers start at one'; END IF;
  IF NEW.stripe_payment_intent_id<>'' AND EXISTS(
    SELECT 1 FROM sales_autopayattempt a WHERE a.stripe_payment_intent_id=NEW.stripe_payment_intent_id AND a.installment_id<>NEW.installment_id
  ) THEN RAISE EXCEPTION 'a payment intent cannot belong to different installments'; END IF;
  RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION sales_payment_balances() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE bought sales_purchase%ROWTYPE; paid_classes numeric; paid_amount numeric; native boolean;
BEGIN
  SELECT * INTO bought FROM sales_purchase WHERE id=NEW.purchase_id OR (NEW.purchase_id IS NULL AND sale_id=NEW.sale_id AND is_initial);
  IF bought.id IS NULL THEN RETURN NULL; END IF;
  SELECT coalesce(sum(classes),0) INTO paid_classes FROM sales_payment WHERE purchase_id=bought.id AND status='SUCCEEDED';
  SELECT coalesce(sum(amount),0) INTO paid_amount FROM sales_payment
    WHERE status='SUCCEEDED' AND (purchase_id=bought.id OR (bought.is_initial AND sale_id=NEW.sale_id AND purpose='TOKEN'));
  SELECT EXISTS(SELECT 1 FROM sales_autopayagreement a WHERE a.purchase_id=bought.id AND a.collection_engine='STRIPE_BILLING') INTO native;
  IF paid_classes>bought.classes OR paid_amount>bought.amount THEN
    RAISE EXCEPTION 'payment allocation exceeds the agreed purchase';
  END IF;
  IF NEW.collection_scope='BILLING_INSTALLMENT' AND NOT EXISTS(
    SELECT 1 FROM sales_autopayinstallment i JOIN sales_autopayagreement a ON a.id=i.agreement_id
      JOIN sales_payment p ON p.id=i.payment_id
      WHERE i.payment_id=NEW.id AND a.collection_engine='STRIPE_BILLING' AND i.position>0
      AND i.stripe_invoice_id IS NOT NULL AND a.purchase_id=bought.id
      AND p.method='STRIPE' AND p.currency='AED' AND p.purpose='TUITION'
      AND p.classes=i.classes AND p.amount=i.amount AND p.stripe_customer_id=a.stripe_customer_id
  ) THEN RAISE EXCEPTION 'native invoice payment must match its own frozen installment'; END IF;
  IF native THEN
    -- Independent invoices may settle out of order. Their ORIGINAL cumulative
    -- rounding differences belong to those installments, never to payment order.
    IF EXISTS(
      SELECT 1 FROM sales_payment p WHERE p.purchase_id=bought.id AND p.status='SUCCEEDED' AND NOT EXISTS(
        SELECT 1 FROM sales_autopayinstallment i JOIN sales_autopayagreement a ON a.id=i.agreement_id
          WHERE i.payment_id=p.id AND a.purchase_id=bought.id AND p.amount=i.amount AND p.classes=i.classes
      )
    ) OR (paid_classes=bought.classes AND paid_amount<>bought.amount) THEN
      RAISE EXCEPTION 'successful Billing allocations must reconcile the frozen installment schedule';
    END IF;
  ELSIF paid_classes>0 AND paid_amount<>round(bought.amount*paid_classes/bought.classes) THEN
    RAISE EXCEPTION 'payment allocation disagrees with the agreed purchase';
  END IF;
  RETURN NULL;
END $$;
"""


def previous_function(module, name):
    # Restore the exact historical implementation on a permitted reversal.
    source = import_module(f'sales.migrations.{module}').SQL
    start = source.index(f'CREATE FUNCTION {name}()')
    end = source.index('END $$;', start) + len('END $$;')
    return source[start:end].replace('CREATE FUNCTION', 'CREATE OR REPLACE FUNCTION', 1)


REVERSE = """
DO $$ BEGIN
  IF EXISTS(SELECT 1 FROM sales_autopayagreement WHERE collection_engine='STRIPE_BILLING')
     OR EXISTS(SELECT 1 FROM sales_payment WHERE collection_scope='BILLING_INSTALLMENT') THEN
    RAISE EXCEPTION 'cannot remove native Billing mappings while Billing history exists';
  END IF;
END $$;
""" + '\n'.join([
    previous_function('0011_autopay_integrity', 'sales_autopay_agreement_fixed'),
    previous_function('0011_autopay_integrity', 'sales_autopay_installment_fixed'),
    previous_function('0011_autopay_integrity', 'sales_autopay_attempt_fixed'),
    previous_function('0009_payment_integrity', 'sales_payment_balances'),
])


class Migration(migrations.Migration):
    dependencies = [('sales', '0013_quote_collection_integrity')]
    operations = [
        migrations.AddField('autopayagreement', 'collection_engine', models.CharField(max_length=20, default='LEGACY_PI', choices=[('LEGACY_PI', 'Historical PaymentIntents'), ('STRIPE_BILLING', 'Stripe Billing')])),
        migrations.AddField('autopayagreement', 'stripe_subscription_id', models.CharField(max_length=255, null=True, blank=True, unique=True)),
        migrations.AddField('autopayagreement', 'stripe_schedule_id', models.CharField(max_length=255, null=True, blank=True, unique=True)),
        migrations.AddField('autopayagreement', 'stripe_product_id', models.CharField(max_length=255, blank=True)),
        migrations.AddField('autopayagreement', 'stripe_subscription_status', models.CharField(max_length=30, blank=True)),
        migrations.AddField('autopayagreement', 'stripe_schedule_status', models.CharField(max_length=30, blank=True)),
        migrations.AddField('autopayagreement', 'billing_status', models.CharField(max_length=30, default='NOT_PROVISIONED')),
        migrations.AddField('autopayagreement', 'billing_message', models.CharField(max_length=255, blank=True)),
        migrations.AddField('autopayagreement', 'billing_request', models.JSONField(default=dict, blank=True)),
        migrations.AddField('autopayagreement', 'provisioning_started_at', models.DateTimeField(null=True, blank=True)),
        migrations.AddField('autopayinstallment', 'stripe_invoice_id', models.CharField(max_length=255, null=True, blank=True, unique=True)),
        migrations.AddField('autopayinstallment', 'stripe_invoice_status', models.CharField(max_length=30, blank=True)),
        migrations.AddField('autopayinstallment', 'stripe_invoice_number', models.CharField(max_length=255, blank=True)),
        migrations.AddField('autopayinstallment', 'stripe_invoice_url', models.URLField(max_length=2048, blank=True)),
        migrations.AddField('autopayinstallment', 'stripe_next_payment_attempt', models.DateTimeField(null=True, blank=True)),
        migrations.AddField('autopayattempt', 'provider_attempt_key', models.CharField(max_length=255, null=True, blank=True, unique=True)),
        migrations.AddField('autopayattempt', 'stripe_invoice_payment_id', models.CharField(max_length=255, blank=True)),
        migrations.AddField('autopayattempt', 'stripe_charge_id', models.CharField(max_length=255, blank=True)),
        migrations.AddField('payment', 'collection_scope', models.CharField(max_length=20, default='INITIAL', choices=[('INITIAL', 'Initial/legacy collection'), ('BILLING_INSTALLMENT', 'Stripe Billing installment')])),
        migrations.RemoveConstraint('payment', 'sales_one_pending_collection'),
        migrations.AddConstraint('payment', models.UniqueConstraint(fields=['sale'], condition=models.Q(status='PENDING', collection_scope='INITIAL'), name='sales_one_pending_initial')),
        migrations.AddConstraint('payment', models.CheckConstraint(condition=models.Q(collection_scope='INITIAL') | models.Q(collection_scope='BILLING_INSTALLMENT', purpose='TUITION', purchase__isnull=False), name='sales_payment_collection_scope')),
        migrations.RunSQL(SQL, REVERSE),
    ]
