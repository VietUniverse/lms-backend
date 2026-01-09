"""
Utility functions for Anki file parsing.
"""
import os
import sqlite3
import tempfile
import zipfile
import shutil
import requests
from django.conf import settings


def download_from_appwrite(file_id: str, dest_path: str) -> None:
    """Download a file from Appwrite Storage to a local path."""
    url = f"{settings.APPWRITE_ENDPOINT}/storage/buckets/{settings.APPWRITE_BUCKET_ID}/files/{file_id}/download"
    headers = {
        "X-Appwrite-Project": settings.APPWRITE_PROJECT_ID,
        "X-Appwrite-Key": settings.APPWRITE_API_KEY,
    }
    response = requests.get(url, headers=headers, stream=True)
    response.raise_for_status()
    with open(dest_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)


def parse_anki_file(apkg_path: str) -> list[dict]:
    """
    Parse an Anki .apkg file and extract cards.
    Handles multiple Note Types by treating the first field as Front
    and combining all other fields as Back.
    """
    cards = []
    temp_dir = tempfile.mkdtemp()
    
    try:
        # Extract the .apkg (it's a ZIP file)
        with zipfile.ZipFile(apkg_path, 'r') as zip_ref:
            zip_ref.extractall(temp_dir)
        
        # Find the SQLite database
        # Some .apkg files have both collection.anki2 and collection.anki21
        # We need to find the one with actual data
        db_path_20 = os.path.join(temp_dir, "collection.anki2")
        db_path_21 = os.path.join(temp_dir, "collection.anki21")
        
        # Anki 2.1.50+ uses collection.anki21 for real data
        # collection.anki2 is often a dummy/placeholder
        best_db = None
        if os.path.exists(db_path_21):
            best_db = db_path_21
            print("Using DB: collection.anki21 (Priority)")
        elif os.path.exists(db_path_20):
            best_db = db_path_20
            print("Using DB: collection.anki2 (Fallback)")
            
        if not best_db:
            print("Error: No Anki database found in .apkg")
            return []

        # Connect to SQLite
        conn = sqlite3.connect(best_db)
        cursor = conn.cursor()
        
        # Query the notes table but ONLY for notes that have associated cards
        # This matches apkg.py logic: "Join bảng cards để biết Note thuộc Deck nào"
        # Since we are importing the whole file as one Deck, we just want to ensure
        # we only get Notes that are actually used in Cards.
        try:
            # Get valid Note IDs from cards table
            cursor.execute("SELECT DISTINCT nid FROM cards")
            valid_nids = {row[0] for row in cursor.fetchall()}
            
            # Get all notes
            cursor.execute("SELECT id, flds FROM notes")
            rows = cursor.fetchall()
            
            print(f"Found {len(rows)} raw notes. Valid notes with cards: {len(valid_nids)}")
        except sqlite3.OperationalError as e:
            print(f"SQLite Error: {e}")
            conn.close()
            return []
        
        for note_id, fields_str in rows:
            # Filter: Only process notes that correspond to actual cards
            if note_id not in valid_nids:
                continue

            # 0x1f is the standard separator for Anki fields
            fields = fields_str.split('\x1f')
            
            if not fields:
                continue
                
            front = fields[0].strip()
            
            # Combine all remaining fields for the Back (Answer)
            if len(fields) > 1:
                # Use <hr> or <br> to separate fields visually
                back = "<br><hr><br>".join([f.strip() for f in fields[1:] if f.strip()])
            else:
                back = "<i>(No content on back)</i>"
            
            # Skip completely empty cards
            if not front and len(fields) == 1:
                continue
                
            cards.append({
                "front": front,
                "back": back,
                "note_id": str(note_id),
            })
        
        conn.close()
        print(f"Successfully parsed {len(cards)} valid notes (cards).")
        
    except Exception as e:
        print(f"Parse error: {e}")
        return []
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
    
    return cards
