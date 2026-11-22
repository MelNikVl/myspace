"""Парсер метаданных фильмов через Kinopoisk API (без ИИ).
Поиск по названию → детали → год, рейтинги IMDb/КП, жанры, описание, статус."""
import json
import os
import re
import sqlite3
import time
import urllib.parse
from urllib.error import HTTPError
from urllib.request import Request, urlopen

KEY = os.environ.get("KP_KEY", "7477ebc7-262b-4ce0-b145-0330de4a6d07")
DB = "/home/nik/shotbox/data/shotbox.db"
BASE = "https://kinopoiskapiunofficial.tech"
HDRS = {"X-API-KEY": KEY, "Content-Type": "application/json"}


def api(path):
    req = Request(BASE + path, headers=HDRS)
    with urlopen(req, timeout=25) as r:
        return json.load(r)


def search(title):
    q = urllib.parse.quote(title)
    try:
        d = api(f"/api/v2.1/films/search-by-keyword?keyword={q}&page=1")
    except HTTPError as e:
        if e.code == 429:
            return "LIMIT"
        return None
    films = d.get("films") or []
    return films[0] if films else None


con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
cols = [r[1] for r in con.execute("PRAGMA table_info(items)")]
if "kp_rating" not in cols:
    con.execute("ALTER TABLE items ADD COLUMN kp_rating REAL")
if "kp_id" not in cols:
    con.execute("ALTER TABLE items ADD COLUMN kp_id INTEGER")
con.commit()

rows = con.execute(
    "SELECT id, title, text, category FROM items "
    "WHERE category IN ('фильм','сериал','мультфильм') AND dup_of IS NULL"
).fetchall()
print(f"фильмов к обогащению: {len(rows)}", flush=True)

year_now = int(time.strftime("%Y"))
ok = 0
t0 = time.time()
for it in rows:
    raw = (it["title"] or "").strip()
    # чистим название от мусора вида "Adolescence (Переходный возраст)"
    clean = re.sub(r"[\(\[].*?[\)\]]", "", raw).strip()
    clean = re.sub(r"\s+", " ", clean)
    if len(clean) < 2:
        continue

    film = None
    for q in [raw, clean]:
        film = search(q)
        if film == "LIMIT":
            print("ДНЕВНОЙ ЛИМИТ Кинопоиска исчерпан (500/день)", flush=True)
            con.close()
            raise SystemExit(0)
        if film:
            break
        time.sleep(0.4)

    if not film:
        print(f"  не найден: {raw[:50]}", flush=True)
        time.sleep(0.3)
        continue

    fid = film.get("filmId")
    details = {}
    try:
        details = api(f"/api/v2.2/films/{fid}")
    except HTTPError:
        details = {}
    time.sleep(0.3)

    def g(*keys):
        for k in keys:
            v = details.get(k) if details else None
            if v in (None, "", []):
                v = film.get(k)
            if v not in (None, "", []):
                return v
        return None

    name_ru = g("nameRu") or clean
    year = g("year")
    try:
        year = int(str(year)[:4]) if year else None
    except Exception:
        year = None
    imdb = g("ratingImdb")
    kp = g("ratingKinopoisk")
    try:
        imdb = round(float(imdb), 1) if imdb else None
    except Exception:
        imdb = None
    try:
        kp = round(float(kp), 1) if kp else None
    except Exception:
        kp = None

    genres = details.get("genres") or film.get("genres") or []
    genre = ", ".join(x.get("genre", "") for x in genres if isinstance(x, dict))[:120]
    desc = (details.get("shortDescription") or details.get("description")
            or film.get("description") or "")
    desc = re.sub(r"<[^>]+>", "", desc)[:400]
    # подтип: мультфильм / сериал / фильм — по данным Кинопоиска
    kp_type = (details.get("type") or film.get("type") or "").upper()
    genres_low = genre.lower()
    if ("мультфильм" in genres_low or "аниме" in genres_low
            or kp_type in ("CARTOON", "ANIMATED_SERIES")):
        subtype = "мультфильм"
    elif kp_type in ("TV_SERIES", "TV_SHOW", "MINI_SERIES", "TV_SERIES_AND_FILM"):
        subtype = "сериал"
    else:
        subtype = "фильм"

    pstatus = (details.get("productionStatus") or "").upper()

    if pstatus in ("FILMING", "PRE_PRODUCTION", "POST_PRODUCTION"):
        status = "upcoming"
    elif pstatus == "COMPLETED" or (year and year <= year_now):
        status = "released"
    else:
        status = "unknown"

    con.execute(
        "UPDATE items SET title=?, year=?, imdb=?, kp_rating=?, genre=?, "
        "status=?, text=CASE WHEN ? != '' THEN ? ELSE text END, "
        "category=?, kp_id=?, enriched=1 WHERE id=?",
        (name_ru[:120], year, imdb, kp, genre, status, desc, desc, subtype, fid, it["id"]),
    )
    con.commit()
    ok += 1
    print(f"  ✓ {name_ru[:35]} | {year} | IMDb {imdb} | КП {kp}", flush=True)

print(f"\nГОТОВО: обновлено {ok} из {len(rows)} за {(time.time()-t0)/60:.1f} мин")
for r in con.execute("SELECT category, COUNT(*) c, COUNT(imdb) i, COUNT(kp_rating) k "
                     "FROM items WHERE category IN ('фильм','сериал','мультфильм') GROUP BY category"):
    print(f"  {r['category']}: {r['c']} (IMDb {r['i']}, КП {r['k']})")
con.close()
