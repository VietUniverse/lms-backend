from django.contrib import admin
from .models import Classroom, Deck, Test, Progress, SupportTicket


@admin.register(Classroom)
class ClassroomAdmin(admin.ModelAdmin):
    list_display = ("name", "teacher", "status", "created_at")
    list_filter = ("status",)
    filter_horizontal = ("students",)


@admin.register(Deck)
class DeckAdmin(admin.ModelAdmin):
    list_display = ("title", "teacher", "card_count", "created_at")
    search_fields = ("title",)


@admin.register(Test)
class TestAdmin(admin.ModelAdmin):
    list_display = ("title", "classroom", "deck", "duration", "status", "created_at")
    list_filter = ("status",)


@admin.register(Progress)
class ProgressAdmin(admin.ModelAdmin):
    list_display = ("student", "deck", "cards_learned", "cards_to_review", "last_sync")


@admin.register(SupportTicket)
class SupportTicketAdmin(admin.ModelAdmin):
    list_display = ("subject", "user", "status", "priority", "created_at")
    list_filter = ("status", "priority")
    search_fields = ("subject", "user__email", "message")
    readonly_fields = ("created_at", "updated_at")