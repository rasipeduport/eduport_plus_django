# Normalise the legacy activity names onto the Hub's convention.
#
# The auth/provisioning paths predated the rest of the log and wrote SCREAMING
# names with their own entity types (LOGIN/LOGOUT/ONBOARDED/USER_UPDATE on
# USER/SESSION), while every other writer already used the Hub's lowercase
# `entity.verb` form on lowercase entity types. That left the table with two
# conventions and made `profile` rows unfilterable alongside `USER` ones.
#
# The log is append-only (see 0002), so the backfill has to drop that trigger,
# rewrite the rows, and put it straight back -- a deliberate, one-off exception
# rather than a loosening of the guard.
#
# Sign-in rows were keyed to the session key with a fixed "User Session" label;
# there is no way back to a session, so they are re-pointed at the actor, which
# is what the row was really about.

from django.db import migrations

RENAMES = (
    ('LOGIN', 'user.sign_in'),
    ('LOGOUT', 'user.sign_out'),
    ('ONBOARDED', 'user.onboarded'),
    ('USER_UPDATE', 'user.update_details'),
)

DROP_TRIGGER = "DROP TRIGGER IF EXISTS activity_log_no_mutate ON activity_log;"

RESTORE_TRIGGER = """
DROP TRIGGER IF EXISTS activity_log_no_mutate ON activity_log;
CREATE TRIGGER activity_log_no_mutate
  BEFORE UPDATE OR DELETE ON activity_log
  FOR EACH ROW EXECUTE FUNCTION activity_log_immutable();
"""


def _rewrite(apps, pairs, sign_in_actions, legacy_entities):
    """Apply action renames, then normalise entity_type and the sign-in rows."""
    ActivityLog = apps.get_model('activity', 'ActivityLog')
    for old, new in pairs:
        ActivityLog.objects.filter(action=old).update(action=new)
    ActivityLog.objects.filter(entity_type__in=legacy_entities).update(entity_type='profile')
    # Re-point sign-in rows from the (now meaningless) session key to the actor.
    for row in ActivityLog.objects.filter(action__in=sign_in_actions).iterator():
        if row.actor_id:
            row.entity_id = str(row.actor_id)
        row.entity_label = row.actor_name or row.actor_email or row.entity_label
        row.save(update_fields=['entity_id', 'entity_label'])


def forwards(apps, schema_editor):
    _rewrite(apps, RENAMES, ('user.sign_in', 'user.sign_out'), ('USER', 'SESSION'))


def backwards(apps, schema_editor):
    # Best effort: the original entity_type split and session keys are gone, so
    # only the action names are restored.
    ActivityLog = apps.get_model('activity', 'ActivityLog')
    for old, new in RENAMES:
        ActivityLog.objects.filter(action=new).update(action=old)


class Migration(migrations.Migration):

    dependencies = [
        ('activity', '0002_append_only_activity_log'),
    ]

    operations = [
        migrations.RunSQL(DROP_TRIGGER, migrations.RunSQL.noop),
        migrations.RunPython(forwards, backwards),
        migrations.RunSQL(RESTORE_TRIGGER, migrations.RunSQL.noop),
    ]
