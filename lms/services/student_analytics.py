"""
Student Analytics Service
Optimized for performance - reads from aggregated tables only.
"""

from django.db.models import Sum, Avg, Count
from django.utils import timezone
from datetime import timedelta
from typing import Dict, List, Any, Optional

from lms.models import DailyStudyStats, StudentStreak, Progress, Deck, Classroom


class StudentAnalyticsService:
    """Service for computing student statistics from aggregated data."""
    
    def __init__(self, user):
        self.user = user

    def get_overview_stats(self) -> Dict[str, Any]:
        """
        Get overview statistics for student dashboard.
        Uses aggregated tables for performance.
        """
        # 1. Streak data (direct read)
        streak = getattr(self.user, 'anki_streak', None)
        
        # 2. Aggregate from DailyStudyStats (fast)
        aggregates = DailyStudyStats.objects.filter(student=self.user).aggregate(
            total_cards=Sum('cards_learned'),
            total_reviews=Sum('cards_reviewed'),
            total_time=Sum('time_spent_seconds'),
            avg_retention=Avg('retention_rate')
        )

        # 3. Count decks with progress
        decks_in_progress = Progress.objects.filter(
            student=self.user, 
            cards_learned__gt=0
        ).count()

        return {
            "total_cards_learned": aggregates['total_cards'] or 0,
            "total_reviews": aggregates['total_reviews'] or 0,
            "total_study_time_seconds": aggregates['total_time'] or 0,
            "avg_retention_rate": round(aggregates['avg_retention'] or 0, 2),
            "current_streak": streak.current_streak if streak else 0,
            "longest_streak": streak.longest_streak if streak else 0,
            "decks_in_progress": decks_in_progress,
        }

    def get_today_stats(self) -> Dict[str, Any]:
        """Get today's study statistics."""
        today = timezone.now().date()
        stats = DailyStudyStats.objects.filter(
            student=self.user, 
            date=today
        ).first()
        
        return {
            "cards_reviewed": stats.cards_reviewed if stats else 0,
            "cards_learned": stats.cards_learned if stats else 0,
            "time_spent_seconds": stats.time_spent_seconds if stats else 0,
            "retention_rate": stats.retention_rate if stats else 0,
        }

    def get_study_history(self, days: int = 30) -> List[Dict[str, Any]]:
        """
        Get study history for charts.
        Returns dates in ISO format (UTC) for frontend timezone conversion.
        """
        start_date = timezone.now().date() - timedelta(days=days)
        
        stats = DailyStudyStats.objects.filter(
            student=self.user,
            date__gte=start_date
        ).order_by('date')
        
        return [
            {
                "date": stat.date.isoformat(),
                "cards_reviewed": stat.cards_reviewed,
                "cards_learned": stat.cards_learned,
                "time_spent_seconds": stat.time_spent_seconds,
                "retention_rate": round(stat.retention_rate, 2),
            }
            for stat in stats
        ]

    def get_deck_progress(self) -> List[Dict[str, Any]]:
        """Get progress for each deck the student has studied."""
        progress_list = Progress.objects.filter(
            student=self.user
        ).select_related('deck')
        
        return [
            {
                "deck_id": prog.deck.id,
                "deck_title": prog.deck.title,
                "cards_learned": prog.cards_learned,
                "cards_to_review": prog.cards_to_review,
                "total_cards": prog.deck.card_count,
                "last_sync": prog.last_sync.isoformat() if prog.last_sync else None,
                "progress_percent": round(
                    (prog.cards_learned / prog.deck.card_count * 100) 
                    if prog.deck.card_count > 0 else 0, 1
                ),
            }
            for prog in progress_list
        ]


class TeacherAnalyticsService:
    """Service for teacher class analytics."""
    
    def __init__(self, classroom: Classroom):
        self.classroom = classroom

    def get_class_overview(self) -> Dict[str, Any]:
        """Get overview statistics for a class."""
        students = self.classroom.students.all()
        student_ids = list(students.values_list('id', flat=True))
        
        today = timezone.now().date()
        week_ago = today - timedelta(days=7)
        
        # Aggregates from DailyStudyStats
        today_stats = DailyStudyStats.objects.filter(
            student_id__in=student_ids,
            date=today
        ).aggregate(
            active_count=Count('student', distinct=True),
            total_reviews=Sum('cards_reviewed')
        )
        
        week_stats = DailyStudyStats.objects.filter(
            student_id__in=student_ids,
            date__gte=week_ago
        ).aggregate(
            total_reviews=Sum('cards_reviewed'),
            avg_retention=Avg('retention_rate')
        )
        
        return {
            "total_students": students.count(),
            "active_students_today": today_stats['active_count'] or 0,
            "total_reviews_today": today_stats['total_reviews'] or 0,
            "total_reviews_this_week": week_stats['total_reviews'] or 0,
            "avg_retention_rate": round(week_stats['avg_retention'] or 0, 2),
        }

    def get_student_progress_list(self) -> List[Dict[str, Any]]:
        """Get progress data for all students in class."""
        students = self.classroom.students.all().prefetch_related('anki_streak')
        deck_ids = list(self.classroom.decks.values_list('id', flat=True))
        
        result = []
        for student in students:
            # Get aggregated stats for this student on class decks
            progress_data = Progress.objects.filter(
                student=student,
                deck_id__in=deck_ids
            ).aggregate(
                total_learned=Sum('cards_learned')
            )
            
            # Get streak
            streak = getattr(student, 'anki_streak', None)
            
            # Get last activity
            last_stats = DailyStudyStats.objects.filter(
                student=student
            ).order_by('-date').first()
            
            result.append({
                "id": student.id,
                "email": student.email,
                "full_name": student.full_name,
                "cards_learned": progress_data['total_learned'] or 0,
                "current_streak": streak.current_streak if streak else 0,
                "last_active": last_stats.date.isoformat() if last_stats else None,
            })
        
        # Sort by cards_learned descending
        result.sort(key=lambda x: x['cards_learned'], reverse=True)
        return result
