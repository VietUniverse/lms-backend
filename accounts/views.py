from django.contrib.auth import authenticate
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken

from .serializers import SignUpSerializer, UserSerializer


def get_tokens_for_user(user):
    refresh = RefreshToken.for_user(user)
    return {
        "refresh": str(refresh),
        "access": str(refresh.access_token),
    }


@api_view(["POST"])
@permission_classes([AllowAny])
def signup_view(request):
    import logging
    logger = logging.getLogger(__name__)
    
    serializer = SignUpSerializer(data=request.data)
    if serializer.is_valid():
        user = serializer.save()
        
        # Create Anki sync server user
        # Get raw password from request since user.password is already hashed
        raw_password = request.data.get("password")
        if raw_password:
            from lms.anki_sync import create_anki_user
            try:
                success = create_anki_user(user.email, raw_password)
                if not success:
                    logger.warning(f"Failed to create Anki user for {user.email}")
            except Exception as e:
                logger.error(f"Anki user creation error for {user.email}: {e}")

        tokens = get_tokens_for_user(user)
        return Response(
            {
                "user": UserSerializer(user).data,
                "tokens": tokens,
            },
            status=status.HTTP_201_CREATED,
        )
    logger.debug(f"Signup validation errors: {serializer.errors}")
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(["POST"])
@permission_classes([AllowAny])
def login_view(request):
    email = request.data.get("email")
    password = request.data.get("password")
    user = authenticate(request, username=email, password=password)
    if not user:
        return Response({"detail": "Invalid credentials"}, status=status.HTTP_400_BAD_REQUEST)

    tokens = get_tokens_for_user(user)
    return Response(
        {
            "user": UserSerializer(user).data,
            "tokens": tokens,
        }
    )


@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated])
def me_view(request):
    user = request.user
    if request.method == "GET":
        return Response(UserSerializer(user).data)
    
    # PATCH: Update profile
    from .serializers import ProfileSerializer
    serializer = ProfileSerializer(user, data=request.data, partial=True, context={'request': request})
    if serializer.is_valid():
        serializer.save()
        return Response(UserSerializer(user).data)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def change_password_view(request):
    import logging
    logger = logging.getLogger(__name__)
    
    from .serializers import ChangePasswordSerializer
    from lms.anki_sync import change_anki_password
    
    serializer = ChangePasswordSerializer(data=request.data)
    if serializer.is_valid():
        user = request.user
        if not user.check_password(serializer.data.get("old_password")):
            return Response({"old_password": ["Mật khẩu cũ không đúng."]}, status=status.HTTP_400_BAD_REQUEST)
        
        new_password = serializer.data.get("new_password")
        
        # Change password in LMS
        user.set_password(new_password)
        user.save()
        
        # Sync to Anki Server
        try:
            success = change_anki_password(user.email, new_password)
            if not success:
                logger.warning(f"Failed to sync Anki password for {user.email}")
        except Exception as e:
            logger.error(f"Anki password sync error for {user.email}: {e}")

        return Response({"message": "Đổi mật khẩu thành công!"}, status=status.HTTP_200_OK)

    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated])
def user_settings_view(request):
    """Get or update user settings (notifications + preferences)."""
    user = request.user
    
    # Default values
    default_notifications = {
        "daily_reminder": True,
        "streak_warning": True,
        "achievements": True,
        "marketing": False
    }
    default_preferences = {
        "dark_mode": False,
        "sound_effects": True,
        "language": "vi",
        "cards_per_day": 20
    }
    
    if request.method == "GET":
        return Response({
            "notifications": {**default_notifications, **(user.notification_settings or {})},
            "preferences": {**default_preferences, **(user.preferences or {})},
        })
    
    # PATCH
    if "notifications" in request.data:
        current = user.notification_settings or {}
        user.notification_settings = {**current, **request.data["notifications"]}
    if "preferences" in request.data:
        current = user.preferences or {}
        user.preferences = {**current, **request.data["preferences"]}
    user.save()
    
    return Response({
        "notifications": {**default_notifications, **(user.notification_settings or {})},
        "preferences": {**default_preferences, **(user.preferences or {})},
    })


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def upload_avatar_view(request):
    """Upload user avatar."""
    from rest_framework.parsers import MultiPartParser, FormParser
    
    user = request.user
    
    if 'avatar' not in request.FILES:
        return Response({"error": "No file uploaded"}, status=status.HTTP_400_BAD_REQUEST)
    
    # Delete old avatar if exists
    if user.avatar:
        user.avatar.delete(save=False)
    
    user.avatar = request.FILES['avatar']
    user.save()
    
    avatar_url = None
    if user.avatar:
        avatar_url = request.build_absolute_uri(user.avatar.url)
    
    return Response({
        "message": "Avatar uploaded successfully",
        "avatar_url": avatar_url
    })


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def delete_account_view(request):
    """Soft delete user account."""
    from django.utils import timezone
    
    user = request.user
    password = request.data.get("password")
    
    if not password:
        return Response({"error": "Mật khẩu là bắt buộc"}, status=status.HTTP_400_BAD_REQUEST)
    
    if not user.check_password(password):
        return Response({"error": "Mật khẩu không đúng"}, status=status.HTTP_400_BAD_REQUEST)
    
    # Soft delete
    user.is_deleted = True
    user.deleted_at = timezone.now()
    user.is_active = False  # Prevent login
    user.save()
    
    return Response({"message": "Tài khoản đã được xóa thành công"})
