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

PROMPT = """Ты помогаешь разобрать личные скриншоты пользователя. Определи, ЗАЧЕМ он это сохранил.
Ответь СТРОГО JSON:
{"category": "<фильм|сериал|мультфильм|дизайн|олх|бизнес|книги|психология|медицина|визы|путешествия|работа|документы|фраза|полезность|другое>",
 "title": "<короткое название: фильма/сериала/книги/препарата/вакансии/страны, товара, суть — до 70 символов>",
 "text": "<сам текст фразы дословно ИЛИ краткое описание содержимого — до 250 символов>"}

Правила категорий:
- фильм: упоминание/кадр фильма, «что за фильм», трейлер, постер
  ВАЖНО для фильмов/сериалов: название бери из ПОДПИСИ или ТЕКСТА ПОСТА,
  а НЕ с рекламного постера/баннера в ленте. Если в подписи написано
  «Крушение мира (2025)» — название «Крушение мира», даже если рядом
  в ленте виден другой постер.
- сериал: сериал, сезон, эпизод, «топ сериалов»
- мультфильм: мультфильм, аниме, мультсериал, Disney/Pixar, «мультик»
- дизайн: визуальный референс — интерьер, логотип, UI, мода, реклама, красивая вёрстка, обои
- олх: объявление о продаже б/у товара (OLX, Avito, Slando), товар с ценой
- бизнес: бизнес-идеи, предпринимательство, маркетинг, продажи, финансы, стартапы, инвестиции, налоги
- книги: книга, обложка, аннотация, список литературы, цитата из книги, что почитать
- психология: психология, саморазвитие, отношения, эмоции, тревога, терапия, ментальное здоровье, цитаты психологов, привычки, мотивация, типология личности
- медицина: ЛЮБОЕ про здоровье — препараты, аптека, дозировка, симптомы, лечение, анализы, врач, клиника, БАД, витамины, упражнения для здоровья
- визы: визы, переезд, иммиграция, ПМЖ, ВНЖ, гражданство, консульства, требования к визе, релокация, эмиграция
- путешествия: билеты, отели, маршруты, города, страны, достопримечательности, курорты, советы туристам, туры
- работа: вакансии, резюме, собеседование, зарплата, hh.kz, LinkedIn, оффер, требования к должности, карьера
- документы: паспорт, диплом, справка, свидетельство, договор, счёт, квитанция, официальный документ, ИИН, выписка
- фраза: текст, цитата, мысль, которую человек сохранил прочитать
- полезность: инструкция, лайфхак, сервис, ссылка, код, настройка, рецепт (не медицинский)
- другое: всё остальное (переписка, покупки, документы, навигация)"""

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
        con.execute(
            "UPDATE items SET category=?, title=?, text=?, analyzed=1 WHERE id=?",
            ((res.get("category") or "другое")[:30],
             (res.get("title") or "")[:300],
             (res.get("text") or "")[:800],
             it["id"]),
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
