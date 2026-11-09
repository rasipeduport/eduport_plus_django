import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('sales', '0005_quote_integrity'), ('bookings', '0016_lead_plan_change_lock')]

    operations = [
        migrations.AddField(
            model_name='quote', name='supersedes',
            field=models.OneToOneField(
                blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                related_name='replacement', to='sales.quote',
            ),
        ),
        migrations.AddIndex(
            model_name='quote',
            index=models.Index(fields=['lead', '-number'], name='sales_quotes_lead_idx'),
        ),
        migrations.RunSQL(
            """
            CREATE FUNCTION sales_quote_selection_checked() RETURNS trigger LANGUAGE plpgsql AS $$
            DECLARE
              locked_at timestamptz;
              previous sales_quotes%ROWTYPE;
            BEGIN
              IF NEW.lead_id IS NULL THEN
                IF NEW.supersedes_id IS NOT NULL THEN
                  RAISE EXCEPTION 'a replacement quote must name an enquiry';
                END IF;
                RETURN NEW;
              END IF;
              -- Serialize all plan changes and the future payment lock on the enquiry.
              SELECT plan_changes_locked_at INTO locked_at FROM leads WHERE id = NEW.lead_id FOR UPDATE;
              IF locked_at IS NOT NULL THEN
                RAISE EXCEPTION 'enquiry % is locked against plan changes', NEW.lead_id;
              END IF;
              SELECT * INTO previous FROM sales_quotes WHERE lead_id = NEW.lead_id ORDER BY number DESC LIMIT 1;
              IF NEW.supersedes_id IS DISTINCT FROM previous.id THEN
                RAISE EXCEPTION 'a quote must replace the latest quote for its own enquiry';
              END IF;
              IF previous.id IS NOT NULL AND NEW.number <= previous.number THEN
                RAISE EXCEPTION 'a replacement quote must have a later reference number';
              END IF;
              RETURN NEW;
            END;
            $$;
            CREATE TRIGGER sales_quote_selection_checked
              BEFORE INSERT ON sales_quotes FOR EACH ROW EXECUTE FUNCTION sales_quote_selection_checked();
            """,
            """
            DROP TRIGGER sales_quote_selection_checked ON sales_quotes;
            DROP FUNCTION sales_quote_selection_checked();
            """,
        ),
    ]
