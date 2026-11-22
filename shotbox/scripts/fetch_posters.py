"""Скачивание официальных постеров фильмов с Кинопоиска (без API-запросов)."""
import os
import sqlite3
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "data", "shotbox.db")
POSTERS = os.path.join(BASE, "posters")
os.makedirs(POSTERS, exist_ok=True)

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
cols = [r[1] for r in con.execute("PRAGMA table_info(items)")]
if "poster" not in cols:
    con.execute("ALTER TABLE items ADD COLUMN poster TEXT")
con.commit()

rows = con.execute(
    "SELECT id, kp_id FROM items WHERE kp_id IS NOT NULL AND (poster IS NULL OR poster='')"
).fetchall()
print(f"постеров к загрузке: {len(rows)}", flush=True)

ok = fail = 0
for r in rows:
    kp = r["kp_id"]
    url = f"https://kinopoiskapiunofficial.tech/images/posters/kp_small/{kp}.jpg"
    name = f"{kp}.jpg"
    path = os.path.join(POSTERS, name)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=25) as resp:
            data = resp.read()
        if len(data) < 2000 or not data[:2] == b"\xff\xd8":
            raise ValueError("not a jpeg")
        open(path, "wb").write(data)
        con.execute("UPDATE items SET poster=? WHERE id=?", (name, r["id"]))
        con.commit()
        ok += 1
    except Exception as e:
        fail += 1
        print(f"  ✗ {kp}: {type(e).__name__}", flush=True)

print(f"ГОТОВО: скачано {ok}, ошибок {fail}")
print("всего с постером:", con.execute("SELECT COUNT(*) FROM items WHERE poster IS NOT NULL AND poster != ''").fetchone()[0])
con.close()
