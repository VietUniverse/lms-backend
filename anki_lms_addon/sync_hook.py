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
        print("[LMS] Starting sync...")
        mw.taskman.run_on_main(lambda: tooltip("Đang kiểm tra deck..."))
        server_decks = client.get_my_decks()
        
        print(f"[LMS] Server returned {len(server_decks) if server_decks else 0} decks")
        
        if not server_decks:
            print("[LMS] No decks assigned")
            tooltip("Không có deck nào được giao.")
            _upload_progress(client)
            return
        
        # Step 2: Check versions and download if needed
        downloaded = 0
        for deck_info in server_decks:
            deck_id = deck_info["lms_deck_id"]
            title = deck_info["title"]
            server_version = deck_info.get("version", 1)
            local_version = config.get_deck_version(deck_id)  # Use deck_id, not title
            
            print(f"[LMS] Deck {deck_id} '{title}': server_version={server_version}, local_version={local_version}")
            
            if server_version > local_version:
                # Download new version
                print(f"[LMS] Downloading deck {deck_id}...")
                tooltip(f"Đang tải: {title}...")
                success = _download_and_import(client, deck_id, title)
                if success:
                    config.set_deck_version(deck_id, server_version)
                    downloaded += 1
                    print(f"[LMS] Deck {deck_id} imported successfully, saved version={server_version}")
            else:
                print(f"[LMS] Deck {deck_id} already up to date, skipping")
        
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
        
        # Verify content is valid
        if not content or len(content) < 100:
            showWarning(f"Lỗi: File deck {title} rỗng hoặc quá nhỏ ({len(content) if content else 0} bytes)")
            return False
        
        # Check for PK header (ZIP/APKG signature)
        if content[:2] != b'PK':
            showWarning(f"Lỗi: File deck {title} không phải định dạng APKG hợp lệ")
            print(f"[LMS] Invalid file header: {content[:20]}")
            return False
        
        print(f"[LMS] Deck {title}: Downloaded {len(content)} bytes, valid PK header")
        
        # Save to temp file - Use delete=False and close immediately for Windows
        # Windows needs file to be closed before other processes can access it
        temp_dir = tempfile.gettempdir()
        temp_path = os.path.join(temp_dir, f"lms_deck_{deck_id}_{version}.apkg")
        
        with open(temp_path, 'wb') as f:
            bytes_written = f.write(content)
        
        # Verify file was written correctly
        saved_size = os.path.getsize(temp_path)
        if saved_size != len(content):
            showWarning(f"Lỗi: File ghi không đầy đủ ({saved_size} vs {len(content)} bytes)")
            return False
        
        print(f"[LMS] Saved to {temp_path}: {saved_size} bytes")
        
        # === VALIDATE APKG BEFORE IMPORT ===
        # Open as ZIP and verify it contains required files
        import zipfile
        try:
            with zipfile.ZipFile(temp_path, 'r') as zf:
                file_list = zf.namelist()
                print(f"[LMS] APKG contains: {file_list}")
                
                # Check for collection database
                has_db = ('collection.anki2' in file_list or 
                          'collection.anki21' in file_list)
                
                if not has_db:
                    showWarning(f"Lỗi: File APKG không chứa database (có thể bị corrupt trong quá trình transfer).\n\nKích thước file: {saved_size} bytes\nFiles trong archive: {file_list}")
                    return False
                
                # Verify ZIP integrity
                bad_file = zf.testzip()
                if bad_file:
                    showWarning(f"Lỗi: File APKG bị corrupt! File lỗi: {bad_file}")
                    return False
                    
                print(f"[LMS] APKG validation passed!")
        except zipfile.BadZipFile as e:
            showWarning(f"Lỗi: File không phải ZIP hợp lệ (có thể bị truncate trong quá trình download).\n\nKích thước: {saved_size} bytes\nLỗi: {e}")
            return False
        
        # Import into Anki using the proper method
        try:
            importer = AnkiPackageImporter(mw.col, temp_path)
            importer.run()
            
            # CRITICAL: Save collection and reset UI to avoid database inconsistency
            # This prevents the "No such deck" error that requires Check Database
            mw.col.save()
            
            # Reset the main window to refresh deck list
            mw.reset()
            
            print(f"[LMS] Import completed for {title}")
        except Exception as import_error:
            print(f"[LMS] Import error: {import_error}")
            # Try to recover by running check database automatically
            try:
                from aqt.operations.collection import check_collection
                check_collection(parent=mw)
                print(f"[LMS] Auto-ran check database after error")
            except Exception:
                pass
            showWarning(f"Lỗi import deck {title}: {import_error}")
            return False
        
        # Try to extract LMS deck ID from deck description
        _register_imported_deck(title, lms_deck_id)
        
        return True
        
    except Exception as e:
        import traceback
        print(f"[LMS] Import error: {traceback.format_exc()}")
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
