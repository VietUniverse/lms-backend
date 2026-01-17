# lms/services/anki_analytics.py
"""
Anki Analytics Service

Collects and aggregates learning data from Anki collections.
Uses SQLite read-only mode with immutable flag to prevent
database locking when Anki sync server is actively writing.
"""

import sqlite3
import logging
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict
from typing import Optional

from django.conf import settings
from django.db.models import Sum, Avg, Count

logger = logging.getLogger(__name__)

# Path to Anki data directory
ANKI_DATA_PATH = Path(getattr(settings, 'ANKI_SYNC_DATA_PATH', '/anki_data'))


class AnkiAnalyticsService:
    """
    Service for collecting and analyzing Anki learning data.
    
    This service reads directly from user's Anki SQLite collection
    and syncs the revlog data to Django models for fast querying.
    """
    
    def __init__(self, student):
        """
        Initialize service for a specific student.
        
        Args:
            student: Django User instance
        """
        self.student = student
        self.collection_path = self._get_collection_path()
    
    def _get_collection_path(self) -> Path:
        """Get path to student's Anki collection."""
        return ANKI_DATA_PATH / self.student.email / "collection.anki2"
    
    def sync_revlog(self) -> int:
        """
        Sync revlog entries from Anki collection to Django DB.
        
        Uses SQLite URI mode with read-only + immutable flags to prevent
        database locking issues when Anki is actively syncing.
        
        Returns:
            Count of new entries synced
        """
        # Import here to avoid circular imports
        from lms.models import AnkiRevlog, StudentStreak, DailyStudyStats
        
        if not self.collection_path.exists():
            logger.debug(f"Collection not found for {self.student.email}: {self.collection_path}")
            return 0
        
        # Get last synced revlog ID
        last_synced = AnkiRevlog.objects.filter(
            student=self.student
        ).order_by('-revlog_id').values_list('revlog_id', flat=True).first() or 0
        
        try:
            # CRITICAL: Use URI mode with read-only + immutable to prevent locking
            # This ensures we never block Anki sync operations
            db_uri = f"file:{self.collection_path}?mode=ro&immutable=1"
            conn = sqlite3.connect(db_uri, uri=True)
            cursor = conn.cursor()
            
            # 1. Get Deck Map first to identify allowed DIDs
            import json
            from lms.models import Deck
            
            # Get list of ALL LMS deck titles to filter
            # Note: We match by exact title. If student renamed deck, it won't sync.
            lms_deck_titles = set(Deck.objects.values_list('title', flat=True))
            
            cursor.execute("SELECT decks FROM col LIMIT 1")
            decks_json = cursor.fetchone()[0]
            decks_data = json.loads(decks_json)
            # {did: {name: '...', ...}}
            # Filter dids that match LMS titles
            allowed_dids = {
                int(did) for did, data in decks_data.items() 
                if data['name'] in lms_deck_titles
            }
            
            if not allowed_dids:
                logger.info(f"No matching LMS decks found in Anki collection for {self.student.email}")
                conn.close()
                return 0

            # 2. Query New Revlogs
            cursor.execute("""
                SELECT id, cid, usn, ease, ivl, lastIvl, factor, time, type
                FROM revlog
                WHERE id > ?
                ORDER BY id
                LIMIT 10000
            """, (last_synced,))
            
            rows = cursor.fetchall()
            if not rows:
                conn.close()
                return 0
                
            # 3. Get Card -> Deck mapping for these entries to filter
            card_ids = list({r[1] for r in rows}) # r[1] is cid
            
            # Chunking card queries
            card_did_map = {}
            chunk_size = 900
            for i in range(0, len(card_ids), chunk_size):
                chunk = card_ids[i:i + chunk_size]
                placeholders = ','.join(['?'] * len(chunk))
                cursor.execute(f"SELECT id, did FROM cards WHERE id IN ({placeholders})", chunk)
                for cid, did in cursor.fetchall():
                    card_did_map[cid] = did
            
            # 4. Filter entries
            new_entries = []
            filtered_count = 0
            for row in rows:
                cid = row[1]
                did = card_did_map.get(cid)
                if did in allowed_dids:
                    new_entries.append(AnkiRevlog(
                        student=self.student,
                        revlog_id=row[0],
                        card_id=row[1],
                        usn=row[2],
                        button_chosen=row[3],
                        interval=row[4],
                        last_interval=row[5],
                        ease_factor=row[6],
                        taken_millis=row[7],
                        review_kind=row[8],
                    ))
                else:
                    filtered_count += 1
            
            logger.info(f"Filtered out {filtered_count} non-LMS entries. Keeping {len(new_entries)} entries.")
            
            if new_entries:
                AnkiRevlog.objects.bulk_create(new_entries, ignore_conflicts=True)
                self._update_daily_stats(new_entries)
                # Ensure we pass the conn for _update_progress if it needs it, 
                # though _update_progress re-queries, it should be fine.
                # Actually _update_progress logic also relies on all entries being passed?
                # Yes, we pass 'new_entries' which are already filtered.
                self._update_progress(new_entries, conn)
                self._update_streak()
                logger.info(f"Synced {len(new_entries)} revlog entries for {self.student.email}")
            
            conn.close()
            return len(new_entries)
            
        except sqlite3.OperationalError as e:
            # Handle case where file is still being written or corrupted
            logger.warning(f"Could not read Anki collection for {self.student.email}: {e}")
            return 0
        except Exception as e:
            logger.error(f"Error syncing revlog for {self.student.email}: {e}")
            return 0
    
    def _update_daily_stats(self, entries: list):
        """
        Update aggregated daily stats from new revlog entries.
        
        Args:
            entries: List of AnkiRevlog model instances
        """
        from lms.models import AnkiRevlog, DailyStudyStats
        
        # Group by date
        daily_data = defaultdict(lambda: {
            'cards_reviewed': 0,
            'time_spent_ms': 0,
            'cards_learned': 0,
            'cards_relearned': 0,
            'again_count': 0,
        })
        
        for entry in entries:
            # revlog_id is timestamp in milliseconds
            date = datetime.fromtimestamp(entry.revlog_id / 1000).date()
            daily_data[date]['cards_reviewed'] += 1
            daily_data[date]['time_spent_ms'] += entry.taken_millis
            
            # review_kind: 0=Learning, 1=Review, 2=Relearning, 3=Filtered, 4=Manual
            if entry.review_kind == 0:
                daily_data[date]['cards_learned'] += 1
            elif entry.review_kind == 2:
                daily_data[date]['cards_relearned'] += 1
            
            # button_chosen: 1=Again, 2=Hard, 3=Good, 4=Easy
            if entry.button_chosen == 1:
                daily_data[date]['again_count'] += 1
        
        # Upsert daily stats
        for date, data in daily_data.items():
            stats, created = DailyStudyStats.objects.get_or_create(
                student=self.student,
                date=date,
                defaults={
                    'cards_reviewed': data['cards_reviewed'],
                    'time_spent_seconds': data['time_spent_ms'] // 1000,
                    'cards_learned': data['cards_learned'],
                    'cards_relearned': data['cards_relearned'],
                }
            )
            
            if not created:
                stats.cards_reviewed += data['cards_reviewed']
                stats.time_spent_seconds += data['time_spent_ms'] // 1000
                stats.cards_learned += data['cards_learned']
                stats.cards_relearned += data['cards_relearned']
            
            # Calculate retention rate for the day
            if stats.cards_reviewed > 0:
                # Count "Again" reviews for this day
                day_start = datetime.combine(date, datetime.min.time())
                day_end = datetime.combine(date + timedelta(days=1), datetime.min.time())
                
                total_again = AnkiRevlog.objects.filter(
                    student=self.student,
                    button_chosen=1,
                    revlog_id__gte=int(day_start.timestamp() * 1000),
                    revlog_id__lt=int(day_end.timestamp() * 1000)
                ).count()
                
                stats.retention_rate = 1 - (total_again / stats.cards_reviewed)
            
            stats.save()

    def _update_progress(self, entries: list, conn: sqlite3.Connection):
        """
        Update Progress model for each deck.
        Maps Anki cards -> Anki Decks -> LMS Decks.
        """
        import json
        from lms.models import Deck, Progress

        # 1. Get Deck Map (did -> name) from col table
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT decks FROM col LIMIT 1")
            decks_json = cursor.fetchone()[0]
            decks_data = json.loads(decks_json)
            # Anki 2.1 schema: decks is a dict {did: {name: "...", ...}}
            # Ensure keys are integers
            deck_map = {int(k): v['name'] for k, v in decks_data.items()}
        except Exception as e:
            logger.error(f"Failed to read decks from Anki collection: {e}")
            return

        # 2. Get Card -> Deck Map for the entries
        card_ids = list(set(e.card_id for e in entries))
        if not card_ids:
            return
        
        # Split into chunks to avoid too many SQL variables
        card_deck_map = {}
        chunk_size = 900
        for i in range(0, len(card_ids), chunk_size):
            chunk = card_ids[i:i + chunk_size]
            placeholders = ','.join(['?'] * len(chunk))
            cursor.execute(f"SELECT id, did FROM cards WHERE id IN ({placeholders})", chunk)
            for cid, did in cursor.fetchall():
                card_deck_map[cid] = did

        # 3. Group by Deck Name
        from collections import defaultdict
        deck_updates = defaultdict(list) # deck_name -> [entry]
        for entry in entries:
            did = card_deck_map.get(entry.card_id)
            if did and did in deck_map:
                deck_name = deck_map[did]
                deck_updates[deck_name].append(entry)

        # 4. Find matching LMS Decks and Update Progress
        for deck_name, deck_entries in deck_updates.items():
            # Find LMS deck by title (approximate match)
            lms_deck = Deck.objects.filter(title=deck_name).first()
            if not lms_deck:
                continue

            progress, _ = Progress.objects.get_or_create(
                student=self.student,
                deck=lms_deck
            )

            # Update cards_learned based on Anki "queue" status (queue > 0 means learned/learning)
            try:
                anki_did = next(k for k, v in deck_map.items() if v == deck_name)
                cursor.execute("SELECT count() FROM cards WHERE did = ? AND queue > 0", (anki_did,))
                learned_count = cursor.fetchone()[0]
                
                progress.cards_learned = learned_count
                progress.save()
                logger.info(f"Updated progress for deck {deck_name}: {learned_count} cards learned")
            except Exception as e:
                logger.error(f"Error updating progress for deck {deck_name}: {e}")
    
    def _update_streak(self):
        """Update student's study streak based on today's activity."""
        from lms.models import StudentStreak
        
        today = datetime.now().date()
        streak, _ = StudentStreak.objects.get_or_create(student=self.student)
        streak.update_streak(today)
    
    def get_metrics(self) -> dict:
        """
        Get comprehensive learning metrics for student.
        
        Returns:
            Dictionary containing today, week, month stats, streak info,
            and difficulty distribution
        """
        from lms.models import AnkiRevlog, StudentStreak, DailyStudyStats
        
        today = datetime.now().date()
        week_ago = today - timedelta(days=7)
        month_ago = today - timedelta(days=30)
        
        # Today's stats
        today_stats = DailyStudyStats.objects.filter(
            student=self.student, date=today
        ).first()
        
        # Weekly aggregates
        weekly = DailyStudyStats.objects.filter(
            student=self.student,
            date__gte=week_ago
        ).aggregate(
            cards=Sum('cards_reviewed'),
            time=Sum('time_spent_seconds'),
            retention=Avg('retention_rate')
        )
        
        # Monthly aggregates
        monthly = DailyStudyStats.objects.filter(
            student=self.student,
            date__gte=month_ago
        ).aggregate(
            cards=Sum('cards_reviewed'),
            time=Sum('time_spent_seconds'),
            retention=Avg('retention_rate')
        )
        
        # Streak
        streak = StudentStreak.objects.filter(student=self.student).first()
        
        # Card difficulty distribution (last 30 days)
        month_start_ms = int(datetime.combine(month_ago, datetime.min.time()).timestamp() * 1000)
        difficulty = AnkiRevlog.objects.filter(
            student=self.student,
            revlog_id__gte=month_start_ms
        ).values('button_chosen').annotate(
            count=Count('id')
        ).order_by('button_chosen')
        
        # Build difficulty distribution with defaults
        difficulty_dist = {1: 0, 2: 0, 3: 0, 4: 0}
        for d in difficulty:
            if d['button_chosen'] in difficulty_dist:
                difficulty_dist[d['button_chosen']] = d['count']
        
        return {
            'today': {
                'cards_reviewed': today_stats.cards_reviewed if today_stats else 0,
                'time_spent_minutes': (today_stats.time_spent_seconds // 60) if today_stats else 0,
                'cards_learned': today_stats.cards_learned if today_stats else 0,
            },
            'week': {
                'cards_reviewed': weekly['cards'] or 0,
                'time_spent_minutes': (weekly['time'] or 0) // 60,
                'avg_retention': round((weekly['retention'] or 0) * 100, 1),
            },
            'month': {
                'cards_reviewed': monthly['cards'] or 0,
                'time_spent_minutes': (monthly['time'] or 0) // 60,
                'avg_retention': round((monthly['retention'] or 0) * 100, 1),
            },
            'streak': {
                'current': streak.current_streak if streak else 0,
                'longest': streak.longest_streak if streak else 0,
                'last_study_date': streak.last_study_date.isoformat() if streak and streak.last_study_date else None,
            },
            'difficulty_distribution': {
                'again': difficulty_dist[1],
                'hard': difficulty_dist[2],
                'good': difficulty_dist[3],
                'easy': difficulty_dist[4],
            },
            'has_synced': self.collection_path.exists(),
        }
    
    def get_study_calendar(self, days: int = 30) -> list:
        """
        Get study activity for calendar heatmap display.
        
        Args:
            days: Number of days to look back
            
        Returns:
            List of {date, cards_reviewed, time_minutes} dicts
        """
        from lms.models import DailyStudyStats
        
        start_date = datetime.now().date() - timedelta(days=days)
        
        stats = DailyStudyStats.objects.filter(
            student=self.student,
            date__gte=start_date
        ).order_by('date').values('date', 'cards_reviewed', 'time_spent_seconds')
        
        return [{
            'date': s['date'].isoformat(),
            'cards_reviewed': s['cards_reviewed'],
            'time_minutes': s['time_spent_seconds'] // 60,
        } for s in stats]
