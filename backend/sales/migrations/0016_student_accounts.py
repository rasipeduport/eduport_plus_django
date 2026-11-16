"""Student financial accounts, guardians, refunds, disputes and the Stripe review queue.

Prepared, not applied. The Customer mapping gains its own key and a student
account; its enquiry key is kept as ``legacy_enquiry``. Existing Customers,
payments, agreements and Stripe IDs are not rewritten (migration 0017 only links
them to backfilled accounts). Trigger functions that joined the Customer by
enquiry now join it by student account.
"""
import uuid
from importlib import import_module

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


def prior_function(module, name):
    source = import_module(f'sales.migrations.{module}').SQL
    start = source.index(f'FUNCTION {name}()')
    end = source.index('END $$;', start) + len('END $$;')
    return 'CREATE OR REPLACE ' + source[start:end]


def replaced(text, old, new):
    if old not in text:
        raise ValueError(f'Expected trigger text not found: {old}')
    return text.replace(old, new)


# Customer mapping: id becomes the key, the enquiry key is kept as legacy history.
RESTRUCTURE_CUSTOMER = """
ALTER TABLE sales_stripecustomer DISABLE TRIGGER sales_customer_origin_fixed;
ALTER TABLE sales_stripecustomer ADD COLUMN id uuid NULL;
UPDATE sales_stripecustomer SET id = gen_random_uuid();
ALTER TABLE sales_stripecustomer ALTER COLUMN id SET NOT NULL;
ALTER TABLE sales_stripecustomer DROP CONSTRAINT sales_stripecustomer_pkey;
ALTER TABLE sales_stripecustomer ADD CONSTRAINT sales_stripecustomer_pkey PRIMARY KEY (id);
ALTER TABLE sales_stripecustomer RENAME COLUMN enquiry_id TO legacy_enquiry_id;
ALTER TABLE sales_stripecustomer ALTER COLUMN legacy_enquiry_id DROP NOT NULL;
ALTER TABLE sales_stripecustomer ADD CONSTRAINT sales_stripecustomer_legacy_enquiry_id_key UNIQUE (legacy_enquiry_id);
ALTER TABLE sales_stripecustomer ADD COLUMN account_id uuid NULL
  CONSTRAINT sales_stripecustomer_account_id_fk REFERENCES sales_studentaccount (id) DEFERRABLE INITIALLY DEFERRED;
CREATE INDEX sales_stripecustomer_account_id_idx ON sales_stripecustomer (account_id);
ALTER TABLE sales_stripecustomer ADD COLUMN stripe_account_id varchar(255) NOT NULL DEFAULT '';
ALTER TABLE sales_stripecustomer ALTER COLUMN stripe_account_id DROP DEFAULT;
ALTER TABLE sales_stripecustomer ADD COLUMN label_format varchar(20) NOT NULL DEFAULT 'LEGACY_PARENT';
ALTER TABLE sales_stripecustomer ALTER COLUMN label_format DROP DEFAULT;
ALTER TABLE sales_stripecustomer ENABLE TRIGGER sales_customer_origin_fixed;
"""

UNRESTRUCTURE_CUSTOMER = """
DO $$ BEGIN
  IF EXISTS(SELECT 1 FROM sales_stripecustomer WHERE legacy_enquiry_id IS NULL) THEN
    RAISE EXCEPTION 'student-account Customers exist; the enquiry-keyed mapping cannot be restored';
  END IF;
END $$;
ALTER TABLE sales_stripecustomer DROP COLUMN label_format;
ALTER TABLE sales_stripecustomer DROP COLUMN stripe_account_id;
ALTER TABLE sales_stripecustomer DROP COLUMN account_id;
ALTER TABLE sales_stripecustomer DROP CONSTRAINT sales_stripecustomer_legacy_enquiry_id_key;
ALTER TABLE sales_stripecustomer ALTER COLUMN legacy_enquiry_id SET NOT NULL;
ALTER TABLE sales_stripecustomer RENAME COLUMN legacy_enquiry_id TO enquiry_id;
ALTER TABLE sales_stripecustomer DROP CONSTRAINT sales_stripecustomer_pkey;
ALTER TABLE sales_stripecustomer ADD CONSTRAINT sales_stripecustomer_pkey PRIMARY KEY (enquiry_id);
ALTER TABLE sales_stripecustomer DROP COLUMN id;
"""

CUSTOMER_SQL = """
CREATE OR REPLACE FUNCTION sales_customer_origin_fixed() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Customer identity history cannot be deleted'; END IF;
  IF (to_jsonb(NEW)-ARRAY['customer_id','creation_started_at','student_metadata_synced','account_id','stripe_account_id']) IS DISTINCT FROM
     (to_jsonb(OLD)-ARRAY['customer_id','creation_started_at','student_metadata_synced','account_id','stripe_account_id'])
     OR (OLD.customer_id IS NOT NULL AND NEW.customer_id IS DISTINCT FROM OLD.customer_id)
     OR (OLD.creation_started_at IS NOT NULL AND NEW.creation_started_at IS DISTINCT FROM OLD.creation_started_at)
     OR (OLD.account_id IS NOT NULL AND NEW.account_id IS DISTINCT FROM OLD.account_id)
     OR (OLD.stripe_account_id<>'' AND NEW.stripe_account_id IS DISTINCT FROM OLD.stripe_account_id)
    THEN RAISE EXCEPTION 'Customer identity and creation request are immutable'; END IF;
  RETURN NEW;
END $$;
"""

PAYMENT_SQL = """
CREATE OR REPLACE FUNCTION sales_payment_fixed() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP='DELETE' THEN RAISE EXCEPTION 'payment history cannot be deleted'; END IF;
  IF TG_OP='UPDATE' THEN
    -- A received payment is final. Only its provider evidence (charge, payer and
    -- card snapshot) may be filled in once, if it was not known at verification.
    IF OLD.status='SUCCEEDED' AND (
      (to_jsonb(NEW)-ARRAY['stripe_charge_id','payer_details']) IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['stripe_charge_id','payer_details'])
      OR (OLD.stripe_charge_id<>'' AND NEW.stripe_charge_id IS DISTINCT FROM OLD.stripe_charge_id)
      OR (OLD.payer_details<>'{}'::jsonb AND NEW.payer_details IS DISTINCT FROM OLD.payer_details)
    ) THEN RAISE EXCEPTION 'payment allocation, receipt and bound provider origin are immutable'; END IF;
    IF OLD.status<>'SUCCEEDED' AND (
      (to_jsonb(NEW)-ARRAY['status','verified_at','stripe_payment_intent','payment_date','stripe_customer_id','stripe_checkout_id','payment_url','stripe_charge_id','payer_details','failure_code','failure_message']) IS DISTINCT FROM
      (to_jsonb(OLD)-ARRAY['status','verified_at','stripe_payment_intent','payment_date','stripe_customer_id','stripe_checkout_id','payment_url','stripe_charge_id','payer_details','failure_code','failure_message'])
      OR (OLD.stripe_customer_id<>'' AND NEW.stripe_customer_id IS DISTINCT FROM OLD.stripe_customer_id)
      OR (OLD.stripe_checkout_id IS NOT NULL AND NEW.stripe_checkout_id IS DISTINCT FROM OLD.stripe_checkout_id)
      OR (OLD.payment_url<>'' AND NEW.payment_url IS DISTINCT FROM OLD.payment_url)
      OR (OLD.stripe_charge_id<>'' AND NEW.stripe_charge_id IS DISTINCT FROM OLD.stripe_charge_id)
    ) THEN RAISE EXCEPTION 'payment allocation, receipt and bound provider origin are immutable'; END IF;
    IF (NEW.stripe_customer_id IS DISTINCT FROM OLD.stripe_customer_id
        OR NEW.stripe_checkout_id IS DISTINCT FROM OLD.stripe_checkout_id
        OR NEW.payment_url IS DISTINCT FROM OLD.payment_url) AND NOT EXISTS(
      SELECT 1 FROM sales_stripecheckoutoperation o JOIN sales_sale s ON s.id=NEW.sale_id
        JOIN sales_stripecustomer c ON c.account_id=s.account_id
        WHERE o.payment_id=NEW.id AND NEW.method='STRIPE' AND NEW.collection_scope='INITIAL'
        AND c.customer_id=NEW.stripe_customer_id AND c.livemode=o.livemode
        AND (NEW.stripe_checkout_id IS NULL OR o.stripe_checkout_id=NEW.stripe_checkout_id)
        AND NEW.payment_url=o.checkout_url
    ) THEN RAISE EXCEPTION 'first provider binding must match the durable Checkout and the student account Customer'; END IF;
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

SALE_SQL = """
CREATE OR REPLACE FUNCTION sales_initial_sale_fixed() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'initial sale history cannot be deleted'; END IF;
  IF (to_jsonb(NEW) - ARRAY['parent_email','student_id','enrolled_at','account_id'])
      IS DISTINCT FROM (to_jsonb(OLD) - ARRAY['parent_email','student_id','enrolled_at','account_id'])
     OR (OLD.student_id IS NOT NULL AND (NEW.student_id IS DISTINCT FROM OLD.student_id
         OR NEW.enrolled_at IS DISTINCT FROM OLD.enrolled_at OR NEW.parent_email IS DISTINCT FROM OLD.parent_email))
     OR (OLD.account_id IS NOT NULL AND NEW.account_id IS DISTINCT FROM OLD.account_id) THEN
    RAISE EXCEPTION 'initial sale attribution is immutable';
  END IF;
  IF NEW.account_id IS NOT NULL AND NEW.student_id IS NOT NULL
     AND NEW.student_id IS DISTINCT FROM (SELECT student_id FROM sales_studentaccount WHERE id=NEW.account_id) THEN
    RAISE EXCEPTION 'a sale''s student must be its student account''s student';
  END IF;
  RETURN NEW;
END $$;
"""

IDENTITY_SQL = """
CREATE FUNCTION sales_student_account_fixed() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP='DELETE' THEN RAISE EXCEPTION 'student account history cannot be deleted'; END IF;
  IF NEW.reference IS DISTINCT FROM OLD.reference OR NEW.created_at IS DISTINCT FROM OLD.created_at
     OR NEW.created_by_id IS DISTINCT FROM OLD.created_by_id
     OR (OLD.origin_lead_id IS NOT NULL AND NEW.origin_lead_id IS DISTINCT FROM OLD.origin_lead_id)
     OR (OLD.student_id IS NOT NULL AND NEW.student_id IS DISTINCT FROM OLD.student_id)
     OR (OLD.identity_locked_at IS NOT NULL AND NEW.identity_locked_at IS DISTINCT FROM OLD.identity_locked_at) THEN
    RAISE EXCEPTION 'student account reference, origin, enrolled student and identity lock are immutable';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER sales_student_account_fixed BEFORE UPDATE OR DELETE ON sales_studentaccount
  FOR EACH ROW EXECUTE FUNCTION sales_student_account_fixed();

CREATE FUNCTION sales_student_guardian_fixed() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP='DELETE' THEN RAISE EXCEPTION 'guardian links are history: end a link instead of deleting it'; END IF;
  IF NEW.account_id IS DISTINCT FROM OLD.account_id OR NEW.guardian_id IS DISTINCT FROM OLD.guardian_id
     OR NEW.basis IS DISTINCT FROM OLD.basis OR NEW.linked_at IS DISTINCT FROM OLD.linked_at
     OR NEW.linked_by_id IS DISTINCT FROM OLD.linked_by_id OR (OLD.ended_at IS NOT NULL AND NEW IS DISTINCT FROM OLD) THEN
    RAISE EXCEPTION 'guardian links are history: end a link instead of changing it';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER sales_student_guardian_fixed BEFORE UPDATE OR DELETE ON sales_studentguardian
  FOR EACH ROW EXECUTE FUNCTION sales_student_guardian_fixed();

CREATE FUNCTION sales_identity_correction_fixed() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'identity corrections are an append-only audit trail';
END $$;
CREATE TRIGGER sales_identity_correction_fixed BEFORE UPDATE OR DELETE ON sales_studentidentitycorrection
  FOR EACH ROW EXECUTE FUNCTION sales_identity_correction_fixed();

CREATE FUNCTION sales_provider_case_fixed() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP='DELETE' THEN RAISE EXCEPTION 'refund and dispute history cannot be deleted'; END IF;
  IF TG_OP='UPDATE' AND (NEW.payment_id IS DISTINCT FROM OLD.payment_id OR NEW.amount IS DISTINCT FROM OLD.amount
     OR NEW.currency IS DISTINCT FROM OLD.currency OR NEW.stripe_created_at IS DISTINCT FROM OLD.stripe_created_at
     OR NEW.stripe_charge_id IS DISTINCT FROM OLD.stripe_charge_id
     OR NEW.stripe_payment_intent_id IS DISTINCT FROM OLD.stripe_payment_intent_id) THEN
    RAISE EXCEPTION 'refund and dispute origin is immutable';
  END IF;
  IF NOT EXISTS(SELECT 1 FROM sales_payment p WHERE p.id=NEW.payment_id AND p.method='STRIPE' AND p.status='SUCCEEDED') THEN
    RAISE EXCEPTION 'refunds and disputes belong only to received Stripe payments';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER sales_refund_fixed BEFORE INSERT OR UPDATE OR DELETE ON sales_refund
  FOR EACH ROW EXECUTE FUNCTION sales_provider_case_fixed();
CREATE TRIGGER sales_dispute_fixed BEFORE INSERT OR UPDATE OR DELETE ON sales_dispute
  FOR EACH ROW EXECUTE FUNCTION sales_provider_case_fixed();

CREATE FUNCTION sales_review_fixed() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Stripe review history cannot be deleted'; END IF;
  IF OLD.status<>'OPEN'
     OR (to_jsonb(NEW)-ARRAY['status','account_id','resolution_note','resolved_by_id','resolved_at'])
        IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['status','account_id','resolution_note','resolved_by_id','resolved_at']) THEN
    RAISE EXCEPTION 'a review item is resolved once and its Stripe evidence is immutable';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER sales_review_fixed BEFORE UPDATE OR DELETE ON sales_stripereviewitem
  FOR EACH ROW EXECUTE FUNCTION sales_review_fixed();
"""

DROP_IDENTITY_SQL = """
DROP TRIGGER sales_review_fixed ON sales_stripereviewitem;
DROP FUNCTION sales_review_fixed();
DROP TRIGGER sales_dispute_fixed ON sales_dispute;
DROP TRIGGER sales_refund_fixed ON sales_refund;
DROP FUNCTION sales_provider_case_fixed();
DROP TRIGGER sales_identity_correction_fixed ON sales_studentidentitycorrection;
DROP FUNCTION sales_identity_correction_fixed();
DROP TRIGGER sales_student_guardian_fixed ON sales_studentguardian;
DROP FUNCTION sales_student_guardian_fixed();
DROP TRIGGER sales_student_account_fixed ON sales_studentaccount;
DROP FUNCTION sales_student_account_fixed();
"""


CHECKOUT_SQL = replaced(prior_function('0015_durable_checkout_recovery', 'sales_checkout_fixed'),
                        'JOIN sales_stripecustomer c ON c.enquiry_id=s.enquiry_id', 'JOIN sales_stripecustomer c ON c.account_id=s.account_id')
AGREEMENT_SQL = prior_function('0015_durable_checkout_recovery', 'sales_autopay_agreement_fixed')
AGREEMENT_SQL = replaced(AGREEMENT_SQL, "'provisioning_rejection_verified','billing_request'",
                         "'provisioning_rejection_verified','billing_request','cancelled_at','cancelled_by_id','cancellation_reason','cancellation_source'")
AGREEMENT_SQL = replaced(AGREEMENT_SQL, "  ) THEN RAISE EXCEPTION 'agreed autopay terms and provider origin are immutable'",
                         "    OR (OLD.cancelled_at IS NOT NULL AND (NEW.cancelled_at, NEW.cancelled_by_id, NEW.cancellation_reason, NEW.cancellation_source)\n"
                         "        IS DISTINCT FROM (OLD.cancelled_at, OLD.cancelled_by_id, OLD.cancellation_reason, OLD.cancellation_source))\n"
                         "  ) THEN RAISE EXCEPTION 'agreed autopay terms and provider origin are immutable'")
AGREEMENT_SQL = replaced(AGREEMENT_SQL, 'JOIN sales_sale s ON s.enquiry_id=c.enquiry_id', 'JOIN sales_sale s ON s.account_id=c.account_id')

SQL = CUSTOMER_SQL + PAYMENT_SQL + SALE_SQL + CHECKOUT_SQL + '\n' + AGREEMENT_SQL + '\n' + IDENTITY_SQL
REVERSE_SQL = (DROP_IDENTITY_SQL
               + prior_function('0015_durable_checkout_recovery', 'sales_customer_origin_fixed') + '\n'
               + prior_function('0015_durable_checkout_recovery', 'sales_payment_fixed') + '\n'
               + prior_function('0009_payment_integrity', 'sales_initial_sale_fixed') + '\n'
               + prior_function('0015_durable_checkout_recovery', 'sales_checkout_fixed') + '\n'
               + prior_function('0015_durable_checkout_recovery', 'sales_autopay_agreement_fixed'))

UUID_PK = dict(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)
USER = settings.AUTH_USER_MODEL
PROTECT = django.db.models.deletion.PROTECT
REVIEW_KINDS = [
    ('INCONSISTENT', 'Rejected: does not match its Django record'), ('PAYMENT_LINK_PAYMENT', 'Payment through a Stripe Payment Link'),
    ('PAYMENT_LINK_CREATED', 'Stripe Payment Link created or changed'), ('UNMATCHED_CHECKOUT', 'Checkout payment not created by Django'),
    ('UNMATCHED_INVOICE', 'Invoice paid outside a Django agreement'), ('UNMATCHED_SUBSCRIPTION', 'Subscription not created by Django'),
    ('UNMATCHED_PAYMENT', 'Payment not created by Django'), ('UNMATCHED_REFUND', 'Refund of an unknown payment'),
    ('UNMATCHED_DISPUTE', 'Dispute of an unknown payment'),
]


class Migration(migrations.Migration):
    dependencies = [
        ('bookings', '0016_lead_plan_change_lock'),
        ('sales', '0015_durable_checkout_recovery'),
        ('students', '0005_student_quota_source_alter_student_total_class_quota'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(name='Guardian', fields=[
            ('id', models.UUIDField(**UUID_PK)),
            ('full_name', models.CharField(max_length=255)),
            ('email', models.EmailField(blank=True, max_length=254)),
            ('phone', models.CharField(blank=True, max_length=20)),
            ('created_at', models.DateTimeField(default=django.utils.timezone.now, editable=False)),
            ('updated_at', models.DateTimeField(auto_now=True)),
            ('created_by', models.ForeignKey(blank=True, null=True, on_delete=PROTECT, related_name='created_guardians', to=USER)),
        ]),
        migrations.CreateModel(name='StudentAccount', fields=[
            ('id', models.UUIDField(**UUID_PK)),
            ('reference', models.CharField(editable=False, max_length=20, unique=True)),
            ('student_name', models.CharField(max_length=255)),
            ('identity_locked_at', models.DateTimeField(blank=True, null=True)),
            ('created_at', models.DateTimeField(default=django.utils.timezone.now, editable=False)),
            ('created_by', models.ForeignKey(blank=True, null=True, on_delete=PROTECT, related_name='created_student_accounts', to=USER)),
            ('origin_lead', models.OneToOneField(blank=True, null=True, on_delete=PROTECT, related_name='student_account', to='bookings.lead')),
            ('student', models.OneToOneField(blank=True, null=True, on_delete=PROTECT, related_name='account', to='students.student')),
        ], options={'ordering': ['reference'], 'constraints': [
            models.CheckConstraint(condition=models.Q(('reference__regex', '^SA-[0-9]{6,}$')), name='sales_account_reference_format')]}),
        migrations.CreateModel(name='StudentGuardian', fields=[
            ('id', models.UUIDField(**UUID_PK)),
            ('relationship', models.CharField(choices=[('PARENT', 'Parent'), ('MOTHER', 'Mother'), ('FATHER', 'Father'), ('GUARDIAN', 'Guardian'), ('OTHER', 'Other')], default='PARENT', max_length=10)),
            ('is_billing_contact', models.BooleanField(default=False)),
            ('basis', models.CharField(choices=[('NEW_FAMILY', 'New family'), ('EXISTING_FAMILY', 'Confirmed existing family'), ('BACKFILL', 'Migrated from the enquiry'), ('CORRECTION', 'Correction')], max_length=20)),
            ('linked_at', models.DateTimeField(default=django.utils.timezone.now)),
            ('ended_at', models.DateTimeField(blank=True, null=True)),
            ('account', models.ForeignKey(on_delete=PROTECT, related_name='guardian_links', to='sales.studentaccount')),
            ('ended_by', models.ForeignKey(blank=True, null=True, on_delete=PROTECT, related_name='+', to=USER)),
            ('guardian', models.ForeignKey(on_delete=PROTECT, related_name='student_links', to='sales.guardian')),
            ('linked_by', models.ForeignKey(blank=True, null=True, on_delete=PROTECT, related_name='+', to=USER)),
        ], options={'constraints': [
            models.UniqueConstraint(condition=models.Q(('ended_at__isnull', True)), fields=('account', 'guardian'), name='sales_guardian_link_once'),
            models.UniqueConstraint(condition=models.Q(('ended_at__isnull', True), ('is_billing_contact', True)), fields=('account',), name='sales_one_billing_contact')]}),
        migrations.CreateModel(name='StudentIdentityCorrection', fields=[
            ('id', models.UUIDField(**UUID_PK)),
            ('changes', models.JSONField()),
            ('reason', models.TextField()),
            ('created_at', models.DateTimeField(default=django.utils.timezone.now, editable=False)),
            ('account', models.ForeignKey(on_delete=PROTECT, related_name='identity_corrections', to='sales.studentaccount')),
            ('corrected_by', models.ForeignKey(on_delete=PROTECT, related_name='+', to=USER)),
        ], options={'ordering': ['created_at'], 'constraints': [
            models.CheckConstraint(condition=models.Q(('reason', ''), _negated=True), name='sales_identity_correction_reason')]}),
        migrations.AddField('sale', 'account', models.ForeignKey(null=True, on_delete=PROTECT, related_name='sales', to='sales.studentaccount')),
        migrations.AddField('payment', 'stripe_charge_id', models.CharField(blank=True, max_length=255)),
        migrations.AddField('payment', 'failure_code', models.CharField(blank=True, max_length=100)),
        migrations.AddField('payment', 'failure_message', models.CharField(blank=True, max_length=255)),
        migrations.AddField('payment', 'payer_details', models.JSONField(blank=True, default=dict)),
        migrations.AddField('autopayagreement', 'cancelled_at', models.DateTimeField(blank=True, null=True)),
        migrations.AddField('autopayagreement', 'cancelled_by', models.ForeignKey(blank=True, null=True, on_delete=PROTECT, related_name='+', to=USER)),
        migrations.AddField('autopayagreement', 'cancellation_reason', models.TextField(blank=True)),
        migrations.AddField('autopayagreement', 'cancellation_source', models.CharField(blank=True, choices=[('ADMIN', 'Administrator'), ('PARENT_REQUEST', 'Parent request'), ('STRIPE', 'Stopped in Stripe')], max_length=20)),
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunSQL(RESTRUCTURE_CUSTOMER, UNRESTRUCTURE_CUSTOMER)],
            state_operations=[
                migrations.RemoveField('stripecustomer', 'enquiry'),
                migrations.AddField('stripecustomer', 'id', models.UUIDField(**UUID_PK)),
                migrations.AddField('stripecustomer', 'legacy_enquiry', models.OneToOneField(blank=True, null=True, on_delete=PROTECT, related_name='legacy_stripe_customer', to='bookings.lead')),
                migrations.AddField('stripecustomer', 'account', models.ForeignKey(null=True, on_delete=PROTECT, related_name='stripe_customers', to='sales.studentaccount')),
                migrations.AddField('stripecustomer', 'stripe_account_id', models.CharField(blank=True, max_length=255)),
                migrations.AddField('stripecustomer', 'label_format', models.CharField(choices=[('STUDENT', 'Student name, parent contact'), ('LEGACY_PARENT', 'Legacy enquiry Customer (parent name)')], default='STUDENT', max_length=20)),
            ],
        ),
        migrations.AddConstraint('stripecustomer', models.UniqueConstraint(fields=('account', 'livemode', 'stripe_account_id'), name='sales_one_customer_per_account_env')),
        migrations.CreateModel(name='Refund', fields=[
            ('id', models.UUIDField(**UUID_PK)),
            ('stripe_refund_id', models.CharField(max_length=255, unique=True)),
            ('stripe_charge_id', models.CharField(blank=True, max_length=255)),
            ('stripe_payment_intent_id', models.CharField(blank=True, max_length=255)),
            ('amount', models.DecimalField(decimal_places=3, max_digits=15)),
            ('currency', models.CharField(max_length=3)),
            ('status', models.CharField(max_length=30)),
            ('reason', models.CharField(blank=True, max_length=100)),
            ('failure_reason', models.CharField(blank=True, max_length=100)),
            ('stripe_created_at', models.DateTimeField()),
            ('classes_effect', models.CharField(default='NONE', max_length=10)),
            ('recorded_at', models.DateTimeField(default=django.utils.timezone.now, editable=False)),
            ('updated_at', models.DateTimeField(auto_now=True)),
            ('payment', models.ForeignKey(on_delete=PROTECT, related_name='refunds', to='sales.payment')),
        ], options={'ordering': ['stripe_created_at', 'id'], 'constraints': [
            models.CheckConstraint(condition=models.Q(('amount__gt', 0)), name='sales_refund_positive'),
            models.CheckConstraint(condition=models.Q(('classes_effect', 'NONE')), name='sales_refund_no_class_effect')]}),
        migrations.CreateModel(name='Dispute', fields=[
            ('id', models.UUIDField(**UUID_PK)),
            ('stripe_dispute_id', models.CharField(max_length=255, unique=True)),
            ('stripe_charge_id', models.CharField(blank=True, max_length=255)),
            ('stripe_payment_intent_id', models.CharField(blank=True, max_length=255)),
            ('amount', models.DecimalField(decimal_places=3, max_digits=15)),
            ('currency', models.CharField(max_length=3)),
            ('status', models.CharField(max_length=40)),
            ('reason', models.CharField(blank=True, max_length=100)),
            ('evidence_due_by', models.DateTimeField(blank=True, null=True)),
            ('stripe_created_at', models.DateTimeField()),
            ('closed_at', models.DateTimeField(blank=True, null=True)),
            ('recorded_at', models.DateTimeField(default=django.utils.timezone.now, editable=False)),
            ('updated_at', models.DateTimeField(auto_now=True)),
            ('payment', models.ForeignKey(on_delete=PROTECT, related_name='disputes', to='sales.payment')),
        ], options={'ordering': ['stripe_created_at', 'id']}),
        migrations.CreateModel(name='StripeReviewItem', fields=[
            ('id', models.UUIDField(**UUID_PK)),
            ('source', models.CharField(choices=[('WEBHOOK', 'Webhook'), ('RECONCILIATION', 'Reconciliation')], default='WEBHOOK', max_length=20)),
            ('kind', models.CharField(choices=REVIEW_KINDS, max_length=30)),
            ('object_type', models.CharField(blank=True, max_length=60)),
            ('object_id', models.CharField(blank=True, max_length=255)),
            ('customer_id', models.CharField(blank=True, max_length=255)),
            ('payment_link_id', models.CharField(blank=True, max_length=255)),
            ('amount', models.DecimalField(blank=True, decimal_places=3, max_digits=15, null=True)),
            ('currency', models.CharField(blank=True, max_length=3)),
            ('livemode', models.BooleanField(default=False)),
            ('summary', models.CharField(blank=True, max_length=255)),
            ('status', models.CharField(choices=[('OPEN', 'Open'), ('LINKED', 'Linked to a student'), ('DISMISSED', 'Dismissed')], default='OPEN', max_length=10)),
            ('resolution_note', models.TextField(blank=True)),
            ('resolved_at', models.DateTimeField(blank=True, null=True)),
            ('created_at', models.DateTimeField(default=django.utils.timezone.now, editable=False)),
            ('account', models.ForeignKey(blank=True, null=True, on_delete=PROTECT, related_name='review_items', to='sales.studentaccount')),
            ('event', models.OneToOneField(blank=True, null=True, on_delete=PROTECT, related_name='review', to='sales.stripeevent')),
            ('resolved_by', models.ForeignKey(blank=True, null=True, on_delete=PROTECT, related_name='+', to=USER)),
        ], options={'ordering': ['-created_at'], 'constraints': [
            models.UniqueConstraint(condition=models.Q(('object_id', ''), _negated=True), fields=('kind', 'object_id'), name='sales_review_once_per_object'),
            models.CheckConstraint(condition=models.Q(models.Q(('resolved_at__isnull', True), ('status', 'OPEN')), models.Q(('resolved_at__isnull', False), ('status__in', ['LINKED', 'DISMISSED'])), _connector='OR'), name='sales_review_resolution_fields'),
            models.CheckConstraint(condition=models.Q(models.Q(('status', 'LINKED'), _negated=True), ('account__isnull', False), _connector='OR'), name='sales_review_linked_account')]}),
        migrations.RunSQL(SQL, REVERSE_SQL),
    ]
