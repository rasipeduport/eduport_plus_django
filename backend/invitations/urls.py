from django.urls import path
from .views import LookupStudentView, CreateInvitationView, InvitationCredentialsView, IssueStudentCredentialsView

app_name = 'invitations'

urlpatterns = [
    path('<uuid:pk>/credentials/', InvitationCredentialsView.as_view(), name='credentials'),
    path('students/<uuid:pk>/issue/', IssueStudentCredentialsView.as_view(), name='issue-student'),
    path('lookup-student/', LookupStudentView.as_view(), name='lookup-student'),
    path('create-student-invitation/', CreateInvitationView.as_view(), name='create-student-invitation'),
    path('', CreateInvitationView.as_view(), name='create-invitation'),
]
