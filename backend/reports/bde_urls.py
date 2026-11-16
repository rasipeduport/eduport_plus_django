from django.urls import path

from .bde_views import BdeBookingReportPdfView, BdeBookingReportShareView, BdeLeadReportsView

app_name = 'bde_reports'

# Under /api/bde/, beside the BDE workspace (bookings.urls): <booking_type> is demo or diagnostic.
urlpatterns = [
    path('enquiries/<uuid:pk>/reports/', BdeLeadReportsView.as_view(), name='lead_reports'),
    path('bookings/<str:booking_type>/<uuid:pk>/report/pdf/', BdeBookingReportPdfView.as_view(), name='pdf'),
    path('bookings/<str:booking_type>/<uuid:pk>/report/share/', BdeBookingReportShareView.as_view(), name='share'),
]
