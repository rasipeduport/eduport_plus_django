from django.urls import path
from .views import (
    ChangePasswordView,
    CsrfTokenView,
    LearnLoginView,
    LoginView,
    LogoutView,
    MeView,
    SelectStudentView,
)

app_name = 'accounts'

urlpatterns = [
    path('csrf/', CsrfTokenView.as_view(), name='csrf'),
    path('login/', LoginView.as_view(), name='login'),
    path('learn/login/', LearnLoginView.as_view(), name='learn-login'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('me/', MeView.as_view(), name='me'),
    path('change-password/', ChangePasswordView.as_view(), name='change-password'),
    path('select-student/', SelectStudentView.as_view(), name='select-student'),
    path('select-student', SelectStudentView.as_view()),
]
