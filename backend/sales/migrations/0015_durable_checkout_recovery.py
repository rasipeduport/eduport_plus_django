"""P1 request durability and classified Billing recovery; prepared, not applied."""
from importlib import import_module

import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


def prior_function(module, name):
    source = import_module(f'sales.migrations.{module}').SQL
    start = source.index(f'FUNCTION {name}()')
    end = source.index('END $$;', start) + len('END $$;')
    return 'CREATE OR REPLACE ' + source[start:end]


AGREEMENT_SQL = prior_function('0014_stripe_billing', 'sales_autopay_agreement_fixed').replace(
    "'billing_message','billing_request'", "'billing_message','billing_issue_scope','provisioning_generation','provisioning_key_started_at','provisioning_rejection_verified','billing_request'")
AGREEMENT_SQL = AGREEMENT_SQL.replace('  RETURN NEW;', """
  IF TG_OP='UPDATE' AND NEW.provisioning_generation IS DISTINCT FROM OLD.provisioning_generation AND (
    NEW.provisioning_generation<>OLD.provisioning_generation+1 OR OLD.billing_status<>'ERROR'
    OR OLD.billing_issue_scope NOT IN ('','PROVISIONING') OR NOT OLD.provisioning_rejection_verified
  ) THEN RAISE EXCEPTION 'only explicit recovery of a rejected provisioning operation can advance its key generation'; END IF;
  IF TG_OP='UPDATE' AND OLD.provisioning_key_started_at IS NOT NULL
    AND NEW.provisioning_key_started_at IS DISTINCT FROM OLD.provisioning_key_started_at
    AND NEW.provisioning_generation=OLD.provisioning_generation
    THEN RAISE EXCEPTION 'a provisioning idempotency window cannot be extended silently'; END IF;
  RETURN NEW;""")

SQL = AGREEMENT_SQL + """
CREATE FUNCTION sales_checkout_fixed() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Checkout request history cannot be deleted'; END IF;
  IF TG_OP='UPDATE' AND (
    (to_jsonb(NEW)-ARRAY['status','message','started_at','stripe_checkout_id','checkout_url']) IS DISTINCT FROM
    (to_jsonb(OLD)-ARRAY['status','message','started_at','stripe_checkout_id','checkout_url'])
    OR (OLD.started_at IS NOT NULL AND NEW.started_at IS DISTINCT FROM OLD.started_at)
    OR (OLD.stripe_checkout_id IS NOT NULL AND NEW.stripe_checkout_id IS DISTINCT FROM OLD.stripe_checkout_id)
    OR (OLD.checkout_url<>'' AND NEW.checkout_url IS DISTINCT FROM OLD.checkout_url)
    OR (OLD.status='BOUND' AND NEW.status<>'BOUND')
  ) THEN RAISE EXCEPTION 'Checkout origin and request parameters are immutable'; END IF;
  IF NEW.request->>'mode' IS DISTINCT FROM 'payment' OR NOT EXISTS(
    SELECT 1 FROM sales_payment p JOIN sales_sale s ON s.id=p.sale_id
      JOIN sales_stripecustomer c ON c.enquiry_id=s.enquiry_id
      WHERE p.id=NEW.payment_id AND p.method='STRIPE' AND p.collection_scope='INITIAL' AND c.livemode=NEW.livemode
      AND NOT EXISTS(SELECT 1 FROM sales_autopayinstallment i WHERE i.payment_id=p.id AND i.position>0)
  ) THEN RAISE EXCEPTION 'Checkout operations belong only to their initial payment and Customer environment'; END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER sales_checkout_fixed BEFORE INSERT OR UPDATE OR DELETE ON sales_stripecheckoutoperation
  FOR EACH ROW EXECUTE FUNCTION sales_checkout_fixed();

CREATE FUNCTION sales_customer_origin_fixed() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Customer identity history cannot be deleted'; END IF;
  IF (to_jsonb(NEW)-ARRAY['customer_id','creation_started_at','student_metadata_synced']) IS DISTINCT FROM
     (to_jsonb(OLD)-ARRAY['customer_id','creation_started_at','student_metadata_synced'])
     OR (OLD.customer_id IS NOT NULL AND NEW.customer_id IS DISTINCT FROM OLD.customer_id)
     OR (OLD.creation_started_at IS NOT NULL AND NEW.creation_started_at IS DISTINCT FROM OLD.creation_started_at)
    THEN RAISE EXCEPTION 'Customer identity and creation request are immutable'; END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER sales_customer_origin_fixed BEFORE UPDATE OR DELETE ON sales_stripecustomer
  FOR EACH ROW EXECUTE FUNCTION sales_customer_origin_fixed();

CREATE OR REPLACE FUNCTION sales_payment_fixed() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP='DELETE' THEN RAISE EXCEPTION 'payment history cannot be deleted'; END IF;
  IF TG_OP='UPDATE' THEN
    IF OLD.status='SUCCEEDED' OR
      (to_jsonb(NEW)-ARRAY['status','verified_at','stripe_payment_intent','payment_date','stripe_customer_id','stripe_checkout_id','payment_url']) IS DISTINCT FROM
      (to_jsonb(OLD)-ARRAY['status','verified_at','stripe_payment_intent','payment_date','stripe_customer_id','stripe_checkout_id','payment_url'])
      OR (OLD.stripe_customer_id<>'' AND NEW.stripe_customer_id IS DISTINCT FROM OLD.stripe_customer_id)
      OR (OLD.stripe_checkout_id IS NOT NULL AND NEW.stripe_checkout_id IS DISTINCT FROM OLD.stripe_checkout_id)
      OR (OLD.payment_url<>'' AND NEW.payment_url IS DISTINCT FROM OLD.payment_url)
    THEN RAISE EXCEPTION 'payment allocation, receipt and bound provider origin are immutable'; END IF;
    IF (NEW.stripe_customer_id IS DISTINCT FROM OLD.stripe_customer_id
        OR NEW.stripe_checkout_id IS DISTINCT FROM OLD.stripe_checkout_id
        OR NEW.payment_url IS DISTINCT FROM OLD.payment_url) AND NOT EXISTS(
      SELECT 1 FROM sales_stripecheckoutoperation o JOIN sales_sale s ON s.id=NEW.sale_id
        JOIN sales_stripecustomer c ON c.enquiry_id=s.enquiry_id
        WHERE o.payment_id=NEW.id AND NEW.method='STRIPE' AND NEW.collection_scope='INITIAL'
        AND c.customer_id=NEW.stripe_customer_id AND c.livemode=o.livemode
        AND (NEW.stripe_checkout_id IS NULL OR o.stripe_checkout_id=NEW.stripe_checkout_id)
        AND NEW.payment_url=o.checkout_url
    ) THEN RAISE EXCEPTION 'first provider binding must match the durable Checkout and Customer'; END IF;
  END IF;
  IF NEW.purchase_id IS NOT NULL AND NEW.sale_id IS DISTINCT FROM(SELECT sale_id FROM sales_purchase WHERE id=NEW.purchase_id)
    THEN RAISE EXCEPTION 'payment must belong to its own purchase'; END IF;
  IF NEW.purpose='TOKEN' AND (SELECT kind FROM sales_sale WHERE id=NEW.sale_id)<>'TOKEN'
    THEN RAISE EXCEPTION 'only a token sale can receive a token'; END IF;
  IF NEW.status='SUCCEEDED' AND (NEW.verified_at IS NULL OR
    (NEW.method='STRIPE' AND NEW.stripe_payment_intent IS NULL) OR
    (NEW.method<>'STRIPE' AND (NOT NEW.received_confirmed OR NEW.proof='')))
    THEN RAISE EXCEPTION 'successful payment requires verified provider evidence or a confirmed receipt'; END IF;
  RETURN NEW;
END $$;
"""

REVERSE = """
DO $$ BEGIN
  IF EXISTS(SELECT 1 FROM sales_stripecheckoutoperation) OR EXISTS(SELECT 1 FROM sales_stripecustomer WHERE customer_id IS NULL)
     OR EXISTS(SELECT 1 FROM sales_autopayagreement WHERE provisioning_generation>0) THEN
    RAISE EXCEPTION 'cannot remove durable Checkout origins while request history exists';
  END IF;
END $$;
DROP TRIGGER sales_checkout_fixed ON sales_stripecheckoutoperation;
DROP FUNCTION sales_checkout_fixed();
DROP TRIGGER sales_customer_origin_fixed ON sales_stripecustomer;
DROP FUNCTION sales_customer_origin_fixed();
""" + prior_function('0009_payment_integrity', 'sales_payment_fixed') + '\n' + prior_function('0014_stripe_billing', 'sales_autopay_agreement_fixed')


class Migration(migrations.Migration):
    dependencies = [('sales', '0014_stripe_billing')]
    operations = [
        migrations.AlterField('stripecustomer', 'customer_id', models.CharField(max_length=255, unique=True, null=True, blank=True)),
        migrations.AddField('stripecustomer', 'creation_request', models.JSONField(default=dict, blank=True)),
        migrations.AddField('stripecustomer', 'creation_started_at', models.DateTimeField(null=True, blank=True)),
        migrations.AddField('autopayagreement', 'billing_issue_scope', models.CharField(max_length=20, blank=True)),
        migrations.AddField('autopayagreement', 'provisioning_generation', models.PositiveIntegerField(default=0)),
        migrations.AddField('autopayagreement', 'provisioning_key_started_at', models.DateTimeField(null=True, blank=True)),
        migrations.AddField('autopayagreement', 'provisioning_rejection_verified', models.BooleanField(default=False)),
        migrations.CreateModel(name='StripeCheckoutOperation', fields=[
            ('id', models.UUIDField(primary_key=True, editable=False, serialize=False)),
            ('livemode', models.BooleanField()),
            ('idempotency_key', models.CharField(max_length=255, unique=True)),
            ('request', models.JSONField()),
            ('status', models.CharField(max_length=30, default='PREPARED')),
            ('message', models.CharField(max_length=255, blank=True)),
            ('started_at', models.DateTimeField(null=True, blank=True)),
            ('stripe_checkout_id', models.CharField(max_length=255, unique=True, null=True, blank=True)),
            ('checkout_url', models.URLField(max_length=2048, blank=True)),
            ('created_at', models.DateTimeField(default=django.utils.timezone.now, editable=False)),
            ('payment', models.ForeignKey(to='sales.payment', on_delete=django.db.models.deletion.PROTECT, related_name='checkout_operations')),
        ]),
        migrations.RunSQL(SQL, REVERSE),
    ]
