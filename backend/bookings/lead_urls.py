from django.urls import path

from .lead_views import LeadBdesView, LeadDetailView, LeadOwnerView, LeadsView

app_name = 'leads'

urlpatterns = [
    path('', LeadsView.as_view(), name='list'),
    path('bdes/', LeadBdesView.as_view(), name='bdes'),
    path('<uuid:pk>/', LeadDetailView.as_view(), name='detail'),
    # Giving the lead to a BDE (bookings.ownership).
    path('<uuid:pk>/owner/', LeadOwnerView.as_view(), name='owner'),
]
