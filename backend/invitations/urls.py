from django.urls import path
from .views import CreateInvitationView, InvitationCredentialsView

app_name = 'invitations'

urlpatterns = [
    path('<uuid:pk>/credentials/', InvitationCredentialsView.as_view(), name='credentials'),
    path('create-student-invitation/', CreateInvitationView.as_view(), name='create-student-invitation'),
    path('', CreateInvitationView.as_view(), name='create-invitation'),
]
