from django.urls import path

from .lead_views import LeadBdesView, LeadDetailView, LeadNotesView, LeadOwnerView, LeadStudentTimezoneView, LeadsView

app_name = 'leads'

urlpatterns = [
    path('', LeadsView.as_view(), name='list'),
    path('bdes/', LeadBdesView.as_view(), name='bdes'),
    path('<uuid:pk>/', LeadDetailView.as_view(), name='detail'),
    # Giving the lead to a BDE (bookings.ownership).
    path('<uuid:pk>/owner/', LeadOwnerView.as_view(), name='owner'),
    # Correcting the time zone the lead's student books from (bookings.student_timezones).
    path('<uuid:pk>/student-timezone/', LeadStudentTimezoneView.as_view(), name='student-timezone'),
    # Staff's notes on the lead, shared with its owner BDE and its tutors (bookings.notes).
    path('<uuid:pk>/notes/', LeadNotesView.as_view(), name='notes'),
]
