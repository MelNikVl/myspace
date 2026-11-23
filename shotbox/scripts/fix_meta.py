"""Fallback поиск в OMDB + чистка неверно подставленных метаданных."""
import difflib
import json
import os
import re
import sqlite3
import time
import urllib.parse
import urllib.request

BASE = "/home/nik/shotbox"
DB = os.path.join(BASE, "data", "shotbox.db")
KP = "7477ebc7-262b-4ce0-b145-0330de4a6d07"
OMDB = os.environ.get("OMDB_KEY", "391664ba")


def norm(s):
    s = (s or "").lower()
    s = re.sub(r"[«»\"'()\[\]]", " ", s)
    s = re.sub(r"\b(19|20)\d{2}\b", " ", s)
    s = re.sub(r"[^a-zа-я0-9ё ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def sim(a, b):
    a, b = norm(a), norm(b)
    return difflib.SequenceMatcher(None, a, b).ratio() if a and b else 0.0


def kp_details(kp_id):
    req = urllib.request.Request(f"https://kinopoiskapiunofficial.tech/api/v2.2/films/{kp_id}",
                                 headers={"X-API-KEY": KP})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.load(r)


def omdb_lookup(title, year=None):
    q = {"apikey": OMDB, "t": title}
    if year:
        q["y"] = str(year)
    url = "https://www.omdbapi.com/?" + urllib.parse.urlencode(q)
    try:
        with urllib.request.urlopen(url, timeout=25) as r:
            d = json.load(r)
        if d.get("Response") == "True":
            return d
    except Exception:
        pass
    return None


def main():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT id, title, year, imdb, kp_rating, kp_id, genre FROM items "
        "WHERE category IN ('фильм','сериал','мультфильм') AND title IS NOT NULL AND title != ''"
    ).fetchall()
    print(f"проверяю {len(rows)} фильмов на соответствие метаданных", flush=True)

    cleared = fixed = ok = 0
    for r in rows:
        title = r["title"]
        # 1) есть kp_id — сверяем название с Кинопоиском
        if r["kp_id"]:
            try:
                d = kp_details(r["kp_id"])
                kp_name = d.get("nameRu") or d.get("nameEn") or ""
                sc = sim(title, kp_name)
            except Exception:
                sc = 1.0
                kp_name = ""
            if sc < 0.5 and kp_name:
                print(f"  ✗ id{r['id']}: «{title}» ≠ КП «{kp_name}» ({sc:.2f}) → чищу", flush=True)
                con.execute(
                    "UPDATE items SET imdb=NULL, kp_rating=NULL, kp_id=NULL, year=NULL, "
                    "genre=NULL, status=NULL, needs_review=1 WHERE id=?", (r["id"],))
                cleared += 1
                continue
            ok += 1
            continue

        # 2) нет kp_id — пробуем OMDB
        d = omdb_lookup(title, r["year"])
        if not d:
            continue
        omdb_title = d.get("Title") or ""
        sc = sim(title, omdb_title)
        if sc < 0.6:
            print(f"  ✗ id{r['id']}: «{title}» ≈ OMDB «{omdb_title}» ({sc:.2f}) — пропуск", flush=True)
            continue
        try:
            imdb = float(d.get("imdbRating")) if d.get("imdbRating") not in (None, "N/A") else None
        except Exception:
            imdb = None
        try:
            yr = int(str(d.get("Year"))[:4])
        except Exception:
            yr = r["year"]
        con.execute(
            "UPDATE items SET imdb=COALESCE(?, imdb), year=COALESCE(?, year), "
            "genre=COALESCE(?, genre), needs_review=0 WHERE id=?",
            (imdb, yr, (d.get("Genre") or "")[:120], r["id"]))
        print(f"  ✓ id{r['id']}: «{title}» → OMDB «{omdb_title}» IMDb {imdb}", flush=True)
        fixed += 1
        con.commit()
        time.sleep(0.2)

    con.commit()
    con.close()
    print(f"\nИТОГО: проверено {ok}, очищено неверных {cleared}, дозаполнено OMDB {fixed}")


if __name__ == "__main__":
    main()
