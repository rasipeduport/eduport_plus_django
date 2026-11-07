from django.urls import path

from .views import (
    BookingCommunicationView,
    BookingMessagePreviewView,
    CallOutcomeView,
    ConfirmationRequestView,
    ParentConfirmationView,
)
from .webhooks import WhatsAppWebhookView

app_name = 'communications'

urlpatterns = [
    # A booking's communication, for the Hub (communications.views); <booking_type> is demo or diagnostic.
    path('bookings/<str:booking_type>/<uuid:pk>/', BookingCommunicationView.as_view(), name='booking'),
    path('bookings/<str:booking_type>/<uuid:pk>/preview/', BookingMessagePreviewView.as_view(), name='booking-preview'),
    path('bookings/<str:booking_type>/<uuid:pk>/confirmation-request/', ConfirmationRequestView.as_view(),
         name='confirmation-request'),
    path('bookings/<str:booking_type>/<uuid:pk>/parent-confirmation/', ParentConfirmationView.as_view(),
         name='parent-confirmation'),
    path('bookings/<str:booking_type>/<uuid:pk>/call-outcome/', CallOutcomeView.as_view(), name='call-outcome'),
    # Meta's WhatsApp Cloud API callbacks: signed, never a session (communications.webhooks).
    path('webhooks/whatsapp/', WhatsAppWebhookView.as_view(), name='whatsapp-webhook'),
]
