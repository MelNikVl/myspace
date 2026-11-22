"""Генерация миниатюр + заполнение базовой таблицы items."""
import hashlib
import os
import re
import sqlite3
from datetime import datetime

from PIL import Image

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PHOTOS = os.path.join(BASE, "photos")
THUMBS = os.path.join(BASE, "thumbs")
DB = os.path.join(BASE, "data", "shotbox.db")

PKG_NAMES = {
    "com.zhiliaoapp.musically": "TikTok",
    "com.instagram.android": "Instagram",
    "com.instagram.barcelona": "Threads",
    "org.telegram.messenger": "Telegram",
    "com.whatsapp.w4b": "WhatsApp Business",
    "com.whatsapp": "WhatsApp",
    "com.microsoft.teams": "Teams",
    "ru.dublgis.dgismobile": "2GIS",
    "com.mapswithme.maps.pro": "Maps.me",
    "com.google.android.apps.maps": "Google Maps",
    "com.yandex.browser": "Яндекс.Браузер",
    "ru.ozon.app.android": "Ozon",
    "kz.kaspi.mobile": "Kaspi",
    "com.android.vending": "Google Play",
    "kz.slando": "OLX",
    "com.avito.android": "Avito",
    "com.microsoft.office.outlook": "Outlook",
    "ru.yandex.mail": "Яндекс.Почта",
    "com.google.android.gm": "Gmail",
    "com.openai.chatgpt": "ChatGPT",
    "com.ruijie.cloudapp": "Ruijie Cloud",
    "org.readera": "ReadEra",
    "com.tradingview.tradingviewapp": "TradingView",
    "com.google.android.googlequicksearchbox": "Google",
    "com.miui.gallery": "Галерея",
    "com.trello": "Trello",
    "com.miui.weather2": "Погода",
    "ru.yandex.taxi": "Яндекс.Такси",
    "com.ubercab": "Uber",
    "com.deliveroo.orderapp": "Deliveroo",
    "ru.aviasales": "Aviasales",
    "ru.safib.assistant": "Safib",
    "com.android.phone": "Телефон",
    "com.google.android.dialer": "Dialer",
    "com.google.android.contacts": "Контакты",
    "com.android.settings": "Настройки",
    "com.miui.euicc": "eSIM",
    "com.miui.calculator": "Калькулятор",
    "com.kcell.myactiv": "Kcell",
    "kz.altel.app": "Altel",
    "com.google.android.apps.photos": "Google Фото",
    "com.epson.iprojection": "Epson iProjection",
    "com.google.android.youtube": "YouTube",
    "com.deepl.mobiletranslator": "DeepL",
    "com.azure.authenticator": "Authenticator",
    "kz.htkz": "HTKZ",
    "com.ezviz": "EZVIZ",
    "com.mm.android.dmss": "DMSS (Dahua)",
    "com.einnovation.temu": "Temu",
    "com.chess": "Chess.com",
}

pkg_re = re.compile(r"((?:com|ru|org|kz|net|io|me)\.[a-z0-9_]+(?:\.[a-z0-9_]+)*)", re.I)
date_re = re.compile(r"Screenshot_(\d{4})-(\d{2})-(\d{2})-(\d{2})-(\d{2})-(\d{2})")


def app_name(fname: str) -> str:
    m = pkg_re.search(fname)
    if not m:
        return ""
    pkg = m.group(1).lower().replace(".jpg", "").replace(".png", "")
    for key, name in sorted(PKG_NAMES.items(), key=lambda x: -len(x[0])):
        if pkg.startswith(key):
            return name
    return pkg


def shot_date(fname: str, fallback: str) -> str:
    m = date_re.search(fname)
    if m:
        y, mo, d, h, mi, s = m.groups()
        return f"{y}-{mo}-{d} {h}:{mi}:{s}"
    return fallback


os.makedirs(THUMBS, exist_ok=True)
con = sqlite3.connect(DB)
con.execute("""CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rel_path TEXT UNIQUE,
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
    added_at TEXT DEFAULT CURRENT_TIMESTAMP
)""")
con.execute("CREATE INDEX IF NOT EXISTS idx_cat ON items(category)")
con.commit()

existing = {r[0] for r in con.execute("SELECT rel_path FROM items")}

added = 0
for dirpath, _, names in os.walk(PHOTOS):
    for n in sorted(names):
        if not n.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
            continue
        src = os.path.join(dirpath, n)
        rel = os.path.relpath(src, PHOTOS)
        if rel in existing:
            continue
        h = hashlib.md5(src.encode()).hexdigest()[:16]
        tpath = os.path.join(THUMBS, h + ".jpg")
        try:
            im = Image.open(src)
            im = im.convert("RGB")
            im.thumbnail((480, 480))
            im.save(tpath, "JPEG", quality=80)
        except Exception as e:
            print("thumb fail", rel, e)
            tpath = ""
        mtime = datetime.fromtimestamp(os.path.getmtime(src)).strftime("%Y-%m-%d %H:%M:%S")
        con.execute(
            "INSERT OR IGNORE INTO items (rel_path, thumb, app, shot_date) VALUES (?,?,?,?)",
            (rel, os.path.basename(tpath) if tpath else "", app_name(n), shot_date(n, mtime)),
        )
        added += 1

con.commit()
total = con.execute("SELECT COUNT(*) FROM items").fetchone()[0]
thumbs = sum(1 for _ in os.listdir(THUMBS))
print(f"добавлено: {added} | всего в БД: {total} | миниатюр: {thumbs}")
print("по приложениям:")
for app, cnt in con.execute("SELECT app, COUNT(*) FROM items GROUP BY app ORDER BY 2 DESC LIMIT 12"):
    print(f"  {app or '(без пакета)'}: {cnt}")
con.close()
