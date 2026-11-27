"""
Tutor IDs for the tutors already here, and the rules that keep every Tutor ID
permanent (accounts.tutor_codes).

All in one transaction, in this order: the accounts table is locked against
writes, every tutor without an ID -- deactivated ones too -- gets one, oldest
account first (created_at, then id), the counter is set to the last one
issued, and only then do the checks and triggers arrive. No account can
become a tutor without an ID in between. Former tutors (another role now) are
left without one; they get one should they teach again.

The backfill only writes tutor_code, a column no foreign key uses, so the
ALTER TABLEs after it find no pending trigger events.

Reversing drops the checks and triggers and keeps the IDs; 0033's reverse
drops them. Once IDs have been shared, fix forward instead: re-applying gives
the same IDs only while the tutors are the same.
"""
from django.db import migrations, models

from accounts.tutor_codes import backfill_tutor_codes

GUARDS_SQL = """
CREATE FUNCTION profiles_tutor_code_fixed() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.tutor_code IS NOT NULL AND NEW.tutor_code IS DISTINCT FROM OLD.tutor_code THEN
    RAISE EXCEPTION 'a Tutor ID never changes once issued';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER profiles_tutor_code_fixed BEFORE UPDATE OF tutor_code ON profiles
  FOR EACH ROW EXECUTE FUNCTION profiles_tutor_code_fixed();

CREATE FUNCTION tutor_code_counter_fixed() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'the Tutor ID counter cannot be deleted'; END IF;
  IF NEW.name IS DISTINCT FROM OLD.name OR NEW.value < OLD.value THEN
    RAISE EXCEPTION 'the Tutor ID counter only goes up';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER tutor_code_counter_fixed BEFORE UPDATE OR DELETE ON tutor_code_counter
  FOR EACH ROW EXECUTE FUNCTION tutor_code_counter_fixed();
"""

REVERSE_GUARDS_SQL = """
DROP TRIGGER tutor_code_counter_fixed ON tutor_code_counter;
DROP FUNCTION tutor_code_counter_fixed();
DROP TRIGGER profiles_tutor_code_fixed ON profiles;
DROP FUNCTION profiles_tutor_code_fixed();
"""


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0033_user_tutor_code'),
    ]

    operations = [
        migrations.RunPython(backfill_tutor_codes, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='user',
            constraint=models.CheckConstraint(
                condition=models.Q(('tutor_code__isnull', True), ('tutor_code__regex', '^EPT[0-9]{4,}$'), _connector='OR'),
                name='profiles_tutor_code_format',
            ),
        ),
        migrations.AddConstraint(
            model_name='user',
            constraint=models.CheckConstraint(
                condition=models.Q(models.Q(('role', 'TUTOR'), _negated=True), ('tutor_code__isnull', False), _connector='OR'),
                name='profiles_tutors_have_code',
            ),
        ),
        migrations.RunSQL(GUARDS_SQL, REVERSE_GUARDS_SQL),
    ]
