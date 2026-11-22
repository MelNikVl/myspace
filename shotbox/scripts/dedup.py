"""Дедупликация: считаем md5 содержимого, помечаем копии."""
import hashlib
import os
import sqlite3

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(BASE, "data", "shotbox.db")
PHOTOS = os.path.join(BASE, "photos")

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row

cols = [r[1] for r in con.execute("PRAGMA table_info(items)")]
if "content_hash" not in cols:
    con.execute("ALTER TABLE items ADD COLUMN content_hash TEXT")
if "dup_of" not in cols:
    con.execute("ALTER TABLE items ADD COLUMN dup_of INTEGER DEFAULT NULL")
con.commit()

rows = con.execute("SELECT id, rel_path, content_hash FROM items").fetchall()
seen = {}
updated = 0
for r in rows:
    if r["content_hash"]:
        seen.setdefault(r["content_hash"], r["id"])
        continue
    p = os.path.join(PHOTOS, r["rel_path"])
    if not os.path.exists(p):
        continue
    h = hashlib.md5(open(p, "rb").read()).hexdigest()
    con.execute("UPDATE items SET content_hash=? WHERE id=?", (h, r["id"]))
    if h in seen:
        con.execute("UPDATE items SET dup_of=? WHERE id=?", (seen[h], r["id"]))
    else:
        seen[h] = r["id"]
    updated += 1

con.commit()
dups = con.execute("SELECT COUNT(*) FROM items WHERE dup_of IS NOT NULL").fetchone()[0]
uniq = con.execute("SELECT COUNT(DISTINCT content_hash) FROM items").fetchone()[0]
print(f"обновлено: {updated} | дублей: {dups} | уникальных: {uniq} из {len(rows)}")
con.close()
