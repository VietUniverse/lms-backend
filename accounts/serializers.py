from django.contrib.auth import get_user_model
from rest_framework import serializers

User = get_user_model()

class SignUpSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)
    confirm_password = serializers.CharField(write_only=True)
    role = serializers.CharField(default='student', required=False)

    class Meta:
        model = User
        fields = ["full_name", "email", "password", "confirm_password", "role"]

    def validate(self, attrs):
        if attrs["password"] != attrs["confirm_password"]:
            raise serializers.ValidationError("Passwords do not match.")
        return attrs

    def create(self, validated_data):
        validated_data.pop("confirm_password")
        user = User(
            full_name=validated_data["full_name"],
            email=validated_data["email"],
            role=validated_data.get("role", "student"),
            username=validated_data["email"],
        )
        user.set_password(validated_data["password"])
        user.save()
        
        # Create Anki Sync User
        try:
             from lms.anki_sync import add_user
             add_user(user.email, validated_data["password"])
        except Exception as e:
            print(f"Failed to create Anki user for {user.email}: {e}")
            
        return user


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "full_name", "email", "role", "date_joined"]


class ProfileSerializer(serializers.ModelSerializer):
    """Serializer để cập nhật thông tin cá nhân (trừ role)."""
    class Meta:
        model = User
        fields = ["full_name", "email"]

    def validate_email(self, value):
        user = self.context['request'].user
        if User.objects.exclude(pk=user.pk).filter(email=value).exists():
            raise serializers.ValidationError("Email này đã được sử dụng.")
        return value

    def update(self, instance, validated_data):
        # Update username to match new email if email changes
        if "email" in validated_data:
            instance.username = validated_data["email"]
        return super().update(instance, validated_data)


class ChangePasswordSerializer(serializers.Serializer):
    """Serializer để thay đổi mật khẩu."""
    old_password = serializers.CharField(required=True)
    new_password = serializers.CharField(required=True)
    confirm_password = serializers.CharField(required=True)

    def validate(self, attrs):
        if attrs['new_password'] != attrs['confirm_password']:
            raise serializers.ValidationError("Mật khẩu mới không khớp.")
        return attrs
