from django.urls import path
from .views import StudentListView, StudentReassignView, StudentDetailView

app_name = 'students'

urlpatterns = [
    path('', StudentListView.as_view(), name='student-list'),
    path('reassign/', StudentReassignView.as_view(), name='student-reassign'),
    path('reassign', StudentReassignView.as_view()),
    path('<uuid:pk>/', StudentDetailView.as_view(), name='student-detail'),
    path('<uuid:pk>', StudentDetailView.as_view()),
]
