# lms/services/event_service.py
"""
Event Service for Phase 2 gamification.

Handles event progress tracking based on user activity.
Called automatically after Anki sync to update event progress.
"""

from django.db.models import Sum
from django.utils import timezone
import logging

logger = logging.getLogger(__name__)


class EventService:
    """
    Service for managing event participation and progress.
    """
    
    def __init__(self, user):
        self.user = user
    
    def get_current_value(self, target_type: str) -> int:
        """
        Get current value for a target type from user's data.
        
        Args:
            target_type: One of CARDS, TIME, STREAK, XP
            
        Returns:
            Current value for that metric
        """
        from lms.models import DailyStudyStats, StudentStreak
        
        if target_type == "CARDS":
            # Total cards learned
            result = DailyStudyStats.objects.filter(
                student=self.user
            ).aggregate(total=Sum('cards_learned'))
            return result['total'] or 0
        
        elif target_type == "TIME":
            # Total study time in minutes
            result = DailyStudyStats.objects.filter(
                student=self.user
            ).aggregate(total=Sum('time_spent_seconds'))
            return (result['total'] or 0) // 60
        
        elif target_type == "STREAK":
            # Current streak
            streak = StudentStreak.objects.filter(student=self.user).first()
            return streak.current_streak if streak else 0
        
        elif target_type == "XP":
            # User's XP
            return self.user.xp
        
        return 0
    
    def update_all_event_progress(self) -> list:
        """
        Update progress for all active events the user has joined.
        
        Returns:
            List of events that were just completed
        """
        from lms.models import EventParticipant
        
        now = timezone.now()
        
        # Get all active participations
        participations = EventParticipant.objects.filter(
            user=self.user,
            completed=False,
            event__is_active=True,
            event__start_date__lte=now,
            event__end_date__gte=now
        ).select_related('event')
        
        completed_events = []
        
        for participation in participations:
            target_type = participation.event.target_type
            current_value = self.get_current_value(target_type)
            
            # Update progress
            just_completed = participation.update_progress(current_value)
            
            if just_completed:
                completed_events.append(participation.event)
                logger.info(f"User {self.user.email} completed event: {participation.event.title}")
        
        return completed_events
    
    def join_event(self, event) -> 'EventParticipant':
        """
        Join an event and set baseline value.
        
        Args:
            event: Event model instance
            
        Returns:
            EventParticipant instance
        """
        from lms.models import EventParticipant
        
        # Get current value as baseline
        baseline = self.get_current_value(event.target_type)
        
        participation, created = EventParticipant.objects.get_or_create(
            event=event,
            user=self.user,
            defaults={'baseline': baseline, 'progress': 0}
        )
        
        if created:
            logger.info(f"User {self.user.email} joined event {event.title} with baseline {baseline}")
        
        return participation
    
    def get_available_events(self, classroom_id: int = None) -> list:
        """
        Get events available to the user.
        
        Args:
            classroom_id: Optional filter by classroom
            
        Returns:
            List of Event instances
        """
        from lms.models import Event, Classroom
        
        now = timezone.now()
        
        # Base query: active and ongoing
        events = Event.objects.filter(
            is_active=True,
            start_date__lte=now,
            end_date__gte=now
        )
        
        if classroom_id:
            # Class-specific events
            events = events.filter(classroom_id=classroom_id)
        else:
            # Global events + events from user's enrolled classes
            enrolled_class_ids = Classroom.objects.filter(
                students=self.user
            ).values_list('id', flat=True)
            
            from django.db.models import Q
            events = events.filter(
                Q(classroom__isnull=True) |  # Global
                Q(classroom_id__in=enrolled_class_ids)  # User's classes
            )
        
        return list(events.distinct())
    
    def get_my_events(self) -> list:
        """
        Get events the user has joined with progress info.
        
        Returns:
            List of dicts with event and progress info
        """
        from lms.models import EventParticipant
        
        participations = EventParticipant.objects.filter(
            user=self.user
        ).select_related('event').order_by('-joined_at')
        
        result = []
        for p in participations:
            result.append({
                'event': p.event,
                'progress': p.progress,
                'target': p.event.target_value,
                'percentage': min(100, round(p.progress / p.event.target_value * 100, 1)) if p.event.target_value > 0 else 100,
                'completed': p.completed,
                'rewarded': p.rewarded,
                'completed_at': p.completed_at,
            })
        
        return result
