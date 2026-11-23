"""Снятие UNIQUE с items.rel_path: один скрин может относиться к нескольким фильмам."""
import shutil
import sqlite3
import time

DB = "/home/nik/shotbox/data/shotbox.db"
BAK = f"/home/nik/shotbox/data/shotbox.db.bak.{time.strftime('%Y%m%d_%H%M%S')}"

shutil.copy2(DB, BAK)
print("бэкап:", BAK)

con = sqlite3.connect(DB)
con.execute("PRAGMA foreign_keys=OFF")

cols = [r[1] for r in con.execute("PRAGMA table_info(items)")]
print("колонок:", len(cols))

con.executescript("""
CREATE TABLE items_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rel_path TEXT,
    thumb TEXT,
    app TEXT,
    shot_date TEXT,
    category TEXT DEFAULT 'не разобрано',
    title TEXT DEFAULT '',
    text TEXT DEFAULT '',
    review TEXT DEFAULT '',
    rating INTEGER DEFAULT 0,
    url TEXT DEFAULT '',
    analyzed INTEGER DEFAULT 0,
    added_at TEXT DEFAULT CURRENT_TIMESTAMP,
    content_hash TEXT,
    dup_of INTEGER DEFAULT NULL,
    year INTEGER,
    imdb REAL,
    status TEXT,
    genre TEXT,
    enriched INTEGER DEFAULT 0,
    watched INTEGER DEFAULT 0,
    kp_rating REAL,
    kp_id INTEGER,
    poster TEXT,
    favorite INTEGER DEFAULT 0,
    needs_review INTEGER DEFAULT 0
);
""")

col_list = ", ".join(cols)
con.execute(f"INSERT INTO items_new ({col_list}) SELECT {col_list} FROM items")
n = con.execute("SELECT COUNT(*) FROM items_new").fetchone()[0]
print("перенесено записей:", n)

con.execute("DROP TABLE items")
con.execute("ALTER TABLE items_new RENAME TO items")
con.execute("CREATE INDEX IF NOT EXISTS idx_cat ON items(category)")
con.execute("CREATE INDEX IF NOT EXISTS idx_relpath ON items(rel_path)")
con.commit()

print("записей после миграции:", con.execute("SELECT COUNT(*) FROM items").fetchone()[0])
print("UNIQUE остался:",
      "UNIQUE" in (con.execute("SELECT sql FROM sqlite_master WHERE name='items'").fetchone()[0]))
con.close()
