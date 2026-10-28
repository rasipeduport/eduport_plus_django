from django.urls import path

from .public_views import PublicBookingCalendarView, PublicBookingCreateView

app_name = 'public_bookings'

urlpatterns = [
    path('booking-calendar/<str:booking_type>/', PublicBookingCalendarView.as_view(), name='calendar'),
    path('bookings/<str:booking_type>/', PublicBookingCreateView.as_view(), name='create'),
]
