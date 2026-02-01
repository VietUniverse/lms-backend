from rest_framework import serializers
from .models import Classroom, Deck, Card, Test, TestSubmission, Progress, SupportTicket, Event, EventParticipant, Achievement, UserAchievement, MarketplaceItem, ClassroomJoinRequest, CoinTransaction
from django.contrib.auth import get_user_model

User = get_user_model()


class StudentSerializer(serializers.ModelSerializer):
    """Serializer cho học sinh trong lớp."""
    class Meta:
        model = User
        fields = ["id", "email", "full_name", "xp", "level", "coin_balance"]


class StudentGamificationSerializer(serializers.ModelSerializer):
    """Serializer with full gamification stats."""
    xp_progress = serializers.SerializerMethodField()
    
    class Meta:
        model = User
        fields = ["id", "email", "full_name", "xp", "level", "coin_balance", "shield_count", "xp_progress"]
    
    def get_xp_progress(self, obj):
        return obj.xp_progress()


class ClassroomJoinRequestSerializer(serializers.ModelSerializer):
    """Serializer cho yêu cầu tham gia lớp."""
    student_email = serializers.CharField(source='student.email', read_only=True)
    student_name = serializers.CharField(source='student.full_name', read_only=True)
    classroom_name = serializers.CharField(source='classroom.name', read_only=True)
    
    class Meta:
        model = ClassroomJoinRequest
        fields = [
            "id", "classroom", "student", "student_email", "student_name",
            "classroom_name", "status", "message", "created_at", "reviewed_at"
        ]
        read_only_fields = ["id", "student", "status", "created_at", "reviewed_at"]


class CoinTransactionSerializer(serializers.ModelSerializer):
    """Serializer cho lịch sử giao dịch Coin."""
    class Meta:
        model = CoinTransaction
        fields = ["id", "amount", "transaction_type", "reason", "balance_after", "created_at"]
        read_only_fields = fields


class DeckSerializer(serializers.ModelSerializer):
    class_name = serializers.SerializerMethodField()
    class_id = serializers.SerializerMethodField()

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
            "class_name",
            "class_id",
        ]
        read_only_fields = ["id", "created_at", "status"]

    def get_class_name(self, obj):
        # Get first classroom this deck is assigned to
        classroom = obj.classrooms.first()
        return classroom.name if classroom else None

    def get_class_id(self, obj):
        classroom = obj.classrooms.first()
        return classroom.id if classroom else None


class TestBriefSerializer(serializers.ModelSerializer):
    """Serializer ngắn gọn cho bài kiểm tra."""
    deck_title = serializers.CharField(source="deck.title", read_only=True, default=None)

    class Meta:
        model = Test
        fields = ["id", "title", "deck_title", "status", "created_at"]


class ClassroomSerializer(serializers.ModelSerializer):
    student_count = serializers.SerializerMethodField()
    is_owner = serializers.SerializerMethodField()

    class Meta:
        model = Classroom
        fields = [
            "id", "name", "description", "join_code", "status", "student_count", "created_at",
            "class_type", "max_students", "is_public", "topics", "is_owner", "teacher"  # Added teacher for fallback
        ]
        read_only_fields = ["id", "join_code", "created_at"]

    def get_student_count(self, obj):
        return obj.students.count()

    def get_is_owner(self, obj):
        request = self.context.get('request')
        if request and hasattr(request, 'user'):
            return obj.teacher == request.user
        return False


class ClassroomDetailSerializer(serializers.ModelSerializer):
    """Serializer chi tiết cho trang quản lý lớp."""
    student_count = serializers.SerializerMethodField()
    students = StudentSerializer(many=True, read_only=True)
    tests = TestBriefSerializer(many=True, read_only=True)
    decks = DeckSerializer(many=True, read_only=True)

    class Meta:
        model = Classroom
        fields = [
            "id", "name", "description", "join_code", "status", "student_count", 
            "students", "tests", "decks", "created_at",
            "class_type", "max_students", "is_public", "topics"  # Advanced fields
        ]
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


# ============================================
# ANKI ADDON INTEGRATION SERIALIZERS
# ============================================

class AnkiDeckSerializer(serializers.ModelSerializer):
    """Serializer cho endpoint /api/anki/my-decks/."""
    lms_deck_id = serializers.IntegerField(source='id')
    
    class Meta:
        model = Deck
        fields = ["lms_deck_id", "title", "version", "updated_at"]


class AnkiReviewSerializer(serializers.Serializer):
    """Serializer cho một review đơn lẻ trong batch."""
    card_id = serializers.CharField()
    ease = serializers.IntegerField(min_value=1, max_value=4)
    time = serializers.IntegerField(min_value=0)  # milliseconds
    timestamp = serializers.FloatField()  # Unix timestamp


class AnkiProgressSerializer(serializers.Serializer):
    """
    Serializer cho endpoint /api/anki/progress/ (Batch Processing).
    Addon gửi lên mảng reviews thay vì từng cái một.
    """
    lms_deck_id = serializers.IntegerField()
    reviews = AnkiReviewSerializer(many=True)
    
    def validate_lms_deck_id(self, value):
        if not Deck.objects.filter(pk=value).exists():
            raise serializers.ValidationError("Deck không tồn tại.")
        return value


# ============================================
# EVENTS SERIALIZERS (Phase 2)
# ============================================

from .models import Event, EventParticipant


class EventSerializer(serializers.ModelSerializer):
    """Serializer for Event (read/write for teachers)."""
    creator_name = serializers.CharField(source='creator.full_name', read_only=True)
    classroom_name = serializers.CharField(source='classroom.name', read_only=True, allow_null=True)
    participant_count = serializers.IntegerField(read_only=True)
    is_ongoing = serializers.BooleanField(read_only=True)
    
    class Meta:
        model = Event
        fields = [
            "id", "title", "description", "classroom", "classroom_name",
            "creator", "creator_name", "target_type", "target_value",
            "reward_xp", "reward_coins", "start_date", "end_date",
            "is_active", "participant_count", "is_ongoing", "created_at"
        ]
        read_only_fields = ["id", "creator", "created_at"]


class EventParticipantSerializer(serializers.ModelSerializer):
    """Serializer for event participation with progress."""
    event_title = serializers.CharField(source='event.title', read_only=True)
    event_target_type = serializers.CharField(source='event.target_type', read_only=True)
    event_target_value = serializers.IntegerField(source='event.target_value', read_only=True)
    event_reward_xp = serializers.IntegerField(source='event.reward_xp', read_only=True)
    event_reward_coins = serializers.IntegerField(source='event.reward_coins', read_only=True)
    event_end_date = serializers.DateTimeField(source='event.end_date', read_only=True)
    percentage = serializers.SerializerMethodField()
    
    class Meta:
        model = EventParticipant
        fields = [
            "id", "event", "event_title", "event_target_type", "event_target_value",
            "event_reward_xp", "event_reward_coins", "event_end_date",
            "progress", "percentage", "completed", "completed_at", "rewarded", "joined_at"
        ]
        read_only_fields = fields
    
    def get_percentage(self, obj):
        if obj.event.target_value <= 0:
            return 100
        return min(100, round(obj.progress / obj.event.target_value * 100, 1))


class LeaderboardEntrySerializer(serializers.Serializer):
    """Serializer for leaderboard entries."""
    rank = serializers.IntegerField()
    user_id = serializers.IntegerField()
    full_name = serializers.CharField()
    email = serializers.CharField()
    xp = serializers.IntegerField()
    level = serializers.IntegerField()
    cards_learned = serializers.IntegerField(required=False)
    current_streak = serializers.IntegerField(required=False)
    study_time_hours = serializers.FloatField(required=False)


# ============================================
# ACHIEVEMENTS SERIALIZERS
# ============================================
from .models import Achievement, UserAchievement


class AchievementSerializer(serializers.ModelSerializer):
    """Serializer for Achievement definitions."""
    unlocked = serializers.SerializerMethodField()
    user_progress = serializers.SerializerMethodField()
    
    class Meta:
        model = Achievement
        fields = [
            "id", "code", "name", "description", "icon",
            "achievement_type", "target_value", "rarity",
            "reward_xp", "reward_coins", "is_hidden",
            "unlocked", "user_progress"
        ]
    
    def get_unlocked(self, obj):
        user = self.context.get('request')
        if user and hasattr(user, 'user'):
            return UserAchievement.objects.filter(user=user.user, achievement=obj).exists()
        return False
    
    def get_user_progress(self, obj):
        user = self.context.get('request')
        if user and hasattr(user, 'user'):
            ua = UserAchievement.objects.filter(user=user.user, achievement=obj).first()
            if ua:
                return ua.progress
        return 0


class UserAchievementSerializer(serializers.ModelSerializer):
    """Serializer for user's unlocked achievements."""
    achievement_code = serializers.CharField(source='achievement.code', read_only=True)
    achievement_name = serializers.CharField(source='achievement.name', read_only=True)
    achievement_description = serializers.CharField(source='achievement.description', read_only=True)
    achievement_icon = serializers.CharField(source='achievement.icon', read_only=True)
    achievement_rarity = serializers.CharField(source='achievement.rarity', read_only=True)
    achievement_type = serializers.CharField(source='achievement.achievement_type', read_only=True)
    reward_xp = serializers.IntegerField(source='achievement.reward_xp', read_only=True)
    reward_coins = serializers.IntegerField(source='achievement.reward_coins', read_only=True)
    
    class Meta:
        model = UserAchievement
        fields = [
            "id", "achievement", "achievement_code", "achievement_name",
            "achievement_description", "achievement_icon", "achievement_rarity",
            "achievement_type", "reward_xp", "reward_coins",
            "progress", "unlocked_at", "rewarded"
        ]
        read_only_fields = fields


class MarketplaceItemSerializer(serializers.ModelSerializer):
    deck_title = serializers.CharField(source='deck.title', read_only=True)
    author_name = serializers.CharField(source='author.email', read_only=True)
    
    class Meta:
        model = MarketplaceItem
        fields = ['id', 'deck', 'deck_title', 'author', 'author_name', 'status', 'price', 'downloads', 'rating', 'source_url', 'created_at']
        read_only_fields = ['id', 'status', 'downloads', 'rating', 'author', 'created_at']

    def create(self, validated_data):
        # Assign author from context
        validated_data['author'] = self.context['request'].user
        return super().create(validated_data)
