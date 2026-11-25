from django.urls import path

from .views import (
    BookingCommunicationView,
    BookingMessagePreviewView,
    ConfirmationRequestSentView,
    ConfirmationRequestView,
    ParentConfirmationView,
)
from .webhooks import WhatsAppWebhookView

app_name = 'communications'

urlpatterns = [
    # A booking's communication, for the Hub (communications.views); <booking_type> is demo or diagnostic.
    path('bookings/<str:booking_type>/<uuid:pk>/', BookingCommunicationView.as_view(), name='booking'),
    path('bookings/<str:booking_type>/<uuid:pk>/preview/', BookingMessagePreviewView.as_view(), name='booking-preview'),
    # Retired (410): the Hub opens the BDE's own WhatsApp instead, and they mark it sent.
    path('bookings/<str:booking_type>/<uuid:pk>/confirmation-request/', ConfirmationRequestView.as_view(),
         name='confirmation-request'),
    path('bookings/<str:booking_type>/<uuid:pk>/confirmation-request/mark-sent/',
         ConfirmationRequestSentView.as_view(), name='confirmation-request-sent'),
    path('bookings/<str:booking_type>/<uuid:pk>/parent-confirmation/', ParentConfirmationView.as_view(),
         name='parent-confirmation'),
    # Meta's WhatsApp Cloud API callbacks: signed, never a session (communications.webhooks).
    path('webhooks/whatsapp/', WhatsAppWebhookView.as_view(), name='whatsapp-webhook'),
]
