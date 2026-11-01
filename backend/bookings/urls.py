from django.urls import path

from .views import BdeBookingCancelView, BdeBookingLinksView, BdeDashboardView, BdeEnquiriesView, BdeEnquiryDetailView

app_name = 'bookings'

urlpatterns = [
    path('booking-links/', BdeBookingLinksView.as_view(), name='bde-booking-links'),
    path('dashboard/', BdeDashboardView.as_view(), name='bde-dashboard'),
    path('enquiries/', BdeEnquiriesView.as_view(), name='bde-enquiries'),
    path('enquiries/<uuid:pk>/', BdeEnquiryDetailView.as_view(), name='bde-enquiry'),
    # Cancelling a booking of the caller's own lead (Q22); ownership checked in the view and the service.
    path('bookings/<str:booking_type>/<uuid:pk>/cancel/', BdeBookingCancelView.as_view(), name='bde-booking-cancel'),
]
