from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from . import views

urlpatterns = [
    path("signup/", views.signup_view, name="signup"),
    path("login/", views.login_view, name="login"),
    path("token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("me/", views.me_view, name="me"),
]
