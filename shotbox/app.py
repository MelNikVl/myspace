"""ShotBox — галерея-органайзер скриншотов (FastAPI + SQLite)."""
import os
import sqlite3
import subprocess
import sys

import hashlib
import secrets
import time

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
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
    ("приколы", "😂 Приколы"),
    ("фраза", "💬 Фразы"),
    ("полезность", "🛠 Полезности"),
    ("другое", "📦 Прочее"),
]

# фильмы/сериалы/мультфильмы — одна группа
FILM_GROUP = ("фильм", "сериал", "мультфильм")

KNOWN = ("('фильм','сериал','мультфильм','дизайн','олх','фраза','полезность','бизнес',"
         "'книги','психология','медицина','визы','путешествия','работа','документы')")

app = FastAPI(title="ShotBox")

COOKIE = "sb_session"
SESSION_DAYS = 30


def _now():
    return int(time.time())


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 200_000)
    return f"{salt}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt, digest = stored.split("$", 1)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 200_000)
        return secrets.compare_digest(dk.hex(), digest)
    except Exception:
        return False


def init_auth():
    con = db()
    con.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
    con.execute("""CREATE TABLE IF NOT EXISTS sessions (
        token TEXT PRIMARY KEY, created_at INTEGER, expires_at INTEGER)""")
    row = con.execute("SELECT value FROM settings WHERE key='admin_password'").fetchone()
    if not row:
        con.execute("INSERT INTO settings (key, value) VALUES ('admin_password', ?)",
                    (hash_password("123"),))
    row = con.execute("SELECT value FROM settings WHERE key='admin_login'").fetchone()
    if not row:
        con.execute("INSERT INTO settings (key, value) VALUES ('admin_login', 'admin')")
    con.commit()
    con.close()


def get_setting(key, default=""):
    con = db()
    row = con.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    con.close()
    return row["value"] if row else default


def set_setting(key, value):
    con = db()
    con.execute("INSERT INTO settings (key, value) VALUES (?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
    con.commit()
    con.close()


def is_authed(request: Request) -> bool:
    token = request.cookies.get(COOKIE)
    if not token:
        return False
    con = db()
    row = con.execute("SELECT expires_at FROM sessions WHERE token=?", (token,)).fetchone()
    con.close()
    return bool(row and row["expires_at"] > _now())


NAS_HOST = os.environ.get("NAS_HOST", "192.168.0.3")
NAS_SHARE = os.environ.get("NAS_SHARE", "photo")
NAS_USER = os.environ.get("NAS_USER", "")
NAS_PASS = os.environ.get("NAS_PASS", "")


def delete_on_nas(rel_path: str) -> bool:
    """Удаляет файл на Synology по относительному пути вида 2025-06/name.jpg."""
    if not (NAS_USER and NAS_PASS):
        return False
    try:
        folder, fname = os.path.split(rel_path)
        parts = folder.split("-")
        if len(parts) != 2:
            return False
        year, month = parts
        smb_path = f"DCIM/Screenshots/{year}/{month}"
        cmd = f'cd "{smb_path}"; del "{fname}"'
        r = subprocess.run(
            ["smbclient", f"//{NAS_HOST}/{NAS_SHARE}", "-U", f"{NAS_USER}%{NAS_PASS}",
             "-c", cmd],
            capture_output=True, text=True, timeout=60)
        return r.returncode == 0
    except Exception:
        return False


PUBLIC_PATHS = ("/login", "/favicon.ico", "/favicon.png", "/health")


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path
    if path in PUBLIC_PATHS or path.startswith("/static"):
        return await call_next(request)
    if not is_authed(request):
        if path.startswith("/api/"):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return RedirectResponse("/login", status_code=302)
    return await call_next(request)


sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


@app.on_event("startup")
def _startup():
    init_auth()


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
    if subtype == "favorite":
        where.append("favorite = 1")
    elif subtype in ("фильм", "сериал", "мультфильм"):
        where.append(f"category = '{subtype}'")
    sql = """SELECT MIN(id) AS id, title, imdb, kp_rating, year, status, genre, text,
                    MAX(watched) AS watched, MAX(favorite) AS favorite, MAX(needs_review) AS needs_review, thumb, rel_path, category, poster,
                    COUNT(*) AS copies
             FROM items
             WHERE {w}
             GROUP BY LOWER(TRIM(COALESCE(NULLIF(title,''), 'id'||id)))
             ORDER BY (MAX(favorite)=1) DESC, (MAX(watched)=1), (imdb IS NULL), imdb DESC, (year IS NULL), year DESC
          """.format(w=" AND ".join(where))
    rows = [dict(r) for r in con.execute(sql)]
    con.close()
    return {"items": rows}


@app.delete("/api/items/{item_id}")
def delete_item(item_id: int, files: int = 1, nas: int = 0):
    """Удалить запись + файлы скрина/миниатюры/постера."""
    con = db()
    row = con.execute("SELECT rel_path, thumb, poster, content_hash FROM items WHERE id=?",
                      (item_id,)).fetchone()
    if not row:
        raise HTTPException(404)
    deleted = []
    nas_deleted = 0
    if nas:
        con2 = db()
        for d in con2.execute("SELECT rel_path FROM items WHERE content_hash=? OR id=?",
                              (row["content_hash"], item_id)).fetchall():
            if delete_on_nas(d["rel_path"]):
                nas_deleted += 1
        con2.close()
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
    return {"ok": True, "deleted_files": len(deleted), "nas_deleted": nas_deleted}


@app.post("/api/items/{item_id}/refresh-kp")
async def refresh_kp(item_id: int, request: Request):
    """Перепарсить метаданные фильма по текущему (или переданному) названию."""
    from kp_lookup import apply_to_item
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    con = db()
    row = con.execute("SELECT title, year FROM items WHERE id=?", (item_id,)).fetchone()
    if not row:
        con.close()
        raise HTTPException(404)
    title = (body.get("title") or row["title"] or "").strip()
    year = body.get("year") or row["year"]
    if not title:
        con.close()
        raise HTTPException(400, "пустое название")
    try:
        res = apply_to_item(con, item_id, title, year)
    except Exception as e:
        con.close()
        raise HTTPException(500, f"ошибка Кинопоиска: {type(e).__name__}")
    con.close()
    return res


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
    favs = con.execute("SELECT COUNT(*) FROM items WHERE favorite=1").fetchone()[0]
    con.close()
    cats = {r["category"]: r["c"] for r in rows}
    # фильмы/сериалы/мультфильмы объединены в одну группу
    cats["фильм"] = sum(cats.get(k, 0) for k in FILM_GROUP)
    return {"total": total, "analyzed": analyzed, "favorites": favs, "categories": cats}


@app.post("/api/items/{item_id}")
async def update_item(item_id: int, request: Request):
    body = await request.json()
    con = db()
    fields, params = [], []
    for key in ("category", "title", "text", "review", "rating", "url", "watched", "favorite"):
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



@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if is_authed(request):
        return RedirectResponse("/", status_code=302)
    return open(os.path.join(BASE, "static", "login.html"), encoding="utf-8").read()


@app.post("/login")
async def login_submit(request: Request):
    form = await request.form()
    username = (form.get("username") or "").strip()
    password = form.get("password") or ""
    ok = (username == get_setting("admin_login", "admin")
          and verify_password(password, get_setting("admin_password", "")))
    if not ok:
        return HTMLResponse(
            open(os.path.join(BASE, "static", "login.html"), encoding="utf-8").read()
            .replace("<!--ERROR-->", '<div class="err">Неверный логин или пароль</div>'),
            status_code=401)
    token = secrets.token_urlsafe(32)
    con = db()
    con.execute("INSERT INTO sessions (token, created_at, expires_at) VALUES (?,?,?)",
                (token, _now(), _now() + SESSION_DAYS * 86400))
    con.commit()
    con.close()
    resp = RedirectResponse("/", status_code=302)
    resp.set_cookie(COOKIE, token, max_age=SESSION_DAYS * 86400,
                    httponly=True, samesite="lax")
    return resp


@app.get("/logout")
def logout(request: Request):
    token = request.cookies.get(COOKIE)
    if token:
        con = db()
        con.execute("DELETE FROM sessions WHERE token=?", (token,))
        con.commit()
        con.close()
    resp = RedirectResponse("/login", status_code=302)
    resp.delete_cookie(COOKIE)
    return resp


@app.post("/api/settings/password")
async def change_password(request: Request):
    body = await request.json()
    old = body.get("old") or ""
    new = body.get("new") or ""
    if len(new) < 3:
        raise HTTPException(400, "пароль слишком короткий")
    if not verify_password(old, get_setting("admin_password", "")):
        raise HTTPException(403, "неверный текущий пароль")
    set_setting("admin_password", hash_password(new))
    # разлогинить все прочие сессии
    con = db()
    con.execute("DELETE FROM sessions")
    con.commit()
    con.close()
    return {"ok": True}


@app.get("/api/settings")
def settings_info():
    return {"login": get_setting("admin_login", "admin")}


@app.get("/favicon.ico")
def favicon_ico():
    return FileResponse(os.path.join(BASE, "static", "favicon.ico"), media_type="image/x-icon")


@app.get("/favicon.png")
def favicon_png():
    return FileResponse(os.path.join(BASE, "static", "favicon.png"), media_type="image/png")


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/", response_class=HTMLResponse)
def index():
    return open(os.path.join(BASE, "static", "index.html"), encoding="utf-8").read()


app.mount("/static", StaticFiles(directory=os.path.join(BASE, "static")), name="static")
