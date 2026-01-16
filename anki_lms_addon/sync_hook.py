"""
Sync Hook Module
Core sync logic: download decks, import to Anki, upload progress.
"""

import os
import re
import tempfile
from typing import Optional, List, Dict, Any
from aqt import mw
from aqt.utils import showInfo, showWarning, tooltip
from anki.importing.apkg import AnkiPackageImporter

from . import config
from .api_client import LMSClient, LMSClientError
from . import progress_cache


def on_sync() -> None:
    """
    Main sync handler. Called when user clicks Sync or via menu.
    1. Check version from my-decks
    2. Download new/updated decks
    3. Import .apkg into Anki
    4. Upload cached progress
    """
    if not config.is_logged_in():
        showWarning("Vui lòng đăng nhập LMS trước khi đồng bộ.")
        return
    
    client = LMSClient()
    
    try:
        # Step 1: Get assigned decks
        mw.taskman.run_on_main(lambda: tooltip("Đang kiểm tra deck..."))
        server_decks = client.get_my_decks()
        
        if not server_decks:
            tooltip("Không có deck nào được giao.")
            _upload_progress(client)
            return
        
        # Step 2: Check versions and download if needed
        downloaded = 0
        for deck_info in server_decks:
            deck_id = deck_info["lms_deck_id"]
            server_version = deck_info.get("version", 1)
            local_version = config.get_deck_version(deck_id)
            
            if server_version > local_version:
                # Download new version
                tooltip(f"Đang tải: {deck_info['title']}...")
                success = _download_and_import(client, deck_id, deck_info["title"])
                if success:
                    config.set_deck_version(deck_id, server_version)
                    downloaded += 1
        
        # Step 3: Upload progress
        synced = _upload_progress(client)
        
        # Show summary
        msgs = []
        if downloaded:
            msgs.append(f"{downloaded} deck mới")
        if synced:
            msgs.append(f"{synced} reviews đã đồng bộ")
        
        if msgs:
            tooltip("Đồng bộ: " + ", ".join(msgs))
        else:
            tooltip("Đã cập nhật.")
            
    except LMSClientError as e:
        showWarning(f"Lỗi đồng bộ: {e}")
    except Exception as e:
        showWarning(f"Lỗi không xác định: {e}")


def _download_and_import(client: LMSClient, deck_id: int, title: str) -> bool:
    """Download and import a single deck."""
    temp_path = None
    try:
        content, lms_deck_id, version = client.download_deck(deck_id)
        
        # Save to temp file - Use delete=False and close immediately for Windows
        # Windows needs file to be closed before other processes can access it
        temp_dir = tempfile.gettempdir()
        temp_path = os.path.join(temp_dir, f"lms_deck_{deck_id}_{version}.apkg")
        
        with open(temp_path, 'wb') as f:
            f.write(content)
        # File is now closed and safe to use
        
        # Import into Anki
        importer = AnkiPackageImporter(mw.col, temp_path)
        importer.run()
        
        # Try to extract LMS deck ID from deck description
        _register_imported_deck(title, lms_deck_id)
        
        return True
        
    except Exception as e:
        showWarning(f"Lỗi import deck {title}: {e}")
        return False
    finally:
        # Cleanup temp file
        if temp_path and os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except Exception:
                pass  # Ignore cleanup errors


def _register_imported_deck(title: str, lms_deck_id: int) -> None:
    """Register deck mapping after import."""
    # Find the deck by name (might have slight variations)
    decks = mw.col.decks.all_names_and_ids()
    for deck in decks:
        if title.lower() in deck.name.lower():
            config.set_deck_mapping(deck.name, lms_deck_id)
            break
    else:
        # Fallback: try exact match
        config.set_deck_mapping(title, lms_deck_id)


def _upload_progress(client: LMSClient) -> int:
    """Upload all cached progress. Returns count of synced reviews."""
    total_synced = 0
    cache = progress_cache.get_all_pending_reviews()
    
    for deck_id_str, reviews in cache.items():
        if not reviews:
            continue
        
        try:
            deck_id = int(deck_id_str)
            result = client.submit_progress(deck_id, reviews)
            synced = result.get("synced_count", 0)
            total_synced += synced
            
            # Clear cache on success
            progress_cache.clear_reviews(deck_id)
        except LMSClientError as e:
            # Log but don't fail entire sync
            print(f"Progress sync failed for deck {deck_id_str}: {e}")
    
    return total_synced


def on_review_card(reviewer, card, ease: int) -> None:
    """
    Hook called when user answers a card.
    Cache the review locally - DO NOT call API.
    """
    # Get deck name
    deck = mw.col.decks.get(card.did)
    if not deck:
        return
    
    deck_name = deck["name"]
    
    # Check if this is a tracked LMS deck
    lms_deck_id = config.get_deck_mapping(deck_name)
    
    # Also try parent deck
    if not lms_deck_id and "::" in deck_name:
        parent_name = deck_name.split("::")[0]
        lms_deck_id = config.get_deck_mapping(parent_name)
    
    if not lms_deck_id:
        # Not an LMS deck, ignore
        return
    
    # Get time taken from card
    time_taken = card.time_taken() if hasattr(card, 'time_taken') else 0
    
    # Cache locally
    progress_cache.add_review(
        lms_deck_id=lms_deck_id,
        card_id=str(card.id),
        ease=ease,
        time_taken=time_taken
    )


def extract_lms_deck_id_from_desc(deck_name: str) -> Optional[int]:
    """
    Extract lms_deck_id from deck description.
    Format in desc: "lms_deck_id:123"
    """
    deck = mw.col.decks.by_name(deck_name)
    if not deck:
        return None
    
    desc = deck.get("desc", "")
    match = re.search(r'lms_deck_id:(\d+)', desc)
    if match:
        return int(match.group(1))
    return None


def scan_and_register_decks() -> int:
    """
    Scan all decks and register any with lms_deck_id in description.
    Returns count of registered decks.
    """
    count = 0
    for deck in mw.col.decks.all():
        deck_id = extract_lms_deck_id_from_desc(deck["name"])
        if deck_id:
            config.set_deck_mapping(deck["name"], deck_id)
            count += 1
    return count
