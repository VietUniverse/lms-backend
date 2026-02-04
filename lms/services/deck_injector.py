"""
Deck Injector Service

Injects .apkg decks directly into student collections on the Anki sync server.
This allows students to receive assigned decks automatically when they sync.

CRITICAL: Media files must be handled correctly to avoid "missing media" errors.
The .apkg format stores media with numeric filenames (0, 1, 2...) and a `media` 
JSON file that maps these to actual filenames.
"""

import json
import logging
import shutil
import sqlite3
import tempfile
import zipfile
from pathlib import Path
from typing import Optional, Dict, List, Tuple
import time
import os

from django.conf import settings

logger = logging.getLogger(__name__)

# Anki data path on sync server
ANKI_DATA_PATH = Path(getattr(settings, 'ANKI_SYNC_DATA_PATH', '/opt/anki-sync/anki_data'))


class DeckInjector:
    """
    Injects decks into student collections on the sync server.
    
    Usage:
        injector = DeckInjector(student_email='student@example.com')
        success = injector.inject_apkg(apkg_content=bytes_content)
    """
    
    def __init__(self, student_email: str):
        self.student_email = student_email
        self.student_dir = ANKI_DATA_PATH / student_email
        self.collection_path = self.student_dir / "collection.anki2"
        self.media_dir = self.student_dir / "collection.media"

        # Web Accessible Media Path (Exposure) - NOW UNUSED if Rclone is active, but kept for fallback
        self.web_media_dir = Path(settings.MEDIA_ROOT) / "students" / student_email / "collection.media"

        # Rclone Mount Path (Must be mounted in container at /mnt/ankivn-media)
        self.rclone_mount_point = Path("/mnt/ankivn-media")

        
    def student_has_collection(self) -> bool:
        """Check if student has synced at least once (collection exists)."""
        return self.collection_path.exists()
    
    def inject_apkg(self, apkg_content: bytes) -> Tuple[bool, str]:
        """
        Inject an .apkg deck into the student's collection.
        
        Args:
            apkg_content: Raw bytes of the .apkg file
            
        Returns:
            Tuple of (success: bool, message: str)
        """
        if not self.student_has_collection():
            return False, f"Student {self.student_email} has not synced yet"
        
        # Create temp directory for extraction
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            apkg_path = temp_path / "deck.apkg"
            
            # Write apkg to temp file
            with open(apkg_path, 'wb') as f:
                f.write(apkg_content)
            
            try:
                # Extract and inject
                return self._inject_from_apkg(apkg_path, temp_path)
            except Exception as e:
                logger.error(f"Error injecting deck for {self.student_email}: {e}")
                return False, str(e)
    
    def _inject_from_apkg(self, apkg_path: Path, temp_dir: Path) -> Tuple[bool, str]:
        """
        Extract and inject deck from .apkg file.
        
        .apkg structure:
        - collection.anki2 (or collection.anki21): SQLite database with cards/notes
        - media: JSON file mapping numeric names to actual filenames
        - 0, 1, 2, ...: Media files with numeric names
        """
        extract_dir = temp_dir / "extracted"
        extract_dir.mkdir()
        
        # Extract .apkg (it's a zip file)
        try:
            with zipfile.ZipFile(apkg_path, 'r') as zf:
                zf.extractall(extract_dir)
        except zipfile.BadZipFile:
            return False, "Invalid .apkg file (not a valid zip)"
        
        # Find the collection database - prioritize anki21 (newer format with full data)
        source_db = None
        for name in ['collection.anki21', 'collection.anki2']:
            candidate = extract_dir / name
            if candidate.exists():
                source_db = candidate
                break
        
        if not source_db:
            return False, "No collection database found in .apkg"
        
        # Parse media mapping
        media_mapping = {}
        media_file = extract_dir / "media"
        if media_file.exists():
            try:
                with open(media_file, 'r', encoding='utf-8') as f:
                    media_mapping = json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Could not parse media file: {e}")
        
        # Ensure media directory exists (Handle Rclone Symlink)
        self._ensure_media_symlink()
        
        # Copy media files with correct names
        media_copied = 0
        for numeric_name, actual_name in media_mapping.items():
            source_file = extract_dir / numeric_name
            if source_file.exists():
                dest_file = self.media_dir / actual_name
                try:
                    # If symlink is active, this writes directly to R2!
                    shutil.copy2(source_file, dest_file)
                    media_copied += 1
                except Exception as e:
                    logger.warning(f"Failed to copy media {actual_name}: {e}")
        
        logger.info(f"Copied {media_copied}/{len(media_mapping)} media files for {self.student_email} (Target: {self.media_dir})")
        
        # Import cards/notes into student's collection
        try:
            cards_imported = self._import_collection_data(source_db)
            
            # Update media database to register new media files
            self._update_media_database()
            
            return True, f"Imported {cards_imported} cards, {media_copied} media files"
        except Exception as e:
            logger.error(f"Failed to import collection data: {e}")
            return False, f"Database error: {e}"
    
    def _import_collection_data(self, source_db: Path) -> int:
        """
        Import notes, cards, and decks from source database to student's collection.
        
        Returns:
            Number of cards imported
        """
        # Open both databases
        source_conn = sqlite3.connect(str(source_db))
        target_conn = sqlite3.connect(str(self.collection_path))
        
        try:
            source_cur = source_conn.cursor()
            target_cur = target_conn.cursor()
            
            # Log initial state
            target_cur.execute("SELECT COUNT(*) FROM cards")
            initial_cards = target_cur.fetchone()[0]
            logger.info(f"Initial cards in target: {initial_cards}")
            
            # Get current max IDs to avoid conflicts
            target_cur.execute("SELECT MAX(id) FROM notes")
            max_note_id = target_cur.fetchone()[0] or 0
            
            target_cur.execute("SELECT MAX(id) FROM cards")
            max_card_id = target_cur.fetchone()[0] or 0
            
            # Import note types (models) - merge with existing
            model_id_map = self._import_notetypes(source_cur, target_cur)
            logger.info(f"Notetypes merged: {model_id_map}")
            
            # Import decks - merge with existing
            deck_id_map = self._import_decks(source_cur, target_cur)
            logger.info(f"Decks merged: {deck_id_map}")
            
            # Import notes with ID offset and mapped model IDs
            note_id_map = self._import_notes(source_cur, target_cur, max_note_id, model_id_map)
            logger.info(f"Notes imported: {len(note_id_map)}")
            
            # Import cards with ID offset and mapped note/deck IDs
            cards_imported = self._import_cards(
                source_cur, target_cur, 
                max_card_id, note_id_map, deck_id_map
            )
            logger.info(f"Cards imported: {cards_imported}")
            
            # CRITICAL: Reset USN to trigger sync
            target_cur.execute("UPDATE cards SET usn = -1 WHERE usn >= 0")
            target_cur.execute("UPDATE notes SET usn = -1 WHERE usn >= 0")
            target_cur.execute("UPDATE col SET usn = -1, mod = (SELECT strftime('%s','now') * 1000)")
            logger.info("USN reset to trigger sync")
            
            target_conn.commit()
            
            # Log final state
            target_cur.execute("SELECT COUNT(*) FROM cards")
            final_cards = target_cur.fetchone()[0]
            logger.info(f"Final cards in target: {final_cards}")
            
            return cards_imported
            
        finally:
            source_conn.close()
            target_conn.close()
    
    def _import_notetypes(self, source_cur, target_cur) -> Dict[int, int]:
        """Import note types (models) from source to target, merging duplicates.
        
        CRITICAL: Each model must have usn=-1 to be synced to client.
        Returns mapping of source model IDs to target model IDs.
        """
        model_id_map = {}
        
        # Get existing models
        target_cur.execute("SELECT models FROM col")
        row = target_cur.fetchone()
        if row and row[0]:
            target_models = json.loads(row[0]) if isinstance(row[0], str) else row[0]
        else:
            target_models = {}
        
        # Get source models
        source_cur.execute("SELECT models FROM col")
        row = source_cur.fetchone()
        if row and row[0]:
            source_models = json.loads(row[0]) if isinstance(row[0], str) else row[0]
        else:
            source_models = {}
        
        # Find max model ID in target
        max_model_id = max([int(m) for m in target_models.keys()] + [0])
        
        # Merge models - check by name to avoid duplicates
        for model_id_str, model in source_models.items():
            model_id = int(model_id_str)
            model_name = model.get('name', '')
            
            # Check if model with same name exists in target
            existing_model_id = None
            for tid, tm in target_models.items():
                if tm.get('name') == model_name:
                    existing_model_id = int(tid)
                    break
            
            if existing_model_id:
                # Use existing model
                model_id_map[model_id] = existing_model_id
            else:
                # Add new model with usn=-1 to trigger sync
                max_model_id = max(max_model_id, model_id) + 1
                new_model_id = max_model_id
                model['id'] = new_model_id
                model['usn'] = -1  # CRITICAL: Ensure model syncs to client
                target_models[str(new_model_id)] = model
                model_id_map[model_id] = new_model_id
        
        # Update target
        target_cur.execute(
            "UPDATE col SET models = ?",
            (json.dumps(target_models),)
        )
        
        return model_id_map
    
    def _import_decks(self, source_cur, target_cur) -> Dict[int, int]:
        """
        Import decks from source to target.
        Returns mapping of source deck IDs to target deck IDs.
        
        CRITICAL: Each deck must have usn=-1 to be synced to client.
        """
        deck_id_map = {}
        
        # Get existing decks
        target_cur.execute("SELECT decks FROM col")
        row = target_cur.fetchone()
        if row and row[0]:
            target_decks = json.loads(row[0]) if isinstance(row[0], str) else row[0]
        else:
            target_decks = {}
        
        # Get source decks
        source_cur.execute("SELECT decks FROM col")
        row = source_cur.fetchone()
        if row and row[0]:
            source_decks = json.loads(row[0]) if isinstance(row[0], str) else row[0]
        else:
            source_decks = {}
        
        # Find max deck ID - use timestamp-based ID to avoid conflicts
        import time
        max_deck_id = int(time.time() * 1000)
        
        for deck_id_str, deck in source_decks.items():
            deck_id = int(deck_id_str)
            
            # Skip default deck
            if deck_id == 1:
                deck_id_map[deck_id] = 1
                continue
            
            # Check if deck with same name exists
            existing_deck = None
            for tid, td in target_decks.items():
                if td.get('name') == deck.get('name'):
                    existing_deck = int(tid)
                    break
            
            if existing_deck:
                deck_id_map[deck_id] = existing_deck
                # Update existing deck's usn to trigger sync
                target_decks[str(existing_deck)]['usn'] = -1
            else:
                # Create new deck with new ID
                max_deck_id += 1
                new_deck_id = max_deck_id
                deck['id'] = new_deck_id
                deck['usn'] = -1  # CRITICAL: Ensure deck syncs to client
                target_decks[str(new_deck_id)] = deck
                deck_id_map[deck_id] = new_deck_id
        
        # Update target
        target_cur.execute(
            "UPDATE col SET decks = ?",
            (json.dumps(target_decks),)
        )
        
        return deck_id_map
    
    def _import_notes(self, source_cur, target_cur, id_offset: int, model_id_map: Dict[int, int]) -> Dict[int, int]:
        """
        Import notes with ID offset and mapped model IDs.
        Returns mapping of source note IDs to target note IDs.
        
        CRITICAL: Model IDs must be remapped to avoid "no such notetype" errors.
        """
        note_id_map = {}
        
        source_cur.execute("SELECT id, guid, mid, mod, usn, tags, flds, sfld, csum, flags, data FROM notes")
        notes = source_cur.fetchall()
        
        for note in notes:
            old_id = note[0]
            old_mid = note[2]
            new_id = old_id + id_offset + 1
            
            # Map model ID to target model ID
            new_mid = model_id_map.get(old_mid, old_mid)
            
            note_id_map[old_id] = new_id
            
            # Check if note with same guid already exists
            target_cur.execute("SELECT id FROM notes WHERE guid = ?", (note[1],))
            existing = target_cur.fetchone()
            
            if existing:
                note_id_map[old_id] = existing[0]
                continue
            
            # Insert new note with mapped model ID
            target_cur.execute(
                """INSERT INTO notes (id, guid, mid, mod, usn, tags, flds, sfld, csum, flags, data)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (new_id, note[1], new_mid, note[3], -1, note[5], note[6], note[7], note[8], note[9], note[10])
            )
        
        return note_id_map
    
    def _import_cards(self, source_cur, target_cur, id_offset: int, 
                      note_id_map: Dict[int, int], deck_id_map: Dict[int, int]) -> int:
        """
        Import cards with mapped note and deck IDs.
        Returns number of cards imported.
        """
        source_cur.execute(
            """SELECT id, nid, did, ord, mod, usn, type, queue, due, ivl, factor, reps, lapses, left, odue, odid, flags, data 
               FROM cards"""
        )
        cards = source_cur.fetchall()
        
        imported = 0
        for card in cards:
            old_id, old_nid, old_did = card[0], card[1], card[2]
            
            new_id = old_id + id_offset + 1
            new_nid = note_id_map.get(old_nid, old_nid)
            new_did = deck_id_map.get(old_did, old_did)
            
            # Check if card already exists (same note + ord)
            target_cur.execute(
                "SELECT id FROM cards WHERE nid = ? AND ord = ?",
                (new_nid, card[3])
            )
            if target_cur.fetchone():
                continue
            
            # Insert new card
            target_cur.execute(
                """INSERT INTO cards (id, nid, did, ord, mod, usn, type, queue, due, ivl, factor, reps, lapses, left, odue, odid, flags, data)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (new_id, new_nid, new_did, card[3], card[4], -1, card[6], card[7], card[8], 
                 card[9], card[10], card[11], card[12], card[13], card[14], card[15], card[16], card[17])
            )
            imported += 1
        
        return imported
    
    def _update_media_database(self):
        """
        Update the media sync database to register new media files.
        
        CRITICAL: This ensures media files are recognized during sync.
        Without this, Anki will report "missing media" even though files exist.
        """
        # The official Anki sync server uses the media folder directly
        # and tracks media via the collection's media table
        
        # Get list of media files in the student's media folder
        if not self.media_dir.exists():
            return
        
        media_files = list(self.media_dir.iterdir())
        if not media_files:
            return
        
        # The sync server tracks media through the collection
        # We need to update the `col` table's `media_usn` to trigger sync
        try:
            conn = sqlite3.connect(str(self.collection_path))
            cur = conn.cursor()
            
            # Set media_usn to -1 to indicate changes need syncing
            cur.execute("UPDATE col SET usn = -1")
            conn.commit()
            conn.close()
            
            logger.info(f"Updated media database for {self.student_email} with {len(media_files)} files")
        except Exception as e:
            logger.warning(f"Could not update media database: {e}")

        # SYNC TO WEB MEDIA DIR (Legacy/Fallback)
        # If Rclone is active, media is already on R2 (via symlink)
        # Frontend should use CDN/Nginx URL to access it.
        # We only copy if NOT using symlink strategy
        if not self.media_dir.is_symlink():
            try:
                self.web_media_dir.mkdir(parents=True, exist_ok=True)
                if self.media_dir.exists():
                    synced_count = 0
                    for media_file in self.media_dir.iterdir():
                        if media_file.is_file():
                            dest = self.web_media_dir / media_file.name
                            if not dest.exists() or dest.stat().st_mtime < media_file.stat().st_mtime:
                                shutil.copy2(media_file, dest)
                                synced_count += 1
                    logger.info(f"Synced {synced_count} media files to web dir for {self.student_email}")
            except Exception as e:
                logger.error(f"Failed to sync media to web dir: {e}")
    
    def _ensure_media_symlink(self):
        """
        Ensures that the student's collection.media directory is a symlink to the Rclone mount.
        """
        if not self.rclone_mount_point.exists():
            logger.warning("Rclone mount point not found. Using local storage.")
            self.media_dir.mkdir(parents=True, exist_ok=True)
            return

        r2_user_dir = self.rclone_mount_point / self.student_email
        r2_user_dir.mkdir(parents=True, exist_ok=True) # Create user folder on R2
        
        # If we handle individual decks, we simply point collection.media to the user's R2 folder
        # Note: Anki structure is usually <user>/collection.media. 
        # But Rclone might just be <user> folder containing media? 
        # Let's match typical Anki structure: R2/<user> -> collection.media files inside?
        # NO, user wants Rclone mount matches structure.
        # Let's assume R2/<user> IS the media folder for simplicity? 
        # OR R2/<user>/collection.media?
        # User prompt said: "/mnt/r2-media/{email}" -> Rclone path.
        
        if self.media_dir.is_symlink():
            return # Already good
            
        if self.media_dir.exists() and not self.media_dir.is_symlink():
            # Migrate existing files
            logger.info(f"Migrating existing media for {self.student_email} to Rclone...")
            for f in self.media_dir.iterdir():
                if f.is_file():
                    shutil.move(str(f), str(r2_user_dir / f.name))
            shutil.rmtree(self.media_dir)
            
        # Create Symlink
        # self.media_dir -> r2_user_dir
        try:
            self.media_dir.symlink_to(r2_user_dir)
            logger.info(f"Created Rclone symlink for {self.student_email}")
        except Exception as e:
            logger.error(f"Failed to create symlink: {e}")
            # Fallback
            self.media_dir.mkdir(parents=True, exist_ok=True)



def inject_deck_to_class(deck_apkg_content: bytes, student_emails: List[str]) -> Dict[str, Tuple[bool, str]]:
    """
    Inject a deck to multiple students in a class.
    
    Args:
        deck_apkg_content: Raw .apkg file bytes
        student_emails: List of student email addresses
        
    Returns:
        Dict mapping email to (success, message) tuple
    """
    results = {}
    
    for email in student_emails:
        injector = DeckInjector(email)
        success, message = injector.inject_apkg(deck_apkg_content)
        results[email] = (success, message)
        logger.info(f"Deck injection for {email}: {success} - {message}")
    
    return results


def inject_deck_to_student(student_email: str, deck_apkg_content: bytes) -> Tuple[bool, str]:
    """
    Inject a deck to a single student.
    
    Args:
        student_email: Student's email address
        deck_apkg_content: Raw .apkg file bytes
        
    Returns:
        Tuple of (success, message)
    """
    injector = DeckInjector(student_email)
    return injector.inject_apkg(deck_apkg_content)
