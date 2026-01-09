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
        db_path = os.path.join(temp_dir, "collection.anki2")
        if not os.path.exists(db_path):
            db_path = os.path.join(temp_dir, "collection.anki21")
        
        if not os.path.exists(db_path):
            print("Error: collection.anki2 not found in .apkg")
            return []
        
        # Connect to SQLite
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Query the notes table
        # fields are separated by 0x1f (unit separator)
        try:
            cursor.execute("SELECT id, flds FROM notes")
            rows = cursor.fetchall()
            print(f"Found {len(rows)} notes in Anki database.")
        except sqlite3.OperationalError as e:
            print(f"SQLite Error: {e}")
            conn.close()
            return []
        
        for note_id, fields_str in rows:
            # 0x1f is the standard separator for Anki fields
            fields = fields_str.split('\x1f')
            
            if not fields:
                continue
                
            front = fields[0].strip()
            
            # Combine all remaining fields for the Back (Answer)
            # This ensures we don't lose data for complex Note Types
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
        print(f"Successfully parsed {len(cards)} cards.")
        
    except Exception as e:
        print(f"Parse error: {e}")
        return []
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
    
    return cards
