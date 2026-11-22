"""ShotBox — галерея-органайзер скриншотов (FastAPI + SQLite)."""
import os
import sqlite3

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

BASE = "/home/nik/shotbox"
DB = os.path.join(BASE, "data", "shotbox.db")
PHOTOS = os.path.join(BASE, "photos")
THUMBS = os.path.join(BASE, "thumbs")
POSTERS = os.path.join(BASE, "posters")

CATEGORIES = [
    ("all", "Всё"),
    ("фильм", "🎬 Фильмы"),
    ("дизайн", "🎨 Дизайн"),
    ("олх", "🛒 OLX"),
    ("бизнес", "💼 Бизнес"),
    ("книги", "📚 Книги"),
    ("психология", "🧠 Психология"),
    ("медицина", "🏥 Медицина"),
    ("визы", "🛂 Визы и переезд"),
    ("путешествия", "✈️ Путешествия"),
    ("работа", "💼 Работа"),
    ("документы", "📄 Документы"),
    ("фраза", "💬 Фразы"),
    ("полезность", "🛠 Полезности"),
    ("другое", "📦 Прочее"),
]

# фильмы/сериалы/мультфильмы — одна группа
FILM_GROUP = ("фильм", "сериал", "мультфильм")

KNOWN = ("('фильм','сериал','мультфильм','дизайн','олх','фраза','полезность','бизнес',"
         "'книги','психология','медицина','визы','путешествия','работа','документы')")

app = FastAPI(title="ShotBox")


def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


@app.get("/thumbs/{name}")
def thumb(name: str):
    p = os.path.join(THUMBS, os.path.basename(name))
    if not os.path.exists(p):
        raise HTTPException(404)
    return FileResponse(p, media_type="image/jpeg")


@app.get("/posters/{name}")
def poster(name: str):
    p = os.path.join(POSTERS, os.path.basename(name))
    if not os.path.exists(p):
        raise HTTPException(404)
    return FileResponse(p, media_type="image/jpeg")


@app.get("/photos/{path:path}")
def photo(path: str):
    full = os.path.realpath(os.path.join(PHOTOS, path))
    if not full.startswith(os.path.realpath(PHOTOS)) or not os.path.exists(full):
        raise HTTPException(404)
    return FileResponse(full)


@app.get("/api/items")
def items(category: str = "all", q: str = "", limit: int = 500, offset: int = 0, dedup: int = 1):
    con = db()
    where, params = [], []
    if dedup:
        where.append("dup_of IS NULL")
    if category and category != "all":
        if category == "фильм":
            where.append("category IN ('фильм','сериал','мультфильм')")
        elif category == "другое":
            where.append(f"category NOT IN {KNOWN}")
        else:
            where.append("category = ?")
            params.append(category)
    if q:
        where.append("(title LIKE ? OR text LIKE ? OR review LIKE ? OR app LIKE ?)")
        like = f"%{q}%"
        params += [like, like, like, like]
    sql = ("SELECT items.*, (SELECT COUNT(*) FROM items d WHERE d.content_hash = items.content_hash) "
           "AS dup_count FROM items")
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY shot_date DESC LIMIT ? OFFSET ?"
    params += [limit, offset]
    rows = [dict(r) for r in con.execute(sql, params)]
    total = con.execute(
        "SELECT COUNT(*) FROM items" + (" WHERE " + " AND ".join(where) if where else ""),
        params[:-2],
    ).fetchone()[0]
    con.close()
    return {"total": total, "items": rows}


@app.get("/api/films")
def films(subtype: str = "all"):
    """Таблица фильмов. Дедуп по названию, опционально по подтипу."""
    con = db()
    where = ["category IN ('фильм','сериал','мультфильм')", "dup_of IS NULL"]
    if subtype in ("фильм", "сериал", "мультфильм"):
        where.append(f"category = '{subtype}'")
    sql = """SELECT MIN(id) AS id, title, imdb, kp_rating, year, status, genre, text,
                    MAX(watched) AS watched, thumb, rel_path, category, poster,
                    COUNT(*) AS copies
             FROM items
             WHERE {w}
             GROUP BY LOWER(TRIM(COALESCE(NULLIF(title,''), 'id'||id)))
             ORDER BY (MAX(watched)=1), (imdb IS NULL), imdb DESC, (year IS NULL), year DESC
          """.format(w=" AND ".join(where))
    rows = [dict(r) for r in con.execute(sql)]
    con.close()
    return {"items": rows}


@app.delete("/api/items/{item_id}")
def delete_item(item_id: int, files: int = 1):
    """Удалить запись + файлы скрина/миниатюры/постера."""
    con = db()
    row = con.execute("SELECT rel_path, thumb, poster, content_hash FROM items WHERE id=?",
                      (item_id,)).fetchone()
    if not row:
        raise HTTPException(404)
    deleted = []
    if files:
        # удаляем все копии (тот же content_hash), включая файлы
        dup_rows = con.execute(
            "SELECT id, rel_path, thumb, poster FROM items WHERE content_hash=? OR id=?",
            (row["content_hash"], item_id)).fetchall()
        for d in dup_rows:
            for field, root in (("rel_path", PHOTOS), ("thumb", THUMBS), ("poster", POSTERS)):
                val = d[field]
                if not val:
                    continue
                path = os.path.realpath(os.path.join(root, val))
                if path.startswith(os.path.realpath(root)) and os.path.exists(path):
                    try:
                        os.remove(path)
                        deleted.append(os.path.basename(path))
                    except Exception:
                        pass
            con.execute("DELETE FROM items WHERE id=?", (d["id"],))
    else:
        con.execute("DELETE FROM items WHERE id=?", (item_id,))
    con.commit()
    con.close()
    return {"ok": True, "deleted_files": len(deleted)}


@app.get("/api/progress")
def progress():
    con = db()
    total = con.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    analyzed = con.execute("SELECT COUNT(*) FROM items WHERE analyzed=1").fetchone()[0]
    con.close()
    left = max(total - analyzed, 0)
    return {
        "analyzed": analyzed,
        "total": total,
        "percent": round(analyzed * 100 / total, 1) if total else 100.0,
        "eta_min": round(left * 13 / 60),
    }


@app.get("/api/stats")
def stats():
    con = db()
    rows = con.execute("SELECT category, COUNT(*) c FROM items GROUP BY category").fetchall()
    total = con.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    analyzed = con.execute("SELECT COUNT(*) FROM items WHERE analyzed=1").fetchone()[0]
    con.close()
    cats = {r["category"]: r["c"] for r in rows}
    # фильмы/сериалы/мультфильмы объединены в одну группу
    cats["фильм"] = sum(cats.get(k, 0) for k in FILM_GROUP)
    return {"total": total, "analyzed": analyzed, "categories": cats}


@app.post("/api/items/{item_id}")
async def update_item(item_id: int, request: Request):
    body = await request.json()
    con = db()
    fields, params = [], []
    for key in ("category", "title", "text", "review", "rating", "url", "watched"):
        if key in body:
            fields.append(f"{key} = ?")
            params.append(body[key])
    if not fields:
        raise HTTPException(400)
    params.append(item_id)
    con.execute(f"UPDATE items SET {', '.join(fields)} WHERE id = ?", params)
    con.commit()
    con.close()
    return {"ok": True}


@app.get("/", response_class=HTMLResponse)
def index():
    return open(os.path.join(BASE, "static", "index.html"), encoding="utf-8").read()


app.mount("/static", StaticFiles(directory=os.path.join(BASE, "static")), name="static")
