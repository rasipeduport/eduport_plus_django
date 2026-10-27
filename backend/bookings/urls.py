from django.urls import path

from .views import BdeBookingLinksView

app_name = 'bookings'

urlpatterns = [
    path('booking-links/', BdeBookingLinksView.as_view(), name='bde-booking-links'),
]
