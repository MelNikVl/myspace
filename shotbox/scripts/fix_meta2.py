"""fix_meta v2: учитывает транслитерацию и англ. названия. Восстанавливает данные."""
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

TRANS = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh",
    "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "c",
    "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu",
    "я": "ya",
}


def translit(s):
    return "".join(TRANS.get(ch, ch) for ch in (s or "").lower())


def norm(s):
    s = (s or "").lower()
    s = re.sub(r"[«»\"'()\[\]:,]", " ", s)
    s = re.sub(r"\b(19|20)\d{2}\b", " ", s)
    s = re.sub(r"[^a-zа-я0-9ё ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def best_sim(title, *candidates):
    """Максимальное сходство с учётом транслитерации."""
    t = norm(title)
    tt = norm(translit(title))
    best = 0.0
    for c in candidates:
        if not c:
            continue
        n = norm(c)
        for a, b in ((t, n), (tt, n), (t, norm(translit(c)))):
            if a and b:
                best = max(best, difflib.SequenceMatcher(None, a, b).ratio())
        # вхождение одного в другое (Лютер ⊂ Лютер: Павшее солнце)
        if t and n and (t in n or n in t):
            best = max(best, 0.75)
    return best


def kp_details(kp_id):
    req = urllib.request.Request(
        f"https://kinopoiskapiunofficial.tech/api/v2.2/films/{kp_id}",
        headers={"X-API-KEY": KP})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.load(r)


def kp_search(title):
    url = ("https://kinopoiskapiunofficial.tech/api/v2.1/films/search-by-keyword?keyword="
           + urllib.parse.quote(title) + "&page=1")
    req = urllib.request.Request(url, headers={"X-API-KEY": KP})
    with urllib.request.urlopen(req, timeout=25) as r:
        return (json.load(r).get("films") or [])


def omdb_lookup(title, year=None):
    q = {"apikey": OMDB, "t": title}
    if year:
        q["y"] = str(year)
    try:
        with urllib.request.urlopen(
                "https://www.omdbapi.com/?" + urllib.parse.urlencode(q), timeout=25) as r:
            d = json.load(r)
        return d if d.get("Response") == "True" else None
    except Exception:
        return None


def type_of(kp_type, genre):
    gl = (genre or "").lower()
    if "мультфильм" in gl or "аниме" in gl:
        return "мультфильм"
    if (kp_type or "").upper() in ("TV_SERIES", "TV_SHOW", "MINI_SERIES", "TV_SERIES_AND_FILM"):
        return "сериал"
    return "фильм"


def apply_kp(con, item_id, kp_id):
    d = kp_details(kp_id)
    genres = d.get("genres") or []
    genre = ", ".join(g.get("genre", "") for g in genres if isinstance(g, dict))[:120]
    yr = d.get("year")
    try:
        yr = int(str(yr)[:4]) if yr else None
    except Exception:
        yr = None
    def num(v):
        try:
            return round(float(v), 1) if v else None
        except Exception:
            return None
    con.execute(
        "UPDATE items SET title=?, year=?, imdb=?, kp_rating=?, genre=?, status=?, "
        "category=?, kp_id=?, needs_review=0 WHERE id=?",
        ((d.get("nameRu") or "")[:120], yr, num(d.get("ratingImdb")),
         num(d.get("ratingKinopoisk")), genre,
         "released" if (yr and yr <= int(time.strftime("%Y"))) else "upcoming",
         type_of(d.get("type"), genre), kp_id, item_id))


def main():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row

    # 1) восстанавливаем те, где данные были почищены, но фильм реально есть
    todo = con.execute(
        "SELECT id, title, year FROM items WHERE needs_review=1 AND kp_id IS NULL "
        "AND category IN ('фильм','сериал','мультфильм') AND title IS NOT NULL AND title != ''"
    ).fetchall()
    print(f"восстанавливаю {len(todo)} записей", flush=True)

    restored = skipped = 0
    for r in todo:
        title = r["title"]
        try:
            films = kp_search(title)
        except Exception:
            continue
        best, best_sc = None, 0.0
        for f in films[:8]:
            sc = best_sim(title, f.get("nameRu"), f.get("nameEn"))
            if r["year"] and f.get("year") and str(r["year"]) == str(f["year"]):
                sc += 0.1
            if sc > best_sc:
                best, best_sc = f, sc
        if best and best_sc >= 0.6:
            apply_kp(con, r["id"], best["filmId"])
            print(f"  ✓ id{r['id']}: «{title}» → КП «{best.get('nameRu')}» ({best_sc:.2f})", flush=True)
            restored += 1
            con.commit()
            time.sleep(0.3)
            continue
        # OMDB
        d = omdb_lookup(title, r["year"])
        if d and best_sim(title, d.get("Title")) >= 0.6:
            try:
                imdb = float(d.get("imdbRating")) if d.get("imdbRating") not in (None, "N/A") else None
            except Exception:
                imdb = None
            con.execute("UPDATE items SET imdb=COALESCE(?,imdb), genre=COALESCE(?,genre), "
                        "needs_review=0 WHERE id=?", (imdb, (d.get("Genre") or "")[:120], r["id"]))
            print(f"  ✓ id{r['id']}: «{title}» → OMDB «{d.get('Title')}» IMDb {imdb}", flush=True)
            restored += 1
            con.commit()
            time.sleep(0.3)
            continue
        print(f"  · id{r['id']}: «{title}» — не найден, оставляю пусто", flush=True)
        skipped += 1

    con.commit()
    con.close()
    print(f"\nВосстановлено: {restored} | оставлено без метаданных: {skipped}")


if __name__ == "__main__":
    main()
