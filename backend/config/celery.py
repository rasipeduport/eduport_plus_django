"""
Celery application for the EduPlus backend.

There is exactly one scheduled job (the enrolment-sheet quota sync), so this
is kept as small as Celery allows: settings come from Django under the
``CELERY_`` namespace, the schedule lives in ``settings.CELERY_BEAT_SCHEDULE``
(a static dict -- no django-celery-beat, no extra tables, no migrations), and
tasks are autodiscovered from each app's ``tasks.py``.

Run it with:
    celery -A config worker --loglevel=info
    celery -A config beat   --loglevel=info
"""
import os

from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

app = Celery('eduplus')

# Every CELERY_* Django setting becomes a Celery option, minus the prefix.
app.config_from_object('django.conf:settings', namespace='CELERY')

# Picks up students/tasks.py (and any future app's) without an explicit import.
app.autodiscover_tasks()
