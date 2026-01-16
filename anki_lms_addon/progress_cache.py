"""
Progress Cache Module
Local cache for card reviews to enable batch upload and prevent API spam.
"""

import json
import os
import time
from typing import Dict, List, Optional
from . import config


def get_cache_path() -> str:
    """Get path to progress cache file."""
    addon_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(addon_dir, "progress_cache.json")


def load_cache() -> Dict[str, List[Dict]]:
    """Load cached reviews. Structure: {deck_id: [reviews]}"""
    cache_path = get_cache_path()
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {}


def save_cache(cache: Dict[str, List[Dict]]) -> None:
    """Save cache to file."""
    cache_path = get_cache_path()
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)


def add_review(
    lms_deck_id: int,
    card_id: str,
    ease: int,
    time_taken: int
) -> None:
    """
    Add a card review to the cache.
    
    Args:
        lms_deck_id: LMS deck ID
        card_id: Anki card ID
        ease: 1=Again, 2=Hard, 3=Good, 4=Easy
        time_taken: Time in milliseconds
    """
    cache = load_cache()
    deck_key = str(lms_deck_id)
    
    if deck_key not in cache:
        cache[deck_key] = []
    
    cache[deck_key].append({
        "card_id": str(card_id),
        "ease": ease,
        "time": time_taken,
        "timestamp": time.time()
    })
    
    save_cache(cache)


def get_pending_reviews(lms_deck_id: int) -> List[Dict]:
    """Get all pending reviews for a deck."""
    cache = load_cache()
    return cache.get(str(lms_deck_id), [])


def get_all_pending_reviews() -> Dict[str, List[Dict]]:
    """Get all pending reviews for all decks."""
    return load_cache()


def clear_reviews(lms_deck_id: int) -> None:
    """Clear reviews for a deck after successful sync."""
    cache = load_cache()
    deck_key = str(lms_deck_id)
    if deck_key in cache:
        del cache[deck_key]
        save_cache(cache)


def clear_all_reviews() -> None:
    """Clear all cached reviews."""
    save_cache({})


def get_pending_count() -> int:
    """Get total count of pending reviews across all decks."""
    cache = load_cache()
    return sum(len(reviews) for reviews in cache.values())


def should_sync() -> bool:
    """
    Check if we should trigger a sync based on cache size.
    Sync when: 50+ reviews OR oldest review is >10 minutes old.
    """
    cache = load_cache()
    total = get_pending_count()
    
    if total >= 50:
        return True
    
    # Check for old reviews
    for reviews in cache.values():
        for review in reviews:
            if time.time() - review.get("timestamp", 0) > 600:  # 10 minutes
                return True
    
    return False


def get_cache_stats() -> Dict:
    """Get statistics about the cache."""
    cache = load_cache()
    deck_counts = {k: len(v) for k, v in cache.items()}
    oldest = None
    
    for reviews in cache.values():
        for review in reviews:
            ts = review.get("timestamp")
            if ts and (oldest is None or ts < oldest):
                oldest = ts
    
    return {
        "total_reviews": get_pending_count(),
        "deck_counts": deck_counts,
        "oldest_timestamp": oldest
    }
