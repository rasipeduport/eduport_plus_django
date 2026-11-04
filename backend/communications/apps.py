from django.apps import AppConfig
from django.db.models.signals import post_migrate


def _ensure_prd_templates(sender, using='default', **kwargs):
    from .prd_templates import ensure_prd_templates

    ensure_prd_templates(using)


class CommunicationsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'communications'
    label = 'communications'
    verbose_name = 'Communications'

    def ready(self):
        # The PRD's templates exist wherever communications is migrated: after
        # every `migrate`, and after a test flushes the tables.
        post_migrate.connect(_ensure_prd_templates, sender=self, dispatch_uid='communications.prd_templates')
