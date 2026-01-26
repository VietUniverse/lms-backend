import sqlite3
import json
from datetime import datetime

conn = sqlite3.connect('collection.anki2')
cur = conn.cursor()

print('=== TABLES ===')
cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
for row in cur.fetchall():
    print(f'  {row[0]}')

print()
print('=== DECKS ===')
cur.execute('SELECT decks FROM col')
decks = json.loads(cur.fetchone()[0])
for did, data in decks.items():
    cur.execute(f"SELECT COUNT(*) FROM cards WHERE did = {did}")
    cards = cur.fetchone()[0]
    print(f'  {data["name"]}: {cards} cards')

print()
print('=== STATS ===')
cur.execute('SELECT COUNT(*) FROM cards')
print(f'Total cards: {cur.fetchone()[0]}')
cur.execute('SELECT COUNT(*) FROM notes')
print(f'Total notes: {cur.fetchone()[0]}')
cur.execute('SELECT COUNT(*) FROM revlog')
print(f'Total revlogs: {cur.fetchone()[0]}')

print()
print('=== REVLOG SAMPLE (for heatmap) ===')
cur.execute('SELECT id, cid, ease, time FROM revlog ORDER BY id DESC LIMIT 10')
for row in cur.fetchall():
    ts = row[0] // 1000
    dt = datetime.fromtimestamp(ts)
    print(f'  {dt}: ease={row[2]}, time={row[3]}ms')

print()
print('=== HEATMAP DATA (reviews per day) ===')
cur.execute('''
    SELECT date(id/1000, 'unixepoch', 'localtime') as day, COUNT(*) as reviews
    FROM revlog
    GROUP BY day
    ORDER BY day DESC
    LIMIT 30
''')
for row in cur.fetchall():
    print(f'  {row[0]}: {row[1]} reviews')

conn.close()
