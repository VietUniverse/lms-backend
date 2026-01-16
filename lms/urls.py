from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r"classes", views.ClassroomViewSet, basename="classroom")
router.register(r"decks", views.DeckViewSet, basename="deck")
router.register(r"tests", views.TestViewSet, basename="test")
router.register(r"progress", views.ProgressViewSet, basename="progress")
router.register(r"tickets", views.SupportTicketViewSet, basename="ticket")

urlpatterns = [
    path("", views.index),
    path("dashboard/stats/", views.dashboard_stats),
    
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
    
    path("", include(router.urls)),
]
