from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('bookings', '0015_redemo_lifecycle')]

    operations = [
        migrations.AddField(
            model_name='lead', name='plan_changes_locked_at',
            field=models.DateTimeField(blank=True, editable=False, null=True),
        ),
        migrations.RunSQL(
            """
            CREATE FUNCTION bookings_plan_lock_permanent() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
              IF OLD.plan_changes_locked_at IS NOT NULL
                 AND NEW.plan_changes_locked_at IS DISTINCT FROM OLD.plan_changes_locked_at THEN
                RAISE EXCEPTION 'enquiry % is locked against plan changes', OLD.id;
              END IF;
              RETURN NEW;
            END;
            $$;
            CREATE TRIGGER bookings_plan_lock_permanent
              BEFORE UPDATE ON leads FOR EACH ROW EXECUTE FUNCTION bookings_plan_lock_permanent();
            """,
            """
            DROP TRIGGER bookings_plan_lock_permanent ON leads;
            DROP FUNCTION bookings_plan_lock_permanent();
            """,
        ),
    ]
