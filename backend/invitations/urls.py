from django.urls import path
from .views import CreateInvitationView, InvitationCredentialsView, InvitationRegenerateView, InvitationResetPasswordView

app_name = 'invitations'

urlpatterns = [
    path('<uuid:pk>/credentials/', InvitationCredentialsView.as_view(), name='credentials'),
    path('<uuid:pk>/credentials/regenerate/', InvitationRegenerateView.as_view(), name='regenerate-credentials'),
    path('<uuid:pk>/credentials/reset/', InvitationResetPasswordView.as_view(), name='reset-password'),
    path('create-student-invitation/', CreateInvitationView.as_view(), name='create-student-invitation'),
    path('', CreateInvitationView.as_view(), name='create-invitation'),
]
