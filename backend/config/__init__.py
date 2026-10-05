# Importing the Celery app here is what makes `@shared_task` bind to it, so
# every task definition reaches the same application no matter what imports it
# first (Django, a worker, or `manage.py sync_student_quotas`).
from .celery import app as celery_app

__all__ = ('celery_app',)
