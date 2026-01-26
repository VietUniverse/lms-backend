from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r"classes", views.ClassroomViewSet, basename="classroom")
router.register(r"decks", views.DeckViewSet, basename="deck")
router.register(r"tests", views.TestViewSet, basename="test")
router.register(r"progress", views.ProgressViewSet, basename="progress")
router.register(r"tickets", views.SupportTicketViewSet, basename="ticket")
router.register(r"events", views.EventViewSet, basename="event")  # Phase 2

urlpatterns = [
    path("", views.index),
    path("dashboard/stats/", views.dashboard_stats),
    
    # Gamification Endpoints (Phase 1)
    path("gamification/stats/", views.gamification_stats, name="gamification-stats"),
    path("gamification/buy-shield/", views.buy_shield, name="buy-shield"),
    
    # Leaderboard (Phase 2)
    path("leaderboard/", views.global_leaderboard, name="leaderboard"),
    
    # Anki Addon Integration Endpoints
    path("anki/my-decks/", views.anki_my_decks, name="anki-my-decks"),
    path("anki/deck/<int:deck_id>/download/", views.anki_deck_download, name="anki-deck-download"),
    path("anki/progress/", views.anki_progress, name="anki-progress"),
    path("anki/token-exchange/", views.anki_token_exchange, name="anki-token-exchange"),
    
    # Anki Sync Server Analytics Endpoints
    path("anki/stats/", views.my_anki_stats, name="anki-stats"),
    path("anki/class/<int:class_id>/stats/", views.class_anki_stats, name="anki-class-stats"),
    path("anki/calendar/", views.anki_calendar, name="anki-calendar"),
    path("anki/sync-status/", views.anki_sync_status, name="anki-sync-status"),
    path("anki/sync-pending-decks/", views.sync_pending_decks, name="anki-sync-pending-decks"),
    
    # Student Analytics Endpoints
    path("student/stats/", views.student_stats, name="student-stats"),
    path("student/history/", views.student_history, name="student-history"),
    path("classes/<int:class_id>/analytics/", views.class_analytics, name="class-analytics"),
    
    # Achievements Endpoints
    path("achievements/", views.achievements_list, name="achievements-list"),
    path("achievements/my/", views.my_achievements, name="my-achievements"),
    path("achievements/<int:achievement_id>/claim/", views.claim_achievement_reward, name="claim-achievement"),
    
    # Deck Card Management
    path("decks/<int:deck_id>/cards/<int:card_id>/", views.deck_card_detail, name="deck-card-detail"),
    
    path("", include(router.urls)),
]
