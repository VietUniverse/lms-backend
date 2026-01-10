from rest_framework import serializers
from .models import Classroom, Deck, Test, Progress, SupportTicket
from django.contrib.auth import get_user_model

User = get_user_model()


class StudentSerializer(serializers.ModelSerializer):
    """Serializer cho học sinh trong lớp."""
    class Meta:
        model = User
        fields = ["id", "email", "full_name"]


class DeckSerializer(serializers.ModelSerializer):
    class Meta:
        model = Deck
        fields = [
            "id",
            "title",
            "appwrite_file_id",
            "appwrite_file_url",
            "card_count",
            "status",
            "created_at",
        ]
        read_only_fields = ["id", "created_at", "status"]


class TestBriefSerializer(serializers.ModelSerializer):
    """Serializer ngắn gọn cho bài kiểm tra."""
    deck_title = serializers.CharField(source="deck.title", read_only=True, default=None)

    class Meta:
        model = Test
        fields = ["id", "title", "deck_title", "status", "created_at"]


class ClassroomSerializer(serializers.ModelSerializer):
    student_count = serializers.SerializerMethodField()

    class Meta:
        model = Classroom
        fields = ["id", "name", "description", "join_code", "status", "student_count", "created_at"]
        read_only_fields = ["id", "join_code", "created_at"]

    def get_student_count(self, obj):
        return obj.students.count()


class ClassroomDetailSerializer(serializers.ModelSerializer):
    """Serializer chi tiết cho trang quản lý lớp."""
    student_count = serializers.SerializerMethodField()
    students = StudentSerializer(many=True, read_only=True)
    tests = TestBriefSerializer(many=True, read_only=True)
    decks = DeckSerializer(many=True, read_only=True)

    class Meta:
        model = Classroom
        fields = ["id", "name", "description", "join_code", "status", "student_count", "students", "tests", "decks", "created_at"]
        read_only_fields = ["id", "join_code", "created_at"]

    def get_student_count(self, obj):
        return obj.students.count()





class TestSerializer(serializers.ModelSerializer):
    class_id = serializers.PrimaryKeyRelatedField(
        queryset=Classroom.objects.all(), source="classroom", write_only=True
    )
    deck_id = serializers.PrimaryKeyRelatedField(
        queryset=Deck.objects.all(), source="deck", write_only=True, required=False, allow_null=True
    )

    class Meta:
        model = Test
        fields = [
            "id",
            "title",
            "class_id",
            "deck_id",
            "duration",
            "question_count",
            "shuffle",
            "show_result",
            "status",
            "created_at",
        ]
        read_only_fields = ["id", "created_at", "status"]


class ProgressSerializer(serializers.ModelSerializer):
    class Meta:
        model = Progress
        fields = ["id", "deck", "cards_learned", "cards_to_review", "last_sync"]
        read_only_fields = ["id", "last_sync"]


class SupportTicketSerializer(serializers.ModelSerializer):
    class Meta:
        model = SupportTicket
        fields = ["id", "subject", "message", "status", "priority", "attachment", "created_at", "updated_at"]
        read_only_fields = ["id", "status", "created_at", "updated_at"]

    def create(self, validated_data):
        # User is handled in ViewSet perform_create
        return super().create(validated_data)
