from django.conf import settings
from django.db import models


class Classroom(models.Model):
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
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

    def __str__(self) -> str:
        return self.name


class Deck(models.Model):
    classroom = models.ForeignKey(
        Classroom,
        on_delete=models.CASCADE,
        related_name="decks",
    )
    title = models.CharField(max_length=255)
    anki_file = models.FileField(upload_to="decks/")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.title


class Progress(models.Model):
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
