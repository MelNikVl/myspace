#!/bin/bash
# ShotBox: перепрогон фильмов + метаданные. Запускается по крону (13:05 / 19:05).
cd /home/nik/shotbox || exit 1
set -a
source ./.env
set +a

echo "$(date '+%F %T) START" >> /tmp/shotbox_resume.log

# 1) сброс фильмов без ручных правок (перепрогон с улучшенным промптом)
./venv/bin/python - <<'PY' >> /tmp/shotbox_resume.log 2>&1
import sqlite3
con = sqlite3.connect("data/shotbox.db")
n = con.execute(
    "UPDATE items SET analyzed=0 "
    "WHERE category IN ('фильм','сериал','мультфильм') "
    "AND COALESCE(review,'')='' AND COALESCE(rating,0)=0 AND COALESCE(favorite,0)=0"
).rowcount
con.commit()
print("сброшено на перепрогон:", n)
con.close()
PY

# 2) классификация (Gemini)
./venv/bin/python analyze_all.py >> /tmp/shotbox_analyze.log 2>&1

# 3) тип/год/жанр/рейтинги из Кинопоиска (fuzzy-поиск)
./venv/bin/python enrich_kp.py >> /tmp/shotbox_enrich.log 2>&1

# 4) дозаполнение IMDb через OMDB
./venv/bin/python fill_omdb.py >> /tmp/shotbox_enrich.log 2>&1

echo "$(date '+%F %T') DONE" >> /tmp/shotbox_resume.log
