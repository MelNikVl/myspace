"""Дозаполнение IMDb-рейтингов через OMDB API (для фильмов без рейтинга)."""
import json
import os
import sqlite3
import time
import urllib.parse
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "data", "shotbox.db")
KEY = os.environ.get("OMDB_KEY", "391664ba")


def omdb(title, year=None):
    q = {"apikey": KEY, "t": title, "type": "movie"}
    if year:
        q["y"] = str(year)
    url = "https://www.omdbapi.com/?" + urllib.parse.urlencode(q)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row

rows = con.execute(
    "SELECT id, title, year FROM items "
    "WHERE category IN ('фильм','сериал','мультфильм') AND dup_of IS NULL "
    "AND (imdb IS NULL OR imdb = 0) AND title IS NOT NULL AND title != ''"
).fetchall()
print(f"без IMDb-рейтинга: {len(rows)}", flush=True)

ok = 0
for it in rows:
    title = (it["title"] or "").strip()
    year = it["year"]
    got = None
    for t in [title]:
        for y in ([year, None] if year else [None]):
            try:
                d = omdb(t, y)
            except Exception as e:
                print(f"  ✗ {title[:30]}: {type(e).__name__}", flush=True)
                time.sleep(1)
                continue
            if d.get("Response") == "True" and d.get("imdbRating") not in (None, "N/A"):
                got = d
                break
            time.sleep(0.2)
        if got:
            break

    if not got:
        print(f"  — не найден: {title[:40]}", flush=True)
        time.sleep(0.3)
        continue

    try:
        imdb = round(float(got["imdbRating"]), 1)
    except Exception:
        imdb = None
    genre = (got.get("Genre") or "")[:120]
    plot = (got.get("Plot") or "")[:400]
    yr = got.get("Year", "")
    try:
        yr_int = int(str(yr)[:4])
    except Exception:
        yr_int = it["year"]

    con.execute(
        "UPDATE items SET imdb=COALESCE(?, imdb), genre=CASE WHEN ? != '' THEN ? ELSE genre END, "
        "year=COALESCE(year, ?), text=CASE WHEN (text IS NULL OR text='') AND ? != '' THEN ? ELSE text END "
        "WHERE id=?",
        (imdb, genre, genre, yr_int, plot, plot, it["id"]),
    )
    con.commit()
    ok += 1
    print(f"  ✓ {title[:35]:37} IMDb {imdb} ({yr})", flush=True)
    time.sleep(0.35)

print(f"\nГОТОВО: дозаполнено {ok} из {len(rows)}")
print("с IMDb:", con.execute(
    "SELECT COUNT(*) FROM items WHERE category IN ('фильм','сериал','мультфильм') "
    "AND imdb IS NOT NULL AND imdb > 0").fetchone()[0], "из",
    con.execute("SELECT COUNT(*) FROM items WHERE category IN ('фильм','сериал','мультфильм') "
                "AND dup_of IS NULL").fetchone()[0])
con.close()
