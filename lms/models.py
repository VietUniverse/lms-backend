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


class Deck(models.Model):
    """Bộ thẻ Anki (.apkg) - file lưu trên Appwrite, chỉ giữ reference ở đây."""
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
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.title


class Assignment(models.Model):
    """Bài tập / Kiểm tra - giao cho lớp dựa trên một Deck."""
    STATUS_CHOICES = [
        ("PENDING", "Chờ xử lý"),
        ("ACTIVE", "Đang diễn ra"),
        ("COMPLETED", "Hoàn thành"),
    ]

    title = models.CharField(max_length=255)
    classroom = models.ForeignKey(
        Classroom,
        on_delete=models.CASCADE,
        related_name="assignments",
    )
    deck = models.ForeignKey(
        Deck,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assignments",
    )
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="created_assignments",
    )
    duration = models.IntegerField(default=45, help_text="Thời gian làm bài (phút)")
    question_count = models.IntegerField(default=20)
    shuffle = models.BooleanField(default=True)
    show_result = models.BooleanField(default=False)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="PENDING")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.title


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
