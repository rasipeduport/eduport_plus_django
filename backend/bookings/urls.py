from django.urls import path

from .views import (
    BdeBookingCancelView,
    BdeBookingLinksView,
    BdeDashboardView,
    BdeDemoInviteView,
    BdeEnquiriesView,
    BdeEnquiryDetailView,
)

app_name = 'bookings'

urlpatterns = [
    path('booking-links/', BdeBookingLinksView.as_view(), name='bde-booking-links'),
    path('dashboard/', BdeDashboardView.as_view(), name='bde-dashboard'),
    path('enquiries/', BdeEnquiriesView.as_view(), name='bde-enquiries'),
    path('enquiries/<uuid:pk>/', BdeEnquiryDetailView.as_view(), name='bde-enquiry'),
    # Cancelling a booking of the caller's own lead (Q22); ownership checked in the view and the service.
    path('bookings/<str:booking_type>/<uuid:pk>/cancel/', BdeBookingCancelView.as_view(), name='bde-booking-cancel'),
    # A Demo invitation from a Diagnostic of the caller's own lead; ownership checked in the view and the service.
    path('bookings/<str:booking_type>/<uuid:pk>/demo-invite/', BdeDemoInviteView.as_view(), name='bde-demo-invite'),
    # The reports on the caller's own leads, and their PDFs, are reports.bde_urls (P9).
]
