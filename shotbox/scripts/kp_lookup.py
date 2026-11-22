"""Умный поиск в Кинопоиске: выбор лучшего совпадения по схожести названия."""
import difflib
import json
import os
import re
import sqlite3
import time
import urllib.parse
from urllib.error import HTTPError
from urllib.request import Request, urlopen

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "data", "shotbox.db")
KEY = os.environ.get("KP_KEY", "7477ebc7-262b-4ce0-b145-0330de4a6d07")
BASEURL = "https://kinopoiskapiunofficial.tech"
HDRS = {"X-API-KEY": KEY, "Content-Type": "application/json"}


def norm(s):
    s = (s or "").lower()
    s = re.sub(r"[«»\"'()\[\]]", " ", s)
    s = re.sub(r"\b(19|20)\d{2}\b", " ", s)   # годы убираем
    s = re.sub(r"[^a-zа-я0-9ё ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def similarity(a, b):
    a, b = norm(a), norm(b)
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def api(path):
    req = Request(BASEURL + path, headers=HDRS)
    with urlopen(req, timeout=25) as r:
        return json.load(r)


def find_best(title, year=None, min_score=0.55):
    """Возвращает (film, score) — лучший кандидат или (None, 0)."""
    q = urllib.parse.quote(title)
    try:
        d = api(f"/api/v2.1/films/search-by-keyword?keyword={q}&page=1")
    except HTTPError as e:
        if e.code == 429:
            raise
        return None, 0.0

    films = d.get("films") or []
    best, best_score = None, 0.0
    for f in films[:8]:
        name_ru = f.get("nameRu") or ""
        name_en = f.get("nameEn") or ""
        sc = max(similarity(title, name_ru), similarity(title, name_en))
        fy = f.get("year")
        # небольшой бонус за совпадение года
        if year and fy and str(year) == str(fy):
            sc += 0.12
        if sc > best_score:
            best, best_score = f, sc
    if best_score < min_score:
        return None, best_score
    return best, best_score


def apply_to_item(con, item_id, title, year=None, force=False):
    """Ищет фильм и обновляет запись. Возвращает dict результата."""
    film, score = find_best(title, year)
    if not film:
        return {"ok": False, "reason": f"не найдено (совпадение {score:.2f})"}

    fid = film.get("filmId")
    try:
        details = api(f"/api/v2.2/films/{fid}")
    except HTTPError:
        details = {}
    time.sleep(0.3)

    genres = details.get("genres") or film.get("genres") or []
    genre = ", ".join(x.get("genre", "") for x in genres if isinstance(x, dict))[:120]
    desc = (details.get("shortDescription") or details.get("description")
            or film.get("description") or "")
    desc = re.sub(r"<[^>]+>", "", desc)[:400]

    kp_type = (details.get("type") or film.get("type") or "").upper()
    gl = genre.lower()
    if "мультфильм" in gl or "аниме" in gl or kp_type in ("CARTOON", "ANIMATED_SERIES"):
        subtype = "мультфильм"
    elif kp_type in ("TV_SERIES", "TV_SHOW", "MINI_SERIES", "TV_SERIES_AND_FILM"):
        subtype = "сериал"
    else:
        subtype = "фильм"

    pstatus = (details.get("productionStatus") or "").upper()
    yr = details.get("year") or film.get("year")
    try:
        yr = int(str(yr)[:4]) if yr else None
    except Exception:
        yr = None
    year_now = int(time.strftime("%Y"))
    if pstatus in ("FILMING", "PRE_PRODUCTION", "POST_PRODUCTION"):
        status = "upcoming"
    elif pstatus == "COMPLETED" or (yr and yr <= year_now):
        status = "released"
    else:
        status = "unknown"

    imdb = details.get("ratingImdb")
    kp = details.get("ratingKinopoisk")
    try:
        imdb = round(float(imdb), 1) if imdb else None
    except Exception:
        imdb = None
    try:
        kp = round(float(kp), 1) if kp else None
    except Exception:
        kp = None

    con.execute(
        "UPDATE items SET title=?, year=?, imdb=?, kp_rating=?, genre=?, status=?, "
        "text=CASE WHEN ? != '' THEN ? ELSE text END, category=?, kp_id=?, enriched=1 WHERE id=?",
        ((details.get("nameRu") or film.get("nameRu") or title)[:120], yr, imdb, kp,
         genre, status, desc, desc, subtype, fid, item_id),
    )
    con.commit()
    return {"ok": True, "title": details.get("nameRu") or film.get("nameRu"),
            "score": round(score, 2), "imdb": imdb, "kp": kp, "year": yr,
            "type": subtype, "kp_id": fid}
