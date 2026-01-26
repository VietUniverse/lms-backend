import sqlite3
import os

db_path = 'db.sqlite3'
if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = [t[0] for t in cursor.fetchall()]
    print("=== ALL LMS Tables in Database ===")
    for t in tables:
        if 'lms' in t.lower() or 'assignment' in t.lower() or 'study' in t.lower() or 'card' in t.lower():
            # Get column info
            cursor.execute(f"PRAGMA table_info({t})")
            cols = cursor.fetchall()
            print(f"\n{t}:")
            for col in cols[:5]:  # Show first 5 columns
                print(f"  - {col[1]} ({col[2]})")
            if len(cols) > 5:
                print(f"  ... and {len(cols)-5} more columns")
    conn.close()
else:
    print(f"Database {db_path} not found")
