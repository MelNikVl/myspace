"""Для записей с пустым названием, но известным kp_id — подтянуть название из Кинопоиска."""
import json
import sqlite3
import time
import urllib.request

DB = "/home/nik/shotbox/data/shotbox.db"
KP = "7477ebc7-262b-4ce0-b145-0330de4a6d07"


def main():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT id, kp_id, poster FROM items "
        "WHERE TRIM(COALESCE(title,''))='' AND kp_id IS NOT NULL"
    ).fetchall()
    print(f"записей с пустым названием и kp_id: {len(rows)}", flush=True)
    fixed = 0
    for r in rows:
        try:
            req = urllib.request.Request(
                f"https://kinopoiskapiunofficial.tech/api/v2.2/films/{r['kp_id']}",
                headers={"X-API-KEY": KP})
            with urllib.request.urlopen(req, timeout=25) as resp:
                d = json.load(resp)
        except Exception as e:
            print(f"  ✗ id{r['id']}: {type(e).__name__}", flush=True)
            continue
        name = (d.get("nameRu") or d.get("nameEn") or "").strip()
        if not name:
            continue
        genres = ", ".join(g.get("genre", "") for g in (d.get("genres") or []) if isinstance(g, dict))
        yr = d.get("year")
        def num(v):
            try:
                return round(float(v), 1) if v else None
            except Exception:
                return None
        con.execute(
            "UPDATE items SET title=?, year=COALESCE(?,year), imdb=COALESCE(?,imdb), "
            "kp_rating=COALESCE(?,kp_rating), genre=COALESCE(?,genre), needs_review=0 WHERE id=?",
            (name[:120], yr, num(d.get("ratingImdb")), num(d.get("ratingKinopoisk")),
             genres[:120], r["id"]))
        print(f"  ✓ id{r['id']}: «{name}» ({yr})", flush=True)
        fixed += 1
        con.commit()
        time.sleep(0.3)
    con.commit()
    con.close()
    print(f"\nдозаполнено названий: {fixed}")


if __name__ == "__main__":
    main()
