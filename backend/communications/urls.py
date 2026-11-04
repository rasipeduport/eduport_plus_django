from django.urls import path

from .webhooks import WhatsAppWebhookView

app_name = 'communications'

urlpatterns = [
    # Meta's WhatsApp Cloud API callbacks: signed, never a session (communications.webhooks).
    path('webhooks/whatsapp/', WhatsAppWebhookView.as_view(), name='whatsapp-webhook'),
]
