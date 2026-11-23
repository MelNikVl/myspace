"""Классификация скриншотов: батчи по N изображений + ресайз (быстро, экономит квоту)."""
import base64
import io
import json
import os
import re
import sqlite3
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from PIL import Image

KEYS = [k for k in (os.environ.get("GEMINI_KEY"), os.environ.get("GEMINI_KEY_2")) if k]
KEY = KEYS[0] if KEYS else ""
KEY_IDX = 0
MODELS = ["gemini-3.1-flash-lite", "gemini-3-flash-preview"]
MODEL = MODELS[0]
BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "data", "shotbox.db")
PHOTOS = os.path.join(BASE, "photos")
BATCH = 6                 # изображений в одном запросе
MAX_SIDE = 1024           # ресайз: длинная сторона
PAUSE = 13                # пауза между запросами (5/мин)

PROMPT = """Ты разбираешь ЛИЧНЫЕ скриншоты пользователя. На входе несколько изображений
по порядку: Изображение 1, Изображение 2, ... Изображение N.

Верни СТРОГО JSON-МАССИВ из N объектов (по одному на каждое изображение, в том же порядке):
[{"index": 1,
  "category": "<фильм|сериал|мультфильм|дизайн|олх|бизнес|книги|психология|медицина|визы|путешествия|китай|ремонт|питание|работа|документы|приколы|фраза|полезность|другое>",
  "title": "<название ДОСЛОВНО из ТЕКСТА скрина, иначе null>",
  "title_source": "<text|poster|none>",
  "evidence": "<фраза из текста, где есть название, до 120 символов>",
  "text": "<ключевой видимый текст скрина, до 200 символов>"},
 ...]

КРИТИЧЕСКИ ВАЖНО про title:
1. Название бери ТОЛЬКО из ТЕКСТА скрина (подпись поста, заголовок, крупная надпись).
2. НЕ бери названия с постеров, обложек DVD, афиш, рекламных баннеров в кадре.
3. Нет названия в тексте → title_source="none", title=null.
4. Название видно только на постере → title_source="poster".
5. evidence — дословная фраза из текста с названием.

Категории:
- фильм / сериал / мультфильм: кино, трейлеры, «что за фильм», постеры
- дизайн: интерьер, логотип, UI, мода, реклама, вёрстка, обои
- олх: объявление о продаже б/у (OLX, Avito, Slando) с ценой
- бизнес: маркетинг, финансы, стартапы, инвестиции, налоги
- книги: книга, аннотация, что почитать
- психология: саморазвитие, отношения, эмоции, терапия, привычки
- медицина: здоровье, препараты, дозировка, симптомы, лечение, анализы
- визы: визы, ПМЖ, ВНЖ, гражданство, релокация, эмиграция
- путешествия: билеты, отели, маршруты, города, достопримечательности, туры (кроме Китая)
- китай: всё про Китай — Гуанчжоу, Пекин, Шанхай, Гонконг, Шэньчжэнь, Иу, рынки,
  фабрики, производство, Alibaba, Taobao, 1688, доставка из Китая, китайские товары,
  поездки и жизнь в Китае
- ремонт: стройка, ремонт квартиры, отделка, материалы, инструменты, сантехника,
  электрика, плитка, обои, мебель, смета, строители
- питание: еда, рецепты, продукты, калории, БЖУ, диеты, витамины, меню, готовка,
  полезные продукты, пищевые привычки
- работа: вакансии, резюме, собеседование, зарплата, hh.kz, LinkedIn
- документы: паспорт, диплом, справка, договор, счёт, выписка
- приколы: мемы, шутки, угарные картинки, коты, смешные комменты
- фраза: цитата, мысль
- полезность: инструкция, лайфхак, сервис, код, рецепт
- другое: переписка, покупки, навигация"""


def prep_image(path):
    """Ресайз до MAX_SIDE и JPEG-сжатие → base64."""
    im = Image.open(path)
    if im.mode not in ("RGB", "L"):
        im = im.convert("RGB")
    w, h = im.size
    if max(w, h) > MAX_SIDE:
        k = MAX_SIDE / max(w, h)
        im = im.resize((int(w * k), int(h * k)), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=82, optimize=True)
    return base64.b64encode(buf.getvalue()).decode()


def call_batch(batch):
    """batch: список dict(id, path). Возвращает список результатов или None."""
    global KEY, KEY_IDX
    parts = [{"text": PROMPT + f"\n\nНа входе {len(batch)} изображений. Верни массив из {len(batch)} объектов."}]
    for i, it in enumerate(batch, 1):
        try:
            b64 = prep_image(it["path"])
        except Exception as e:
            print(f"  ресайз fail {it['path']}: {type(e).__name__}", flush=True)
            continue
        parts.append({"text": f"Изображение {i}:"})
        parts.append({"inline_data": {"mime_type": "image/jpeg", "data": b64}})

    if len(parts) <= 1:
        return None

    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": {
            "temperature": 0,
            "maxOutputTokens": 400 * len(batch) + 300,
            "responseMimeType": "application/json",
        },
    }
    for attempt in range(5):
        req = Request(
            f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", "x-goog-api-key": KEY},
        )
        try:
            with urlopen(req, timeout=180) as r:
                resp = json.load(r)
            txt = resp["candidates"][0]["content"]["parts"][0]["text"]
            data = json.loads(txt)
            if isinstance(data, dict):
                data = [data]
            return data
        except HTTPError as e:
            body = e.read().decode()
            if e.code == 429:
                if "per day" in body:
                    KEY_IDX += 1
                    if KEY_IDX < len(KEYS):
                        KEY = KEYS[KEY_IDX]
                        print(f"  дневная квота ключа #{KEY_IDX} исчерпана → перехожу на ключ #{KEY_IDX+1}",
                              flush=True)
                        continue
                    raise SystemExit("ВСЕ КЛЮЧИ GEMINI ИСЧЕРПАНЫ (дневная квота)")
                m = re.search(r"retry in ([0-9.]+)s", body)
                time.sleep(float(m.group(1)) + 2 if m else 16)
                continue
            print(f"  HTTP {e.code}", flush=True)
            return None
        except json.JSONDecodeError:
            print("  ответ не JSON — пропускаю батч", flush=True)
            return None
        except Exception as e:
            print(f"  {type(e).__name__}", flush=True)
            time.sleep(5)
            continue
    return None


def save(con, item_id, res):
    cat = (res.get("category") or "другое")[:30]
    title = (res.get("title") or "").strip() if isinstance(res.get("title"), str) else ""
    src = (res.get("title_source") or "none").lower()
    text = (res.get("text") or "")[:800]
    evidence = (res.get("evidence") or "").strip()

    needs_review = 0
    if cat in ("фильм", "сериал", "мультфильм"):
        if not title or src == "none":
            title = ""
            needs_review = 1
        elif src == "poster":
            needs_review = 1
        else:
            hay = (text + " " + evidence).lower()
            probe = title.lower().strip("«»\"'")
            if probe and probe not in hay:
                needs_review = 1

    con.execute(
        "UPDATE items SET category=?, title=?, text=?, needs_review=?, analyzed=1 WHERE id=?",
        (cat, title[:300], text, needs_review, item_id),
    )


def main():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    rows = con.execute("SELECT id, rel_path FROM items WHERE analyzed=0").fetchall()
    todo = [{"id": r["id"], "path": os.path.join(PHOTOS, r["rel_path"])} for r in rows
            if os.path.exists(os.path.join(PHOTOS, r["rel_path"]))]
    print(f"к обработке: {len(todo)} | батч: {BATCH} | запросов: ~{-(-len(todo)//BATCH)}", flush=True)

    done = 0
    t0 = time.time()
    for i in range(0, len(todo), BATCH):
        batch = todo[i:i + BATCH]
        res = call_batch(batch)
        if not res:
            continue
        # сопоставляем по index (1-based), иначе по порядку
        by_idx = {}
        for k, r in enumerate(res):
            if isinstance(r, dict):
                idx = r.get("index")
                by_idx[int(idx) if isinstance(idx, int) else k + 1] = r
        for pos, it in enumerate(batch, 1):
            r = by_idx.get(pos)
            if r:
                save(con, it["id"], r)
        con.commit()
        done += len(batch)
        el = time.time() - t0
        rate = done / el if el else 0
        print(f"{done}/{len(todo)} | {rate*60:.0f} фото/мин | ETA {(len(todo)-done)/rate/60:.0f} мин",
              flush=True)
        time.sleep(PAUSE)

    print(f"\nГОТОВО: {done} за {(time.time()-t0)/60:.1f} мин", flush=True)
    for r in con.execute("SELECT category, COUNT(*) c FROM items GROUP BY category ORDER BY c DESC"):
        print(f"  {r['category']}: {r['c']}")
    con.close()


if __name__ == "__main__":
    main()
