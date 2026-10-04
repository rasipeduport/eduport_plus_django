from django.urls import path
from .views import (
    StudentListView,
    StudentReassignView,
    StudentDetailView,
    StudentProfileView,
    StudentNoteListView,
    StudentNoteDetailView,
)

app_name = 'students'

urlpatterns = [
    path('', StudentListView.as_view(), name='student-list'),
    path('reassign/', StudentReassignView.as_view(), name='student-reassign'),
    path('reassign', StudentReassignView.as_view()),
    # Internal notes. The literal prefixes are listed before the bare
    # `<uuid:pk>/` catch-all below so neither can shadow the other.
    path('notes/<uuid:note_id>/', StudentNoteDetailView.as_view(), name='student-note-detail'),
    path('notes/<uuid:note_id>', StudentNoteDetailView.as_view()),
    path('<uuid:pk>/profile/', StudentProfileView.as_view(), name='student-profile'),
    path('<uuid:pk>/profile', StudentProfileView.as_view()),
    path('<uuid:pk>/notes/', StudentNoteListView.as_view(), name='student-notes'),
    path('<uuid:pk>/notes', StudentNoteListView.as_view()),
    path('<uuid:pk>/', StudentDetailView.as_view(), name='student-detail'),
    path('<uuid:pk>', StudentDetailView.as_view()),
]
