from django.urls import path

from .views import BookingSlotsView

app_name = 'booking_slots'

urlpatterns = [
    path('<str:booking_type>/<str:date>/', BookingSlotsView.as_view(), name='day'),
]
