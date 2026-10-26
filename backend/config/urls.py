"""
URL configuration for eduplus project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from exams.views import ScorecardView, StudentScoresView
from students.views import StaffDashboardStatsView, StudentDashboardView
from accounts.views import (
    MentorListView,
    TutorListView,
    AdminListView,
    UserDetailView,
    StaffStatusView,
    StaffReassignView,
)

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/auth/', include('accounts.urls', namespace='accounts')),
    path('api/invitations/', include('invitations.urls', namespace='invitations')),
    path('api/dashboard/stats/', StaffDashboardStatsView.as_view(), name='staff-dashboard-stats'),
    path('api/student/dashboard/', StudentDashboardView.as_view(), name='student-dashboard'),
    path('api/mentors/', MentorListView.as_view(), name='mentor-list'),
    path('api/tutors/', TutorListView.as_view(), name='tutor-list'),
    path('api/admins/', AdminListView.as_view(), name='admin-list'),
    path('api/admins', AdminListView.as_view()),
    path('api/users/<uuid:pk>/', UserDetailView.as_view(), name='user-detail'),
    path('api/users/<uuid:pk>', UserDetailView.as_view()),
    path('api/users/<uuid:pk>/status/', StaffStatusView.as_view(), name='user-status'),
    path('api/users/<uuid:pk>/status', StaffStatusView.as_view()),
    path('api/users/<uuid:pk>/reassign/', StaffReassignView.as_view(), name='user-reassign'),
    path('api/users/<uuid:pk>/reassign', StaffReassignView.as_view()),
    # Team Management: staff accounts for administrators (accounts/team.py).
    path('api/team/', include('accounts.team_urls', namespace='team')),
    # Each app is included once, under its trailing-slash root. The slash-less
    # duplicates (`api/students`, ...) registered the same namespace twice
    # (urls.W005) and no SPA caller used them: every endpoint string in both
    # frontends ends with a slash, and APPEND_SLASH still redirects a stray GET.
    path('api/students/', include('students.urls', namespace='students')),
    path('api/sessions/', include('sessions.urls', namespace='sessions')),
    path('api/activity/', include('activity.urls', namespace='activity')),
    path('api/exams/', include('exams.urls', namespace='exams')),
    path('api/additional-exams/', include('exams.additional_urls', namespace='additional_exams')),
    path('api/homework/', include('homework.urls', namespace='homework')),
    path('api/student/scorecard/', ScorecardView.as_view(), name='student-scorecard'),
    path('api/student/scorecard', ScorecardView.as_view()),
    path('api/student/scores/', StudentScoresView.as_view(), name='student-scores'),
    path('api/student/scores', StudentScoresView.as_view()),
]
