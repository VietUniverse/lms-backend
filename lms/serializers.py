from rest_framework import serializers
from .models import Classroom, Deck, Assignment, Progress


class ClassroomSerializer(serializers.ModelSerializer):
    student_count = serializers.SerializerMethodField()

    class Meta:
        model = Classroom
        fields = ["id", "name", "description", "status", "student_count", "created_at"]
        read_only_fields = ["id", "created_at"]

    def get_student_count(self, obj):
        return obj.students.count()


class DeckSerializer(serializers.ModelSerializer):
    class Meta:
        model = Deck
        fields = [
            "id",
            "title",
            "appwrite_file_id",
            "appwrite_file_url",
            "card_count",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]


class AssignmentSerializer(serializers.ModelSerializer):
    class_id = serializers.PrimaryKeyRelatedField(
        queryset=Classroom.objects.all(), source="classroom", write_only=True
    )
    deck_id = serializers.PrimaryKeyRelatedField(
        queryset=Deck.objects.all(), source="deck", write_only=True, required=False, allow_null=True
    )

    class Meta:
        model = Assignment
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
