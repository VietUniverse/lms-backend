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
    path("", include(router.urls)),
]
