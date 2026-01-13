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
