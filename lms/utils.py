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
    Parse an Anki .apkg file, extract cards, and upload media to Appwrite.
    """
    import json
    import re

    cards = []
    temp_dir = tempfile.mkdtemp()
    
    # Appwrite Config
    appwrite_url = f"{settings.APPWRITE_ENDPOINT}/storage/buckets/{settings.APPWRITE_BUCKET_ID}/files"
    headers = {
        "X-Appwrite-Project": settings.APPWRITE_PROJECT_ID,
        "X-Appwrite-Key": settings.APPWRITE_API_KEY,
    }

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

                # Upload each media file
                for zip_name, filename in media_map.items():
                    # Skip if not an image (audio/video support can be added later)
                    if not any(filename.lower().endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.gif', '.svg', '.webp']):
                         continue

                    file_path = os.path.join(temp_dir, zip_name)
                    if os.path.exists(file_path):
                        # Upload to Appwrite
                        try:
                            with open(file_path, 'rb') as img_file:
                                files = {'fileId': 'unique()', 'file': (filename, img_file)}
                                # Use separate headers for upload because 'Content-Type' is set by requests
                                upload_headers = {
                                    "X-Appwrite-Project": settings.APPWRITE_PROJECT_ID,
                                    "X-Appwrite-Key": settings.APPWRITE_API_KEY,
                                }
                                res = requests.post(appwrite_url, headers=upload_headers, files=files)
                                
                                if res.status_code in [200, 201]:
                                    file_id = res.json()['$id']
                                    # Construct View URL
                                    view_url = f"{settings.APPWRITE_ENDPOINT}/storage/buckets/{settings.APPWRITE_BUCKET_ID}/files/{file_id}/view?project={settings.APPWRITE_PROJECT_ID}"
                                    url_mapping[filename] = view_url
                                else:
                                    print(f"Failed to upload {filename}: {res.text}")
                        except Exception as e:
                            print(f"Error uploading {filename}: {e}")
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
            """Replace src="filename" with src="url" """
            for filename, url in url_mapping.items():
                # Simple string replacement (can be optimized with regex for exact matches inside src="")
                # Anki usually puts filename directly or urlencoded. 
                # This is a basic replacement that works for most cases.
                if filename in content:
                    content = content.replace(f'src="{filename}"', f'src="{url}"')
                    content = content.replace(f"src='{filename}'", f"src='{url}'")
                    # Handle unquoted (rare but possible in old HTMl)
                    # content = content.replace(filename, url) # Too risky
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
