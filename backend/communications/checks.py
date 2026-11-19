"""
System checks on the WhatsApp settings. A misconfiguration is a warning --
printed by `check` in the entrypoint and by `migrate` -- and never stops the
backend, its worker or beat: WhatsApp is not what the rest of the backend
runs on. While it lasts, no WhatsApp message is sent: the safety gate holds
every one back as MISCONFIGURED, and the dispatcher logs why on each run
(communications.safety, communications.tasks).
"""
from django.core import checks

from .safety import blocks_sending, configuration_problems

HELD_BACK = 'No WhatsApp message is sent until this is fixed (held back as MISCONFIGURED); nothing else is affected.'
NOT_READ = 'The allow-list is not read while COMMUNICATIONS_ALLOW_ALL_RECIPIENTS is on, so nothing is held back for it.'


def check_whatsapp_settings(app_configs=None, **kwargs):
    return [
        checks.Warning(problem, hint=HELD_BACK if blocks_sending(check_id) else NOT_READ, id=check_id)
        for check_id, problem in configuration_problems()
    ]
