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
    
    Args:
        apkg_path: Path to the .apkg file.
        
    Returns:
        List of dicts with 'front', 'back', 'note_id' keys.
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
            # Try alternative name
            db_path = os.path.join(temp_dir, "collection.anki21")
        
        if not os.path.exists(db_path):
            raise FileNotFoundError("Could not find Anki database in .apkg file")
        
        # Connect to SQLite and extract notes
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Query the notes table - fields are separated by 0x1f (unit separator)
        cursor.execute("SELECT id, flds FROM notes")
        rows = cursor.fetchall()
        
        for note_id, fields_str in rows:
            # Split fields by the unit separator character
            fields = fields_str.split('\x1f')
            
            if len(fields) >= 2:
                front = fields[0].strip()
                back = fields[1].strip()
            elif len(fields) == 1:
                front = fields[0].strip()
                back = ""
            else:
                continue
            
            # Skip empty cards
            if not front:
                continue
                
            cards.append({
                "front": front,
                "back": back,
                "note_id": str(note_id),
            })
        
        conn.close()
        
    finally:
        # Always cleanup temp directory
        shutil.rmtree(temp_dir, ignore_errors=True)
    
    return cards
