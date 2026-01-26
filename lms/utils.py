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
    import logging
    logger = logging.getLogger(__name__)
    
    url = f"{settings.APPWRITE_ENDPOINT}/storage/buckets/{settings.APPWRITE_BUCKET_ID}/files/{file_id}/download"
    headers = {
        "X-Appwrite-Project": settings.APPWRITE_PROJECT_ID,
        "X-Appwrite-Key": settings.APPWRITE_API_KEY,
    }
    
    logger.info(f"Downloading file {file_id} from Appwrite...")
    
    # Increase timeout for large files (35MB+)
    response = requests.get(url, headers=headers, stream=True, timeout=300)
    response.raise_for_status()
    
    # Get expected file size from headers
    expected_size = int(response.headers.get('Content-Length', 0))
    logger.info(f"Expected file size: {expected_size} bytes ({expected_size / 1024 / 1024:.2f} MB)")
    
    # Download with larger chunk size for big files
    chunk_size = 1024 * 1024  # 1MB chunks for faster download
    bytes_downloaded = 0
    
    with open(dest_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=chunk_size):
            if chunk:
                f.write(chunk)
                bytes_downloaded += len(chunk)
    
    # Verify downloaded size
    actual_size = os.path.getsize(dest_path)
    logger.info(f"Downloaded: {actual_size} bytes ({actual_size / 1024 / 1024:.2f} MB)")
    
    if expected_size > 0 and actual_size != expected_size:
        raise Exception(f"File size mismatch! Expected {expected_size}, got {actual_size}")
    
    logger.info(f"Download complete: {dest_path}")


def extract_deck_names(apkg_path: str) -> list[str]:
    """
    Extract deck names from an .apkg file.
    Supports both old (JSON in col.decks) and new (separate decks table) Anki formats.
    
    Returns:
        List of deck names found in the .apkg file
    """
    import json
    
    deck_names = []
    temp_dir = tempfile.mkdtemp()
    
    try:
        # Extract the .apkg
        with zipfile.ZipFile(apkg_path, 'r') as zip_ref:
            zip_ref.extractall(temp_dir)
        
        # Find database - prefer anki21 (newer format)
        db_path_20 = os.path.join(temp_dir, "collection.anki2")
        db_path_21 = os.path.join(temp_dir, "collection.anki21")
        best_db = db_path_21 if os.path.exists(db_path_21) else (db_path_20 if os.path.exists(db_path_20) else None)
        
        if not best_db:
            return []
        
        conn = sqlite3.connect(best_db)
        cursor = conn.cursor()
        
        try:
            # Check if new format (separate decks table)
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='decks'")
            has_decks_table = cursor.fetchone() is not None
            
            if has_decks_table:
                # New Anki 2.1.50+ format
                cursor.execute("SELECT name FROM decks WHERE name != 'Default'")
                deck_names = [row[0] for row in cursor.fetchall()]
            else:
                # Old format - JSON in col.decks
                cursor.execute("SELECT decks FROM col LIMIT 1")
                decks_json = cursor.fetchone()[0]
                if decks_json:
                    decks_data = json.loads(decks_json)
                    deck_names = [data.get('name') for data in decks_data.values() 
                                  if data.get('name') and data.get('name') != 'Default']
        except Exception as e:
            print(f"Error reading decks: {e}")
        finally:
            conn.close()
            
    except Exception as e:
        print(f"Error extracting deck names: {e}")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
    
    return deck_names


def get_primary_deck_name(apkg_path: str) -> str:
    """
    Get the primary (top-level, non-Default) deck name from an .apkg file.
    
    Returns:
        The primary deck name, or empty string if not found
    """
    deck_names = extract_deck_names(apkg_path)
    
    # Filter out subdecks (those containing ::) to get top-level decks
    top_level_decks = [name for name in deck_names if '::' not in name]
    
    if top_level_decks:
        return top_level_decks[0]
    elif deck_names:
        # If only subdecks exist, get the root deck name from the first subdeck
        return deck_names[0].split('::')[0]
    return ""


def parse_anki_file(apkg_path: str) -> list[dict]:
    """
    Parse an Anki .apkg file, extract cards, and save media to local storage (VPS).
    """
    import json
    
    cards = []
    temp_dir = tempfile.mkdtemp()
    
    # Destination for media files
    media_dir = os.path.join(settings.MEDIA_ROOT, 'anki_media')
    if not os.path.exists(media_dir):
        os.makedirs(media_dir)
        
    # Use ABSOLUTE URL for production
    # Hardcode for now or get from settings.ALLOWED_HOSTS[0]
    # Better to use a setting variable, but for quick fix:
    domain = "https://api.ankivn.com" 
    media_url_base = f"{domain}{settings.MEDIA_URL}anki_media/"

    try:
        # Extract the .apkg
        with zipfile.ZipFile(apkg_path, 'r') as zip_ref:
            zip_ref.extractall(temp_dir)
        
        # 1. Handle Media
        media_map = {}
        media_file_path = os.path.join(temp_dir, "media")
        url_mapping = {}  # filename -> public_url

        if os.path.exists(media_file_path):
            try:
                with open(media_file_path, 'r') as f:
                    media_map = json.load(f) # {"0": "image.jpg", ...}
                
                print(f"Found {len(media_map)} media files.")

                # Process each media file
                for zip_name, filename in media_map.items():
                    # Skip if not an image (audio/video support can be added later if needed)
                    if not any(filename.lower().endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.gif', '.svg', '.webp']):
                         continue

                    src_path = os.path.join(temp_dir, zip_name)
                    dest_path = os.path.join(media_dir, filename)
                    
                    if os.path.exists(src_path):
                        # Copy file to media directory
                        # Use copy2 to preserve metadata, or just copy
                        try:
                            shutil.copy2(src_path, dest_path)
                            # Generate URL
                            url_mapping[filename] = f"{media_url_base}{filename}"
                        except Exception as e:
                            print(f"Error copying {filename}: {e}")
            except Exception as e:
                print(f"Error processing media file: {e}")

        # 2. Find Database
        db_path_20 = os.path.join(temp_dir, "collection.anki2")
        db_path_21 = os.path.join(temp_dir, "collection.anki21")
        best_db = db_path_21 if os.path.exists(db_path_21) else (db_path_20 if os.path.exists(db_path_20) else None)
            
        if not best_db:
            print("Error: No Anki database found")
            return []

        # Connect to SQLite
        conn = sqlite3.connect(best_db)
        cursor = conn.cursor()
        
        try:
            cursor.execute("SELECT DISTINCT nid FROM cards")
            valid_nids = {row[0] for row in cursor.fetchall()}
            
            cursor.execute("SELECT id, flds FROM notes")
            rows = cursor.fetchall()
            
            print(f"Found {len(rows)} raw notes. Valid notes: {len(valid_nids)}")
        except sqlite3.OperationalError as e:
            print(f"SQLite Error: {e}")
            conn.close()
            return []
        
        def replace_media_src(content):
            """Replace src="filename" with src="/media/anki_media/filename" """
            for filename, url in url_mapping.items():
                if filename in content:
                    content = content.replace(f'src="{filename}"', f'src="{url}"')
                    content = content.replace(f"src='{filename}'", f"src='{url}'")
            return content

        for note_id, fields_str in rows:
            if note_id not in valid_nids:
                continue

            fields = fields_str.split('\x1f')
            if not fields:
                continue
                
            front = fields[0].strip()
            if len(fields) > 1:
                back = "<br><hr><br>".join([f.strip() for f in fields[1:] if f.strip()])
            else:
                back = "<i>(No content on back)</i>"
            
            # Replace media URLs
            front = replace_media_src(front)
            back = replace_media_src(back)

            if not front and len(fields) == 1:
                continue
                
            cards.append({
                "front": front,
                "back": back,
                "note_id": str(note_id),
            })
        
        conn.close()
        print(f"Parsed {len(cards)} cards.")
        
    except Exception as e:
        print(f"Parse error: {e}")
        return []
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
    
    return cards
