from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from . import views

urlpatterns = [
    path("signup/", views.signup_view, name="signup"),
    path("login/", views.login_view, name="login"),
    path("token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("me/", views.me_view, name="me"),
    path("change-password/", views.change_password_view, name="change_password"),
    
    # New endpoints
    path("settings/", views.user_settings_view, name="user_settings"),
    path("avatar/", views.upload_avatar_view, name="upload_avatar"),
    path("delete/", views.delete_account_view, name="delete_account"),
]
