import secrets
import string

from django.conf import settings
from django.db import models


def generate_join_code():
    """Tạo mã tham gia lớp 6 ký tự."""
    chars = string.ascii_uppercase + string.digits
    return ''.join(secrets.choice(chars) for _ in range(6))


class Classroom(models.Model):
    """Lớp học do giáo viên quản lý."""
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    join_code = models.CharField(max_length=10, unique=True, blank=True)
    status = models.CharField(
        max_length=20,
        choices=[("ACTIVE", "Đang hoạt động"), ("FINISHED", "Đã kết thúc"), ("DRAFT", "Bản nháp")],
        default="ACTIVE",
    )
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="managed_classes",
    )
    students = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name="enrolled_classes",
        blank=True,
    )
    decks = models.ManyToManyField(
        "Deck",
        related_name="classrooms",
        blank=True,
    )
    
    # === ADVANCED CLASS FEATURES ===
    CLASS_TYPE_CHOICES = [
        ("CLASS", "Lớp học"),
        ("GROUP", "Nhóm học tập"),
    ]
    class_type = models.CharField(max_length=10, choices=CLASS_TYPE_CHOICES, default="CLASS")
    max_students = models.PositiveIntegerField(default=50, help_text="Số lượng học viên tối đa")
    is_public = models.BooleanField(default=False, help_text="Công khai cho mọi người tìm kiếm")
    topics = models.JSONField(default=list, blank=True, help_text="Danh sách chủ đề (tags)")
    
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if not self.join_code:
            # Auto-generate unique join code
            for _ in range(10):  # Try up to 10 times
                code = generate_join_code()
                if not Classroom.objects.filter(join_code=code).exists():
                    self.join_code = code
                    break
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.name


class ClassroomJoinRequest(models.Model):
    """Yêu cầu tham gia lớp học, cần giáo viên phê duyệt."""
    STATUS_CHOICES = [
        ("PENDING", "Chờ duyệt"),
        ("APPROVED", "Đã duyệt"),
        ("REJECTED", "Từ chối"),
    ]
    
    classroom = models.ForeignKey(
        Classroom,
        on_delete=models.CASCADE,
        related_name="join_requests"
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="join_requests"
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="PENDING")
    message = models.TextField(blank=True, help_text="Lời nhắn từ học sinh")
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_join_requests"
    )
    
    class Meta:
        unique_together = ('classroom', 'student')
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.student.email} -> {self.classroom.name} ({self.status})"

    def approve(self, reviewer):
        """Approve the join request and add student to classroom."""
        from django.utils import timezone
        self.status = "APPROVED"
        self.reviewed_at = timezone.now()
        self.reviewed_by = reviewer
        self.save()
        self.classroom.students.add(self.student)
        # Award XP for joining a class
        self.student.add_xp(10)

    def reject(self, reviewer):
        """Reject the join request."""
        from django.utils import timezone
        self.status = "REJECTED"
        self.reviewed_at = timezone.now()
        self.reviewed_by = reviewer
        self.save()


class CoinTransaction(models.Model):
    """Lịch sử giao dịch Coin."""
    TRANSACTION_TYPES = [
        ("EARN", "Kiếm được"),
        ("SPEND", "Chi tiêu"),
        ("BONUS", "Thưởng"),
        ("REFUND", "Hoàn lại"),
    ]
    
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="coin_transactions"
    )
    amount = models.IntegerField(help_text="Positive for earn, negative for spend")
    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPES)
    reason = models.CharField(max_length=255, blank=True)
    balance_after = models.IntegerField(default=0, help_text="Balance after transaction")
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def save(self, *args, **kwargs):
        if not self.pk:  # Only on create
            self.balance_after = self.user.coin_balance
        super().save(*args, **kwargs)
    
    def __str__(self):
        sign = "+" if self.amount > 0 else ""
        return f"{self.user.email}: {sign}{self.amount} Coin ({self.reason})"


class Activity(models.Model):
    """Track user activities for dashboard feed."""
    ACTIVITY_TYPES = [
        ("CARD_REVIEW", "Reviewed cards"),
        ("CLASS_JOIN", "Joined class"),
        ("CLASS_CREATE", "Created class"),
        ("DECK_CREATE", "Created deck"),
        ("DECK_UPLOAD", "Uploaded deck"),
        ("TEST_SUBMIT", "Submitted test"),
        ("ACHIEVEMENT", "Unlocked achievement"),
        ("LOGIN", "Logged in"),
    ]
    
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="activities"
    )
    activity_type = models.CharField(max_length=50, choices=ACTIVITY_TYPES)
    description = models.TextField()
    target_name = models.CharField(max_length=255, blank=True)
    target_id = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-created_at']
        verbose_name_plural = "Activities"
    
    def __str__(self):
        return f"{self.user.email}: {self.activity_type} - {self.description[:50]}"


class Deck(models.Model):
    """Bộ thẻ Anki (.apkg) - file lưu trên Appwrite, chỉ giữ reference ở đây."""
    STATUS_CHOICES = [
        ("PROCESSING", "Đang xử lý"),
        ("DRAFT", "Bản nháp"),
        ("ACTIVE", "Đang hoạt động"),
    ]

    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="decks",
        null=True,
        blank=True,
    )
    title = models.CharField(max_length=255)
    # Thay FileField bằng CharField để lưu Appwrite file ID
    appwrite_file_id = models.CharField(max_length=255, blank=True)
    appwrite_file_url = models.URLField(max_length=500, blank=True)
    card_count = models.IntegerField(default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="PROCESSING")
    version = models.IntegerField(default=1, help_text="Auto-incremented on update")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def delete(self, *args, **kwargs):
        """Override delete to also remove the associated .apkg file."""
        import os
        from pathlib import Path
        from django.conf import settings as django_settings
        
        # Delete local apkg file if exists
        if self.appwrite_file_id and self.appwrite_file_id.startswith('local:'):
            filename = self.appwrite_file_id.replace('local:', '')
            media_path = Path(django_settings.MEDIA_ROOT) / 'decks' / filename
            if media_path.exists():
                try:
                    os.remove(media_path)
                    print(f"Deleted apkg file: {media_path}")
                except Exception as e:
                    print(f"Failed to delete apkg file {media_path}: {e}")
        
        super().delete(*args, **kwargs)

    def __str__(self) -> str:
        return self.title


class Card(models.Model):
    """Một thẻ Anki thuộc về một Deck."""
    deck = models.ForeignKey(
        Deck,
        on_delete=models.CASCADE,
        related_name="cards",
    )
    front = models.TextField(help_text="Mặt trước (câu hỏi)")
    back = models.TextField(help_text="Mặt sau (trả lời)")
    note_id = models.CharField(max_length=100, blank=True, help_text="ID gốc từ Anki")
    
    # Flexible fields - lưu tất cả fields từ Anki note (VD: {"Text": "...", "Extra": "..."})
    fields = models.JSONField(default=dict, blank=True, help_text="All note fields as JSON")
    note_type = models.CharField(max_length=255, blank=True, help_text="Note type/template name")
    tags = models.JSONField(default=list, blank=True, help_text="Card tags")
    
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.deck.title} - {self.front[:50]}..."
    
    def get_display_fields(self):
        """Return fields for display. If fields is empty, fallback to front/back."""
        if self.fields:
            return self.fields
        return {"Front": self.front, "Back": self.back}


class Test(models.Model):
    """Bài kiểm tra - giáo viên tạo từ Deck, học sinh làm bài có điểm."""
    STATUS_CHOICES = [
        ("PENDING", "Chờ xử lý"),
        ("ACTIVE", "Đang diễn ra"),
        ("COMPLETED", "Hoàn thành"),
    ]

    title = models.CharField(max_length=255)
    classroom = models.ForeignKey(
        Classroom,
        on_delete=models.CASCADE,
        related_name="tests",
    )
    deck = models.ForeignKey(
        Deck,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tests",
    )
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="created_tests",
    )
    duration = models.IntegerField(default=45, help_text="Thời gian làm bài (phút)")
    question_count = models.IntegerField(default=20)
    shuffle = models.BooleanField(default=True)
    show_result = models.BooleanField(default=False)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="PENDING")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'lms_assignment'  # Keep using existing table name

    def __str__(self) -> str:
        return self.title


class TestSubmission(models.Model):
    """Kết quả bài kiểm tra của học sinh."""
    test = models.ForeignKey(
        Test,
        on_delete=models.CASCADE,
        related_name="submissions",
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="test_submissions",
    )
    score = models.FloatField(default=0.0)
    total_questions = models.IntegerField(default=0)
    correct_answers = models.IntegerField(default=0)
    submitted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'lms_assignmentsubmission'  # Keep using existing table name
        unique_together = ("test", "student")

    def __str__(self) -> str:
        return f"{self.student} - {self.test} - {self.score}"


class Progress(models.Model):
    """Tiến độ học tập của học sinh trên một Deck."""
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="progress",
    )
    deck = models.ForeignKey(
        Deck,
        on_delete=models.CASCADE,
        related_name="progress",
    )
    cards_learned = models.IntegerField(default=0)
    cards_to_review = models.IntegerField(default=0)
    last_sync = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("student", "deck")

    def __str__(self) -> str:
        return f"{self.student} - {self.deck}"


class SupportTicket(models.Model):
    """Ticket hỗ trợ của user gửi cho admin."""
    STATUS_CHOICES = [
        ("OPEN", "Mở"),
        ("IN_PROGRESS", "Đang xử lý"),
        ("CLOSED", "Đã đóng"),
    ]
    PRIORITY_CHOICES = [
        ("LOW", "Thấp"),
        ("MEDIUM", "Trung bình"),
        ("HIGH", "Cao"),
    ]
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE, 
        related_name="tickets"
    )
    subject = models.CharField(max_length=255)
    message = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="OPEN")
    priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES, default="MEDIUM")
    attachment = models.FileField(upload_to='tickets/', blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"[{self.status}] {self.subject} ({self.user.email})"


# ============================================
# ANKI ADDON INTEGRATION MODELS
# ============================================

class StudySession(models.Model):
    """
    Phiên học tập của học sinh trên một Deck.
    Được tạo khi Addon submit batch reviews.
    """
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="study_sessions",
    )
    deck = models.ForeignKey(
        Deck,
        on_delete=models.CASCADE,
        related_name="study_sessions",
    )
    start_time = models.DateTimeField()
    duration_seconds = models.IntegerField(default=0)
    cards_reviewed = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['student', 'deck']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f"{self.student.email} - {self.deck.title} - {self.cards_reviewed} cards"


class CardReview(models.Model):
    """
    Lịch sử review từng thẻ - Big Data table.
    Cần đánh index để query thống kê không bị treo.
    """
    EASE_CHOICES = [
        (1, 'Again'),
        (2, 'Hard'),
        (3, 'Good'),
        (4, 'Easy'),
    ]
    
    session = models.ForeignKey(
        StudySession,
        on_delete=models.CASCADE,
        related_name="reviews",
    )
    card_id = models.CharField(max_length=50, help_text="Anki card ID")
    ease = models.IntegerField(choices=EASE_CHOICES)
    time_taken = models.IntegerField(help_text="Milliseconds")
    reviewed_at = models.DateTimeField()

    class Meta:
        indexes = [
            models.Index(fields=['card_id', 'reviewed_at']),
            models.Index(fields=['session']),
        ]

    def __str__(self):
        return f"Card {self.card_id} - Ease {self.ease}"


# ============================================
# ANKI SYNC SERVER ANALYTICS MODELS
# ============================================

class AnkiRevlog(models.Model):
    """
    Mirror of Anki's revlog table for each student.
    Populated by periodic sync from user's collection.anki2 file.
    
    This is a "Big Data" table - indexes are critical for query performance.
    """
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="anki_revlogs"
    )
    revlog_id = models.BigIntegerField(
        help_text="Anki revlog.id (timestamp in milliseconds)"
    )
    card_id = models.BigIntegerField(
        help_text="Anki card ID"
    )
    usn = models.IntegerField(
        help_text="Update sequence number (-1 for local changes)"
    )
    button_chosen = models.SmallIntegerField(
        help_text="1=Again, 2=Hard, 3=Good, 4=Easy, 0=Manual"
    )
    interval = models.IntegerField(
        help_text="New interval (positive=days, negative=seconds)"
    )
    last_interval = models.IntegerField(
        help_text="Previous interval"
    )
    ease_factor = models.IntegerField(
        help_text="Ease factor * 1000 (e.g., 2500 = 250%)"
    )
    taken_millis = models.IntegerField(
        help_text="Time spent answering in milliseconds"
    )
    review_kind = models.SmallIntegerField(
        help_text="0=Learn, 1=Review, 2=Relearn, 3=Filtered, 4=Manual"
    )
    synced_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # Composite unique constraint prevents duplicate entries
        unique_together = ('student', 'revlog_id')
        indexes = [
            models.Index(fields=['student', '-revlog_id']),
            models.Index(fields=['card_id']),
            models.Index(fields=['student', 'button_chosen']),
        ]

    def __str__(self):
        return f"Revlog {self.revlog_id} - Card {self.card_id} - Ease {self.button_chosen}"


class StudentStreak(models.Model):
    """
    Track daily study streaks for students.
    One record per student - updated on each sync.
    """
    student = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="anki_streak"
    )
    current_streak = models.IntegerField(
        default=0,
        help_text="Current consecutive days studied"
    )
    longest_streak = models.IntegerField(
        default=0,
        help_text="Longest streak ever achieved"
    )
    last_study_date = models.DateField(
        null=True,
        blank=True,
        help_text="Last date the student reviewed cards"
    )
    updated_at = models.DateTimeField(auto_now=True)
    
    def update_streak(self, study_date):
        """
        Update streak based on new study activity.
        
        Args:
            study_date: Date when study occurred
        """
        from datetime import timedelta
        
        if self.last_study_date:
            diff = (study_date - self.last_study_date).days
            if diff == 1:
                # Consecutive day - increment streak
                self.current_streak += 1
            elif diff > 1:
                # Streak broken - reset to 1
                self.current_streak = 1
            # diff == 0 means same day, don't change streak
        else:
            # First study ever
            self.current_streak = 1
        
        # Update longest streak if current exceeds it
        self.longest_streak = max(self.longest_streak, self.current_streak)
        self.last_study_date = study_date
        self.save()
    
    def __str__(self):
        return f"{self.student.email} - Streak: {self.current_streak} days"


class DailyStudyStats(models.Model):
    """
    Pre-aggregated daily statistics for fast dashboard queries.
    One record per student per day.
    """
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="daily_study_stats"
    )
    date = models.DateField()
    cards_reviewed = models.IntegerField(
        default=0,
        help_text="Total cards reviewed"
    )
    time_spent_seconds = models.IntegerField(
        default=0,
        help_text="Total time spent studying"
    )
    cards_learned = models.IntegerField(
        default=0,
        help_text="New cards learned (review_kind=0)"
    )
    cards_relearned = models.IntegerField(
        default=0,
        help_text="Cards relearned after lapse (review_kind=2)"
    )
    retention_rate = models.FloatField(
        default=0.0,
        help_text="Percentage of cards not marked 'Again' (0.0 to 1.0)"
    )
    
    class Meta:
        unique_together = ('student', 'date')
        indexes = [
            models.Index(fields=['student', '-date']),
        ]
        verbose_name_plural = "Daily study stats"

    def __str__(self):
        return f"{self.student.email} - {self.date} - {self.cards_reviewed} cards"


# ============================================
# EVENTS SYSTEM (Phase 2)
# ============================================

class Event(models.Model):
    """
    Events với mục tiêu và phần thưởng.
    Có thể là class-specific hoặc global.
    """
    TARGET_TYPES = [
        ("CARDS", "Số thẻ học"),
        ("TIME", "Thời gian học (phút)"),
        ("STREAK", "Streak liên tục (ngày)"),
        ("XP", "Điểm XP"),
    ]
    
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    classroom = models.ForeignKey(
        'Classroom',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="events",
        help_text="Null = Global event"
    )
    creator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="created_events"
    )
    target_type = models.CharField(max_length=20, choices=TARGET_TYPES)
    target_value = models.IntegerField(help_text="Mục tiêu cần đạt")
    reward_xp = models.IntegerField(default=0)
    reward_coins = models.IntegerField(default=0)
    start_date = models.DateTimeField()
    end_date = models.DateTimeField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-start_date']
        indexes = [
            models.Index(fields=['is_active', '-start_date']),
            models.Index(fields=['classroom', 'is_active']),
        ]
    
    def __str__(self):
        scope = self.classroom.name if self.classroom else "Global"
        return f"{self.title} ({scope})"
    
    @property
    def is_ongoing(self):
        from django.utils import timezone
        now = timezone.now()
        return self.is_active and self.start_date <= now <= self.end_date
    
    @property
    def participant_count(self):
        return self.participants.count()


class EventParticipant(models.Model):
    """
    Tracking participation và progress của user trong event.
    """
    event = models.ForeignKey(
        Event,
        on_delete=models.CASCADE,
        related_name="participants"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="event_participations"
    )
    progress = models.IntegerField(default=0, help_text="Current progress towards target")
    baseline = models.IntegerField(default=0, help_text="Starting value when joined")
    completed = models.BooleanField(default=False)
    completed_at = models.DateTimeField(null=True, blank=True)
    rewarded = models.BooleanField(default=False)
    joined_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ('event', 'user')
        ordering = ['-progress']
    
    def __str__(self):
        status = "✓" if self.completed else f"{self.progress}/{self.event.target_value}"
        return f"{self.user.email} - {self.event.title}: {status}"
    
    def update_progress(self, current_value: int) -> bool:
        """
        Update progress based on current value minus baseline.
        Returns True if just completed.
        """
        self.progress = max(0, current_value - self.baseline)
        
        # Check completion
        just_completed = False
        if not self.completed and self.progress >= self.event.target_value:
            from django.utils import timezone
            self.completed = True
            self.completed_at = timezone.now()
            just_completed = True
        
        self.save()
        return just_completed
    
    def claim_reward(self) -> bool:
        """
        Claim reward if completed and not yet rewarded.
        Returns True if claimed successfully.
        """
        if not self.completed or self.rewarded:
            return False
        
        # Award XP and Coins
        if self.event.reward_xp > 0:
            self.user.add_xp(self.event.reward_xp)
        if self.event.reward_coins > 0:
            self.user.add_coins(self.event.reward_coins, f"Event: {self.event.title}")
        
        self.rewarded = True
        self.save()
        return True


# ============================================
# MARKETPLACE SYSTEM
# ============================================

class MarketplaceItem(models.Model):
    """
    Deck được user chia sẻ lên Marketplace.
    Cần Admin duyệt (APPROVED) mới hiện công khai.
    """
    STATUS_CHOICES = [
        ("PENDING", "Chờ duyệt"),
        ("APPROVED", "Đã duyệt"),
        ("REJECTED", "Từ chối"),
    ]
    
    deck = models.OneToOneField(
        'Deck',
        on_delete=models.CASCADE,
        related_name="marketplace_item"
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="marketplace_items"
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="PENDING")
    
    # Metadata
    price = models.IntegerField(default=0, help_text="Giá coin (0 = miễn phí)")
    downloads = models.IntegerField(default=0)
    rating = models.FloatField(default=0.0)
    
    # Source info (if imported)
    source_url = models.URLField(blank=True, max_length=500)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', '-created_at']),
        ]
        
    def __str__(self):
        return f"{self.deck.title} ({self.status})"

# ============================================
# ACHIEVEMENTS SYSTEM
# ============================================

class Achievement(models.Model):
    """
    Achievement definitions.
    Unlock conditions are checked by AchievementService.
    """
    ACHIEVEMENT_TYPES = [
        ('STREAK', 'Streak liên tục'),
        ('CARDS', 'Số thẻ học'),
        ('XP', 'Điểm XP'),
        ('TIME', 'Thời gian học'),
        ('LEVEL', 'Level đạt được'),
        ('SPECIAL', 'Đặc biệt'),
    ]
    
    RARITY_CHOICES = [
        ('COMMON', 'Thường'),
        ('RARE', 'Hiếm'),
        ('EPIC', 'Sử thi'),
        ('LEGENDARY', 'Huyền thoại'),
    ]
    
    code = models.CharField(max_length=50, unique=True)  # e.g., 'streak_7', 'cards_100'
    name = models.CharField(max_length=100)
    description = models.TextField()
    icon = models.CharField(max_length=10, default='🏆')  # Emoji or icon name
    
    achievement_type = models.CharField(max_length=20, choices=ACHIEVEMENT_TYPES)
    target_value = models.IntegerField(default=1)  # Value needed to unlock
    
    rarity = models.CharField(max_length=20, choices=RARITY_CHOICES, default='COMMON')
    reward_xp = models.IntegerField(default=0)
    reward_coins = models.IntegerField(default=0)
    
    sort_order = models.IntegerField(default=0)
    is_hidden = models.BooleanField(default=False)  # Hidden until unlocked
    is_active = models.BooleanField(default=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['sort_order', 'achievement_type', 'target_value']
    
    def __str__(self):
        return f"{self.icon} {self.name}"


class UserAchievement(models.Model):
    """User's unlocked achievements."""
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='achievements'
    )
    achievement = models.ForeignKey(
        Achievement,
        on_delete=models.CASCADE,
        related_name='user_unlocks'
    )
    
    unlocked_at = models.DateTimeField(auto_now_add=True)
    rewarded = models.BooleanField(default=False)
    
    # Progress tracking (for achievements with multiple tiers)
    progress = models.IntegerField(default=0)
    
    class Meta:
        unique_together = ['user', 'achievement']
        ordering = ['-unlocked_at']
    
    def claim_reward(self):
        """Claim XP and Coin reward."""
        if self.rewarded:
            return False
        
        if self.achievement.reward_xp > 0:
            self.user.add_xp(self.achievement.reward_xp)
        if self.achievement.reward_coins > 0:
            self.user.add_coins(self.achievement.reward_coins, f"Achievement: {self.achievement.name}")
        
        self.rewarded = True
        self.save()
        return True
