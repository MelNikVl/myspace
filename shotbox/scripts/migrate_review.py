import sqlite3
con = sqlite3.connect("/home/nik/shotbox/data/shotbox.db")
cols = [r[1] for r in con.execute("PRAGMA table_info(items)")]
if "needs_review" not in cols:
    con.execute("ALTER TABLE items ADD COLUMN needs_review INTEGER DEFAULT 0")
    print("добавлено: needs_review")
con.commit(); con.close()
