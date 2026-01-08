from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r"classes", views.ClassroomViewSet, basename="classroom")
router.register(r"decks", views.DeckViewSet, basename="deck")
router.register(r"assignments", views.AssignmentViewSet, basename="assignment")
router.register(r"progress", views.ProgressViewSet, basename="progress")

urlpatterns = [
    path("", views.index),
    path("", include(router.urls)),
]
