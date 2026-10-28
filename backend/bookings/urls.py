from django.urls import path

from .views import BdeBookingLinksView, BdeDashboardView, BdeEnquiriesView, BdeEnquiryDetailView

app_name = 'bookings'

urlpatterns = [
    path('booking-links/', BdeBookingLinksView.as_view(), name='bde-booking-links'),
    path('dashboard/', BdeDashboardView.as_view(), name='bde-dashboard'),
    path('enquiries/', BdeEnquiriesView.as_view(), name='bde-enquiries'),
    path('enquiries/<uuid:pk>/', BdeEnquiryDetailView.as_view(), name='bde-enquiry'),
]
