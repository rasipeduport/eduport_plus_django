from django.urls import path

from .lead_views import AdmissionsDashboardView

app_name = 'admissions'

urlpatterns = [
    # The admissions pipeline at a glance, for administrators (bookings.admissions).
    path('dashboard/', AdmissionsDashboardView.as_view(), name='dashboard'),
]
