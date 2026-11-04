"""
Meta's WhatsApp Cloud API, the intended production provider -- for now only
its webhooks (Phase 2B, step 5): the subscription check Meta makes when the
callback URL is set up, the signature on every callback, and the delivery
statuses inside them. Sending through the Cloud API comes once Eduport Plus
has its own WhatsApp Business account; until then this provider is not one
COMMUNICATIONS_WHATSAPP_PROVIDER can choose (communications.providers), and
its send() refuses.

Meta signs each callback's raw body with the app secret, HMAC-SHA256, in
``X-Hub-Signature-256: sha256=<hex>`` (COMMUNICATIONS_META_APP_SECRET); the
subscription check echoes ``hub.challenge`` only when ``hub.verify_token`` is
ours (COMMUNICATIONS_META_VERIFY_TOKEN). With either unset, nothing is
accepted. Neither secret, nor anything a callback says about the parent, is
ever logged.

A callback's ``entry[].changes[]`` with ``field == "messages"`` carries
``value.statuses[]``: one per message status, with the message's WAMID
(``id``), ``status`` (sent, delivered, read, failed), a Unix ``timestamp``
and, for failed, ``errors[]`` with Meta's code, title and details. Anything
else in it -- incoming messages, other fields, other statuses -- is left for
later phases and skipped.
"""
import hashlib
import hmac
from datetime import datetime, timezone as dt_timezone

from django.conf import settings

from ..models import MessageStatus
from .base import ProviderNotConfigured, StatusUpdate, WhatsAppProvider

PROVIDER_NAME = 'meta'
SIGNATURE_HEADER = 'X-Hub-Signature-256'
SIGNATURE_PREFIX = 'sha256='
# The object every WhatsApp Business callback names.
WHATSAPP_OBJECT = 'whatsapp_business_account'
# Meta's status words, as ours.
STATUSES = {
    'sent': MessageStatus.SENT,
    'delivered': MessageStatus.DELIVERED,
    'read': MessageStatus.READ,
    'failed': MessageStatus.FAILED,
}
# Meta error codes that are about the moment, not the message: throttling,
# a service hiccup, Meta holding a message back for now. Every other code --
# no WhatsApp account, a template rejected, a parameter wrong -- will fail the
# same way again.
TEMPORARY_ERRORS = frozenset({
    '1',        # API unknown
    '2',        # API service temporarily unavailable
    '4',        # API too many calls
    '80007',    # rate limit issues
    '130429',   # rate limit hit
    '131000',   # something went wrong
    '131016',   # service unavailable
    '131048',   # spam rate limit hit
    '131049',   # Meta chose not to deliver, for now
    '131056',   # pair rate limit hit
    '133004',   # server temporarily unavailable
})
# The failure code of a failed status that came without one.
UNSPECIFIED_ERROR = 'META_FAILED'
ERROR_TEXT_LIMIT = 1000


class InvalidWebhook(ValueError):
    """A signed callback that is not what a WhatsApp callback looks like."""


def is_temporary_error(code):
    """Whether Meta error ``code`` is about the moment rather than the message."""
    return str(code) in TEMPORARY_ERRORS


def valid_signature(body, header, secret):
    """Whether ``header`` is Meta's HMAC-SHA256 of ``body`` with ``secret``, compared in constant time."""
    if not secret or not header or not header.startswith(SIGNATURE_PREFIX):
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected.encode(), header[len(SIGNATURE_PREFIX):].strip().lower().encode())


def subscription_challenge(params, token):
    """The ``hub.challenge`` to echo when ``params`` subscribe with our verify ``token``; else None."""
    given = params.get('hub.verify_token', '')
    if not token or params.get('hub.mode') != 'subscribe' or not hmac.compare_digest(given.encode(), token.encode()):
        return None
    return params.get('hub.challenge') or None


def status_updates(payload):
    """
    The StatusUpdates in a callback's parsed JSON ``payload``, and how many
    status entries were skipped as not ours to read. InvalidWebhook when the
    payload is not a WhatsApp callback's shape; one for another object is
    simply empty.
    """
    if not isinstance(payload, dict):
        raise InvalidWebhook('The callback is not a JSON object.')
    if payload.get('object') != WHATSAPP_OBJECT:
        return [], 0
    entries = payload.get('entry')
    if not isinstance(entries, list):
        raise InvalidWebhook('The callback has no entries.')
    updates, skipped = [], 0
    for entry in entries:
        changes = entry.get('changes') if isinstance(entry, dict) else None
        if not isinstance(changes, list):
            raise InvalidWebhook('An entry has no changes.')
        for change in changes:
            if not isinstance(change, dict) or change.get('field') != 'messages':
                continue
            value = change.get('value')
            statuses = value.get('statuses', []) if isinstance(value, dict) else None
            if not isinstance(statuses, list):
                raise InvalidWebhook('A change has no statuses list.')
            for item in statuses:
                update = _status_update(item)
                if update is None:
                    skipped += 1
                else:
                    updates.append(update)
    return updates, skipped


def _status_update(item):
    if not isinstance(item, dict):
        return None
    wamid, word = item.get('id'), item.get('status')
    if not isinstance(wamid, str) or not wamid or word not in STATUSES:
        return None
    timestamp = item.get('timestamp')
    occurred_at = _moment(timestamp)
    code, text, temporary = '', '', None
    if word == 'failed':
        errors = item.get('errors')
        error = errors[0] if isinstance(errors, list) and errors and isinstance(errors[0], dict) else {}
        code = str(error.get('code') or '') or UNSPECIFIED_ERROR
        details = (error.get('error_data') or {}).get('details') if isinstance(error.get('error_data'), dict) else None
        text = ' -- '.join(str(part) for part in (error.get('title'), details or error.get('message')) if part)
        temporary = is_temporary_error(code)
    return StatusUpdate(
        provider_message_id=wamid,
        status=STATUSES[word],
        provider_status=word,
        occurred_at=occurred_at,
        error_code=code,
        error_message=text[:ERROR_TEXT_LIMIT],
        error_temporary=temporary,
        # A repeated callback carries the same status of the same message at the same moment.
        event_key=f'{wamid}:{word}:{timestamp}:{code}',
    )


def _moment(timestamp):
    """A callback's Unix timestamp (seconds, as text or a number) as an aware datetime, or None."""
    try:
        return datetime.fromtimestamp(int(timestamp), tz=dt_timezone.utc)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


class MetaCloudProvider(WhatsAppProvider):
    """Meta's WhatsApp Cloud API: webhooks only for now; not selectable for sending."""
    name = PROVIDER_NAME
    statuses = frozenset({MessageStatus.QUEUED, MessageStatus.SENT, MessageStatus.DELIVERED,
                          MessageStatus.READ, MessageStatus.FAILED})

    def send(self, message, timeout):
        raise ProviderNotConfigured('Sending through the WhatsApp Cloud API is not built yet.')

    def verify_webhook(self, request):
        return valid_signature(request.body, request.headers.get(SIGNATURE_HEADER, ''),
                               settings.COMMUNICATIONS_META_APP_SECRET)

    def subscription_challenge(self, request):
        return subscription_challenge(request.GET, settings.COMMUNICATIONS_META_VERIFY_TOKEN)

    def parse_webhook(self, payload):
        return status_updates(payload)
