from django.apps import AppConfig


class AccountsConfig(AppConfig):
    name = 'accounts'

    def ready(self):
        # Group-membership guard, group-permission audit, role-change clean-up.
        from . import signals
        signals.connect()
