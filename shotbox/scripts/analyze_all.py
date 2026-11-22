"""Классификация скриншотов через Gemini в категории ShotBox."""
import base64
import json
import os
import re
import sqlite3
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

KEY = os.environ["GEMINI_KEY"]
MODELS = ["gemini-3-flash-preview", "gemini-3.1-flash-lite", "gemini-2.5-flash"]
MODEL = MODELS[0]
BASE = "/home/nik/shotbox"
DB = os.path.join(BASE, "data", "shotbox.db")
PHOTOS = os.path.join(BASE, "photos")
PAUSE = 13

PROMPT = """Ты разбираешь личные скриншоты пользователя. Определи, ЗАЧЕМ он это сохранил.

Ответь СТРОГО JSON:
{"category": "<фильм|сериал|мультфильм|дизайн|олх|бизнес|книги|фильм|психология|медицина|визы|путешествия|работа|документы|приколы|фраза|полезность|другое>",
 "title": "<название фильма/сериала/книги/препарата/товара — ДОСЛОВНО как написано в ТЕКСТЕ скрина>",
 "title_source": "<text|poster|none>",
 "evidence": "<фраза из текста скрина, где встречается это название, дословно, до 120 символов>",
 "text": "<весь ключевой видимый текст скрина (подпись поста, заголовок, надписи), до 250 символов>"}

КРИТИЧЕСКИ ВАЖНО про title:
1. Название бери ТОЛЬКО из ТЕКСТА на скрине: подпись поста, заголовок, крупная надпись,
   описание. Например, если в подписи написано «Называется "Отель с призраками"» —
   title = "Отель с призраками".
2. НЕ БЕРИ названия с ПОСТЕРОВ, обложек DVD/Blu-ray, афиш, рекламных баннеров и
   картинок внутри кадра. На скрине соцсети в кадре часто мелькают постерами ДРУГИЕ
   фильмы — их игнорируй полностью.
3. Если в тексте скрина названия НЕТ — поставь title_source="none" и title=null.
4. Если название видно только на постере/обложке (а текста нет) — title_source="poster",
   title=<название с постера>, но это будет проверяться вручную.
5. evidence — обязательное доказательство: дословная фраза из текста, где есть название.

Правила категорий:
- фильм: фильм, трейлер, «что за фильм», постер фильма
- сериал: сериал, сезон, эпизод, «топ сериалов»
- мультфильм: мультфильм, аниме, мультсериал, Disney/Pixar, Netflix мультфильм
- дизайн: интерьер, логотип, UI, мода, реклама, вёрстка, обои
- олх: объявление о продаже б/у товара (OLX, Avito, Slando) с ценой
- бизнес: бизнес-идеи, маркетинг, финансы, стартапы, инвестиции, налоги
- книги: книга, обложка, аннотация, список литературы, что почитать
- психология: саморазвитие, отношения, эмоции, терапия, привычки, типология личности
- медицина: здоровье, препараты, дозировка, симптомы, лечение, анализы, врач, БАД
- визы: визы, ПМЖ, ВНЖ, гражданство, консульства, релокация, эмиграция
- путешествия: билеты, отели, маршруты, города, достопримечательности, туры
- работа: вакансии, резюме, собеседование, зарплата, hh.kz, LinkedIn, карьера
- документы: паспорт, диплом, справка, свидетельство, договор, счёт, выписка
- приколы: мемы, шутки, угарные картинки, юмор, коты, смешные комменты
- фраза: цитата, мысль, которую сохранили прочитать
- полезность: инструкция, лайфхак, сервис, ссылка, код, настройка, рецепт
- другое: переписка, покупки, навигация, прочее"""

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row

PRIORITY = ["TikTok", "Instagram", "Threads", "OLX", "Ozon", "YouTube", "Avito",
            "Kaspi", "Temu", "Chess.com", "ReadEra", "2GIS", "Яндекс.Браузер",
            "Telegram", "WhatsApp", "WhatsApp Business", "Google", "ChatGPT"]

rows = con.execute("SELECT id, rel_path, app FROM items WHERE analyzed=0").fetchall()
todo = [dict(r) for r in rows]
# приоритетные приложения вперёд
todo.sort(key=lambda r: (0 if r["app"] in PRIORITY else 1, r["app"] or ""))
print(f"к обработке: {len(todo)}", flush=True)

done = 0
t0 = time.time()
for it in todo:
    path = os.path.join(PHOTOS, it["rel_path"])
    if not os.path.exists(path):
        continue
    data = open(path, "rb").read()
    if len(data) > 15 * 1024 * 1024:
        continue
    ext = os.path.splitext(path)[1].lower().lstrip(".")
    mime = "image/png" if ext == "png" else ("image/webp" if ext == "webp" else "image/jpeg")
    payload = {
        "contents": [{"parts": [
            {"text": PROMPT},
            {"inline_data": {"mime_type": mime, "data": base64.b64encode(data).decode()}},
        ]}],
        "generationConfig": {"temperature": 0, "maxOutputTokens": 350,
                             "responseMimeType": "application/json"},
    }
    res = None
    for attempt in range(5):
        req = Request(
            f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", "x-goog-api-key": KEY},
        )
        try:
            with urlopen(req, timeout=90) as r:
                resp = json.load(r)
            res = json.loads(resp["candidates"][0]["content"]["parts"][0]["text"])
            break
        except HTTPError as e:
            body = e.read().decode()
            if e.code == 429 and "per day" in body:
                try:
                    i = MODELS.index(MODEL)
                    if i + 1 < len(MODELS):
                        MODEL = MODELS[i + 1]
                        print(f"квота исчерпана → переключаюсь на {MODEL}", flush=True)
                        globals()["MODEL"] = MODEL
                        continue
                except ValueError:
                    pass
            if e.code == 429:
                m = re.search(r"retry in ([0-9.]+)s", body)
                time.sleep(float(m.group(1)) + 2 if m else 16)
                continue
            break
        except Exception:
            time.sleep(4)
            continue

    if res:
        # модель иногда возвращает [ {...} ] вместо {...}
        if isinstance(res, list):
            res = res[0] if res and isinstance(res[0], dict) else None
        if not isinstance(res, dict):
            res = None
    if res:
        cat = (res.get("category") or "другое")[:30]
        title = (res.get("title") or "").strip()
        src = (res.get("title_source") or "none").lower()
        text = (res.get("text") or "")[:800]
        evidence = (res.get("evidence") or "").strip()

        # фильмы: title только если он реально есть в тексте
        needs_review = 0
        if cat in ("фильм", "сериал", "мультфильм"):
            if not title or src == "none":
                title = ""
                needs_review = 1
            elif src == "poster":
                needs_review = 1          # взято с постера — требуем проверки
            else:
                # проверяем, что название есть в тексте/evidence
                hay = (text + " " + evidence).lower()
                probe = title.lower().strip("«»\"'")
                if probe and probe not in hay:
                    # не подтверждено текстом — помечаем
                    needs_review = 1
        con.execute(
            "UPDATE items SET category=?, title=?, text=?, needs_review=?, analyzed=1 WHERE id=?",
            (cat, title[:300], text, needs_review, it["id"]),
        )
        con.commit()
        done += 1
    if done % 10 == 0:
        el = time.time() - t0
        eta = (len(todo) - done) / (done / el) / 60 if done else 0
        print(f"{done}/{len(todo)} | ETA {eta:.0f} мин", flush=True)
    time.sleep(PAUSE)

print(f"ГОТОВО: {done} за {(time.time()-t0)/60:.0f} мин", flush=True)
for r in con.execute("SELECT category, COUNT(*) c FROM items GROUP BY category ORDER BY c DESC"):
    print(f"  {r['category']}: {r['c']}")
con.close()
