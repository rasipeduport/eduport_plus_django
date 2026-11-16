"""
The WhatsApp webhook (Phase 2B, step 5): /api/communications/webhooks/whatsapp/,
the callback URL Meta's WhatsApp Cloud API calls (communications.providers.meta).

    GET   Meta's subscription check: hub.challenge echoed back as plain text
          when hub.verify_token is ours; 403 otherwise.
    POST  Delivery statuses: refused with 403 unless X-Hub-Signature-256 is
          the app secret's signature of the exact body; 400 for a signed body
          that is not a WhatsApp callback; otherwise each status applied
          (communications.status_updates) and 200.

No session or login is read (no authentication classes, so no CSRF check
either): Meta's servers carry none. IsMetaCallback is the guard -- the verify
token, or the signature. With the verify token or the app secret unset, every
request is refused. Nothing a callback says about the parent, nor either
secret, is logged -- an unknown message id by its last characters only. A
failure while applying answers 500, so Meta delivers the callback again;
statuses already applied are recognised then and skipped. A status for a
message id not recorded yet is kept until it is (communications.status_updates).
"""
import json
import logging
from collections import Counter

from django.http import HttpResponse, JsonResponse
from rest_framework.permissions import BasePermission
from rest_framework.views import APIView

from .providers.meta import InvalidWebhook, MetaCloudProvider
from .status_updates import StatusResult, apply_status_update

logger = logging.getLogger(__name__)


class IsMetaCallback(BasePermission):
    """
    The guard of the webhook: a subscription check with our verify token
    (GET), or a callback signed with our app secret (POST). Any other method
    is let through to be answered 405.
    """

    def has_permission(self, request, view):
        provider = MetaCloudProvider()
        if request.method == 'GET':
            if provider.subscription_challenge(request) is not None:
                return True
            logger.warning('WhatsApp webhook: a subscription check was refused.')
            self.message = {'error': 'VERIFICATION_FAILED', 'message': 'The subscription could not be verified.'}
            return False
        if request.method == 'POST':
            if provider.verify_webhook(request):
                return True
            logger.warning('WhatsApp webhook: a callback without a valid signature was refused.')
            self.message = {'error': 'INVALID_SIGNATURE', 'message': 'The callback signature is missing or does not match.'}
            return False
        return True


class WhatsAppWebhookView(APIView):
    authentication_classes = []
    permission_classes = [IsMetaCallback]

    def get(self, request, *args, **kwargs):
        return HttpResponse(MetaCloudProvider().subscription_challenge(request), content_type='text/plain')

    def post(self, request, *args, **kwargs):
        provider = MetaCloudProvider()
        try:
            updates, skipped = provider.parse_webhook(json.loads(request.body))
        except (ValueError, InvalidWebhook):
            logger.warning('WhatsApp webhook: a signed callback that is not a WhatsApp callback was refused.')
            return JsonResponse({'error': 'INVALID_PAYLOAD', 'message': 'The callback is not a WhatsApp callback.'},
                                status=400)
        results = Counter()
        for update in updates:
            result = apply_status_update(provider.name, update)
            results[result] += 1
            if result == StatusResult.STORED:
                logger.info('WhatsApp webhook: a %s status for a message not known yet (...%s), kept for it.',
                            update.provider_status, update.provider_message_id[-8:])
        if results or skipped:
            logger.info('WhatsApp webhook: %s', {**{str(key): value for key, value in results.items()}, 'skipped': skipped})
        return JsonResponse({'received': len(updates)})
